#!/usr/bin/env python3
"""
金主 (JinZhu) — 刘海蟾点金算法核心大脑

唯一真相来源：所有推荐生成、结算反哺、权重进化都经过这里。
外部只需调用 JinZhu.daily_run()，不直接操作 games/*.py 或 algo_module.py。

架构四层：
  Model Layer   → weight-config.json (唯一模型参数出处)
  Generation Layer → generate_ssq/dlt/qxc (策略差异化+随机扰动)
  Evaluation Layer → settle/backtest (结果驱动进化)
  Evolution Layer  → GEPA (写回Model，下一代自动生效)

设计原则：
  1. 所有权重从 config 读取，不许硬编码
  2. 推荐生成必须用 Model 参数，确保进化生效
  3. 结算结果驱动进化，进化写回 Model，闭环
  4. 等权号码加随机扰动，保证可重复生成不同推荐
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
    'version': 1, 'algo_version': 'v4.0-JinZhu', 'evolution_log': [],
    'lock_config': {},
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
                # 合并默认值（防止新字段缺失）
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
        """更新单个模型参数（可附带进化日志）"""
        old = self.model.get(key)
        self.model[key] = value
        if evolve_log_entry:
            self.model.setdefault('evolution_log', []).append(evolve_log_entry)
        self._save_model()
        return old

    # ============================================================
    #  Generation Layer — 推荐生成（策略差异化 + 随机扰动）
    # ============================================================

    def generate_recs(self, game: str, history_data: list = None, kelly_bias: float = 0.0, seed: int = None) -> list:
        """统一推荐入口

        Args:
            game: 'ssq' / 'dlt' / 'qxc'
            history_data: 历史开奖数据（不传则自动获取）
            kelly_bias: Kelly偏向 (>0偏热, <0偏冷, 0均衡)
            seed: 随机种子（None=不可复现, 固定值=可复现）

        Returns:
            5注推荐列表
        """
        if seed is not None:
            self._rng = random.Random(seed)

        if history_data is None:
            history_data = self._fetch_history(game)

        if not history_data:
            logging.error(f"[Gen] {game} 历史数据为空，无法生成推荐")
            return []

        analysis = self._analyze(game, history_data)
        if not analysis:
            logging.error(f"[Gen] {game} 分析失败")
            return []

        gen_map = {
            'ssq': self._gen_ssq,
            'dlt': self._gen_dlt,
            'qxc': self._gen_qxc,
        }
        gen_fn = gen_map.get(game)
        if not gen_fn:
            logging.error(f"[Gen] 未知彩种: {game}")
            return []

        recs = gen_fn(analysis, kelly_bias)
        logging.info(f"[Gen] {game} 生成{len(recs)}注推荐")
        return recs

    def _fetch_history(self, game: str) -> list:
        """自动获取历史数据"""
        try:
            fetch_map = {
                'ssq': lambda: __import__('lottery_analyzer', fromlist=['fetch_ssq_history']).fetch_ssq_history(15),
                'dlt': lambda: __import__('lottery_analyzer', fromlist=['fetch_dlt_history']).fetch_dlt_history(15),
                'qxc': lambda: __import__('lottery_analyzer', fromlist=['fetch_qxc_history']).fetch_qxc_history(50),
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
            return analyze_map[game]()
        except Exception as e:
            logging.error(f"[Gen] {game} 分析失败: {e}")
            return {}

    # ------ 双色球推荐 ------

    def _gen_ssq(self, analysis: dict, kelly_bias: float = 0.0) -> list:
        """双色球5注推荐（策略差异化 + 随机扰动）"""
        # 1. 构建 all_pool
        red_weight_dict = dict(analysis['red_weights'])
        all_pool = []
        for n in range(1, 34):
            w = red_weight_dict.get(n, 0)
            f = analysis['red_freq'].get(n, 0)
            m = analysis['red_miss'].get(n, 0)
            all_pool.append((n, w, f, m))

        # 2. Kelly偏向排序
        all_pool = self._kelly_sort(all_pool, kelly_bias)
        strategy_tag = self._kelly_tag(kelly_bias)

        # 3. 核心注A: TOP6权重
        core_A = sorted([n for n, w, f, m in all_pool[:6]])

        # 4. 核心注B: 完全独立 (TOP6-11)
        core_B = self._select_independent_pool(all_pool, core_A, 6)

        # 5. 扩展1(形态): 形态优化贪心搜索
        target_sum = analysis.get('avg_sum', 100)
        top20 = [n for n, w, f, m in all_pool[:20]]
        must_keep = sorted([n for n, w, f, m in all_pool[:2]])
        ext1 = self._shape_optimized_select(top20, 6, target_sum, target_odd=3, target_big=3, must_include=must_keep)

        # 6. 扩展2(回补): 中等频率+遗漏回补
        ext2 = self._select_recovery_pool(analysis, all_pool, set(core_A) | set(core_B) | set(ext1), n_select=6)

        # 7. 冷号注: 多维评分 (从Model读取权重!)
        used = set(core_A) | set(core_B) | set(ext1) | set(ext2)
        cold = self._select_cold_reds(analysis, used, game='ssq')

        # 8. 蓝球: 智能选择+互斥
        blues = self._select_blues(analysis, n_blues=5)  # 5注5个不同蓝球

        # 9. 随机扰动: 等权号码微调 (保证可重复生成不同推荐)
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
        # 1. 构建 all_pool
        front_weight_dict = dict(analysis['front_weights'])
        all_pool = []
        for n in range(1, 36):
            w = front_weight_dict.get(n, 0)
            f = analysis['front_freq'].get(n, 0)
            m = analysis['front_miss'].get(n, 0)
            all_pool.append((n, w, f, m))

        # 2. Kelly偏向排序
        all_pool = self._kelly_sort(all_pool, kelly_bias)
        strategy_tag = self._kelly_tag(kelly_bias)

        # 3. 核心注A: TOP5
        core_A = sorted([n for n, w, f, m in all_pool[:5]])

        # 4. 核心注B: 完全独立 (TOP5-9)
        core_B = self._select_independent_pool(all_pool, core_A, 5)

        # 5. 扩展1(形态): 保留TOP3 + 形态优化补充2个
        top20 = [n for n, w, f, m in all_pool[:20]]
        must_keep = sorted([n for n, w, f, m in all_pool[:3]])
        ext1 = self._shape_optimized_select(top20, 5, target_sum=analysis.get('avg_sum', 90),
                                            target_odd=3, target_big=3, must_include=must_keep, big_threshold=18)

        # 6. 扩展2(回补)
        ext2 = self._select_recovery_pool(analysis, all_pool, set(core_A) | set(core_B) | set(ext1), n_select=5)

        # 7. 冷号注
        used = set(core_A) | set(core_B) | set(ext1) | set(ext2)
        cold = self._select_cold_front(analysis, all_pool, used)

        # 8. 后区: 智能选择+互斥 (每注不同后区对)
        backs = self._select_backs(analysis, n_pairs=5)

        # 9. 随机扰动
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
        """七星彩5注推荐（逐位选号 + 策略差异化）"""
        positions = analysis['positions']
        total = analysis.get('total_periods', 15)

        # 每位候选池（0-9按权重排序）
        pos_pools = []
        for pos_data in positions:
            weights = pos_data['weights']
            pos_pools.append([n for n, w in weights])

        # 核心注A: 每位权重TOP1
        core_A = [pool[0] if pool else 0 for pool in pos_pools]

        # 核心注B: 策略差异化 — 每位选权重排名和A最远的号码（真正的差异化）
        core_B = []
        for i, pool in enumerate(pos_pools):
            # 从后往前选（权重最低的），和A形成最大差异
            for n in reversed(pool):
                if n != core_A[i]:
                    core_B.append(n)
                    break
            else:
                core_B.append(pool[-1] if pool else 0)

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
            # 选频率中等+遗漏到期（周期信号）的号码
            best_n = None
            best_score = -999
            for n in range(10):
                if n == core_A[i]:
                    continue
                f_score = min(freq.get(n, 0) / 3.0, 1.5)
                m = miss.get(n, 0)
                avg_i = avg_interval.get(n, 5)
                cycle = min(m / max(avg_i, 1), 2.0)
                # 回补策略: 中等频率 + 到期信号
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

        # 随机扰动: 每位有小概率替换为次优
        core_A = self._perturb_qxc(core_A, pos_pools, max_swaps=2)
        core_B = self._perturb_qxc(core_B, pos_pools, max_swaps=2)

        return [
            {'digits': core_A, 'strategy': '核心注(权重)A'},
            {'digits': core_B, 'strategy': '核心注(反转)B'},
            {'digits': ext1, 'strategy': Strategy.EXT1},
            {'digits': ext2, 'strategy': Strategy.EXT2},
            {'digits': cold, 'strategy': Strategy.COLD},
        ]

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
        # 从排名6-20的区间选
        candidates = [n for n, w, f, m in all_pool[6:20] if n not in existing_set]
        if len(candidates) >= n:
            return sorted(candidates[:n])
        # 不够则从更后补
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
                # 等权号码加微小随机扰动
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
            # 回补策略: 频率中等(不追最热) + 遗漏到期
            score = f_score * 0.4 + m_score * 0.6
            score += self._rng.uniform(-0.01, 0.01)  # 随机扰动
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
        """大乐透冷号注前区（复用 _select_cold_reds）"""
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

        # 计算每个蓝球综合得分
        scores = {}
        for n in range(1, 17):
            w = blue_weight_dict.get(n, 0)
            m = blue_miss.get(n, 0)
            f = blue_freq.get(n, 0)

            if m >= 10:
                miss_score = 3.0
            elif m >= 6:
                miss_score = 2.5
            elif m >= 3:
                miss_score = 1.5
            elif m == 0:
                miss_score = 1.0
            else:
                miss_score = 0.8

            freq_score = min(f, 4) / 2.0
            scores[n] = w * 0.4 + freq_score * 0.3 + miss_score * 0.3

        # 按得分排序
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 贪心选择 n_blues 个，确保互斥 + 奇偶分散
        selected = []
        used_odd_even = {'odd': 0, 'even': 0}
        for n, s in ranked:
            if len(selected) >= n_blues:
                break
            # 奇偶分散: 如果某一类已满3个，优先选另一类
            parity = 'odd' if n % 2 == 1 else 'even'
            if used_odd_even[parity] >= 3 and used_odd_even['odd'] + used_odd_even['even'] < n_blues:
                continue  # 跳过，让另一类有机会
            selected.append(n)
            used_odd_even[parity] += 1

        # 不够则从剩余补
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

        # 每个后区号综合得分
        scores = {}
        for n in range(1, 13):
            w = back_weight_dict.get(n, 0)
            m = back_miss.get(n, 0)
            f = back_freq.get(n, 0)

            if m >= 8:
                miss_score = 3.0
            elif m >= 5:
                miss_score = 2.5
            elif m >= 3:
                miss_score = 1.5
            elif m == 0:
                miss_score = 1.0
            else:
                miss_score = 0.8

            freq_score = min(f, 4) / 2.0
            scores[n] = w * 0.4 + freq_score * 0.3 + miss_score * 0.3

        # 贪心选 n_pairs 组，每组2个，尽量不重复
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

            # 奇偶优化: 尽量一奇一偶
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

            # 最后一组用冷号评分
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
        """随机扰动: 等权号码微调 (同分号码可互换)"""
        result = list(nums)
        pool_dict = {n: (w, f, m) for n, w, f, m in all_pool}

        for _ in range(max_swaps):
            if not result:
                break
            idx = self._rng.randint(0, len(result) - 1)
            current_n = result[idx]
            current_w = pool_dict.get(current_n, (0, 0, 0))[0]

            # 找权重接近的替代号码（±10%以内）
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
        """结算指定日期的推荐，写入 algo_settlements"""
        from algo_module import AlgoDB
        db = AlgoDB()

        if date is None:
            date = (_now_cst() - timedelta(days=1)).strftime('%Y-%m-%d')

        games = [game] if game else ['ssq', 'dlt', 'qxc']
        results = {}

        for g in games:
            try:
                result = self._settle_game(db, g, date)
                results[g] = result
                logging.info(f"[Settle] {g} {date}: {result.get('summary', 'done')}")
            except Exception as e:
                logging.error(f"[Settle] {g} {date} 失败: {e}")
                results[g] = {'error': str(e)}

        return results

    def _settle_game(self, db, game, date):
        """结算单个彩种"""
        # 获取开奖数据
        history = self._fetch_history(game)
        if not history:
            return {'error': '无法获取开奖数据'}

        actual = history[0]  # 最新一期
        actual_period = actual.get('period', '')

        # 查找该日期的推荐
        conn = db._get_conn()
        rows = conn.execute(
            "SELECT id, numbers, strategy FROM algo_bets WHERE date=? AND game=? AND status='pending'",
            (date, game)
        ).fetchall()
        conn.close()

        if not rows:
            return {'error': f'无待结算推荐', 'game': game, 'date': date}

        total_prize = 0
        total_cost = 0
        hits = []

        for row in rows:
            numbers = json.loads(row['numbers'])
            strategy = row['strategy']

            from algo_module import AlgoEngine
            engine = AlgoEngine()
            prize_info = engine._calc_prize(game, numbers, actual)

            total_cost += 2
            total_prize += prize_info.get('prize', 0)

            # 写入结算表
            conn = db._get_conn()
            actual_str = json.dumps(actual, ensure_ascii=False)
            conn.execute(
                "INSERT INTO algo_settlements (bet_id, user_id, actual_numbers, hit_count, prize_tier, prize_name, prize_amount, settled_at) VALUES (?,?,?,?,?,?,?,?)",
                (row['id'], 'default', actual_str, prize_info.get('hit_count', 0),
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

        results = []
        for i in range(min(n_periods, len(history) - 1)):
            draw = history[i]
            # 用该期之前的数据生成推荐
            train_data = history[i + 1:]
            if len(train_data) < 5:
                continue

            recs = self.generate_recs(game, train_data, seed=42)
            # 计算命中
            for rec in recs:
                from algo_module import AlgoEngine
                engine = AlgoEngine()
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
    #  Evolution Layer — GEPA 进化 (写回Model)
    # ============================================================

    def evolve(self, game: str = None):
        """GEPA进化 — 结算数据驱动权重调整，写回Model"""
        from algo_module import AlgoDB
        db = AlgoDB()
        games = [game] if game else ['ssq', 'dlt', 'qxc']

        evolution_results = {}
        for g in games:
            try:
                result = self._evolve_game(db, g)
                evolution_results[g] = result
            except Exception as e:
                logging.error(f"[Evolve] {g} 进化失败: {e}")
                evolution_results[g] = {'error': str(e)}

        return evolution_results

    def _evolve_game(self, db, game):
        """单彩种进化"""
        # 读取最近7天结算数据
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
            return {'status': '数据不足', 'samples': len(rows)}

        # 按策略统计
        strategy_stats = defaultdict(lambda: {'count': 0, 'total_prize': 0, 'total_hits': 0})
        for r in rows:
            s = strategy_stats[r['strategy']]
            s['count'] += 1
            s['total_prize'] += r['prize_amount']
            s['total_hits'] += r['hit_count']

        # 找最优和最差策略
        best_strategy = max(strategy_stats.items(), key=lambda x: x[1]['total_prize'])
        worst_strategy = min(strategy_stats.items(), key=lambda x: x[1]['total_prize'])

        changes = []

        # 热号领先 → freq 微增, miss 微减
        if '追热' in best_strategy[0] or '核心' in best_strategy[0]:
            old_freq = self.model.get('freq', 0.30)
            old_miss = self.model.get('miss', 0.25)
            step = 0.01
            self.model['freq'] = round(old_freq + step, 4)
            self.model['miss'] = round(old_miss - step, 4)
            changes.append(f"热号领先 → freq +{step}, miss -{step}")

        # 冷号领先 → cold_cycle 微增
        if '冷号' in best_strategy[0]:
            old_cycle = self.model.get('cold_cycle_front', 0.30)
            step = 0.005
            self.model['cold_cycle_front'] = round(old_cycle + step, 4)
            changes.append(f"冷号领先 → cold_cycle_front +{step}")

        # 归一化约束: freq+miss+trend+zone = 1.0
        total = self.model['freq'] + self.model['miss'] + self.model['trend'] + self.model['zone']
        if abs(total - 1.0) > 0.001:
            scale = 1.0 / total
            for k in ['freq', 'miss', 'trend', 'zone']:
                self.model[k] = round(self.model[k] * scale, 4)
            changes.append(f"归一化修正: {total:.4f}→1.0")

        # 更新版本号
        self.model['version'] = self.model.get('version', 1) + 1
        self.model['algo_version'] = 'v4.0-JinZhu'

        # 记录进化日志
        log_entry = {
            'date': _now_cst().strftime('%Y-%m-%d'),
            'trigger': '结算驱动',
            'sample_size': len(rows),
            'changes': changes,
            'best_strategy': best_strategy[0],
            'best_prize': best_strategy[1]['total_prize'],
        }
        self.model.setdefault('evolution_log', []).append(log_entry)

        # 写回Model
        self._save_model()

        return {
            'status': '进化完成',
            'samples': len(rows),
            'changes': changes,
            'version': self.model['version'],
        }

    # ============================================================
    #  Daily Loop — 每日闭环
    # ============================================================

    def daily_run(self, kelly_bias: float = 0.0) -> dict:
        """每日完整闭环: 结算 → 进化 → 生成推荐

        Returns:
            {ssq: [5注], dlt: [5注], qxc: [5注], settle: {...}, evolve: {...}}
        """
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
        for game in ['ssq', 'dlt', 'qxc']:
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

    def _record_daily_bets(self, date, result):
        """将推荐记录到 algo_bets"""
        from algo_module import AlgoDB, ROITracker
        db = AlgoDB()
        tracker = ROITracker(db)
        kelly_map = {'ssq': 0, 'dlt': 0, 'qxc': 0}

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

        # 去重
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


# ===== 模块级便捷函数（向后兼容 games/*.py 调用）=====

_jinzhu_instance = None

def get_jinzhu() -> JinZhu:
    """获取 JinZhu 单例"""
    global _jinzhu_instance
    if _jinzhu_instance is None:
        _jinzhu_instance = JinZhu()
    return _jinzhu_instance
