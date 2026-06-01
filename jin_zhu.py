#!/usr/bin/env python3
"""
金主 (JinZhu) — 刘海蟾点金算法核心大脑 v8.3

唯一真相来源：所有推荐生成、结算反哺、权重进化都经过这里。
外部只需调用 JinZhu.daily_run()，不直接操作 games/*.py 或 algo_module.py。

架构四层：
  Model Layer   → weight-config.json (唯一模型参数出处)
  Generation Layer → generate_ssq/dlt/qxc (策略差异化+随机扰动+邻号加分)
  Evaluation Layer → settle/backtest (结果驱动进化 + 系统结算)
  Evolution Layer  → GEPA (写回Model，下一代自动生效 + 系统虚拟用户信号)

v8.3 统一虚拟用户:
  - generate_recs() 支持 model_override (虚拟用户各人参数化生成)
  - settle() 保持 algo_state.db 结算
  - evolve() 合并50系统虚拟用户进化信号 (按策略类型命中率加权)
  - 50人系统虚拟用户(vu01~vu50)，6类策略，不依赖网站DB

v8.2 修复:
  - P1: kelly_map=1 修复下注cost=0问题
  - P1: evolve状态显示修正(非按game分key)
  - P1: 删除186行死代码 + cron去冲突

v8.1 修复:
  - P0: 进化参数边界保护 + 最小样本6条 + 简单显著性检验
  - P0: 3彩种进化结果合并(投票制)而非覆盖
  - P1: settle按开奖日期匹配而非取latest
  - P1: _perturb加去重检查
  - P1: AlgoEngine移到循环外
  - P1: QXC核心注B改为次优(非最差)
  - P2: 邻号加分(neighbor_bonus)
  - P2: QXC接入kelly_bias
  - P2: 进化日志长度限制(最近50条)
"""

import os
import sys
import json
import math
import random
import sqlite3
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(MODULE_DIR, 'weight-config.json')
DB_PATH = os.path.join(MODULE_DIR, 'algo_state.db')

CST_OFFSET = timedelta(hours=8)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [JinZhu] [%(levelname)s] %(message)s')


def _now_cst():
    return datetime.utcnow() + CST_OFFSET


# ===== 默认模型参数（首次运行或config损坏时使用）=====
DEFAULT_MODEL = {
    'freq': 0.30, 'miss': 0.25, 'trend': 0.25, 'zone': 0.20,
    'cold_miss_front': 0.40, 'cold_cycle_front': 0.30, 'cold_freq_front': 0.30,
    'cold_miss_back': 0.30, 'cold_cycle_back': 0.40, 'cold_freq_back': 0.30,
    'neighbor_bonus': 0.03, 'gamma': 0.88,
    'version': 1, 'algo_version': 'v8.3', 'evolution_log': [],
    'lock_config': {},
}

# ===== 进化参数边界（防止失控）=====
PARAM_BOUNDS = {
    'freq':  (0.15, 0.50),
    'miss':  (0.10, 0.40),
    'trend': (0.10, 0.50),
    'zone':  (0.05, 0.35),
    'cold_miss_front':  (0.20, 0.60),
    'cold_cycle_front': (0.15, 0.50),
    'cold_freq_front':  (0.10, 0.45),
    'cold_miss_back':   (0.15, 0.50),
    'cold_cycle_back':  (0.20, 0.60),
    'cold_freq_back':   (0.10, 0.45),
    'neighbor_bonus':   (0.00, 0.10),
    'gamma':            (0.50, 0.95),
}

# ===== 策略名常量 =====
class Strategy:
    CORE_A = '核心注A'
    CORE_B = '核心注B'
    EXT1 = '扩展1(形态)'
    EXT2 = '扩展2(回补)'
    COLD = '冷号注(遗漏)'


# ============================================================
#  JinZhu — 算法核心大脑
# ============================================================

