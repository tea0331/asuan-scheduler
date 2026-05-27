#!/usr/bin/env python3
"""
双色球模块 — 薄壳，委托 JinZhu 生成推荐
数据获取仍在此模块，推荐逻辑全部交给 JinZhu
"""

from typing import List, Dict, Optional


def fetch_ssq_history(periods: int = 15) -> Optional[List[Dict]]:
    """双色球历史数据获取"""
    from lottery_analyzer import fetch_ssq_history as _fetch
    return _fetch(periods)


def analyze_ssq(history_data: List[Dict]) -> Dict:
    """双色球加权分析"""
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_ssq()


def generate_recs_ssq(analysis: Dict = None, kelly_bias: float = 0.0) -> List[Dict]:
    """生成双色球推荐 — 委托 JinZhu"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('ssq', kelly_bias=kelly_bias)


def get_ssq_recommendations(history_data: List[Dict] = None, kelly_bias: float = 0.0) -> List[Dict]:
    """一键获取双色球推荐"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('ssq', history_data=history_data, kelly_bias=kelly_bias)
