#!/usr/bin/env python3
"""台湾彩种生成脚本（独立运行，mock数据）"""
import argparse
import random
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def generate_pln():
    """台湾威力彩（6/38 + 1/8）——从CSV读取真实数据"""
    import csv
    recs = []
    strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
    # 读CSV
    try:
        with open('data/taiwan_pln.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if len(rows) >= 5:
                # 用最近5期数据生成推荐（简单逻辑：取最近一期微调）
                latest = rows[-1]
                base = [int(x) for x in latest['numbers'].split()]
                special = int(latest['special'])
                for i in range(5):
                    # 微调：随机替换1-2个号
                    new = base.copy()
                    for j in range(random.randint(1, 3)):
                        idx = random.randint(0, 5)
                        new[idx] = random.randint(1, 38)
                    recs.append({
                        'numbers': sorted(new) + [special],
                        'type': f'P{i}',
                        'strategy': strategies[i]
                    })
            else:
                # CSV数据不足，用mock
                for i in range(5):
                    main = sorted(random.sample(range(1, 39), 6))
                    special = random.randint(1, 8)
                    recs.append({
                        'numbers': main + [special],
                        'type': f'P{i}',
                        'strategy': strategies[i]
                    })
    except Exception as e:
        logging.warning(f"CSV读取失败: {e}，使用mock数据")
        for i in range(5):
            main = sorted(random.sample(range(1, 39), 6))
            special = random.randint(1, 8)
            recs.append({
                'numbers': main + [special],
                'type': f'P{i}',
                'strategy': strategies[i]
            })
    return recs

def generate_ltn():
    """台湾大乐透（6/49）——从CSV读取真实数据"""
    import csv
    recs = []
    strategies = ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold']
    try:
        with open('data/taiwan_ltn.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if len(rows) >= 5:
                latest = rows[-1]
                base = [int(x) for x in latest['numbers'].split()]
                for i in range(5):
                    new = base.copy()
                    for j in range(random.randint(1, 3)):
                        idx = random.randint(0, 5)
                        new[idx] = random.randint(1, 49)
                    recs.append({
                        'numbers': sorted(new),
                        'type': f'P{i}',
                        'strategy': strategies[i]
                    })
            else:
                for i in range(5):
                    main = sorted(random.sample(range(1, 50), 6))
                    recs.append({
                        'numbers': main,
                        'type': f'P{i}',
                        'strategy': strategies[i]
                    })
    except Exception as e:
        logging.warning(f"CSV读取失败: {e}，使用mock数据")
        for i in range(5):
            main = sorted(random.sample(range(1, 50), 6))
            recs.append({
                'numbers': main,
                'type': f'P{i}',
                'strategy': strategies[i]
            })
    return recs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--type', type=str, required=True,
                        choices=['PLN', 'LTN'],
                        help='PLN=威力彩, LTN=大乐透')
    args = parser.parse_args()
    
    if args.type == 'PLN':
        recs = generate_pln()
        print("## 🎰 台湾威力彩推荐\n")
    else:
        recs = generate_ltn()
        print("## 🎰 台湾大乐透推荐\n")
    
    for i, r in enumerate(recs):
        print(f"注{i+1}: {r['numbers']} ({r['strategy']})")
    
    logging.info(f"✅ {args.type} 推荐生成完成（共{len(recs)}注）")
    return 0

if __name__ == '__main__':
    exit(main())
