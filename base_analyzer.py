"""
分析器基类 - 从 lottery_analyzer.py 拆出
v4.0 重构: 包含 WeightedAnalyzer 基类
"""

import math
import sqlite3
import json
import os
from typing import List, Dict, Optional, Callable, Tuple
from collections import Counter

# ===== 策略枚举 =====
class Strategy:
    CORE_HOT = '核心注(热号)'
    CORE_COLD = '核心注(冷号)'
    CORE_WEIGHTED = '核心注(加权)'
    EXT1_WEIGHTED = '扩展1(加权)'
    EXT2_WEIGHTED = '扩展2(加权)'
    COLD_MISS = '冷号注(遗漏)'

# ===== 工具函数 =====
def _load_bayesian_adj(number_range, db_path='algo_state.db'):
    """从DB读取贝叶斯修正系数"""
    try:
        if not os.path.exists(db_path):
            return None
        
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # 判断是哪个彩种
        if max(number_range) == 33:  # SSQ红球
            game = 'ssq'
        elif max(number_range) == 35:  # DLT前区
            game = 'dlt'
        else:  # QXC
            game = 'qxc'
        
        c.execute("SELECT number, adjustment FROM algo_bayesian_weights WHERE game=? ORDER BY id DESC LIMIT ?", 
                 (game, len(number_range)))
        rows = c.fetchall()
        conn.close()
        
        if rows:
            adj = {row[0]: row[1] for row in rows}
            return adj
    except Exception as e:
        print(f"[Bayesian] 读取失败: {e}")
        return None


