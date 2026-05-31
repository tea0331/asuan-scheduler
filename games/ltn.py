#!/usr/bin/env python3
"""
台湾大乐透(LTN)模块 — 直接调用JinZhu算法
LTN规则：前区5球(1-47) + 后区2球(1-38)
"""

from typing import List, Dict, Optional
import random


def fetch_ltn_history(periods: int = 15) -> Optional[List[Dict]]:
    """LTN历史数据获取"""
    from lottery_analyzer import fetch_ltn_history as _fetch
    return _fetch(periods)


def analyze_ltn(history_data: List[Dict]) -> Dict:
    """LTN加权分析 — 使用WeightedAnalyzer"""
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_ltn()


def generate_recs_ltn(analysis: Dict = None, kelly_bias: float = 0.0) -> List[Dict]:
    """生成LTN推荐 — 直接算法"""
    if not analysis:
        return []
    
    recs = []
    front_weights = analysis.get('front_weights', [])
    back_weights = analysis.get('back_weights', [])
    
    strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
    
    for i in range(5):
        # 前区选号
        if front_weights:
            if i == 0:  # core_hot: 高权重
                selected = sorted([x[0] for x in front_weights[:5]])
            elif i == 1:  # core_independent: 次高权重
                selected = sorted([x[0] for x in front_weights[5:10]])
            else:  # 其他：随机组合
                selected = sorted([x[0] for x in random.sample(front_weights, 5)])
        else:
            selected = sorted(random.sample(range(1, 48), 5))
        
        # 后区选号
        if back_weights:
            if i < 2:
                selected_back = sorted([x[0] for x in back_weights[i*2:(i+1)*2]])
            else:
                selected_back = sorted([x[0] for x in random.sample(back_weights, 2)])
        else:
            selected_back = sorted(random.sample(range(1, 39), 2))
        
        recs.append({
            'numbers': selected + selected_back,
            'type': f'P{i}',
            'strategy': strategies[i]
        })
    return recs


def get_ltn_recommendations(history_data: List[Dict] = None, kelly_bias: float = 0.0) -> List[Dict]:
    """一键获取LTN推荐"""
    try:
        if not history_data:
            history_data = fetch_ltn_history(15)
        if not history_data:
            return []
        analysis = analyze_ltn(history_data)
        return generate_recs_ltn(analysis, kelly_bias)
    except Exception as e:
        print(f'[LTN] 生成失败: {e}')
        import traceback; traceback.print_exc()
        return []
