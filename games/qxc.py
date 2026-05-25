"""
七星彩模块 - 从 lottery_analyzer.py 拆出
v4.0 重构: 独立QXC分析和推荐生成逻辑
"""

import sys
from typing import List, Dict, Optional

from lottery_analyzer import WeightedAnalyzer, Strategy


def fetch_qxc_history(periods: int = 15) -> Optional[List[Dict]]:
    """七星彩历史数据获取（从lottery_analyzer导入）"""
    from lottery_analyzer import fetch_qxc_history as _fetch
    return _fetch(periods)


def analyze_qxc(history_data: List[Dict]) -> Dict:
    """七星彩加权分析（独立函数，逐位统计）
    
    Args:
        history_data: 七星彩历史数据 [{'period':xxx, 'digits':[...]}, ...]
    
    Returns:
        analysis dict: 包含 positions (7位各自权重) 等
    """
    if not history_data or len(history_data) == 0:
        raise ValueError("历史数据为空，无法分析")
    
    # 直接调用 lottery_analyzer 中的方法
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_qxc()


def generate_recs_qxc(analysis: Dict) -> List[Dict]:
    """根据加权分析生成七星彩推荐（逐位选号）
    
    Args:
        analysis: analyze_qxc() 返回的分析结果
    
    Returns:
        推荐列表 [{'digits':[...], 'strategy':...}, ...]
        共5注: P0核心注A/B(35%) + P1激进注(20%) + P2回补注(23%) + P3冷号注(22%)
    """
    if not analysis:
        raise ValueError("analysis为空，无法生成推荐")
    
    positions = analysis['positions']
    total = analysis.get('total_periods', 15)
    
    # 权重排序（每位前11个号码）
    all_pool = []
    for pos_idx, pos_data in enumerate(positions):
        weights = pos_data['weights']
        all_pool.append([n for n, w in weights[:11]])
    
    # 核心注A: 每位权重TOP1
    core_A = [pool[0] if pool else 0 for pool in all_pool]
    
    # 核心注B: 完全独立（TOP7-11，和A不重叠）
    core_B = []
    for pos_idx, pool in enumerate(all_pool):
        found = False
        for n in pool[6:11]:  # TOP7-11
            if n != core_A[pos_idx]:
                core_B.append(n)
                found = True
                break
        if not found:
            core_B.append(pool[1] if len(pool) > 1 else (pool[0] if pool else 0))
    
    # 扩展1: 前3位核心+后4位次高权重
    ext1 = list(core_A)
    for i in range(3, 7):
        weights = positions[i]['weights']
        ext1[i] = weights[1][0] if len(weights) > 1 else (weights[0][0] if weights else 0)
    
    # 扩展2: 前2位核心+后5位中等频率
    ext2 = list(core_A)
    for i in range(2, 7):
        freq = positions[i]['freq']
        mid = [n for n, c in freq.items() if 2 <= c <= 3]
        if not mid:
            miss = positions[i]['miss']
            mid = sorted(miss.keys(), key=lambda x: miss.get(x, 0), reverse=True)[:1]
        ext2[i] = mid[0] if mid else (positions[i]['weights'][0][0] if positions[i]['weights'] else 0)
    
    # 冷号注: 每位遗漏最高
    cold = []
    for pos_idx, pos_data in enumerate(positions):
        miss = pos_data['miss']
        if miss:
            cold_num = sorted(miss.keys(), key=lambda x: miss[x], reverse=True)[0]
        else:
            cold_num = pos_data['weights'][0][0] if pos_data['weights'] else 0
        cold.append(cold_num)
    
    return [
        {'digits': core_A, 'strategy': '核心注(权重)A'},  # P0核心注A (35%)
        {'digits': core_B, 'strategy': '核心注(权重)B'},  # P0核心注B (35%)
        {'digits': ext1, 'strategy': '扩展1(次热)'},  # P1激进注 (20%)
        {'digits': ext2, 'strategy': '扩展2(回补)'},  # P2回补注 (23%)
        {'digits': cold, 'strategy': '冷号注(遗漏)'},  # P3冷号注 (22%)
    ]


# 便捷函数：一键获取七星彩推荐
def get_qxc_recommendations(history_data: List[Dict]) -> List[Dict]:
    """一键获取七星彩推荐
    
    Args:
        history_data: 历史数据
    
    Returns:
        5注推荐列表
    """
    analysis = analyze_qxc(history_data)
    return generate_recs_qxc(analysis)
