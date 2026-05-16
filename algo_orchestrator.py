#!/usr/bin/env python3
"""
刘海蟾点金 - 算法统筹管理器 v3.0
所有模块的调度中心，通过全局context字典实现模块间通信

核心设计：
- context字典：模块间只通过context通信，不直接依赖
- 降级机制：任何模块异常不影响整体流程
- 向后兼容：不改AlgoEngine接口，Orchestrator在AlgoEngine之上
"""

import os
import json
import math
import traceback
from datetime import datetime, timedelta
from collections import defaultdict

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
CST_OFFSET = timedelta(hours=8)

def _now_cst():
    return datetime.utcnow() + CST_OFFSET


class AlgoOrchestrator:
    """
    算法统筹管理器 — 统一调度所有模块

    流程:
    1. settle() → 结算昨日 + 贝叶斯后验更新
    2. detect_entropy() → 信息熵检测，写入context
    3. update_markov() → 马尔可夫转移矩阵更新
    4. evolve() → GEPA进化 (受context影响)
    5. stack_predict() → Stacking集成预测
    6. validate() → 蒙特卡洛验证
    7. generate() → 生成推荐
    """

    def __init__(self):
        from algo_module import AlgoEngine, AlgoDB
        self.engine = AlgoEngine()
        self.db = AlgoDB()

        # 延迟导入新模块
        self._entropy = None
        self._bayesian = None
        self._markov = None
        self._stacking = None
        self._monte_carlo = None

        # 全局上下文
        self.context = {
            'mode': 'normal',          # normal / conservative / aggressive
            'entropy_ratio': 1.0,      # 信息熵比
            'bayesian_adj': {},         # 贝叶斯修正系数 {game: {number: adj}}
            'markov_signals': {},       # 马尔可夫信号 {game: {number: transition_prob}}
            'confidence': {},           # 蒙特卡洛置信区间
            'module_status': {},        # 各模块运行状态
        }

    @property
    def entropy(self):
        if self._entropy is None:
            from algo_entropy import EntropyDetector
            self._entropy = EntropyDetector()
        return self._entropy

    @property
    def bayesian(self):
        if self._bayesian is None:
            from algo_bayesian import BayesianUpdater
            self._bayesian = BayesianUpdater(self.db)
        return self._bayesian

    @property
    def markov(self):
        if self._markov is None:
            from algo_markov import MarkovPredictor
            self._markov = MarkovPredictor(self.db)
        return self._markov

    @property
    def stacking(self):
        if self._stacking is None:
            from algo_stacking import StackingEnsemble
            self._stacking = StackingEnsemble(self.db)
        return self._stacking

    @property
    def monte_carlo(self):
        if self._monte_carlo is None:
            from algo_montecarlo import MonteCarloValidator
            self._monte_carlo = MonteCarloValidator()
        return self._monte_carlo

    def daily_run(self, history_data=None):
        """每日完整流程
        
        Args:
            history_data: 可选，外部传入的历史数据 {game: [draws]}
                         如果不传，Orchestrator会自己从网络拉取
        """
        today = _now_cst().strftime('%Y-%m-%d')
        print(f"[Orchestrator] === 开始每日流程 {today} ===")

        # Step 0: 获取历史数据（如果外部没传，自己拉）
        if history_data is None:
            history_data = self._fetch_history()

        # Step 1: 结算 + 贝叶斯更新
        self._safe_run('settle', self._step_settle)

        # Step 2: 信息熵检测
        self._safe_run('entropy', self._step_entropy, history_data)

        # Step 3: 马尔可夫更新
        self._safe_run('markov', self._step_markov, history_data)

        # Step 4: 进化（传入context）
        self._safe_run('evolve', self._step_evolve, history_data)

        # Step 5: Stacking集成
        self._safe_run('stacking', self._step_stacking, history_data)

        # Step 6: 蒙特卡洛验证
        self._safe_run('validate', self._step_validate, history_data)

        # 保存context快照
        self._save_context(today)

        print(f"[Orchestrator] === 每日流程完成 ===")
        print(f"  模式: {self.context['mode']}")
        print(f"  熵比: {self.context['entropy_ratio']:.4f}")
        print(f"  模块状态: {self.context['module_status']}")

        return self.context

    def _safe_run(self, step_name, fn, *args):
        """安全执行：异常不中断整体流程"""
        try:
            fn(*args)
            self.context['module_status'][step_name] = 'ok'
        except Exception as e:
            print(f"[Orchestrator] ⚠️ {step_name} 异常: {e}")
            traceback.print_exc()
            self.context['module_status'][step_name] = f'error: {str(e)[:100]}'

    def _step_settle(self):
        """结算 + 贝叶斯后验更新"""
        self.engine.settle()
        # 贝叶斯用昨日开奖数据更新先验→后验
        self.bayesian.update_from_settlement(self.db)

    def _step_entropy(self, history_data):
        """信息熵检测"""
        if not history_data:
            return
        for game in ['ssq', 'dlt', 'qxc']:
            game_data = history_data.get(game, [])
            if not game_data:
                continue
            is_anomalous, ratio = self.entropy.is_anomalous(
                game_data,
                self._get_number_range(game),
                self._get_extract_fn(game)
            )
            self.context['entropy_ratio'] = ratio
            if is_anomalous:
                self.context['mode'] = 'aggressive'
            elif ratio > 0.95:
                self.context['mode'] = 'conservative'
            else:
                self.context['mode'] = 'normal'

    def _step_markov(self, history_data):
        """马尔可夫转移矩阵更新"""
        if not history_data:
            return
        for game in ['ssq', 'dlt', 'qxc']:
            game_data = history_data.get(game, [])
            if not game_data:
                continue
            self.markov.fit(game, game_data, self._get_number_range(game), self._get_extract_fn(game))
            signals = self.markov.get_transition_signals(game, game_data, self._get_number_range(game), self._get_extract_fn(game))
            self.context['markov_signals'][game] = signals

    def _step_evolve(self, history_data):
        """GEPA进化（受context影响）"""
        # 根据模式调整进化参数
        mode = self.context.get('mode', 'normal')
        if mode == 'conservative':
            # 保守模式：缩小进化步长
            self.engine.gepa.step_size = max(0.01, self.engine.gepa.step_size * 0.5)
        elif mode == 'aggressive':
            # 激进模式：扩大进化步长
            self.engine.gepa.step_size = min(0.05, self.engine.gepa.step_size * 1.5)

        # 调用原有evolve（参数由调用方传入）
        # 这里只做模式适配，实际evolve由lottery_analyzer调用
        pass

    def _step_stacking(self, history_data):
        """Stacking集成预测"""
        if not history_data:
            return
        for game in ['ssq', 'dlt', 'qxc']:
            game_data = history_data.get(game, [])
            if len(game_data) < 30:
                continue
            self.stacking.fit(game, game_data)

    def _step_validate(self, history_data):
        """蒙特卡洛验证"""
        if not history_data:
            return
        # 简化：用历史数据做蒙特卡洛验证
        for game in ['ssq', 'dlt', 'qxc']:
            game_data = history_data.get(game, [])
            if len(game_data) < 10:
                continue
            confidence = self.monte_carlo.validate(game, game_data, n_simulations=500)
            self.context['confidence'][game] = confidence

    def _save_context(self, date):
        """保存context快照到DB"""
        try:
            conn = self.db._get_conn()
            c = conn.cursor()
            # 确保表存在
            c.execute('''CREATE TABLE IF NOT EXISTS algo_orchestrator_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                context TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(date))''')
            c.execute('''INSERT OR REPLACE INTO algo_orchestrator_context (date, context, created_at)
                         VALUES (?, ?, ?)''',
                      (date, json.dumps(self.context, ensure_ascii=False, default=str), _now_cst().isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Orchestrator] 保存context失败: {e}")

    @staticmethod
    def _get_number_range(game):
        """各玩法号码范围"""
        if game == 'ssq':
            return list(range(1, 34))  # 红球
        elif game == 'dlt':
            return list(range(1, 36))  # 前区
        elif game == 'qxc':
            return list(range(10))     # 每位0-9
        return []

    @staticmethod
    def _get_extract_fn(game):
        """各玩法号码提取函数（从history_item中提取号码）"""
        if game == 'ssq':
            return lambda d: d.get('reds', d.get('numbers', []))
        elif game == 'dlt':
            return lambda d: d.get('front', d.get('numbers', []))
        elif game == 'qxc':
            return lambda d: d.get('digits', d.get('numbers', []))
        return lambda d: d.get('numbers', [])

    def _fetch_history(self):
        """从网络拉取历史开奖数据
        
        Returns:
            dict: {game: [draws]}  各玩法历史数据
        """
        history = {}
        try:
            from lottery_analyzer import fetch_ssq_history, fetch_dlt_history, fetch_qxc_history
            print("[Orchestrator] 拉取历史数据...")
            
            for game, fetch_fn in [('ssq', fetch_ssq_history), ('dlt', fetch_dlt_history), ('qxc', fetch_qxc_history)]:
                try:
                    data = fetch_fn(periods=50)
                    if data:
                        history[game] = data
                        print(f"[Orchestrator] {game}: {len(data)}期历史数据")
                    else:
                        print(f"[Orchestrator] {game}: 无数据")
                except Exception as e:
                    print(f"[Orchestrator] {game} 数据拉取失败: {e}")
                    
        except ImportError:
            print("[Orchestrator] ⚠️ lottery_analyzer不可用，新模块将跳过历史数据分析")
        
        return history


def run_orchestrator_daily():
    """便捷入口"""
    orch = AlgoOrchestrator()
    orch.daily_run()


if __name__ == '__main__':
    print("=" * 50)
    print("刘海蟾点金 - 算法统筹管理器 v3.0 自检")
    print("=" * 50)
    orch = AlgoOrchestrator()
    print(f"✓ AlgoEngine: 已加载")
    print(f"✓ AlgoDB: {orch.db.db_path}")
    print(f"✓ Context: {orch.context}")
    print("\n自检通过 ✓")
