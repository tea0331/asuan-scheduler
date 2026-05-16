#!/usr/bin/env python3
"""
刘海蟾点金 - 马尔可夫状态转移预测模块
构建号码状态(cold/warm/hot)的转移概率矩阵，预测号码状态变化

核心:
- 三态: cold(遗漏>均值×1.5) / warm(0.5-1.5倍均值) / hot(<均值×0.5)
- 转移矩阵: transition[from_state][to_state] = 计数
- 信号: 当前cold→hot概率高的号 = "即将变热"的号

融合方式:
- 新增P4_MARKOV策略: 选转移概率最高(cold→hot/warm→hot)的号
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta


CST_OFFSET = timedelta(hours=8)

def _now_cst():
    return datetime.utcnow() + CST_OFFSET


class MarkovPredictor:
    """马尔可夫状态转移预测器"""

    STATES = ['cold', 'warm', 'hot']

    def __init__(self, db):
        self.db = db
        self._ensure_table()
        # transition[game][number][from_state][to_state] = count
        self._transition = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int))))
        self._current_state = defaultdict(lambda: defaultdict(str))
        self._loaded = False

    def _ensure_table(self):
        """确保马尔可夫状态表存在"""
        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS algo_markov_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            transition_json TEXT NOT NULL DEFAULT '{}',
            current_state_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            UNIQUE(game))''')
        conn.commit()
        conn.close()

    def _load_state(self):
        """从DB加载状态"""
        if self._loaded:
            return

        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute('SELECT game, transition_json, current_state_json FROM algo_markov_state')
        rows = c.fetchall()
        conn.close()

        for row in rows:
            game = row['game']
            trans = json.loads(row['transition_json'])
            cur = json.loads(row['current_state_json'])

            for n_str, state_trans in trans.items():
                n = int(n_str)
                for from_s, to_dict in state_trans.items():
                    for to_s, count in to_dict.items():
                        self._transition[game][n][from_s][to_s] = count

            for n_str, state in cur.items():
                self._current_state[game][int(n_str)] = state

        self._loaded = True

    def _save_state(self, game):
        """持久化状态到DB"""
        self._load_state()

        conn = self.db._get_conn()
        c = conn.cursor()

        # 序列化转移矩阵
        trans_dict = {}
        for n, state_trans in self._transition[game].items():
            trans_dict[str(n)] = {from_s: dict(to_dict) for from_s, to_dict in state_trans.items()}

        cur_dict = {str(n): s for n, s in self._current_state[game].items()}

        c.execute('''INSERT OR REPLACE INTO algo_markov_state (game, transition_json, current_state_json, updated_at)
                     VALUES (?, ?, ?, ?)''',
                  (game, json.dumps(trans_dict), json.dumps(cur_dict), _now_cst().isoformat()))
        conn.commit()
        conn.close()

    def fit(self, game, history, number_range, extract_fn):
        """
        从历史数据拟合转移矩阵

        Args:
            game: 玩法
            history: 历史开奖数据列表（按时间倒序，history[0]最近）
            number_range: 号码范围
            extract_fn: 提取号码函数
        """
        self._load_state()

        # 计算每个号码的平均遗漏间隔
        avg_miss = self._calc_avg_miss(history, number_range, extract_fn)

        for n in number_range:
            # 获取状态序列
            states = self._get_state_sequence(n, history, extract_fn, avg_miss.get(n, 5))

            # 更新转移计数
            for i in range(len(states) - 1):
                self._transition[game][n][states[i]][states[i+1]] += 1

            # 记录当前状态
            if states:
                self._current_state[game][n] = states[-1]

        self._save_state(game)
        print(f"[Markov] {game} 转移矩阵拟合完成, 号码数={len(number_range)}")

    def predict(self, game, number, default_state='warm'):
        """
        预测号码的下一状态概率分布

        Args:
            game: 玩法
            number: 号码
            default_state: 当前状态的默认值
        Returns:
            dict: {cold: prob, warm: prob, hot: prob}
        """
        self._load_state()

        current = self._current_state[game].get(number, default_state)
        trans = self._transition[game].get(number, {})

        total = sum(trans.get(current, {}).values())
        if total == 0:
            return {'cold': 0.33, 'warm': 0.34, 'hot': 0.33}

        return {s: trans.get(current, {}).get(s, 0) / total for s in self.STATES}

    def get_transition_signals(self, game, history, number_range, extract_fn):
        """
        获取转移信号: 找出"即将变热"的号码

        信号 = P(cold→hot) 或 P(warm→hot)，概率越高越值得选

        Returns:
            dict: {number: transition_signal}
        """
        self._load_state()

        signals = {}
        for n in number_range:
            current = self._current_state[game].get(n, 'warm')
            trans = self._transition[game].get(n, {})

            total = sum(trans.get(current, {}).values())
            if total < 3:
                # 样本太少，不给信号
                signals[n] = 0.0
                continue

            hot_prob = trans.get(current, {}).get('hot', 0) / total

            # cold→hot信号加权（比warm→hot更珍贵）
            if current == 'cold':
                signals[n] = hot_prob * 1.5  # 冷转热信号更强
            elif current == 'warm':
                signals[n] = hot_prob * 1.0
            else:
                signals[n] = 0.0  # 已热的不需要转移信号

        return signals

    def get_top_transition_numbers(self, game, number_range, top_k=6):
        """获取转移信号最强的top_k个号码（P4马尔可夫注核心选号）"""
        signals = {}
        for n in number_range:
            pred = self.predict(game, n)
            current = self._current_state[game].get(n, 'warm')

            if current == 'cold':
                signals[n] = pred.get('hot', 0) * 1.5
            elif current == 'warm':
                signals[n] = pred.get('hot', 0) * 1.0
            else:
                signals[n] = 0.0

        sorted_nums = sorted(signals.items(), key=lambda x: x[1], reverse=True)
        return sorted_nums[:top_k]

    @staticmethod
    def _calc_avg_miss(history, number_range, extract_fn):
        """计算各号码的平均遗漏间隔"""
        avg_miss = {}
        for n in number_range:
            positions = [i for i, d in enumerate(history) if n in (extract_fn(d) if callable(extract_fn) else d)]
            if len(positions) >= 2:
                intervals = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
                avg_miss[n] = sum(intervals) / len(intervals)
            elif len(positions) == 1:
                avg_miss[n] = max(positions[0], 1)
            else:
                avg_miss[n] = len(history)
        return avg_miss

    @staticmethod
    def _get_state_sequence(number, history, extract_fn, avg_miss):
        """将号码的遗漏序列转为状态序列"""
        if avg_miss <= 0:
            return ['warm']

        states = []
        miss_count = 0
        appeared = False

        # history[0]最近，倒序遍历
        for d in reversed(history):
            nums = extract_fn(d) if callable(extract_fn) else d
            if number in nums:
                states.append(MarkovPredictor._miss_to_state(miss_count, avg_miss))
                miss_count = 0
                appeared = True
            else:
                miss_count += 1

        # 最后一段遗漏
        if appeared:
            states.append(MarkovPredictor._miss_to_state(miss_count, avg_miss))

        return states

    @staticmethod
    def _miss_to_state(miss, avg_miss):
        """遗漏值→状态"""
        if avg_miss <= 0:
            return 'warm'
        ratio = miss / avg_miss
        if ratio > 1.5:
            return 'cold'
        elif ratio < 0.5:
            return 'hot'
        else:
            return 'warm'


if __name__ == '__main__':
    print("马尔可夫状态转移模块自检")

    # 模拟测试
    import sqlite3
    import random

    class MockDB:
        def __init__(self):
            self.db_path = '/tmp/test_markov.db'
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute('CREATE TABLE IF NOT EXISTS algo_markov_state (id INTEGER PRIMARY KEY, game TEXT UNIQUE, transition_json TEXT, current_state_json TEXT, updated_at TEXT)')
            conn.commit()
            conn.close()

        def _get_conn(self):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    db = MockDB()
    predictor = MarkovPredictor(db)

    # 模拟20期双色球
    ssq_range = list(range(1, 34))
    history = [{'reds': random.sample(ssq_range, 6)} for _ in range(20)]

    predictor.fit('ssq', history, ssq_range, lambda d: d['reds'])

    # 预测
    for n in [1, 5, 10, 15, 20, 33]:
        pred = predictor.predict('ssq', n)
        print(f"  号码{n}: cold={pred['cold']:.2f} warm={pred['warm']:.2f} hot={pred['hot']:.2f}")

    # 转移信号
    top = predictor.get_top_transition_numbers('ssq', ssq_range, top_k=6)
    print(f"  最强转移信号: {top}")

    import os
    os.unlink('/tmp/test_markov.db')
    print("\n自检通过 ✓")
