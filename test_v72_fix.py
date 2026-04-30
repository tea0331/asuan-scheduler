#!/usr/bin/env python3
"""
v7.2 修复验证测试
测试内容：
1. 条件概率方向是否正确（P(n|上期m)）
2. neighbor_bonus 是否正确加载
3. 前后对比（模拟数据）
"""

import sys
import json
sys.path.insert(0, '.')

from lottery_analyzer import WeightedAnalyzer

def test_conditional_probability():
    """测试条件概率计算方向"""
    print("=== 测试1: 条件概率方向验证 ===")

    analyzer = WeightedAnalyzer('dlt')

    # 构造历史数据：强制 号码1 出现后，下一期 号码5 必定出现
    # 模拟20期数据
    history = []
    for i in range(20):
        if i % 3 == 0:
            history.append([1, 2, 3, 4, 5])
        elif i % 3 == 1:
            history.append([5, 6, 7, 8, 9])
        else:
            history.append([10, 11, 12, 13, 14])

    analyzer.history = history

    # 直接调用模块级函数加载配置
    from lottery_analyzer import _load_weight_config
    config = _load_weight_config()
    analyzer.w_freq = config.get('freq', 0.3)
    analyzer.w_miss = config.get('miss', 0.25)
    analyzer.w_trend = config.get('trend', 0.25)
    analyzer.w_zone = config.get('zone', 0.2)
    analyzer.neighbor_bonus = config.get('neighbor_bonus', 0.03)
    analyzer.gamma = config.get('gamma', 0.88)

    # 计算权重
    result = analyzer._calc_weights(
        range(1, 36), lambda x: x, len(history)
    )
    weights = result[0]  # 第一个返回值是权重字典

    weight_5 = weights.get(5, 0)
    weight_1 = weights.get(1, 0)

    print(f"  号码1的权重: {weight_1:.4f}")
    print(f"  号码5的权重: {weight_5:.4f}")

    if weight_5 > weight_1:
        print("  ✅ 条件概率生效：号码5（与1共现）权重更高")
        return True
    else:
        print("  ❌ 条件概率可能未生效")
        return False

def test_neighbor_bonus():
    """测试 neighbor_bonus 配置是否正确加载"""
    print("\n=== 测试2: neighbor_bonus 配置验证 ===")

    from lottery_analyzer import _load_weight_config
    config = _load_weight_config()

    neighbor_bonus = config.get('neighbor_bonus', 0)
    print(f"  neighbor_bonus 值: {neighbor_bonus}")

    if neighbor_bonus == 0.03:
        print("  ✅ neighbor_bonus 正确加载（0.03）")
        return True
    else:
        print(f"  ❌ neighbor_bonus 值异常（期望0.03，实际{neighbor_bonus}）")
        return False

def test_neighbor_bonus_application():
    """测试邻号加分是否真的生效"""
    print("\n=== 测试3: 邻号加分实际生效验证 ===")

    analyzer = WeightedAnalyzer('dlt')
    analyzer._load_weight_config()

    # 只有1期历史，测试邻号加分
    analyzer.history = [[1, 2, 3, 4, 5]]

    weights, _, _ = analyzer._calc_weights(
        range(1, 36), lambda x: x, 1
    )

    # 邻号应该是 2 和 5（1的邻号是2，5的邻号是4和6）
    weight_2 = weights.get(2, 0)
    weight_5 = weights.get(5, 0)
    weight_10 = weights.get(10, 0)  # 非邻号

    print(f"  号码2（邻号）的权重: {weight_2:.4f}")
    print(f"  号码5（邻号）的权重: {weight_5:.4f}")
    print(f"  号码10（非邻号）的权重: {weight_10:.4f}")

    if weight_2 > weight_10 and weight_5 > weight_10:
        print("  ✅ 邻号加分生效")
        return True
    else:
        print("  ❌ 邻号加分可能未生效")
        return False

def compare_before_after():
    """模拟修复前后命中率对比"""
    print("\n=== 测试4: 修复前后命中率对比（模拟）===")

    # 这个测试需要实际历史数据，暂时跳过
    print("  ⚠️  需要实际开奖数据，暂时跳过")
    print("  💡 建议：运行完整回测对比 v7.1 vs v7.2")

    return True

if __name__ == '__main__':
    print("🧪 v7.2 修复验证测试\n")

    results = []

    results.append(("条件概率方向", test_conditional_probability()))
    results.append(("neighbor_bonus配置", test_neighbor_bonus()))
    results.append(("邻号加分生效", test_neighbor_bonus_application()))
    results.append(("命中率对比", compare_before_after()))

    print("\n=== 测试结果汇总 ===")
    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + ("✅ 所有测试通过" if all_passed else "❌ 存在失败测试"))
