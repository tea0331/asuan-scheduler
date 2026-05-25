"""
大乐透模块 - 从 lottery_analyzer.py 拆出
v4.0 重构: 独立DLT分析和推荐生成逻辑
"""

import sys
from typing import List, Dict, Optional

from lottery_analyzer import WeightedAnalyzer, Strategy


def fetch_dlt_history(periods: int = 15) -> Optional[List[Dict]]:
    """大乐透历史数据获取（从lottery_analyzer导入）"""
    from lottery_analyzer import fetch_dlt_history as _fetch
    return _fetch(periods)


def analyze_dlt(history_data: List[Dict]) -> Dict:
    """大乐透加权分析（独立函数）
    
    Args:
        history_data: 大乐透历史数据 [{'period':xxx, 'front':[...], 'back':[...]}, ...]
    
    Returns:
        analysis dict: 包含 front_weights, back_weights, zone_balance 等
    """
    if not history_data or len(history_data) == 0:
        raise ValueError("历史数据为空，无法分析")
    
    # 直接调用 lottery_analyzer 中的方法
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_dlt()


def generate_recs_dlt(analysis: Dict, kelly_bias: float = 0.0) -> List[Dict]:
    """根据加权分析生成大乐透推荐
    
    Args:
        analysis: analyze_dlt() 返回的分析结果
        kelly_bias: Kelly调节参数 (>0偏热号, <0偏冷号)
    
    Returns:
        推荐列表 [{'front':[...], 'back':[...], 'strategy':...}, ...]
        共5注: P0核心注A/B(35%) + P1激进注(20%) + P2回补注(23%) + P3冷号注(22%)
    """
    if not analysis:
        raise ValueError("analysis为空，无法生成推荐")
    
    # 重建 all_pool
    front_weight_dict = dict(analysis['front_weights'])
    all_pool = []
    for n in range(1, 36):
        w = front_weight_dict.get(n, 0)
        f = analysis['front_freq'].get(n, 0)
        m = analysis['front_miss'].get(n, 0)
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
    
    # 核心注A: TOP5
    core_front_A = sorted([n for n, w, f, m in all_pool[:5]])
    
    # 核心注B: TOP6-10（完全独立）
    core_front_B_pool = [n for n, w, f, m in all_pool[5:10]]
    core_front_B = sorted(core_front_B_pool) if len(core_front_B_pool) >= 5 else core_front_A
    
    # 扩展1: 保留TOP3 + 新增2个
    top8 = sorted(all_pool, key=lambda x: x[1], reverse=True)
    ext1_keep = sorted([n for n, w, f, m in top8[:3]])
    ext1_new = sorted([n for n, w, f, m in top8[6:10] if n not in ext1_keep][:2])
    ext1_front = sorted(ext1_keep + ext1_new)
    
    # 扩展2: 核心2号 + 频率中等号
    ext2_keep = sorted([n for n, w, f, m in all_pool[:2]])
    mid_freq = sorted([(n, f) for n, w, f, m in all_pool if 2 <= f <= 3 and n not in [x[0] for x in all_pool[:5]]][:3])
    if len(mid_freq) < 3:
        mid_freq = sorted([(n, f) for n, w, f, m in all_pool if f <= 1 and n not in [x[0] for x in all_pool[:5]]][:3])
    ext2_front = sorted(ext2_keep + [n for n, f in mid_freq[:3]])
    
    # 冷号注
    miss_front = sorted([(n, m) for n, w, f, m in all_pool if m > 0], key=lambda x: x[1], reverse=True)
    if not miss_front:
        miss_front = sorted([(n, 0) for n in range(1, 36) if n not in [x[0] for x in all_pool[:5]]][:5])
    cold_front = sorted([n for n, m in miss_front[:5]])
    
    # 后区选择（互斥逻辑，5注后区完全不同）
    back_weight_list = analysis.get('back_weights', [])
    back_miss_dict = analysis.get('back_miss', {})
    
    # 核心注A+B：用TOP2（互斥）
    if len(back_weight_list) >= 2:
        core_back = [back_weight_list[0][0], back_weight_list[1][0]]
    else:
        core_back = [1, 2]
    
    # 扩展1：用TOP3-4（和核心注不同）
    if len(back_weight_list) >= 4:
        ext1_back = [back_weight_list[2][0], back_weight_list[3][0]]
    else:
        ext1_back = core_back[:]
    
    # 扩展2：用TOP5-6（保证互斥）
    if len(back_weight_list) >= 6:
        ext2_back = [back_weight_list[4][0], back_weight_list[5][0]]
    else:
        ext2_back = ext1_back[:]
    
    # 冷号注：用遗漏最高的2个（和前面不同）
    cold_back = core_back[:]  # fallback
    if back_miss_dict:
        sorted_miss = sorted(back_miss_dict.items(), key=lambda x: x[1], reverse=True)
        cold_candidates = [n for n, m in sorted_miss if n not in core_back and n not in ext1_back and n not in ext2_back]
        if len(cold_candidates) >= 2:
            cold_back = cold_candidates[:2]
        elif len(sorted_miss) >= 2:
            cold_back = [sorted_miss[0][0], sorted_miss[1][0]]
    
    return [
        {'front': core_front_A, 'back': core_back, 'strategy': '核心注(加权)A'},  # P0核心注A (35%)
        {'front': core_front_B, 'back': core_back, 'strategy': '核心注(加权)B'},  # P0核心注B (35%)
        {'front': ext1_front, 'back': ext1_back, 'strategy': '扩展1(加权)'},  # P1激进注 (20%)
        {'front': ext2_front, 'back': ext2_back, 'strategy': '扩展2(加权)'},  # P2回补注 (23%)
        {'front': cold_front, 'back': cold_back, 'strategy': '冷号注(遗漏)'},  # P3冷号注 (22%)
    ]

        {'front': core_front_A, 'back': [core_back, core_back_2], 'strategy': f'核心注(加权)A'},  # P0核心注A (35%)
        {'front': core_front_B, 'back': [core_back, core_back_2], 'strategy': f'核心注(加权)B'},  # P0核心注B (35%)
        {'front': ext1_front, 'back': [ext1_back_1, ext1_back_2], 'strategy': '扩展1(加权)'},  # P1激进注 (20%)
        {'front': ext2_front, 'back': [ext2_back_1, ext2_back_2], 'strategy': '扩展2(加权)'},  # P2回补注 (23%)
        {'front': cold_front, 'back': [cold_back_1, cold_back_2], 'strategy': '冷号注(遗漏)'},  # P3冷号注 (22%)
    ]


# 便捷函数：一键获取大乐透推荐
def get_dlt_recommendations(history_data: List[Dict], kelly_bias: float = 0.0) -> List[Dict]:
    """一键获取大乐透推荐
    
    Args:
        history_data: 历史数据
        kelly_bias: Kelly调节参数
    
    Returns:
        5注推荐列表
    """
    analysis = analyze_dlt(history_data)
    return generate_recs_dlt(analysis, kelly_bias)