# ===== WeightedAnalyzer 基类 =====
class WeightedAnalyzer:
    """
    基于多维度加权的号码分析器。
    不依赖AI,纯数学计算,结果喂给AI作为参考。

    维度:
    1. 频率加权:近N期出现次数越多权重越高
    2. 遗漏加权:连续未出现期数越多,回补权重越高
    3. 近期趋势加权:最近5期比前10期出现多的号加分(趋势上升)
    4. 连号分析:统计连号对出现频率
    5. 和值分析:统计和值范围
    6. 🟢 v6.7: 邻号加分 - 上期开出的号±1获得额外权重(球机机械偏差)
    """

    def __init__(self, history, weight_freq=None, weight_miss=None, weight_trend=None, weight_zone=None, gamma=None):
        self.history = history
        # 🟢 v6.3: gamma可配置,默认0.88,可从配置文件读取
        import json
        try:
            with open('/root/asuan-scheduler/weight-config.json', 'r') as f: config = json.load(f)
        except Exception: config = {}
        self.w_freq = weight_freq if weight_freq is not None else config.get('freq', 0.30)
        self.w_miss = weight_miss if weight_miss is not None else config.get('miss', 0.25)
        self.w_trend = weight_trend if weight_trend is not None else config.get('trend', 0.25)
        self.w_zone = weight_zone if weight_zone is not None else config.get('zone', 0.20)
        self.gamma = gamma if gamma is not None else config.get('gamma', 0.88)  # 🟢 v6.3
        # 🔴 v6.8: 邻号bonus和冷号注权重也从配置读取
        # 🔴 分前后区:前区/红球miss主导,后区/蓝球/七星彩cycle主导
        self.neighbor_bonus = config.get('neighbor_bonus', 0.03)
        self.cold_miss_front = config.get('cold_miss_front', 0.40)
        self.cold_cycle_front = config.get('cold_cycle_front', 0.30)
        self.cold_freq_front = config.get('cold_freq_front', 0.30)
        self.cold_miss_back = config.get('cold_miss_back', 0.30)
        self.cold_cycle_back = config.get('cold_cycle_back', 0.40)
        self.cold_freq_back = config.get('cold_freq_back', 0.30)

    def _calc_weights(self, number_range, extract_fn, total_periods):
        """通用加权计算
        extract_fn(history_item) -> list of numbers
        🟢 v6.3: 频率改为指数衰减,近期数据权重提升2-3倍,解冻号码粘滞
        """
        # 🟢 v6.3: 指数衰减频率统计 - γ=0.88,近1期权重≈远期5倍
        gamma = self.gamma
        decay_freq = Counter()
        decay_total = 0.0
        for idx, d in enumerate(self.history):
            w = gamma ** idx  # idx=0最近期权重最大
            decay_total += w
            for n in extract_fn(d):
                decay_freq[n] += w

        # 等权频率也保留(供冷号注等需要原始频率的场景)
        raw_freq = Counter()
        for d in self.history:
            raw_freq.update(extract_fn(d))

        # 遗漏值:连续未出现期数
        miss = {}
        # 🟢 v6.2: 平均遗漏间隔(历史平均隔几期出现一次)
        avg_miss_interval = {}
        for n in number_range:
            # 当前遗漏
            count = 0
            for d in self.history:
                if n in extract_fn(d):
                    break
                count += 1
            miss[n] = count
            
            # 平均遗漏间隔:找所有出现位置,计算间隔均值
            positions = [i for i, d in enumerate(self.history) if n in extract_fn(d)]
            if len(positions) >= 2:
                intervals = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
                avg_miss_interval[n] = sum(intervals) / len(intervals)
            elif len(positions) == 1:
                avg_miss_interval[n] = positions[0] if positions[0] > 0 else len(self.history)
            else:
                avg_miss_interval[n] = len(self.history)  # 从未出现

        # 近期趋势:最近5期 vs 前10期
        recent = Counter()
        older = Counter()
        mid = min(5, len(self.history))
        for d in self.history[:mid]:
            recent.update(extract_fn(d))
        for d in self.history[mid:mid*2]:
            older.update(extract_fn(d))

        # 🟢 P1修复:分区平衡真正融入权重
        # 🔴 Bug3修复:zone_size统一,与analyze_ssq(n//11)/analyze_dlt(n//12)一致
        if max(number_range) == 33:  # 双色球红球1-33,分区1-11/12-22/23-33
            zone_size = 11
        elif max(number_range) == 35:  # 大乐透前区1-35,分区1-12/13-24/25-35
            zone_size = 12
        else:  # 七星彩每位0-9,分区0-3/4-6/7-9
            zone_size = (max(number_range) + 1) // 3
            
        zone_counts = [0, 0, 0]
        for d in self.history[:5]:
            for n in extract_fn(d):
                z = min(n // zone_size, 2)
                zone_counts[z] += 1
        total_z = sum(zone_counts) or 1
        zone_expected = total_z / 3  # 均衡期望

        # 计算综合权重
        weights = {}
        for n in number_range:
            f = decay_freq.get(n, 0) / max(decay_total, 1)  # 🟢 v6.3: 指数衰减频率
            m = math.log1p(miss.get(n, 0)) / math.log1p(total_periods)
            t = (recent.get(n, 0) - older.get(n, 0)) / max(mid, 1)
            # 🔴 Bug4修复:趋势权重逻辑修正
            if t > 0:
                t_weight = t * 1.0  # 🟢 v6.2: 上升趋势(对称,无先验偏好)
            elif t < 0:
                t_weight = t * 0.8  # 🟢 v6.2: 下降趋势轻微衰减(0.8而非0.5,不过度惩罚)
            else:
                t_weight = 0

            # 🟢 分区平衡:偏低区的号加分,偏高区的号减分
            z = min(n // zone_size, 2)
            z_factor = max(0, (zone_expected - zone_counts[z]) / max(zone_expected, 1))

            # 🟢 v6.2: 遗漏周期加分 - 当前遗漏 > 平均遗漏间隔时,说明"到期"
            avg_interval = avg_miss_interval.get(n, total_periods)
            overdue_bonus = 0
            if avg_interval > 0 and miss.get(n, 0) > avg_interval:
                overdue_bonus = min((miss.get(n, 0) - avg_interval) / max(avg_interval, 1) * 0.15, 0.3)

            # 🟢 v6.7: 邻号加分 - 上期开出的号±1获得微弱加分
            neighbor_bonus = 0
            if self.history:
                last_drawn = set(extract_fn(self.history[0]))
                if (n - 1) in last_drawn or (n + 1) in last_drawn:
                    neighbor_bonus = self.neighbor_bonus

            # 🟢 v7.1→v3.0: 号码相关性bonus
            correlation_bonus = 0
            if self.history:
                last_drawn_set = set(extract_fn(self.history[0]))
                n_appear = raw_freq.get(n, 0)
                n_total = len(self.history)
                if n_total >= 5 and n_appear > 0:
                    p_n = n_appear / n_total
                    for m in last_drawn_set:
                        if m == n:
                            continue
                        co_occur = 0
                        m_occur = 0
                        for i in range(len(self.history) - 1):
                            if m in extract_fn(self.history[i]):
                                m_occur += 1
                                if n in extract_fn(self.history[i + 1]):
                                    co_occur += 1
                        if m_occur >= 3:
                            p_n_given_m = co_occur / m_occur
                            lift = p_n_given_m / max(p_n, 0.01)
                            if lift > 1.2:
                                correlation_bonus += min((lift - 1.0) * 0.02, 0.06)

            weights[n] = (
                self.w_freq * f +
                self.w_miss * m +
                self.w_trend * t_weight +
                self.w_zone * z_factor +
                overdue_bonus +
                neighbor_bonus +
                correlation_bonus
            )

        # === v3.0: 贝叶斯动态权重修正 ===
        bayesian_adj = _load_bayesian_adj(number_range)
        if bayesian_adj:
            adj_count = 0
            for n in number_range:
                adj = bayesian_adj.get(n, 1.0)
                if adj != 1.0:
                    weights[n] *= adj
                    adj_count += 1
            if adj_count > 0:
                print(f"  [Bayesian] 修正{adj_count}个号码权重")

        return weights, raw_freq, miss, avg_miss_interval

    def _shape_optimized_select(self, candidates, n_select, target_sum, target_odd, target_big, must_include=None, big_threshold=17):
        """🟢 v6.4: 形态优化选号 - 贪心搜索,支持大候选池
        candidates: 候选号码列表(支持20+个)
        n_select: 选几个号
        target_sum: 目标和值
        target_odd: 目标奇数个数
        target_big: 目标大号个数
        must_include: 必须包含的号码
        big_threshold: 大号阈值(SSQ=17, DLT=18)
        """
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
                # 评分:和值偏差 + 奇偶偏差 + 大小偏差
                sum_penalty = -abs(s - target_sum) / max(target_sum, 1) * 2.0
                odd_penalty = -abs(odd_count - target_odd) * 1.5
                big_penalty = -abs(big_count - target_big) * 1.5
                score = sum_penalty + odd_penalty + big_penalty
                if score > best_score:
                    best_score = score
                    best_n = n
            if best_n is not None:
                result.append(best_n)
                remaining.remove(best_n)
            else:
                break

        return sorted(result)

    def _smart_blue_select(self, analysis, mode='hot', exclude=None):
        """🔴 双色球蓝球智能选号(1-16)
        mode: 'hot'权重优先 / 'mix'均衡 / 'miss'遗漏回补
        exclude: set of blue numbers to skip (for dispersion across bets)
        """
        blue_weight_dict = dict(analysis['blue_weights'])
        blue_miss = analysis['blue_miss']
        blue_freq = analysis['blue_freq']
        exclude = exclude or set()
        
        # 综合评分:权重(40%) + 遗漏回补力(30%) + 近期活跃度(30%)
        scores = {}
        for n in range(1, 17):
            if n in exclude:
                continue
            weight_score = blue_weight_dict.get(n, 0)
            # 遗漏回补力:遗漏越大,回补概率越高(但超过10期可能偏冷)
            miss_val = blue_miss.get(n, 0)
            if miss_val >= 8:
                miss_score = 3.0  # 深度遗漏,强回补信号
            elif miss_val >= 5:
                miss_score = 2.5
            elif miss_val >= 3:
                miss_score = 1.5
            elif miss_val == 0:
                miss_score = 1.0  # 刚出,回补力弱
            else:
                miss_score = 0.5
            # 近期活跃度(近5期出现次数)
            recent_active = blue_freq.get(n, 0)
            active_score = min(recent_active / 5.0, 1.0)
            
            # 综合评分
            score = weight_score * 0.4 + miss_score * 0.3 + active_score * 0.3
            scores[n] = score
        
        if not scores:
            return 1  # fallback
        return max(scores.items(), key=lambda x: x[1])[0]

    def _smart_back_select(self, analysis, count=2, mode='hot', exclude=None):
        """🔴 大乐透后区智能选号(1-12)
        mode: 'hot'权重优先 / 'mix'均衡 / 'miss'遗漏回补
        exclude: set of back numbers already used
        """
        back_weight_dict = dict(analysis['back_weights'])
        back_miss = analysis['back_miss']
        back_freq = analysis['back_freq']
        exclude = exclude or set()
        
        # 综合评分
        scores = {}
        for n in range(1, 13):
            if n in exclude:
                continue
            weight_score = back_weight_dict.get(n, 0)
            miss_val = back_miss.get(n, 0)
            miss_score = min(miss_val / 10.0, 3.0)
            avg_interval = analysis.get('back_avg_interval', {}).get(n, 15)
            cycle_signal = min(miss_val / max(avg_interval, 1), 2.0)
            freq_score = min(back_freq.get(n, 0) / 3.0, 1.5)
            
            if mode == 'hot':
                score = weight_score * 0.6 + freq_score * 0.4
            elif mode == 'miss':
                score = miss_score * 0.5 + cycle_signal * 0.3 + freq_score * 0.2
            else:  # mix
                score = weight_score * 0.4 + miss_score * 0.3 + freq_score * 0.3
            scores[n] = score
        
        if not scores:
            return [1, 2][:count]
        
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [n for n, s in sorted_scores[:count]]
