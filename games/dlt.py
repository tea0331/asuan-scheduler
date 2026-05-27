#!/usr/bin/env python3
"""
大乐透模块 — 薄壳，委托 JinZhu 生成推荐
"""

from typing import List, Dict, Optional


def fetch_dlt_history(periods: int = 15) -> Optional[List[Dict]]:
    """大乐透历史数据获取"""
    from lottery_analyzer import fetch_dlt_history as _fetch
    return _fetch(periods)


def analyze_dlt(history_data: List[Dict]) -> Dict:
    """大乐透加权分析"""
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_dlt()


def generate_recs_dlt(analysis: Dict = None, kelly_bias: float = 0.0) -> List[Dict]:
    """生成大乐透推荐 — 委托 JinZhu"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('dlt', kelly_bias=kelly_bias)


def get_dlt_recommendations(history_data: List[Dict] = None, kelly_bias: float = 0.0) -> List[Dict]:
    """一键获取大乐透推荐"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('dlt', history_data=history_data, kelly_bias=kelly_bias)
