#!/usr/bin/env python3
"""
七星彩模块 — 薄壳，委托 JinZhu 生成推荐
"""

from typing import List, Dict, Optional


def fetch_qxc_history(periods: int = 15) -> Optional[List[Dict]]:
    """七星彩历史数据获取"""
    from lottery_analyzer import fetch_qxc_history as _fetch
    return _fetch(periods)


def analyze_qxc(history_data: List[Dict]) -> Dict:
    """七星彩加权分析"""
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_qxc()


def generate_recs_qxc(analysis: Dict = None) -> List[Dict]:
    """生成七星彩推荐 — 委托 JinZhu"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('qxc')


def get_qxc_recommendations(history_data: List[Dict] = None) -> List[Dict]:
    """一键获取七星彩推荐"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('qxc', history_data=history_data)
