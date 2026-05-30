#!/usr/bin/env python3
"""台湾彩种生成脚本（独立运行，不碰现有逻辑）"""
import os
import sys
import json
import random
import logging

CST = __import__('datetime').timezone(__import__('datetime').timedelta(hours=8))
today_str = __import__('datetime').datetime.now(CST).strftime('%Y-%m-%d')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def generate_pln():
    """台湾威力彩（6/38 + 1/8）"""
    recs = []
    for i in range(5):
        main = sorted(random.sample(range(1, 39), 6))
        special = random.randint(1, 8)
        recs.append({
            'numbers': main + [special],
            'type': f'P{i}',
            'strategy': ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold'][i]
        })
    return recs

def generate_ltn():
    """台湾大乐透（6/49）"""
    recs = []
    for i in range(5):
        main = sorted(random.sample(range(1, 50), 6))
        recs.append({
            'numbers': main,
            'type': f'P{i}',
            'strategy': ['core_hot', 'core_independent', 'ext1', 'ext2', 'cold'][i]
        })
    return recs

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--type', type=str, required=True,
                        choices=['PLN', 'LTN'],
                        help='PLN=威力彩, LTN=大乐透')
    args = parser.parse_args()
    
    if args.type == 'PLN':
        recs = generate_pln()
        print(f"## 🎰 台湾威力彩推荐 {today_str}\n")
    else:
        recs = generate_ltn()
        print(f"## 🎰 台湾大乐透推荐 {today_str}\n")
    
    for i, r in enumerate(recs):
        print(f"注{i+1}: {r['numbers']} ({r['strategy']})")
    
    # 记录到 lottery-predictions.json
    preds = {}
    if os.path.exists('lottery-predictions.json'):
        with open('lottery-predictions.json', 'r') as f:
            preds = json.load(f)
    
    if args.type == 'PLN':
        preds[today_str] = {'PLN': [{'numbers': r['numbers'], 'type': r['type']} for r in recs]}
    else:
        preds[today_str] = {'LTN': [{'numbers': r['numbers'], 'type': r['type']} for r in recs]}
    
    with open('lottery-predictions.json', 'w') as f:
        json.dump(preds, f, ensure_ascii=False, indent=2)
    
    logging.info(f"✅ {args.type} 推荐已生成并记录")
    return 0

if __name__ == '__main__':
    sys.exit(main())
