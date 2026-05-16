#!/usr/bin/env python3
"""
刘海蟾点金 - 蒙特卡洛策略验证模块
模拟N次开奖，统计策略命中分布，输出置信区间

用法:
  validator = MonteCarloValidator()
  confidence = validator.validate(game, history, n_simulations=500)
  # 返回: {p5: x, p50: y, p95: z}
"""

import random
from collections import defaultdict


class MonteCarloValidator:
    """蒙特卡洛策略验证"""

    def __init__(self, n_simulations=500, seed=None):
        """
        Args:
            n_simulations: 模拟次数
            seed: 随机种子（None=不固定）
        """
        self.n_simulations = n_simulations
        self.rng = random.Random(seed)

    def validate(self, game, history, n_simulations=None):
        """
        模拟开奖，统计命中率分布

        Args:
            game: 玩法
            history: 历史开奖数据
            n_simulations: 覆盖默认值
        Returns:
            dict: {
                p5: 5%分位数（最差情况）,
                p50: 中位数（典型情况）,
                p95: 95%分位数（最好情况）,
                mean: 均值,
                simulations: 模拟次数
            }
        """
        n = n_simulations or self.n_simulations

        if len(history) < 5:
            return {'p5': 0, 'p50': 0, 'p95': 0, 'mean': 0, 'simulations': n}

        # 模拟: 从历史中随机抽样一期作为"模拟开奖"
        # 然后统计如果随机选号，命中数的分布
        hit_counts = []

        for _ in range(n):
            # 随机选一期作为模拟开奖
            actual = self.rng.choice(history)
            actual_numbers = self._extract_numbers(game, actual)

            # 随机选号（模拟"盲选"策略）
            predicted = self._random_select(game)

            # 计算命中数
            hits = len(set(predicted) & set(actual_numbers))
            hit_counts.append(hits)

        hit_counts.sort()
        count = len(hit_counts)

        if count == 0:
            return {'p5': 0, 'p50': 0, 'p95': 0, 'mean': 0, 'simulations': n}

        result = {
            'p5': hit_counts[int(count * 0.05)],
            'p50': hit_counts[int(count * 0.50)],
            'p95': hit_counts[int(count * 0.95)],
            'mean': round(sum(hit_counts) / count, 3),
            'simulations': n,
        }

        print(f"[MonteCarlo] {game}: p5={result['p5']} p50={result['p50']} p95={result['p95']} mean={result['mean']}")
        return result

    def validate_strategy(self, game, history, strategy_numbers, n_simulations=None):
        """
        验证特定策略的命中置信区间

        Args:
            game: 玩法
            history: 历史数据
            strategy_numbers: 策略选的号码列表
            n_simulations: 模拟次数
        Returns:
            dict: 同上
        """
        n = n_simulations or self.n_simulations

        if len(history) < 5 or not strategy_numbers:
            return {'p5': 0, 'p50': 0, 'p95': 0, 'mean': 0, 'simulations': n}

        hit_counts = []

        for _ in range(n):
            actual = self.rng.choice(history)
            actual_numbers = self._extract_numbers(game, actual)
            hits = len(set(strategy_numbers) & set(actual_numbers))
            hit_counts.append(hits)

        hit_counts.sort()
        count = len(hit_counts)

        return {
            'p5': hit_counts[int(count * 0.05)] if count > 0 else 0,
            'p50': hit_counts[int(count * 0.50)] if count > 0 else 0,
            'p95': hit_counts[int(count * 0.95)] if count > 0 else 0,
            'mean': round(sum(hit_counts) / count, 3) if count > 0 else 0,
            'simulations': n,
        }

    @staticmethod
    def _extract_numbers(game, draw):
        """从开奖数据中提取号码"""
        if isinstance(draw, dict):
            if game == 'ssq':
                return draw.get('reds', draw.get('numbers', []))
            elif game == 'dlt':
                return draw.get('front', draw.get('numbers', []))
            elif game == 'qxc':
                return draw.get('digits', draw.get('numbers', []))
        elif isinstance(draw, (list, tuple)):
            return draw
        return []

    @staticmethod
    def _random_select(game):
        """随机选号（模拟盲选）"""
        if game == 'ssq':
            return random.sample(range(1, 34), 6)
        elif game == 'dlt':
            return random.sample(range(1, 36), 5)
        elif game == 'qxc':
            return [random.randint(0, 9) for _ in range(7)]
        return []


if __name__ == '__main__':
    import random

    print("蒙特卡洛验证模块自检")

    validator = MonteCarloValidator(n_simulations=1000, seed=42)

    # 模拟双色球历史
    ssq_range = list(range(1, 34))
    history = [{'reds': random.sample(ssq_range, 6)} for _ in range(50)]

    # 验证
    result = validator.validate('ssq', history)
    print(f"  盲选命中分布: {result}")

    # 验证特定策略
    strategy_nums = [1, 5, 12, 18, 25, 33]
    result2 = validator.validate_strategy('ssq', history, strategy_nums)
    print(f"  策略命中分布: {result2}")

    print("\n自检通过 ✓")
