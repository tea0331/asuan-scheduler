#!/usr/bin/env python3
"""
刘海蟾点金 - 信息熵异常检测模块
计算号码分布的香农熵，检测是否偏离纯随机分布

用法:
  detector = EntropyDetector()
  is_anomalous, ratio = detector.is_anomalous(recent_draws, number_range, extract_fn)
  # ratio < threshold → 可能存在非随机模式 → aggressive模式
"""

import math
from collections import Counter


class EntropyDetector:
    """信息熵异常检测器"""

    def __init__(self, threshold=0.85, window=5):
        """
        Args:
            threshold: 熵比阈值，低于此值判定异常（0.85=偏离均匀分布15%以上）
            window: 检测窗口（近N期）
        """
        self.threshold = threshold
        self.window = window

    @staticmethod
    def calc_shannon_entropy(numbers, number_range):
        """
        计算号码分布的香农熵

        Args:
            numbers: 开出号码列表（多期合并）
            number_range: 号码范围 list[int]
        Returns:
            float: 香农熵 (bits)
        """
        if not numbers:
            return 0.0

        freq = Counter(numbers)
        total = len(numbers)
        entropy = 0.0
        for n in number_range:
            p = freq.get(n, 0) / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    @staticmethod
    def max_entropy(number_range):
        """均匀分布时的最大熵"""
        n = len(number_range)
        if n <= 1:
            return 0.0
        return math.log2(n)

    def calc_entropy_ratio(self, draws, number_range, extract_fn):
        """
        计算近window期的平均熵比 (实际熵/最大熵)

        Args:
            draws: 历史开奖数据列表
            number_range: 号码范围
            extract_fn: 提取号码的函数
        Returns:
            float: 熵比 [0, 1]，1=完全随机
        """
        max_e = self.max_entropy(number_range)
        if max_e == 0:
            return 1.0

        recent = draws[-self.window:] if len(draws) >= self.window else draws
        if not recent:
            return 1.0

        ratios = []
        for draw in recent:
            nums = extract_fn(draw) if callable(extract_fn) else draw
            if not nums:
                continue
            e = self.calc_shannon_entropy(nums, number_range)
            ratios.append(e / max_e)

        return sum(ratios) / len(ratios) if ratios else 1.0

    def is_anomalous(self, draws, number_range, extract_fn):
        """
        检测号码分布是否偏离纯随机

        Args:
            draws: 历史开奖数据
            number_range: 号码范围
            extract_fn: 提取号码函数
        Returns:
            (bool, float): (是否异常, 熵比)
        """
        ratio = self.calc_entropy_ratio(draws, number_range, extract_fn)
        return ratio < self.threshold, ratio

    def get_mode_recommendation(self, draws, number_range, extract_fn):
        """
        根据熵比推荐运行模式

        Returns:
            dict: {mode, entropy_ratio, recommendation}
        """
        is_anomalous, ratio = self.is_anomalous(draws, number_range, extract_fn)

        if ratio < 0.70:
            mode = 'aggressive'
            recommendation = '熵值极低，强烈偏离随机，可能存在可利用模式'
        elif ratio < self.threshold:
            mode = 'aggressive'
            recommendation = '熵值偏低，存在轻微偏离，适度激进'
        elif ratio > 0.95:
            mode = 'conservative'
            recommendation = '熵值接近纯随机，策略边际收益低，保守为上'
        else:
            mode = 'normal'
            recommendation = '熵值正常，维持当前策略'

        return {
            'mode': mode,
            'entropy_ratio': ratio,
            'is_anomalous': is_anomalous,
            'recommendation': recommendation,
        }


if __name__ == '__main__':
    # 自检：用模拟数据测试
    import random

    print("信息熵检测模块自检")

    detector = EntropyDetector()

    # 测试1: 纯随机数据
    random_draws = [list(range(1, 7)) for _ in range(10)]  # 伪随机
    for d in random_draws:
        random.shuffle(d)
    ssq_range = list(range(1, 34))
    # 模拟双色球红球
    test_draws = [{'reds': random.sample(ssq_range, 6)} for _ in range(10)]
    is_a, ratio = detector.is_anomalous(test_draws, ssq_range, lambda d: d['reds'])
    print(f"随机数据: 熵比={ratio:.4f}, 异常={is_a}")

    # 测试2: 固定模式（异常）
    biased_draws = [{'reds': [1, 2, 3, 4, 5, 6]} for _ in range(10)]
    is_a2, ratio2 = detector.is_anomalous(biased_draws, ssq_range, lambda d: d['reds'])
    print(f"固定模式: 熵比={ratio2:.4f}, 异常={is_a2}")

    # 测试3: 模式推荐
    rec = detector.get_mode_recommendation(test_draws, ssq_range, lambda d: d['reds'])
    print(f"推荐: {rec}")

    print("\n自检通过 ✓")
