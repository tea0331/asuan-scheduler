#!/usr/bin/env python3
"""
测试尾数集中度功能
"""

import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jin_zhu import JinZhu

def test_tail_concentration():
    """测试尾数集中度评分函数"""
    
    jz = JinZhu()
    
    print("=" * 60)
    print("测试尾数集中度评分函数")
    print("=" * 60)
    
    # 测试用例
    test_cases = [
        # (号码列表, 期望评分范围, 说明)
        ([1, 2, 3, 4, 5, 6], (0.5, 0.7), "无尾数重复（过度分散）"),
        ([3, 13, 23, 1, 2, 4], (0.9, 1.0), "1组重复（03/13/23），理想状态"),
        ([7, 17, 2, 12, 22, 5], (0.8, 1.0), "2组重复（07/17, 02/12/22），较好"),
        ([3, 13, 23, 33, 1, 2], (0.1, 0.3), "过度集中（尾数3重复4次）"),
        ([3, 13, 7, 17, 1, 11], (0.3, 0.5), "过多重复组（3组）"),
        ([], (0.4, 0.6), "空列表"),
        ([5, 15, 25, 2, 12, 22], (0.8, 1.0), "2组重复，每组3次"),
    ]
    
    all_passed = True
    
    for numbers, expected_range, description in test_cases:
        score = jz._tail_concentration_score(numbers)
        min_expected, max_expected = expected_range
        
        passed = min_expected <= score <= max_expected
        status = "✅" if passed else "❌"
        
        print(f"\n{status} {description}")
        print(f"   号码: {numbers}")
        print(f"   评分: {score:.2f} (期望范围: {min_expected:.1f}~{max_expected:.1f})")
        
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    print(f"测试结果: {'全部通过 ✅' if all_passed else '存在失败 ❌'}")
    print("=" * 60)
    
    return all_passed

def test_apply_tail_concentration():
    """测试尾数集中度调整功能"""
    
    print("\n" + "=" * 60)
    print("测试尾数集中度调整功能")
    print("=" * 60)
    
    jz = JinZhu()
    
    # 模拟5注推荐（尾数过度集中）
    recommendations = [
        {'reds': [3, 13, 23, 33, 1, 2], 'blue': 5, 'strategy': '核心注A'},  # 尾数3重复4次
        {'reds': [4, 14, 24, 2, 12, 22], 'blue': 8, 'strategy': '核心注B'},  # 尾数4/2/1重复
        {'reds': [5, 6, 7, 8, 9, 10], 'blue': 3, 'strategy': '扩展1'},
        {'reds': [11, 12, 13, 14, 15, 16], 'blue': 7, 'strategy': '扩展2'},
        {'reds': [17, 18, 19, 20, 21, 22], 'blue': 1, 'strategy': '冷号注'},
    ]
    
    print("\n调整前的尾数集中度:")
    for i, rec in enumerate(recommendations):
        reds = rec['reds']
        tails = [n % 10 for n in reds]
        score = jz._tail_concentration_score(reds)
        print(f"  注{i+1}: {reds} -> 尾数{tails} -> 评分{score:.2f}")
    
    # 应用调整
    adjusted = jz._apply_tail_concentration(recommendations, game='ssq')
    
    print("\n调整后的价格尾数集中度:")
    for i, rec in enumerate(adjusted):
        reds = rec['reds']
        tails = [n % 10 for n in reds]
        score = jz._tail_concentration_score(reds)
        print(f"  注{i+1}: {reds} -> 尾数{tails} -> 评分{score:.2f}")
    
    return True

if __name__ == '__main__':
    print("\n🧪 开始测试尾数集中度功能\n")
    
    try:
        test1 = test_tail_concentration()
        test2 = test_apply_tail_concentration()
        
        if test1 and test2:
            print("\n✅ 所有测试通过！尾数集中度功能正常")
            sys.exit(0)
        else:
            print("\n❌ 部分测试失败，请检查代码")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
