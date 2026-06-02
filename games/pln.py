#!/usr/bin/env python3
"""
台湾威力彩(PLN)模块 — 薄壳，委托 JinZhu 生成推荐
PLN规则：6球(1-38) + 特别号(1-8)
"""

from typing import List, Dict, Optional


def fetch_pln_history(periods: int = 15) -> Optional[List[Dict]]:
    """PLN历史数据获取"""
    from lottery_analyzer import fetch_pln_history as _fetch
    return _fetch(periods)


def analyze_pln(history_data: List[Dict]) -> Dict:
    """PLN加权分析 — 使用WeightedAnalyzer"""
    import lottery_analyzer as la
    wa = la.WeightedAnalyzer(history_data)
    return wa.analyze_pln()


def generate_recs_pln(history_data: Dict = None, kelly_bias: float = 0.0) -> List[Dict]:
    """生成PLN推荐 — 委托 JinZhu"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('pln', history_data=history_data, kelly_bias=kelly_bias)


def get_pln_recommendations(history_data: List[Dict] = None, kelly_bias: float = 0.0) -> List[Dict]:
    """一键获取PLN推荐"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    return jz.generate_recs('pln', history_data=history_data, kelly_bias=kelly_bias)