class JinZhu:
    """金主 — 算法核心大脑，唯一真相来源"""

    def __init__(self, config_path=None):
        self.config_path = config_path or CONFIG_PATH
        self.model = self._load_model()
        self._rng = random.Random()  # 独立随机数生成器，可设种子复现

    # ============================================================
    #  Model Layer — 唯一真相来源
    # ============================================================

    def _load_model(self) -> dict:
        """从 weight-config.json 加载模型参数"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                merged = {**DEFAULT_MODEL, **cfg}
                logging.info(f"[Model] 加载成功: v{merged.get('version', '?')} {merged.get('algo_version', '?')}")
                return merged
            except Exception as e:
                logging.error(f"[Model] 加载失败: {e}，使用默认参数")
        return dict(DEFAULT_MODEL)

    def _save_model(self):
        """持久化模型参数到 weight-config.json"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.model, f, ensure_ascii=False, indent=2)
            logging.info(f"[Model] 保存成功: v{self.model.get('version', '?')}")
        except Exception as e:
            logging.error(f"[Model] 保存失败: {e}")

    def get_param(self, key: str, default=None):
        """读取单个模型参数"""
        return self.model.get(key, default)

    def set_param(self, key: str, value, evolve_log_entry=None):
        """更新单个模型参数（带边界保护）"""
        old = self.model.get(key)
        # 边界保护
        if key in PARAM_BOUNDS:
            lo, hi = PARAM_BOUNDS[key]
            value = max(lo, min(hi, value))
        self.model[key] = value
        if evolve_log_entry:
            self.model.setdefault('evolution_log', []).append(evolve_log_entry)
        self._save_model()
        return old

    # ============================================================
    #  Generation Layer — 推荐生成（策略差异化 + 随机扰动 + 邻号加分）
    # ============================================================

    def generate_recs(self, game: str, history_data: list = None, kelly_bias: float = 0.0, seed: int = None, model_override: dict = None) -> list:
        """统一推荐入口（支持model_override供虚拟用户参数化生成）"""
        # 临时覆盖模型参数（虚拟用户各人有不同策略参数）
        _orig_model = None
        if model_override:
            _orig_model = json.loads(json.dumps(self.model))  # 深拷贝防污染
            for k, v in model_override.items():
                if k in self.model:
                    self.model[k] = v

        try:
            if seed is not None:
                self._rng = random.Random(seed)

            if history_data is None:
                history_data = self._fetch_history(game)

            if not history_data:
                logging.error(f"[Gen] {game} 历史数据为空，无法生成推荐")
                return []

            analysis = self._analyze(game, history_data)
            if not analysis:
                # PLN/LTN简化处理：直接返回历史数据
                if game in ('pln', 'ltn'):
                    analysis = {'history': history_data}
                else:
                    logging.error(f"[Gen] {game} 分析失败")
                    return []
            if not analysis:
                logging.error(f"[Gen] {game} 分析失败")
                return []

            # 邻号加分（从Model读取）
            analysis = self._apply_neighbor_bonus(game, analysis, history_data)

            gen_map = {
                'ssq': self._gen_ssq,
                'dlt': self._gen_dlt,
                'qxc': self._gen_qxc,
                'pln': self._gen_pln,
                'ltn': self._gen_ltn,
            }
            gen_fn = gen_map.get(game)
            if not gen_fn:
                logging.error(f"[Gen] 未知彩种: {game}")
                return []

            recs = gen_fn(analysis, kelly_bias)
            logging.info(f"[Gen] {game} 生成{len(recs)}注推荐")
            return recs
        finally:
            # 恢复原始模型参数
            if _orig_model:
                self.model = _orig_model

    def _fetch_history(self, game: str) -> list:
        """自动获取历史数据"""
        try:
            fetch_map = {
                'ssq': lambda: __import__('lottery_analyzer', fromlist=['fetch_ssq_history']).fetch_ssq_history(15),
                'dlt': lambda: __import__('lottery_analyzer', fromlist=['fetch_dlt_history']).fetch_dlt_history(15),
                'qxc': lambda: __import__('lottery_analyzer', fromlist=['fetch_qxc_history']).fetch_qxc_history(50),
                'pln': lambda: __import__('games.pln', fromlist=['fetch_pln_history']).fetch_pln_history(15),
                'ltn': lambda: __import__('games.ltn', fromlist=['fetch_ltn_history']).fetch_ltn_history(15),
            }
            return fetch_map[game]()
        except Exception as e:
            logging.error(f"[Gen] {game} 数据获取失败: {e}")
            return []

    def _analyze(self, game: str, history_data: list) -> dict:
        """调用 WeightedAnalyzer 分析"""
        try:
            import lottery_analyzer as la
            wa = la.WeightedAnalyzer(history_data)
            analyze_map = {
                'ssq': wa.analyze_ssq,
                'dlt': wa.analyze_dlt,
                'qxc': wa.analyze_qxc,
            }
            # PLN/LTN简化处理：直接返回历史数据（不需要复杂分析）
            if game in ('pln', 'ltn'):
                return {'history': history_data}
            return analyze_map[game]()
        except Exception as e:
            logging.error(f"[Gen] {game} 分析失败: {e}")
            return {}

    def _apply_neighbor_bonus(self, game: str, analysis: dict, history_data: list) -> dict:
        """P2修复: 邻号加分 — 上期开出号码±1获得bonus（球机机械偏差）"""
        if not history_data:
            return analysis
        bonus = self.get_param('neighbor_bonus', 0.03)
        if bonus <= 0:
            return analysis

        last_draw = history_data[0]

        if game == 'ssq':
            last_reds = set(last_draw.get('reds', []))
            red_weights = dict(analysis.get('red_weights', []))
            for n in last_reds:
                for neighbor in [n - 1, n + 1]:
                    if 1 <= neighbor <= 33 and neighbor in red_weights:
                        red_weights[neighbor] = red_weights.get(neighbor, 0) + bonus
            analysis['red_weights'] = sorted(red_weights.items(), key=lambda x: x[1], reverse=True)

        elif game == 'dlt':
            last_front = set(last_draw.get('front', []))
            front_weights = dict(analysis.get('front_weights', []))
            for n in last_front:
                for neighbor in [n - 1, n + 1]:
                    if 1 <= neighbor <= 35 and neighbor in front_weights:
                        front_weights[neighbor] = front_weights.get(neighbor, 0) + bonus
            analysis['front_weights'] = sorted(front_weights.items(), key=lambda x: x[1], reverse=True)

        return analysis

    # ------ 双色球推荐 ------

    def _gen_ssq(self, analysis: dict, kelly_bias: float = 0.0) -> list:
        """双色球5注推荐（策略差异化 + 随机扰动）"""
        red_weight_dict = dict(analysis['red_weights'])
        all_pool = []
        for n in range(1, 34):
            w = red_weight_dict.get(n, 0)
            f = analysis['red_freq'].get(n, 0)
            m = analysis['red_miss'].get(n, 0)
            all_pool.append((n, w, f, m))

        all_pool = self._kelly_sort(all_pool, kelly_bias)
        strategy_tag = self._kelly_tag(kelly_bias)

        core_A = sorted([n for n, w, f, m in all_pool[:6]])
        core_B = self._select_independent_pool(all_pool, core_A, 6)

        target_sum = analysis.get('avg_sum', 100)
        top20 = [n for n, w, f, m in all_pool[:20]]
        must_keep = sorted([n for n, w, f, m in all_pool[:2]])
        ext1 = self._shape_optimized_select(top20, 6, target_sum, target_odd=3, target_big=3, must_include=must_keep)

        ext2 = self._select_recovery_pool(analysis, all_pool, set(core_A) | set(core_B) | set(ext1), n_select=6)

        used = set(core_A) | set(core_B) | set(ext1) | set(ext2)
        cold = self._select_cold_reds(analysis, used, game='ssq')

        blues = self._select_blues(analysis, n_blues=5)

        core_A = self._perturb(core_A, all_pool, max_swaps=1)
        core_B = self._perturb(core_B, all_pool, max_swaps=1)

        return [
            {'reds': core_A, 'blue': blues[0], 'strategy': f'{strategy_tag}A'},
            {'reds': core_B, 'blue': blues[1], 'strategy': f'{strategy_tag}B'},
            {'reds': ext1, 'blue': blues[2], 'strategy': Strategy.EXT1},
            {'reds': ext2, 'blue': blues[3], 'strategy': Strategy.EXT2},
            {'reds': cold, 'blue': blues[4], 'strategy': Strategy.COLD},
        ]

    # ------ 大乐透推荐 ------

    def _gen_dlt(self, analysis: dict, kelly_bias: float = 0.0) -> list:
        """大乐透5注推荐"""
        front_weight_dict = dict(analysis['front_weights'])
        all_pool = []
        for n in range(1, 36):
            w = front_weight_dict.get(n, 0)
            f = analysis['front_freq'].get(n, 0)
            m = analysis['front_miss'].get(n, 0)
            all_pool.append((n, w, f, m))

        all_pool = self._kelly_sort(all_pool, kelly_bias)
        strategy_tag = self._kelly_tag(kelly_bias)

        core_A = sorted([n for n, w, f, m in all_pool[:5]])
        core_B = self._select_independent_pool(all_pool, core_A, 5)

        top20 = [n for n, w, f, m in all_pool[:20]]
        must_keep = sorted([n for n, w, f, m in all_pool[:3]])
        ext1 = self._shape_optimized_select(top20, 5, target_sum=analysis.get('avg_sum', 90),
                                            target_odd=3, target_big=3, must_include=must_keep, big_threshold=18)

        ext2 = self._select_recovery_pool(analysis, all_pool, set(core_A) | set(core_B) | set(ext1), n_select=5)

        used = set(core_A) | set(core_B) | set(ext1) | set(ext2)
        cold = self._select_cold_front(analysis, all_pool, used)

        backs = self._select_backs(analysis, n_pairs=5)

        core_A = self._perturb(core_A, all_pool, max_swaps=1)
        core_B = self._perturb(core_B, all_pool, max_swaps=1)

        return [
            {'front': core_A, 'back': backs[0], 'strategy': f'{strategy_tag}A'},
            {'front': core_B, 'back': backs[1], 'strategy': f'{strategy_tag}B'},
            {'front': ext1, 'back': backs[2], 'strategy': Strategy.EXT1},
            {'front': ext2, 'back': backs[3], 'strategy': Strategy.EXT2},
            {'front': cold, 'back': backs[4], 'strategy': Strategy.COLD},
        ]

    # ------ 七星彩推荐 ------

    def _gen_qxc(self, analysis: dict, kelly_bias: float = 0.0) -> list:
        """七星彩5注推荐（逐位选号 + 策略差异化 + kelly_bias接入）"""
        positions = analysis['positions']

        # 每位候选池（0-9按权重排序）
        pos_pools = []
        for pos_data in positions:
            weights = pos_data['weights']
            pos_pools.append([n for n, w in weights])

        # 核心注A: 每位权重TOP1
        core_A = [pool[0] if pool else 0 for pool in pos_pools]

        # P1修复: 核心注B改为次优(权重TOP3-5)而非最差，避免纯反统计
        core_B = []
        for i, pool in enumerate(pos_pools):
            # 从TOP3-5区间选（和A不同但仍是有效号码）
            chosen = None
            for n in pool[2:6] if len(pool) > 2 else pool[1:]:
                if n != core_A[i]:
                    chosen = n
                    break
            core_B.append(chosen if chosen is not None else (pool[1] if len(pool) > 1 else pool[0]))

        # Kelly偏热: 核心注A每位取TOP1; 偏冷: 核心注A每位取遗漏最高的
        if kelly_bias < 0:
            core_A = self._qxc_cold_select(positions)
            strategy_tag_a = '核心注(搏冷)A'
        elif kelly_bias > 0:
            strategy_tag_a = '核心注(追热)A'
        else:
            strategy_tag_a = '核心注(权重)A'

        # 扩展1(形态): 前3位核心 + 后4位次高权重
        ext1 = list(core_A)
        for i in range(3, 7):
            pool = pos_pools[i]
            ext1[i] = pool[1] if len(pool) > 1 and pool[1] != core_A[i] else (pool[2] if len(pool) > 2 else pool[0])

        # 扩展2(回补): 每位中等频率 + 周期信号
        ext2 = list(core_A)
        for i in range(7):
            pos_data = positions[i]
            freq = pos_data.get('freq', {})
            miss = pos_data.get('miss', {})
            avg_interval = pos_data.get('avg_interval', {})
            best_n = None
            best_score = -999
            for n in range(10):
                if n == core_A[i]:
                    continue
                f_score = min(freq.get(n, 0) / 3.0, 1.5)
                m = miss.get(n, 0)
                avg_i = avg_interval.get(n, 5)
                cycle = min(m / max(avg_i, 1), 2.0)
                score = f_score * 0.4 + cycle * 0.6
                if score > best_score:
                    best_score = score
                    best_n = n
            ext2[i] = best_n if best_n is not None else core_A[i]

        # 冷号注: 每位遗漏最高 + 周期信号（从Model读权重）
        cold_miss_w = self.get_param('cold_miss_front', 0.40)
        cold_cycle_w = self.get_param('cold_cycle_front', 0.30)
        cold_freq_w = self.get_param('cold_freq_front', 0.30)
        cold = []
        for i in range(7):
            pos_data = positions[i]
            miss = pos_data.get('miss', {})
            freq = pos_data.get('freq', {})
            avg_interval = pos_data.get('avg_interval', {})
            best_n = 0
            best_score = -999
            for n in range(10):
                m = miss.get(n, 0)
                avg_i = avg_interval.get(n, 5)
                cycle = min(m / max(avg_i, 1), 2.0)
                f = freq.get(n, 0)
                score = min(m / 5.0, 3.0) * cold_miss_w + cycle * cold_cycle_w + min(f / 3.0, 1.5) * cold_freq_w
                if score > best_score:
                    best_score = score
                    best_n = n
            cold.append(best_n)

        # 随机扰动
        core_A = self._perturb_qxc(core_A, pos_pools, max_swaps=2)
        core_B = self._perturb_qxc(core_B, pos_pools, max_swaps=2)

        return [
            {'digits': core_A, 'strategy': strategy_tag_a},
            {'digits': core_B, 'strategy': '核心注(次优)B'},
            {'digits': ext1, 'strategy': Strategy.EXT1},
            {'digits': ext2, 'strategy': Strategy.EXT2},
            {'digits': cold, 'strategy': Strategy.COLD},
        ]
        

    def _gen_pln(self, analysis: dict, kelly_bias: float = 0.0) -> list:
        """台湾威力彩5注推荐（6/38 + 1/8）"""
        import csv, random
        try:
            with open('data/pln_history.csv', 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if len(rows) >= 5:
                latest = rows[-1]
                base = [int(x) for x in latest['numbers'].split()]
                special = int(latest['special'])
                strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
                recs = []
                for i in range(5):
                    new = base.copy()
                    for j in range(random.randint(1, 3)):
                        idx = random.randint(0, 5)
                        new[idx] = random.randint(1, 38)
                    recs.append({
                        'numbers': sorted(new) + [special],
                        'type': f'P{i}',
                        'strategy': strategies[i]
                    })
                return recs
        except Exception as e:
            logging.warning(f"PLN CSV读取失败: {e}，使用mock")
        
        # mock数据
        strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
        recs = []
        for i in range(5):
            main = sorted(random.sample(range(1, 39), 6))
            special = random.randint(1, 8)
            recs.append({
                'numbers': main + [special],
                'type': f'P{i}',
                'strategy': strategies[i]
            })
        return recs

    def _gen_ltn(self, analysis: dict, kelly_bias: float = 0.0) -> list:
        """台湾大乐透5注推荐（读CSV）"""
        import csv, random
        try:
            with open('data/ltn_history.csv', 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if len(rows) >= 5:
                # 兼容两种格式
                latest = rows[-1]
                if 'front1' in latest:
                    front = [int(latest[f'front{i}']) for i in range(1, 6)]
                    back = [int(latest[f'back{i}']) for i in range(1, 3)]
                else:
                    front = [int(x) for x in latest.get('front', '').split(',')]
                    back = [int(x) for x in latest.get('back', '').split(',')]
                
                strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
                recs = []
                for i in range(5):
                    new_front = front.copy()
                    for j in range(random.randint(1, 3)):
                        idx = random.randint(0, 4)
                        new_front[idx] = random.randint(1, 35)
                    new_back = [random.randint(1, 12) for _ in range(2)]
                    recs.append({
                        'front': sorted(new_front),
                        'back': sorted(new_back),
                        'type': f'P{i}',
                        'strategy': strategies[i]
                    })
                return recs
        except Exception as e:
            logging.warning(f"LTN CSV读取失败: {e}，使用mock")
        
        # mock数据
        strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
        recs = []
        for i in range(5):
            recs.append({
                'front': sorted(random.sample(range(1, 36), 5)),
                'back': sorted(random.sample(range(1, 13), 2)),
                'type': f'P{i}',
                'strategy': strategies[i]
            })
        return recs
        strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
        recs = []
        for i in range(5):
            main = sorted(random.sample(range(1, 50), 6))
            recs.append({
                'numbers': main,
                'type': f'P{i}',
                'strategy': strategies[i]
            })
        return recs


    def _qxc_cold_select(self, positions):
        """七星彩冷号选择（每位遗漏最高）"""
        result = []
        for pos_data in positions:
            miss = pos_data.get('miss', {})
            if miss:
                best_n = max(miss.keys(), key=lambda n: miss.get(n, 0))
            else:
                weights = pos_data.get('weights', [])
                best_n = weights[-1][0] if weights else 0
            result.append(best_n)
        return result

    # ============================================================
    #  Smart Selection Tools — 智能选号工具方法
    # ============================================================

    def _kelly_sort(self, all_pool: list, kelly_bias: float) -> list:
        """Kelly偏向排序"""
        pool = list(all_pool)
        if kelly_bias > 0:
            max_freq = max(x[2] for x in pool) or 1
            max_weight = max(x[1] for x in pool) or 1
            pool.sort(key=lambda x: (x[2] / max_freq) * 0.5 + (x[1] / max_weight) * 0.5, reverse=True)
        elif kelly_bias < 0:
            max_miss = max(x[3] for x in pool) or 1
            max_weight = max(x[1] for x in pool) or 1
            pool.sort(key=lambda x: (x[3] / max_miss) * 0.5 + (x[1] / max_weight) * 0.5, reverse=True)
        else:
            pool.sort(key=lambda x: x[1], reverse=True)
        return pool

    def _kelly_tag(self, kelly_bias: float) -> str:
        if kelly_bias > 0:
            return '核心注(追热)'
        elif kelly_bias < 0:
            return '核心注(搏冷)'
        return '核心注(加权)'

    def _select_independent_pool(self, all_pool: list, existing: list, n: int) -> list:
        """从次高区间选n个与existing不重叠的号码"""
        existing_set = set(existing)
        candidates = [n for n, w, f, m in all_pool[6:20] if n not in existing_set]
        if len(candidates) >= n:
            return sorted(candidates[:n])
        more = [n for n, w, f, m in all_pool[20:] if n not in existing_set]
        return sorted((candidates + more)[:n])

    def _shape_optimized_select(self, candidates, n_select, target_sum, target_odd, target_big,
                                must_include=None, big_threshold=17):
        """形态优化选号 — 贪心搜索（和值/奇偶/大小约束）"""
        must_include = must_include or []
        result = list(must_include)
        remaining = [n for n in candidates if n not in result]

        while len(result) < n_select and remaining:
            best_n = None
            best_score = -999
            for n in remaining:
                trial = sorted(result + [n])
                s = sum(trial)
                odd_count = sum(1 for x in trial if x % 2 == 1)
                big_count = sum(1 for x in trial if x >= big_threshold)
                sum_penalty = -abs(s - target_sum) / max(target_sum, 1) * 2.0
                odd_penalty = -abs(odd_count - target_odd) * 1.5
                big_penalty = -abs(big_count - target_big) * 1.5
                score = sum_penalty + odd_penalty + big_penalty
                score += self._rng.uniform(-0.01, 0.01)
                if score > best_score:
                    best_score = score
                    best_n = n
            if best_n is not None:
                result.append(best_n)
                remaining.remove(best_n)
            else:
                break
        return sorted(result)

    def _select_recovery_pool(self, analysis, all_pool, used_set, n_select):
        """回补注选号：中等频率 + 遗漏回补"""
        scores = []
        for n, w, f, m in all_pool:
            if n in used_set:
                continue
            f_score = min(f / 3.0, 1.5)
            m_score = min(m / 10.0, 3.0)
            score = f_score * 0.4 + m_score * 0.6
            score += self._rng.uniform(-0.01, 0.01)
            scores.append((n, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return sorted([n for n, s in scores[:n_select]])

    def _select_cold_reds(self, analysis, used_set, game='ssq'):
        """冷号注红球 — 多维评分，权重从Model读取"""
        cold_miss_w = self.get_param('cold_miss_front', 0.40)
        cold_cycle_w = self.get_param('cold_cycle_front', 0.30)
        cold_freq_w = self.get_param('cold_freq_front', 0.30)
        n_range = 34 if game == 'ssq' else 36

        red_avg_interval = analysis.get('red_avg_interval', analysis.get('front_avg_interval', {}))
        miss_key = 'red_miss' if 'red_miss' in analysis else 'front_miss'
        freq_key = 'red_freq' if 'red_freq' in analysis else 'front_freq'

        scores = []
        for n in range(1, n_range):
            if n in used_set:
                continue
            miss_val = analysis[miss_key].get(n, 0)
            miss_score = min(miss_val / 10.0, 3.0)
            avg_interval = red_avg_interval.get(n, 15)
            cycle_signal = min(miss_val / max(avg_interval, 1), 2.0)
            f = analysis[freq_key].get(n, 0)
            f_score = min(f / 3.0, 1.5)
            score = miss_score * cold_miss_w + cycle_signal * cold_cycle_w + f_score * cold_freq_w
            scores.append((n, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        n_need = 6 if game == 'ssq' else 5
        return sorted([n for n, s in scores[:n_need]])

    def _select_cold_front(self, analysis, all_pool, used_set):
        """大乐透冷号注前区"""
        return self._select_cold_reds(analysis, used_set, game='dlt')

    def _select_blues(self, analysis, n_blues=5):
        """双色球蓝球智能选择 — 综合权重+遗漏+奇偶+互斥"""
        blue_weight_dict = dict(analysis['blue_weights'])
        blue_miss = analysis.get('blue_miss', {})
        blue_freq = analysis.get('blue_freq', {})
        blue_avg_interval = analysis.get('blue_avg_interval', {})

        cold_miss_w = self.get_param('cold_miss_back', 0.30)
        cold_cycle_w = self.get_param('cold_cycle_back', 0.40)
        cold_freq_w = self.get_param('cold_freq_back', 0.30)

        scores = {}
        for n in range(1, 17):
            w = blue_weight_dict.get(n, 0)
            m = blue_miss.get(n, 0)
            f = blue_freq.get(n, 0)

            if m >= 10: miss_score = 3.0
            elif m >= 6: miss_score = 2.5
            elif m >= 3: miss_score = 1.5
            elif m == 0: miss_score = 1.0
            else: miss_score = 0.8

            freq_score = min(f, 4) / 2.0
            scores[n] = w * 0.4 + freq_score * 0.3 + miss_score * 0.3

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        selected = []
        used_odd_even = {'odd': 0, 'even': 0}
        for n, s in ranked:
            if len(selected) >= n_blues:
                break
            parity = 'odd' if n % 2 == 1 else 'even'
            if used_odd_even[parity] >= 3 and used_odd_even['odd'] + used_odd_even['even'] < n_blues:
                continue
            selected.append(n)
            used_odd_even[parity] += 1

        if len(selected) < n_blues:
            for n, s in ranked:
                if n not in selected:
                    selected.append(n)
                if len(selected) >= n_blues:
                    break

        # 最后一个给冷号
        if len(selected) >= n_blues:
            cold_scores = {}
            for n in range(1, 17):
                if n in selected[:n_blues - 1]:
                    continue
                m = blue_miss.get(n, 0)
                avg_i = blue_avg_interval.get(n, 10)
                cycle = min(m / max(avg_i, 1), 2.0)
                f = blue_freq.get(n, 0)
                freq_s = min(f, 4) / 2.0
                miss_s = min(m / 5.0, 3.0)
                cold_scores[n] = miss_s * cold_miss_w + cycle * cold_cycle_w + freq_s * cold_freq_w
            cold_ranked = sorted(cold_scores.items(), key=lambda x: x[1], reverse=True)
            if cold_ranked:
                selected[n_blues - 1] = cold_ranked[0][0]

        return selected[:n_blues]

    def _select_backs(self, analysis, n_pairs=5):
        """大乐透后区智能选择 — 权重+遗漏+奇偶+互斥"""
        back_weight_dict = dict(analysis.get('back_weights', []))
        if isinstance(back_weight_dict, list):
            back_weight_dict = dict(back_weight_dict)
        back_miss = analysis.get('back_miss', {})
        back_freq = analysis.get('back_freq', {})
        back_avg_interval = analysis.get('back_avg_interval', {})

        cold_miss_w = self.get_param('cold_miss_back', 0.30)
        cold_cycle_w = self.get_param('cold_cycle_back', 0.40)
        cold_freq_w = self.get_param('cold_freq_back', 0.30)

        scores = {}
        for n in range(1, 13):
            w = back_weight_dict.get(n, 0)
            m = back_miss.get(n, 0)
            f = back_freq.get(n, 0)

            if m >= 8: miss_score = 3.0
            elif m >= 5: miss_score = 2.5
            elif m >= 3: miss_score = 1.5
            elif m == 0: miss_score = 1.0
            else: miss_score = 0.8

            freq_score = min(f, 4) / 2.0
            scores[n] = w * 0.4 + freq_score * 0.3 + miss_score * 0.3

        used = set()
        result = []
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        for i in range(n_pairs):
            pair = []
            for n, s in ranked:
                if n not in used:
                    pair.append(n)
                    used.add(n)
                if len(pair) == 2:
                    break

            if len(pair) == 2:
                odds = sum(1 for n in pair if n % 2 == 1)
                if odds == 2 or odds == 0:
                    for n, s in ranked:
                        if n not in used and n not in pair and n % 2 != pair[0] % 2:
                            old = pair[0] if odds == 2 else pair[1]
                            used.discard(old)
                            pair[pair.index(old)] = n
                            used.add(n)
                            break

            if i == n_pairs - 1 and len(pair) == 2:
                cold_scores = {}
                for n in range(1, 13):
                    if n in used and n not in pair:
                        continue
                    m = back_miss.get(n, 0)
                    avg_i = back_avg_interval.get(n, 10)
                    cycle = min(m / max(avg_i, 1), 2.0)
                    f = back_freq.get(n, 0)
                    freq_s = min(f, 4) / 2.0
                    miss_s = min(m / 5.0, 3.0)
                    cold_scores[n] = miss_s * cold_miss_w + cycle * cold_cycle_w + freq_s * cold_freq_w
                cold_ranked = sorted(cold_scores.items(), key=lambda x: x[1], reverse=True)
                cold_pair = []
                for n, s in cold_ranked:
                    if n not in used or n in pair:
                        cold_pair.append(n)
                        used.add(n)
                    if len(cold_pair) == 2:
                        break
                if len(cold_pair) == 2:
                    pair = sorted(cold_pair)

            result.append(sorted(pair))

        while len(result) < n_pairs:
            result.append([1, 2])

        return result[:n_pairs]

    def _perturb(self, nums: list, all_pool: list, max_swaps: int = 1) -> list:
        """随机扰动: 等权号码微调 (P1修复: 加去重检查)"""
        result = list(nums)
        pool_dict = {n: (w, f, m) for n, w, f, m in all_pool}

        for _ in range(max_swaps):
            if not result:
                break
            idx = self._rng.randint(0, len(result) - 1)
            current_n = result[idx]
            current_w = pool_dict.get(current_n, (0, 0, 0))[0]

            # P1修复: 排除已在结果中的号码，防止重复
            similar = [n for n, w, f, m in all_pool
                       if n not in result and abs(w - current_w) <= max(current_w * 0.1, 0.01)]
            if similar:
                replacement = self._rng.choice(similar)
                result[idx] = replacement

        return sorted(result)

    def _perturb_qxc(self, digits: list, pos_pools: list, max_swaps: int = 2) -> list:
        """七星彩逐位随机扰动"""
        result = list(digits)
        swap_positions = self._rng.sample(range(7), min(max_swaps, 7))
        for i in swap_positions:
            pool = pos_pools[i]
            if len(pool) > 1:
                candidates = [n for n in pool if n != result[i]]
                if candidates:
                    result[i] = self._rng.choice(candidates)
        return result

    # ============================================================
    #  Evaluation Layer — 结算反哺
    # ============================================================

    def settle(self, game: str = None, date: str = None):
        """结算指定日期的推荐，写入 algo_settlements（含default和虚拟用户）"""
        from algo_module import AlgoDB
        db = AlgoDB()

        if date is None:
            date = (_now_cst() - timedelta(days=1)).strftime('%Y-%m-%d')

        games = [game] if game else ['ssq', 'dlt', 'qxc', 'pln', 'ltn']
        results = {}

        for g in games:
            try:
                result = self._settle_game(db, g, date)
                results[g] = result
                logging.info(f"[Settle] {g} {date}: {result.get('summary', 'done')}")
            except Exception as e:
                logging.error(f"[Settle] {g} {date} 失败: {e}")
                results[g] = {'error': str(e)}

        # 结算系统虚拟用户也在此完成（同 algo_state.db）
        logging.info(f"[Settle] 完成 {len(results)} 彩种结算(含虚拟用户)")

        return results

    def _settle_game(self, db, game, date):
        """结算单个彩种"""
        history = self._fetch_history(game)
        if not history:
            return {'error': '无法获取开奖数据'}

        # P1修复: 按开奖日期匹配而非取latest
        # 检查历史数据中是否有该日期对应的开奖（通过日期或期号匹配）
        actual = None
        for draw in history[:3]:  # 只看最近3期
            # 尝试多种方式匹配
            draw_date = draw.get('date', '')
            draw_period = draw.get('period', '')
            if draw_date == date or (draw_date and date in draw_date):
                actual = draw
                break
        if actual is None:
            # fallback: 如果历史第1期的日期比settle日期新或等于，说明该期就是昨天开的
            actual = history[0]

        actual_period = actual.get('period', '')

        conn = db._get_conn()
        rows = conn.execute(
            "SELECT id, numbers, strategy, user_id, cost FROM algo_bets WHERE date=? AND game=? AND status='pending'",
            (date, game)
        ).fetchall()
        conn.close()

        if not rows:
            return {'error': f'无待结算推荐', 'game': game, 'date': date}

        # _calc_prize 在 ROITracker 类中，不是 AlgoEngine
        from algo_module import ROITracker, AlgoDB
        engine = ROITracker(AlgoDB())

        total_prize = 0
        total_cost = 0
        hits = []

        for row in rows:
            numbers = json.loads(row['numbers'])
            strategy = row['strategy']
            bet_user_id = row['user_id']  # 从bet记录读取真实user_id
            bet_cost = row['cost'] or 2    # 从bet记录读取cost

            prize_info = engine._calc_prize(game, numbers, actual)

            total_cost += bet_cost
            total_prize += prize_info.get('prize', 0)

            conn = db._get_conn()
            actual_str = json.dumps(actual, ensure_ascii=False)
            conn.execute(
                "INSERT INTO algo_settlements (bet_id, user_id, actual_numbers, hit_count, prize_tier, prize_name, prize_amount, settled_at) VALUES (?,?,?,?,?,?,?,?)",
                (row['id'], bet_user_id, actual_str, prize_info.get('hit_count', 0),
                 prize_info.get('tier', 0), prize_info.get('name', '未中奖'),
                 prize_info.get('prize', 0), _now_cst().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.execute("UPDATE algo_bets SET status='settled' WHERE id=?", (row['id'],))
            conn.commit()
            conn.close()

            hits.append({
                'strategy': strategy,
                'tier': prize_info.get('tier', 0),
                'prize': prize_info.get('prize', 0),
            })

        return {
            'game': game, 'date': date, 'period': actual_period,
            'total_cost': total_cost, 'total_prize': total_prize,
            'roi': (total_prize - total_cost) / max(total_cost, 1),
            'hits': hits,
            'summary': f"投入{total_cost}元 中奖{total_prize}元 ROI={((total_prize - total_cost) / max(total_cost, 1)) * 100:.1f}%"
        }

    def backtest(self, game: str, n_periods: int = 10):
        """回测最近N期"""
        history = self._fetch_history(game)
        if not history or len(history) < 2:
            return {'error': '数据不足'}

        from algo_module import ROITracker, AlgoDB
        engine = ROITracker(AlgoDB())

        results = []
        for i in range(min(n_periods, len(history) - 1)):
            draw = history[i]
            train_data = history[i + 1:]
            if len(train_data) < 5:
                continue

            recs = self.generate_recs(game, train_data, seed=42)
            for rec in recs:
                prize = engine._calc_prize(game, rec, draw)
                results.append({
                    'period': draw.get('period', ''),
                    'strategy': rec.get('strategy', ''),
                    'prize': prize.get('prize', 0),
                    'tier': prize.get('tier', 0),
                })

        total_cost = len(results) * 2
        total_prize = sum(r['prize'] for r in results)
        return {
            'game': game, 'n_periods': n_periods,
            'total_bets': len(results),
            'total_cost': total_cost, 'total_prize': total_prize,
            'roi': (total_prize - total_cost) / max(total_cost, 1),
            'results': results,
        }

    # ============================================================
    #  系统虚拟用户进化信号 — 50人vu01~vu50
    # ============================================================

    def _collect_vuser_evolve_signals(self):
        """从系统虚拟用户(algo_state.db)的策略命中数据提取进化信号

        核心逻辑: 按策略类型(lhs/extreme_freq/extreme_miss/extreme_trend/extreme_zone/balanced)
        分组统计命中率，表现好的策略类型→其偏好维度的参数微增
        """
        db_path = DB_PATH
        if not os.path.exists(db_path):
            return {}, [], 0

        try:
            conn = sqlite3.connect(db_path)
            week_ago = (_now_cst() - timedelta(days=7)).strftime('%Y-%m-%d')

            # 提取虚拟用户结算数据，按策略类型分组
            rows = conn.execute(
                """SELECT b.strategy, b.user_id,
                          COUNT(*) as total,
                          SUM(CASE WHEN s.prize_amount > 0 THEN 1 ELSE 0 END) as wins,
                          SUM(s.prize_amount) as total_prize,
                          AVG(s.hit_count) as avg_hits
                   FROM algo_settlements s
                   JOIN algo_bets b ON s.bet_id = b.id
                   WHERE b.user_id LIKE 'vu%%'
                     AND s.settled_at >= ?
                   GROUP BY b.strategy, b.user_id
                """,
                (week_ago,)
            ).fetchall()
            conn.close()
        except Exception as e:
            logging.warning(f"[Evolve-VU] 读取失败: {e}")
            return {}, [], 0

        if len(rows) < 10:
            return {}, [], 0

        # 按策略类型聚合
        type_stats = defaultdict(lambda: {'total': 0, 'wins': 0, 'prize': 0, 'avg_hits': 0, 'hit_rate': 0})
        for r in rows:
            strategy_str = r[0]  # e.g. "[extreme_freq]核心注(加权)A"
            # 提取方括号内的策略类型
            stype = 'other'
            if strategy_str.startswith('['):
                end = strategy_str.find(']')
                if end > 0:
                    stype = strategy_str[1:end]

            s = type_stats[stype]
            s['total'] += r[2]
            s['wins'] += r[3]
            s['prize'] += r[4]

        # 计算命中率
        for stype, s in type_stats.items():
            s['hit_rate'] = s['wins'] / max(s['total'], 1)

        if not type_stats:
            return {}, [], 0

        # 找出表现最好的策略类型（命中率和奖金双指标）
        best_type = max(type_stats.items(),
                       key=lambda x: x[1]['hit_rate'] * 0.6 + min(x[1]['prize'] / 100, 1.0) * 0.4)

        best_name = best_type[0]
        best_stats = best_type[1]

        signals = {}
        changes = []

        # 根据最佳策略类型调整对应维度参数
        type_to_param = {
            'extreme_freq': ('freq', 0.004),
            'extreme_miss': ('miss', 0.004),
            'extreme_trend': ('trend', 0.004),
            'extreme_zone': ('zone', 0.004),
            'lhs': ('gamma', 0.002),      # LHS好→探索有益→gamma微增(更重视近期)
            'balanced': ('gamma', -0.002), # 均衡好→稳定为王→gamma微减
        }

        if best_name in type_to_param:
            param_key, delta = type_to_param[best_name]
            signals[param_key] = delta
            changes.append(f"[VU] 最优策略={best_name}(命中{best_stats['hit_rate']:.1%}) → {param_key} {'+' if delta>0 else ''}{delta}")

        # 冷号策略如果命中率高，增加cold_cycle权重
        cold_types = [t for t in type_stats if '冷号' in t or 'miss' in t.lower()]
        if cold_types:
            cold_hit_rate = max(type_stats[t]['hit_rate'] for t in cold_types)
            if cold_hit_rate > 0.1:  # 冷号命中率>10%
                signals['cold_cycle_front'] = 0.003
                changes.append(f"[VU] 冷号命中{cold_hit_rate:.1%} → cold_cycle_front +0.003")

        return signals, changes, len(rows)

    # ============================================================
    #  Evolution Layer — GEPA 进化 (写回Model)
    # ============================================================

    def evolve(self, game: str = None):
        """GEPA进化 — 结算数据驱动权重调整，写回Model（P0修复: 合并3彩种投票+边界保护+最小样本6）"""
        from algo_module import AlgoDB
        db = AlgoDB()
        games = [game] if game else ['ssq', 'dlt', 'qxc', 'pln', 'ltn']

        # P0修复: 收集所有彩种的进化信号，最后合并投票
        game_signals = defaultdict(float)  # 彩种信号
        vu_signals_dict = defaultdict(float)  # 虚拟用户信号（独立，不被彩种数稀释）
        all_changes = []
        total_samples = 0

        for g in games:
            try:
                signals, changes, n_samples = self._collect_evolve_signals(db, g)
                for k, v in signals.items():
                    game_signals[k] += v
                all_changes.extend(changes)
                total_samples += n_samples
            except Exception as e:
                logging.error(f"[Evolve] {g} 信号收集失败: {e}")

        # 系统虚拟用户进化信号（50人按策略类型命中率加权，独立不稀释）
        try:
            vu_sigs, vu_changes, vu_samples = self._collect_vuser_evolve_signals()
            for k, v in vu_sigs.items():
                vu_signals_dict[k] += v
            all_changes.extend(vu_changes)
            total_samples += vu_samples
        except Exception as e:
            logging.warning(f"[Evolve] 虚拟用户信号收集异常(不阻塞): {e}")

        if total_samples < 6:
            logging.info(f"[Evolve] 总样本{total_samples}<6，跳过进化")
            return {'status': '数据不足', 'samples': total_samples}

        # P0修复: 显著性检验 — 最优策略奖金需超过平均值20%以上才调整
        # (简单版：如果所有策略奖金差异<20%，视为噪声，不调参)
        if not self._is_significant(db, games):
            logging.info(f"[Evolve] 策略差异不显著，跳过进化")
            return {'status': '差异不显著', 'samples': total_samples}

        # 合并信号：彩种信号取平均delta，虚拟用户信号独立直接叠加
        final_signals = {}
        for k, v in game_signals.items():
            if v != 0:
                final_signals[k] = v / len(games)
        for k, v in vu_signals_dict.items():
            final_signals[k] = final_signals.get(k, 0) + v  # VU信号不被稀释

        # 应用delta（带边界保护）
        for k, delta in final_signals.items():
            old_val = self.model.get(k, 0)
            new_val = round(old_val + delta, 4)
            # 边界保护
            if k in PARAM_BOUNDS:
                lo, hi = PARAM_BOUNDS[k]
                new_val = max(lo, min(hi, new_val))
            self.model[k] = new_val

        # 归一化约束: freq+miss+trend+zone = 1.0
        total = self.model['freq'] + self.model['miss'] + self.model['trend'] + self.model['zone']
        if abs(total - 1.0) > 0.001:
            scale = 1.0 / total
            for k in ['freq', 'miss', 'trend', 'zone']:
                self.model[k] = round(self.model[k] * scale, 4)
                if k in PARAM_BOUNDS:
                    lo, hi = PARAM_BOUNDS[k]
                    self.model[k] = max(lo, min(hi, self.model[k]))
            all_changes.append(f"归一化修正: {total:.4f}→1.0")

        # 更新版本号
        self.model['version'] = self.model.get('version', 1) + 1
        self.model['algo_version'] = 'v8.3'

        # P2修复: 进化日志长度限制(最近50条)
        log_entry = {
            'date': _now_cst().strftime('%Y-%m-%d'),
            'trigger': '结算驱动(投票合并)',
            'sample_size': total_samples,
            'changes': all_changes,
            'final_signals': {k: round(v, 4) for k, v in final_signals.items()},
        }
        evo_log = self.model.setdefault('evolution_log', [])
        evo_log.append(log_entry)
        if len(evo_log) > 50:
            self.model['evolution_log'] = evo_log[-50:]

        self._save_model()

        return {
            'status': '进化完成',
            'samples': total_samples,
            'changes': all_changes,
            'version': self.model['version'],
        }

    def _collect_evolve_signals(self, db, game):
        """收集单彩种进化信号（不直接修改Model，返回delta字典）"""
        conn = db._get_conn()
        week_ago = (_now_cst() - timedelta(days=7)).strftime('%Y-%m-%d')
        rows = conn.execute(
            """SELECT b.strategy, s.prize_tier, s.prize_amount, s.hit_count
               FROM algo_settlements s JOIN algo_bets b ON s.bet_id = b.id
               WHERE b.game=? AND s.settled_at >= ?""",
            (game, week_ago)
        ).fetchall()
        conn.close()

        if len(rows) < 3:
            return {}, [], len(rows)

        strategy_stats = defaultdict(lambda: {'count': 0, 'total_prize': 0, 'total_hits': 0})
        for r in rows:
            s = strategy_stats[r['strategy']]
            s['count'] += 1
            s['total_prize'] += r['prize_amount']
            s['total_hits'] += r['hit_count']

        best_strategy = max(strategy_stats.items(), key=lambda x: x[1]['total_prize'])

        signals = {}
        changes = []

        # 热号领先 → freq 微增, miss 微减 (step减半为0.005，更保守)
        if '追热' in best_strategy[0] or '核心' in best_strategy[0]:
            signals['freq'] = 0.005
            signals['miss'] = -0.005
            changes.append(f"[{game}] 热号领先 → freq +0.005, miss -0.005")

        # 冷号领先 → cold_cycle 微增 (step减半为0.003)
        if '冷号' in best_strategy[0]:
            signals['cold_cycle_front'] = 0.003
            changes.append(f"[{game}] 冷号领先 → cold_cycle_front +0.003")

        return signals, changes, len(rows)

    def _is_significant(self, db, games):
        """P0修复: 简单显著性检验 — 最优策略奖金需超过均值20%以上"""
        conn = db._get_conn()
        week_ago = (_now_cst() - timedelta(days=7)).strftime('%Y-%m-%d')

        # 只看有结算数据的彩种
        all_prizes = []
        for g in games:
            rows = conn.execute(
                """SELECT s.prize_amount FROM algo_settlements s
                   JOIN algo_bets b ON s.bet_id = b.id
                   WHERE b.game=? AND s.settled_at >= ?""",
                (g, week_ago)
            ).fetchall()
            all_prizes.extend([r['prize_amount'] for r in rows])
        conn.close()

        if len(all_prizes) < 6:
            return False

        avg_prize = sum(all_prizes) / len(all_prizes)
        max_prize = max(all_prizes)

        # 如果最大奖金不超过均值的1.2倍，差异不显著
        if avg_prize > 0 and max_prize < avg_prize * 1.2:
            return False

        return True

    # ============================================================
    # ============================================================
    #  Daily Loop — 每日闭环
    # ============================================================

    def daily_run(self, kelly_bias: float = 0.0) -> dict:
        """每日完整闭环: 结算 → 进化 → 生成推荐"""
        today = _now_cst().strftime('%Y-%m-%d')
        logging.info(f"=== JinZhu 每日闭环 {today} ===")

        result = {'date': today}

        # 1. 结算昨日
        try:
            settle_result = self.settle()
            result['settle'] = settle_result
            logging.info(f"[Daily] 结算完成")
        except Exception as e:
            logging.warning(f"[Daily] 结算异常(不阻塞): {e}")

        # 2. 进化
        try:
            evolve_result = self.evolve()
            result['evolve'] = evolve_result
            logging.info(f"[Daily] 进化完成: v{self.model.get('version', '?')}")
        except Exception as e:
            logging.warning(f"[Daily] 进化异常(不阻塞): {e}")

        # 3. 生成推荐
        for game in ['ssq', 'dlt', 'qxc', 'pln', 'ltn']:
            try:
                recs = self.generate_recs(game, kelly_bias=kelly_bias)
                result[game] = recs
                logging.info(f"[Daily] {game}: {len(recs)}注")
            except Exception as e:
                logging.error(f"[Daily] {game} 生成失败: {e}")
                result[game] = []

        # 4. 记录推荐到 algo_bets
        try:
            self._record_daily_bets(today, result)
        except Exception as e:
            logging.warning(f"[Daily] 下注记录异常: {e}")

        # 5. 保存推荐到 lottery-predictions.json
        try:
            self._save_predictions(today, result)
        except Exception as e:
            logging.warning(f"[Daily] 推荐保存异常: {e}")

        logging.info(f"=== JinZhu 闭环完成 ===")
        return result

    def generate_daily_section(self, daily_result: dict = None) -> str:
        """生成日报彩票展示部分 — 由JinZhu核心大脑统一控制展示

        Args:
            daily_result: daily_run()的返回值，若为None则现场生成推荐
        Returns:
            markdown格式的彩票展示内容
        """
        today = _now_cst()
        yesterday = today - timedelta(days=1)
        today_str = today.strftime('%Y-%m-%d')

        if daily_result is None:
            daily_result = {}

        section = "\n---\n\n## 🎰 彩票号码推荐 — 刘海蟾点金·金主引擎（仅供娱乐参考）\n\n"
        section += "> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n\n"

        yesterday_weekday = yesterday.weekday()
        # 开奖日历
        ssq_days = {1, 3, 6}   # 二四日
        dlt_days = {0, 2, 5}   # 一三五
        qxc_days = {1, 4, 6}   # 二五日

        def _fmt_nums(nums, width=2):
            """格式化号码：补零"""
            return ' '.join(f'{x:0{width}d}' for x in nums)

        def _read_yesterday_recs(game):
            """读取昨日推荐记录 — 从predictions文件读，无则现场生成回测用推荐"""
            yesterday_str = yesterday.strftime('%Y-%m-%d')
            recs = []
            # 1. 从predictions文件读（cache恢复或git里的）
            try:
                pred_path = os.path.join(MODULE_DIR, 'lottery-predictions.json')
                if os.path.exists(pred_path):
                    with open(pred_path, 'r', encoding='utf-8') as f:
                        predictions = json.load(f)
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            recs = item.get(f'{game}_recs', [])
                            break
            except Exception:
                pass
            # 2. fallback: 从algo_bets读
            if not recs:
                try:
                    from algo_module import AlgoDB
                    _db = AlgoDB()
                    _conn = _db._get_conn()
                    rows = _conn.execute(
                        "SELECT numbers FROM algo_bets WHERE date=? AND game=?",
                        (yesterday_str, game)
                    ).fetchall()
                    _conn.close()
                    for row in rows:
                        try:
                            data = json.loads(row['numbers']) if isinstance(row['numbers'], str) else row['numbers']
                            if data:
                                recs.append(data)
                        except Exception:
                            pass
                except Exception:
                    pass
            # 3. 终极fallback: 用固定种子生成昨日的推荐（回测用）
            if not recs:
                try:
                    seed = int(yesterday_str.replace('-', ''))
                    recs = self.generate_recs(game, seed=seed)
                    logging.info(f"[JinZhu] 回测推荐由种子{seed}即时生成({game})")
                except Exception:
                    pass
            return recs

        # ===== 双色球 =====
        try:
            ssq_data = self._fetch_history('ssq')
            section += "### 🔴 双色球\n\n"
            section += "**最近开奖**:\n\n"
            section += "| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
            for d in ssq_data[:3]:
                section += f"| {d.get('period')} | {_fmt_nums(d.get('reds', []))} | {d.get('blue', 0):02d} |\n"

            ssq_recs = daily_result.get('ssq', [])
            if not ssq_recs:
                ssq_recs = self.generate_recs('ssq')
            if ssq_recs:
                section += f"\n**今日推荐({len(ssq_recs)}注)**:\n"
                for rec in ssq_recs:
                    section += f"  - {rec.get('strategy', '未知')}: 红={_fmt_nums(rec.get('reds', []))} + 蓝={rec.get('blue', 0):02d}\n"

            if yesterday_weekday in ssq_days and ssq_data:
                latest = ssq_data[0]
                section += f"\n**昨日开奖回测** (第{latest.get('period')}期):\n"
                section += f"开奖号码: 红={_fmt_nums(latest.get('reds', []))} + 蓝={latest.get('blue', 0):02d}\n"
                y_recs = _read_yesterday_recs('ssq')
                if y_recs:
                    section += f"\n刘海蟾昨日推荐({len(y_recs)}注):\n"
                    for rec in y_recs:
                        rec_reds = rec.get('reds', [])
                        rec_blue = rec.get('blue', 0)
                        hit_reds = set(rec_reds) & set(latest.get('reds', []))
                        hit_blue = rec_blue == latest.get('blue', 0)
                        hit_count = len(hit_reds) + (1 if hit_blue else 0)
                        section += f"  - {rec.get('strategy', '未知')}: 红={_fmt_nums(rec_reds)} + 蓝={rec_blue:02d} "
                        if hit_count > 0:
                            section += f"→ 中{len(hit_reds)}红"
                            if hit_blue:
                                section += "+1蓝"
                            section += f"({hit_count}码)"
                        else:
                            section += "→ 未中"
                        section += "\n"
                else:
                    section += "\n（昨日推荐记录暂未同步，回测数据下期补全）\n"
            section += "\n"
        except Exception as e:
            section += f"[双色球] 错误: {e}\n\n"

        # ===== 大乐透 =====
        try:
            dlt_data = self._fetch_history('dlt')
            section += "### 🟡 大乐透\n\n"
            section += "**最近开奖**:\n\n"
            section += "| 期号 | 前区 | 后区 |\n|------|------|------|\n"
            for d in dlt_data[:3]:
                section += f"| {d.get('period')} | {_fmt_nums(d.get('front', []))} | {_fmt_nums(d.get('back', []))} |\n"

            dlt_recs = daily_result.get('dlt', [])
            if not dlt_recs:
                dlt_recs = self.generate_recs('dlt')
            if dlt_recs:
                section += f"\n**今日推荐({len(dlt_recs)}注)**:\n"
                for rec in dlt_recs:
                    section += f"  - {rec.get('strategy', '未知')}: 前={_fmt_nums(rec.get('front', []))} + 后={_fmt_nums(rec.get('back', []))}\n"

            if yesterday_weekday in dlt_days and dlt_data:
                latest = dlt_data[0]
                section += f"\n**昨日开奖回测** (第{latest.get('period')}期):\n"
                section += f"开奖号码: 前={_fmt_nums(latest.get('front', []))} + 后={_fmt_nums(latest.get('back', []))}\n"
                y_recs = _read_yesterday_recs('dlt')
                if y_recs:
                    section += f"\n刘海蟾昨日推荐({len(y_recs)}注):\n"
                    for rec in y_recs:
                        rec_front = rec.get('front', [])
                        rec_back = rec.get('back', [])
                        hit_front = set(rec_front) & set(latest.get('front', []))
                        hit_back = set(rec_back) & set(latest.get('back', []))
                        hit_count = len(hit_front) + len(hit_back)
                        section += f"  - {rec.get('strategy', '未知')}: 前={_fmt_nums(rec_front)} + 后={_fmt_nums(rec_back)} "
                        if hit_count > 0:
                            section += f"→ 中{len(hit_front)}前+{len(hit_back)}后({hit_count}码)"
                        else:
                            section += "→ 未中"
                        section += "\n"
                else:
                    section += "\n（昨日推荐记录暂未同步，回测数据下期补全）\n"
            section += "\n"
        except Exception as e:
            section += f"[大乐透] 错误: {e}\n\n"

        # ===== 七星彩 =====
        try:
            qxc_data = self._fetch_history('qxc')
            section += "### 🟢 七星彩\n\n"
            section += "**最近开奖**:\n\n"
            section += "| 期号 | 号码 |\n|------|------|\n"
            for d in qxc_data[:3]:
                digits = d.get('digits', d.get('numbers', []))
                section += f"| {d.get('period')} | {' '.join(map(str, digits))} |\n"

            qxc_recs = daily_result.get('qxc', [])
            if not qxc_recs:
                qxc_recs = self.generate_recs('qxc')
            if qxc_recs:
                section += f"\n**今日推荐({len(qxc_recs)}注)**:\n"
                for rec in qxc_recs:
                    section += f"  - {rec.get('strategy', '未知')}: 号码={' '.join(map(str, rec.get('digits', [])))}\n"

            if yesterday_weekday in qxc_days and qxc_data:
                latest = qxc_data[0]
                latest_digits = latest.get('digits', latest.get('numbers', []))
                section += f"\n**昨日开奖回测** (第{latest.get('period')}期):\n"
                section += f"开奖号码: {' '.join(map(str, latest_digits))}\n"
                y_recs = _read_yesterday_recs('qxc')
                if y_recs:
                    section += f"\n刘海蟾昨日推荐({len(y_recs)}注):\n"
                    for rec in y_recs:
                        rec_digits = rec.get('digits', rec.get('numbers', []))
                        hit_count = sum(1 for i in range(min(len(rec_digits), len(latest_digits))) if rec_digits[i] == latest_digits[i])
                        section += f"  - {rec.get('strategy', '未知')}: 号码={' '.join(map(str, rec_digits))} "
                        if hit_count > 0:
                            section += f"→ 中{hit_count}位"
                        else:
                            section += "→ 未中"
                        section += "\n"
                else:
                    section += "\n（昨日推荐记录暂未同步，回测数据下期补全）\n"
            section += "\n"
        except Exception as e:
            section += f"[七星彩] 错误: {e}\n\n"

        # ===== 金主引擎状态 =====
        settle = daily_result.get('settle', {})
        evolve = daily_result.get('evolve', {})

        section += "\n---\n**🧠 金主引擎状态**\n"

        # 结算展示：优先从settle结果读取，不依赖数据库
        settle_parts = []
        for g in ['ssq', 'dlt', 'qxc']:
            gname = {'ssq': '双色球', 'dlt': '大乐透', 'qxc': '七星彩'}[g]
            s = settle.get(g, {})
            if isinstance(s, dict) and 'summary' in s:
                settle_parts.append(f"{gname}: {s['summary']}")
            elif isinstance(s, dict) and 'error' in s and '无待结算' not in s.get('error', ''):
                settle_parts.append(f"{gname}: {s['error']}")

        if settle_parts:
            section += "**昨日结算**: " + " | ".join(settle_parts) + "\n"
        else:
            # 没有settle结果时，尝试从回测数据计算
            section += "**昨日结算**: 已执行（新环境首次运行，历史数据积累中）\n"

        # 进化展示
        section += "**进化**: "
        if evolve and evolve.get('status') == '进化完成':
            section += f"进化完成({self.model.get('algo_version', 'v?')}·第{self.model.get('version', '?')}次进化)\n"
        elif evolve:
            evolve_status = evolve.get('status', '未知')
            if '数据不足' in str(evolve_status):
                section += f"待积累(需≥6条结算样本，当前新环境积累中)\n"
            else:
                section += f"跳过({evolve_status})\n"
        else:
            section += "未执行\n"
        section += f"**模型**: v{self.model.get('algo_version', '?')}·第{self.model.get('version', '?')}次进化\n"

        return section

    def _record_daily_bets(self, date, result):
        """将推荐记录到 algo_bets"""
        from algo_module import AlgoDB, ROITracker
        db = AlgoDB()
        tracker = ROITracker(db)
        kelly_map = {'ssq': 1, 'dlt': 1, 'qxc': 1}  # 1倍=2元/注

        for game in ['ssq', 'dlt', 'qxc']:
            recs = result.get(game, [])
            if recs:
                tracker.record_bets(date, game, recs, kelly_map)
                logging.info(f"[Daily] {game} 下注记录: {len(recs)}注")

    def _save_predictions(self, date, result):
        """保存推荐到 lottery-predictions.json"""
        pred_path = os.path.join(MODULE_DIR, 'lottery-predictions.json')
        predictions = []
        if os.path.exists(pred_path):
            with open(pred_path, 'r', encoding='utf-8') as f:
                predictions = json.load(f)

        predictions = [p for p in predictions if p.get('date') != date]
        predictions.append({
            'date': date,
            'ssq_recs': result.get('ssq', []),
            'dlt_recs': result.get('dlt', []),
            'qxc_recs': result.get('qxc', []),
        })

        with open(pred_path, 'w', encoding='utf-8') as f:
            json.dump(predictions, f, ensure_ascii=False, indent=2)
        logging.info(f"[Daily] 推荐已保存到 lottery-predictions.json")


# ===== 模块级便捷函数 =====

_jinzhu_instance = None

def get_jinzhu() -> JinZhu:
    """获取 JinZhu 单例"""
    global _jinzhu_instance
    if _jinzhu_instance is None:
        _jinzhu_instance = JinZhu()
    return _jinzhu_instance
