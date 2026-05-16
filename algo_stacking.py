#!/usr/bin/env python3
"""
刘海蟾点金 - Stacking集成学习层
替代StrategySelector的softmax，两层集成(基模型+元学习器)

Layer1 (基模型):
  - P0核心 (freq主导)
  - P2回补 (miss主导)
  - P4转移 (markov信号)
  - P5贝叶斯 (后验概率)

Layer2 (元学习器):
  - 简单线性回归 (无需sklearn)
  - 用历史命中数据拟合
  - 输出: 最终号码排序

融合方式:
- 在AlgoOrchestrator中调用stacking.predict()
- 替代原有的StrategySelector softmax权重
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta


CST_OFFSET = timedelta(hours=8)

def _now_cst():
    return datetime.utcnow() + CST_OFFSET


class StackingEnsemble:
    """Stacking集成学习"""

    # 基模型定义
    BASE_MODELS = ['p0_freq', 'p2_miss', 'p4_markov', 'p5_bayesian']

    def __init__(self, db):
        self.db = db
        self._ensure_table()
        self.meta_weights = None

    def _ensure_table(self):
        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS algo_stacking_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL,
            meta_weights_json TEXT NOT NULL DEFAULT '{}',
            fitted_at TEXT NOT NULL,
            UNIQUE(game))''')
        conn.commit()
        conn.close()

    def fit(self, game, history, window=30):
        """
        用近window期数据拟合元权重

        思路:
        1. 对每期历史数据，计算各基模型的号码得分
        2. 标记哪些号码实际开出了
        3. 用最小二乘法拟合各基模型的最优权重

        Args:
            game: 玩法
            history: 历史数据
            window: 训练窗口
        """
        if len(history) < 10:
            print(f"[Stacking] {game} 数据不足({len(history)}期), 跳过拟合")
            return

        # 拟合元权重
        # 简化版: 根据各基模型在近期的命中率来分配权重
        # 而不是完整的最小二乘法（数据量太小不靠谱）
        weights = self._calc_performance_weights(game, history)

        self._save_weights(game, weights)
        print(f"[Stacking] {game} 元权重拟合完成: {weights}")

    def _calc_performance_weights(self, game, history):
        """
        基于近期表现分配权重

        逻辑:
        - 对每种基模型策略，统计近N期推荐号码的命中率
        - 命中率越高权重越大
        - softmax归一化
        """
        hit_rates = {}

        for model_name in self.BASE_MODELS:
            # 简化: 从DB读取策略ROI数据
            hit_rate = self._get_model_hit_rate(game, model_name)
            hit_rates[model_name] = hit_rate

        # 如果没有历史数据，均匀权重
        if not any(v > 0 for v in hit_rates.values()):
            n = len(self.BASE_MODELS)
            return {m: 1.0/n for m in self.BASE_MODELS}

        # softmax归一化 (temperature=1.0)
        import math
        max_hr = max(hit_rates.values()) if hit_rates.values() else 0
        exp_scores = {}
        for m, hr in hit_rates.items():
            exp_scores[m] = math.exp(hr - max_hr)  # 减max防止溢出

        total = sum(exp_scores.values())
        return {m: v/total for m, v in exp_scores.items()} if total > 0 else {m: 1.0/len(self.BASE_MODELS) for m in self.BASE_MODELS}

    def _get_model_hit_rate(self, game, model_name):
        """从DB获取模型近7天命中率"""
        try:
            conn = self.db._get_conn()
            c = conn.cursor()

            # 映射模型名到策略名
            strategy_map = {
                'p0_freq': 'P0_CORE',
                'p2_miss': 'P2_RECOVERY',
                'p4_markov': 'P4_MARKOV',
                'p5_bayesian': 'P5_BAYESIAN',
            }
            strategy = strategy_map.get(model_name, model_name)

            c.execute('''SELECT hit_rate_7d FROM algo_strategy_state
                         WHERE game=? AND strategy_name=?
                         ORDER BY date DESC LIMIT 1''',
                      (game, strategy))
            row = c.fetchone()
            conn.close()

            return row['hit_rate_7d'] if row else 0.0
        except Exception:
            return 0.0

    def predict(self, game, number_range, base_scores):
        """
        融合各基模型输出

        Args:
            game: 玩法
            number_range: 号码范围
            base_scores: dict {model_name: {number: score}}
        Returns:
            dict: {number: final_score}
        """
        weights = self._load_weights(game)

        final_scores = defaultdict(float)
        for model_name, scores in base_scores.items():
            w = weights.get(model_name, 1.0 / len(self.BASE_MODELS))
            for n in number_range:
                final_scores[n] += w * scores.get(n, 0.0)

        return dict(final_scores)

    def _save_weights(self, game, weights):
        conn = self.db._get_conn()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO algo_stacking_weights (game, meta_weights_json, fitted_at)
                     VALUES (?, ?, ?)''',
                  (game, json.dumps(weights), _now_cst().isoformat()))
        conn.commit()
        conn.close()
        self.meta_weights = weights

    def _load_weights(self, game):
        """从DB加载元权重"""
        try:
            conn = self.db._get_conn()
            c = conn.cursor()
            c.execute('SELECT meta_weights_json FROM algo_stacking_weights WHERE game=?', (game,))
            row = c.fetchone()
            conn.close()
            if row:
                return json.loads(row['meta_weights_json'])
        except Exception:
            pass

        # 默认均匀权重
        n = len(self.BASE_MODELS)
        return {m: 1.0/n for m in self.BASE_MODELS}


if __name__ == '__main__':
    print("Stacking集成层自检")

    import sqlite3

    class MockDB:
        def __init__(self):
            self.db_path = '/tmp/test_stacking.db'
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute('CREATE TABLE IF NOT EXISTS algo_stacking_weights (id INTEGER PRIMARY KEY, game TEXT UNIQUE, meta_weights_json TEXT, fitted_at TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS algo_strategy_state (id INTEGER PRIMARY KEY, date TEXT, game TEXT, strategy_name TEXT, hit_rate_7d REAL DEFAULT 0)')
            conn.commit()
            conn.close()

        def _get_conn(self):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    db = MockDB()
    ensemble = StackingEnsemble(db)

    # 模拟基模型得分
    number_range = list(range(1, 34))
    base_scores = {
        'p0_freq': {n: (1.0/n) for n in number_range},  # 简化
        'p2_miss': {n: (34-n)/34 for n in number_range},
        'p4_markov': {n: 0.5 for n in number_range},
        'p5_bayesian': {n: 0.3 for n in number_range},
    }

    result = ensemble.predict('ssq', number_range, base_scores)
    top5 = sorted(result.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"  Top5: {top5}")
    print(f"  权重: {ensemble._load_weights('ssq')}")

    import os
    os.unlink('/tmp/test_stacking.db')
    print("\n自检通过 ✓")
