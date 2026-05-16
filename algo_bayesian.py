#!/usr/bin/env python3
"""
刘海蟾点金 - 贝叶斯动态权重更新模块
每期开奖后更新各号码的先验→后验概率，生成权重修正系数

核心:
- Beta先验 (alpha=1, beta=1 均匀分布)
- 开出→alpha+1, 未开出→beta+1
- 后验均值 = alpha/(alpha+beta)
- 修正系数 = 后验均值 / 均匀概率

融合方式:
- 在WeightedAnalyzer._calc_weights()末尾乘以贝叶斯修正系数
- 限制±20%避免过激
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta


CST_OFFSET = timedelta(hours=8)

def _now_cst():
    return datetime.utcnow() + CST_OFFSET


class BayesianUpdater:
    """贝叶斯动态权重更新器"""

    # 修正系数上下限（防止过激）
    ADJ_MIN = 0.80
    ADJ_MAX = 1.20

    def __init__(self, db):
        self.db = db
        self._ensure_table()
        self._alpha, self._beta = self._load_state()

    def _ensure_table(self):
        """确保贝叶斯状态表存在"""
        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS algo_bayesian_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            alpha_json TEXT NOT NULL DEFAULT '{}',
            beta_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            UNIQUE(game))''')
        conn.commit()
        conn.close()

    def _load_state(self):
        """从DB加载贝叶斯状态"""
        alpha = defaultdict(lambda: defaultdict(float))
        beta = defaultdict(lambda: defaultdict(float))

        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute('SELECT game, alpha_json, beta_json FROM algo_bayesian_state')
        rows = c.fetchall()
        conn.close()

        for row in rows:
            game = row['game']
            a_dict = json.loads(row['alpha_json'])
            b_dict = json.loads(row['beta_json'])
            for n_str, v in a_dict.items():
                alpha[game][int(n_str)] = v
            for n_str, v in b_dict.items():
                beta[game][int(n_str)] = v

        # 默认先验: Beta(1,1) 均匀分布
        return alpha, beta

    def _save_state(self):
        """持久化贝叶斯状态到DB"""
        conn = self.db._get_conn()
        c = conn.cursor()
        for game in set(list(self._alpha.keys()) + list(self._beta.keys())):
            a_dict = {str(n): v for n, v in self._alpha[game].items()}
            b_dict = {str(n): v for n, v in self._beta[game].items()}
            c.execute('''INSERT OR REPLACE INTO algo_bayesian_state (game, alpha_json, beta_json, updated_at)
                         VALUES (?, ?, ?, ?)''',
                      (game, json.dumps(a_dict), json.dumps(b_dict), _now_cst().isoformat()))
        conn.commit()
        conn.close()

    def update(self, game, number_range, actual_numbers):
        """
        开奖后更新: 出现→alpha+1, 未出现→beta+1

        Args:
            game: 玩法 (ssq/dlt/qxc)
            number_range: 号码范围
            actual_numbers: 本期开出的号码列表
        """
        actual_set = set(actual_numbers)
        for n in number_range:
            # 默认先验 Beta(1,1)
            if n not in self._alpha[game]:
                self._alpha[game][n] = 1.0
            if n not in self._beta[game]:
                self._beta[game][n] = 1.0

            if n in actual_set:
                self._alpha[game][n] += 1.0
            else:
                self._beta[game][n] += 1.0

        self._save_state()

    def update_from_settlement(self, db):
        """从结算数据批量更新贝叶斯状态"""
        conn = db._get_conn()
        c = conn.cursor()

        # 查找已结算但未更新贝叶斯的记录
        c.execute('''SELECT DISTINCT b.game, b.numbers, s.actual_numbers
                     FROM algo_bets b
                     JOIN algo_settlements s ON b.id = s.bet_id
                     WHERE s.settled_at > COALESCE(
                         (SELECT MAX(updated_at) FROM algo_bayesian_state), '2000-01-01')
                     ORDER BY s.settled_at''')
        rows = c.fetchall()
        conn.close()

        if not rows:
            return

        # 按game分组更新
        from algo_orchestrator import AlgoOrchestrator
        game_groups = defaultdict(list)
        for row in rows:
            game_groups[row['game']].append(row)

        for game, settlements in game_groups.items():
            number_range = AlgoOrchestrator._get_number_range(game)
            # 用最近一期的实际开奖号码更新
            latest = settlements[-1]
            actual = json.loads(latest['actual_numbers']) if isinstance(latest['actual_numbers'], str) else latest['actual_numbers']
            self.update(game, number_range, actual)

        print(f"[Bayesian] 更新完成: {len(rows)}条结算记录")

    def get_posterior_prob(self, game, number_range):
        """
        返回各号码的后验概率 (Beta分布均值)

        Returns:
            dict: {number: posterior_prob}
        """
        probs = {}
        for n in number_range:
            a = self._alpha[game].get(n, 1.0)
            b = self._beta[game].get(n, 1.0)
            probs[n] = a / (a + b)
        return probs

    def get_weight_adjustment(self, game, number_range):
        """
        生成权重修正系数

        逻辑: 后验概率偏离均匀分布 → 号码出现频率异于期望 → 应调整权重

        Returns:
            dict: {number: adjustment_factor}
                >1 = 该号码后验概率高于均匀(热号)
                <1 = 该号码后验概率低于均匀(冷号)
        """
        probs = self.get_posterior_prob(game, number_range)
        n_numbers = len(number_range)
        if n_numbers == 0:
            return {}

        uniform_prob = 1.0 / n_numbers
        adjustment = {}
        for n in number_range:
            raw_adj = probs[n] / uniform_prob if uniform_prob > 0 else 1.0
            # 限制在[ADJ_MIN, ADJ_MAX]区间
            adjustment[n] = max(self.ADJ_MIN, min(self.ADJ_MAX, raw_adj))

        return adjustment

    def get_stats(self, game, number_range):
        """获取贝叶斯统计摘要"""
        probs = self.get_posterior_prob(game, number_range)
        adj = self.get_weight_adjustment(game, number_range)

        # 找最热和最冷的号
        sorted_by_prob = sorted(probs.items(), key=lambda x: x[1], reverse=True)

        return {
            'game': game,
            'hottest': sorted_by_prob[:3] if len(sorted_by_prob) >= 3 else sorted_by_prob,
            'coldest': sorted_by_prob[-3:] if len(sorted_by_prob) >= 3 else sorted_by_prob,
            'alpha_count': len(self._alpha.get(game, {})),
            'beta_count': len(self._beta.get(game, {})),
        }


if __name__ == '__main__':
    print("贝叶斯动态权重模块自检")

    # 用内存DB测试
    import sqlite3
    import os

    # 创建临时DB
    class MockDB:
        def __init__(self):
            self.db_path = '/tmp/test_bayesian.db'
            self._init_mock()

        def _init_mock(self):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            # 创建必要的表
            conn.execute('CREATE TABLE IF NOT EXISTS algo_bayesian_state (id INTEGER PRIMARY KEY, game TEXT UNIQUE, alpha_json TEXT, beta_json TEXT, updated_at TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS algo_bets (id INTEGER PRIMARY KEY, date TEXT, game TEXT, numbers TEXT, status TEXT DEFAULT "pending")')
            conn.execute('CREATE TABLE IF NOT EXISTS algo_settlements (id INTEGER PRIMARY KEY, bet_id INTEGER, actual_numbers TEXT, settled_at TEXT)')
            conn.commit()
            conn.close()

        def _get_conn(self):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    db = MockDB()
    updater = BayesianUpdater(db)

    # 模拟5期双色球开奖
    ssq_range = list(range(1, 34))
    draws = [
        [1, 5, 12, 18, 25, 33],
        [3, 7, 15, 22, 28, 31],
        [2, 8, 14, 19, 26, 30],
        [4, 9, 16, 23, 27, 32],
        [1, 6, 13, 20, 29, 33],
    ]

    for draw in draws:
        updater.update('ssq', ssq_range, draw)

    adj = updater.get_weight_adjustment('ssq', ssq_range)
    probs = updater.get_posterior_prob('ssq', ssq_range)

    # 找修正最大的号
    top_adj = sorted(adj.items(), key=lambda x: x[1], reverse=True)[:5]
    low_adj = sorted(adj.items(), key=lambda x: x[1])[:5]

    print(f"修正最高的号: {[(n, f'{a:.4f}') for n, a in top_adj]}")
    print(f"修正最低的号: {[(n, f'{a:.4f}') for n, a in low_adj]}")
    print(f"统计: {updater.get_stats('ssq', ssq_range)}")

    # 清理
    os.unlink('/tmp/test_bayesian.db')
    print("\n自检通过 ✓")
