"""
双色球模块 - 从 lottery_analyzer.py 拆出
v4.0 重构: 独立SSQ分析和推荐生成逻辑
"""

import sys
from typing import List, Dict, Optional

# 导入基础类和工具
from lottery_analyzer import WeightedAnalyzer, Strategy


def fetch_ssq_history(periods: int = 15) -> Optional[List[Dict]]:
    """双色球历史数据获取（从lottery_analyzer导入）"""
    from lottery_analyzer import fetch_ssq_history as _fetch
    return _fetch(periods)


def analyze_ssq(history_data: List[Dict]) -> Dict:
    """双色球加权分析（独立函数）
    
    Args:
        history_data: 双色球历史数据 [{'period':xxx, 'reds':[...], 'blue':x}, ...]
    
    Returns:
        analysis dict: 包含 red_weights, blue_weights, zone_balance 等
    """
    if not history_data or len(history_data) == 0:
        raise ValueError("历史数据为空，无法分析")
    
    # 直接调用 lottery_analyzer 中的方法
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_ssq()


def generate_recs_ssq(analysis: Dict, kelly_bias: float = 0.0) -> List[Dict]:
    """根据加权分析生成双色球推荐（纯数学，不依赖AI）
    
    Args:
        analysis: analyze_ssq() 返回的分析结果
        kelly_bias: Kelly调节参数 (>0偏热号, <0偏冷号)
    
    Returns:
        推荐列表 [{'reds':[...], 'blue':x, 'strategy':...}, ...]
        共5注: P0核心注A/B(35%) + P1激进注(20%) + P2回补注(23%) + P3冷号注(22%)
    """
    if not analysis:
        raise ValueError("analysis为空，无法生成推荐")
    
    # 重建 all_pool（和 lottery_analyzer.py 中逻辑一致）
    red_weight_dict = dict(analysis['red_weights'])
    all_pool = []
    for n in range(1, 34):
        w = red_weight_dict.get(n, 0)
        f = analysis['red_freq'].get(n, 0)
        m = analysis['red_miss'].get(n, 0)
        all_pool.append((n, w, f, m))
    
    # Kelly bias 排序
    if kelly_bias > 0:
        max_freq = max(x[2] for x in all_pool) or 1
        max_weight = max(x[1] for x in all_pool) or 1
        all_pool.sort(key=lambda x: (x[2]/max_freq) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
        strategy_tag = Strategy.CORE_HOT
    elif kelly_bias < 0:
        max_miss = max(x[3] for x in all_pool) or 1
        max_weight = max(x[1] for x in all_pool) or 1
        all_pool.sort(key=lambda x: (x[3]/max_miss) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
        strategy_tag = Strategy.CORE_COLD
    else:
        all_pool.sort(key=lambda x: x[1], reverse=True)
        strategy_tag = Strategy.CORE_WEIGHTED
    
    # 核心注A: TOP6
    core_reds_A = sorted([n for n, w, f, m in all_pool[:6]])
    
    # 核心注B: TOP6-11（完全独立）
    if len(all_pool) >= 12:
        core_reds_B = sorted([n for n, w, f, m in all_pool[6:12]])
    else:
        remaining = sorted(set([n for n, w, f, m in all_pool[6:]]) - set(core_reds_A))
        core_reds_B = sorted(list(remaining)[:6]) if remaining else core_reds_A
    
    # 扩展1: 保留TOP4 + 新增2个
    ext1_keep = sorted([n for n, w, f, m in all_pool[:4]])
    ext1_new = sorted([n for n, w, f, m in all_pool[6:8] if n not in ext1_keep][:2])
    ext1_reds = sorted(ext1_keep + ext1_new)
    
    # 扩展2: 形态优化选号
    from lottery_analyzer import WeightedAnalyzer
    target_sum = analysis.get('avg_sum', 100)
    top20 = [n for n, w, f, m in all_pool[:20]]
    # 注意：这里需要WeightedAnalyzer实例来调用_shape_optimized_select
    # 但为保持模块独立，暂时用简单逻辑
    ext2_reds = sorted([n for n, w, f, m in all_pool[8:14]])
    
    # 冷号注
    used_reds = set(core_reds_A) | set(core_reds_B) | set(ext1_reds) | set(ext2_reds)
    cold_scores = []
    red_avg_interval = analysis.get('red_avg_interval', {})
    for n in range(1, 34):
        if n in used_reds:
            continue
        miss_val = analysis['red_miss'].get(n, 0)
        miss_score = min(miss_val / 10.0, 3.0)
        avg_interval = red_avg_interval.get(n, 15)
        cycle_signal = min(miss_val / max(avg_interval, 1), 2.0)
        f = analysis['red_freq'].get(n, 0)
        f_score = min(f / 3.0, 1.5)
        # 使用默认权重（与lottery_analyzer.py中一致）
        score = miss_score * 0.5 + cycle_signal * 0.3 + f_score * 0.2
        cold_scores.append((n, score))
    cold_scores.sort(key=lambda x: x[1], reverse=True)
    cold_red_nums = sorted([n for n, s in cold_scores[:6]])
    
    # 蓝球选择（简化版，使用analysis中的blue_weights）
    blue_weights = dict(analysis['blue_weights'])
    sorted_blues = sorted(blue_weights.items(), key=lambda x: x[1], reverse=True)
    
    core_blue = sorted_blues[0][0] if sorted_blues else 1
    ext1_blue = sorted_blues[1][0] if len(sorted_blues) > 1 else 1
    ext2_blue = sorted_blues[2][0] if len(sorted_blues) > 2 else 1
    cold_blue = sorted_blues[-1][0] if len(sorted_blues) > 3 else 1
    
    return [
        {'reds': core_reds_A, 'blue': core_blue, 'strategy': strategy_tag},  # P0核心注A (35%)
        {'reds': core_reds_B, 'blue': core_blue, 'strategy': strategy_tag},  # P0核心注B (35%)
        {'reds': ext1_reds, 'blue': ext1_blue, 'strategy': Strategy.EXT1_WEIGHTED},  # P1激进注 (20%)
        {'reds': ext2_reds, 'blue': ext2_blue, 'strategy': Strategy.EXT2_WEIGHTED},  # P2回补注 (23%)
        {'reds': cold_red_nums, 'blue': cold_blue, 'strategy': Strategy.COLD_MISS},  # P3冷号注 (22%)
    ]


# 便捷函数：一次性完成分析和生成
def get_ssq_recommendations(history_data: List[Dict], kelly_bias: float = 0.0) -> List[Dict]:
    """一键获取双色球推荐
    
    Args:
        history_data: 历史数据
        kelly_bias: Kelly调节参数
    
    Returns:
        5注推荐列表
    """
    analysis = analyze_ssq(history_data)
    return generate_recs_ssq(analysis, kelly_bias)
