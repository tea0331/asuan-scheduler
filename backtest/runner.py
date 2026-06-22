#!/usr/bin/env python3
"""
回测框架 - 阿算智能引擎 阶段二
读取真实开奖数据，模拟JinZhu推荐逻辑，计算命中率
"""

import json
import sys
import random
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data-pipeline/raw"
PROCESSED_DIR = BASE_DIR / "data-pipeline/processed"
RESULTS_DIR = Path(__file__).parent / "results"

def load_data(lottery_code: str, max_periods: int = 100) -> list:
    """加载真实开奖数据"""
    raw_file = RAW_DIR / f"{lottery_code}.json"
    if not raw_file.exists():
        print(f"❌ {raw_file} 不存在")
        return []
    
    with open(raw_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 按期号排序（旧→新）
    data.sort(key=lambda x: int(x.get("issue", "0")))
    return data[-max_periods:]  # 取最近N期

def simulate_jinzhu(record: dict) -> dict:
    """
    模拟JinZhu推荐逻辑（简化版）
    实际逻辑在 jin_zhu.py，这里做简化模拟
    """
    lottery = record.get("lottery", "")
    numbers = record.get("numbers", [])
    
    if not numbers:
        return None
    
    # 简化推荐：随机选号（实际应调用 jin_zhu.py）
    if lottery == "SSQ":
        # 双色球：6+1
        red = random.sample(range(1, 34), 6)
        blue = random.randint(1, 17)
        recommended = {"red": sorted(red), "blue": blue}
    elif lottery == "DLT":
        # 大乐透：5+2
        front = random.sample(range(1, 36), 5)
        back = random.sample(range(1, 13), 2)
        recommended = {"front": sorted(front), "back": sorted(back)}
    else:
        return None
    
    return recommended

def check_hit(record: dict, recommended: dict) -> dict:
    """检查推荐与实际开奖的命中情况"""
    lottery = record.get("lottery", "")
    actual = record.get("numbers", [])
    rec = recommended
    
    if lottery == "SSQ":
        actual_red = set(actual[:6])
        actual_blue = actual[6]
        rec_red = set(rec["red"])
        rec_blue = rec["blue"]
        
        red_hit = len(actual_red & rec_red)
        blue_hit = 1 if actual_blue == rec_blue else 0
        
        return {
            "red_hit": red_hit,
            "blue_hit": blue_hit,
            "total_hit": red_hit + blue_hit,
            "level": calculate_ssq_level(red_hit, blue_hit)
        }
    
    elif lottery == "DLT":
        actual_front = set(actual[:5])
        actual_back = set(actual[5:])
        rec_front = set(rec["front"])
        rec_back = set(rec["back"])
        
        front_hit = len(actual_front & rec_front)
        back_hit = len(actual_back & rec_back)
        
        return {
            "front_hit": front_hit,
            "back_hit": back_hit,
            "total_hit": front_hit + back_hit,
            "level": calculate_dlt_level(front_hit, back_hit)
        }
    
    return {}

def calculate_ssq_level(red_hit: int, blue_hit: int) -> int:
    """计算双色球奖级"""
    if red_hit == 6 and blue_hit == 1:
        return 1  # 一等奖
    elif red_hit == 6:
        return 2  # 二等奖
    elif red_hit == 5 and blue_hit == 1:
        return 3
    elif red_hit == 5 or (red_hit == 4 and blue_hit == 1):
        return 4
    elif red_hit == 4 or (red_hit == 3 and blue_hit == 1):
        return 5
    elif blue_hit == 1:
        return 6  # 六等奖
    else:
        return 0  # 未中奖

def calculate_dlt_level(front_hit: int, back_hit: int) -> int:
    """计算大乐透奖级"""
    if front_hit == 5 and back_hit == 2:
        return 1
    elif front_hit == 5 and back_hit == 1:
        return 2
    elif front_hit == 5 or (front_hit == 4 and back_hit == 2):
        return 3
    elif (front_hit == 4 and back_hit == 1) or (front_hit == 3 and back_hit == 2):
        return 4
    elif (front_hit == 4) or (front_hit == 3 and back_hit == 1) or (front_hit == 2 and back_hit == 2):
        return 5
    elif back_hit == 2:
        return 6
    elif back_hit == 1:
        return 7
    elif front_hit == 3 or (front_hit == 1 and back_hit == 2):
        return 8
    else:
        return 0

def run_backtest(lottery_code: str, periods: int = 100):
    """运行回测"""
    print(f"\n=== 回测 {lottery_code}（最近{periods}期）===")
    
    data = load_data(lottery_code, periods)
    if not data:
        return
    
    results = []
    level_stats = {i: 0 for i in range(9)}  # 0-8奖级
    
    for i, record in enumerate(data):
        recommended = simulate_jinzhu(record)
        if not recommended:
            continue
        
        hit_result = check_hit(record, recommended)
        results.append({
            "issue": record.get("issue"),
            "date": record.get("date"),
            "actual": record.get("numbers"),
            "recommended": recommended,
            "hit": hit_result
        })
        
        level = hit_result.get("level", 0)
        level_stats[level] += 1
        
        if (i + 1) % 20 == 0:
            print(f"  已回测 {i + 1}/{len(data)} 期...")
    
    # 保存结果
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_file = RESULTS_DIR / f"{lottery_code}_backtest.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 统计
    total = len(results)
    print(f"\n✅ 回测完成：{total} 期")
    print(f"  未中奖：{level_stats[0]} 期（{level_stats[0]/total*100:.1f}%）")
    for level in range(1, 9):
        count = level_stats[level]
        if count > 0:
            print(f"  {level}等奖：{count} 期（{count/total*100:.1f}%）")
    
    return results

def main():
    print("=== 阿算智能引擎 回测框架 ===")
    
    # 回测SSQ（最近100期）
    run_backtest("SSQ", periods=100)
    
    # 回测DLT（最近100期）
    run_backtest("DLT", periods=100)
    
    print("\n=== 回测完成 ===")

if __name__ == "__main__":
    main()
