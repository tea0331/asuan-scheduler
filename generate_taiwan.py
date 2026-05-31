#!/usr/bin/env python3
"""
生成台湾威力彩(PLN)和台湾大乐透(LTN)推荐
阶段1：清淤完成，建立基础框架
后续阶段2：接入JinZhu四维加权算法
"""
import os
import sys
import csv
import random
import logging
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
today = datetime.now(CST)
today_str = today.strftime('%Y-%m-%d')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def load_pln_history(csv_path=None, count=15):
    """从CSV加载PLN历史数据"""
    if csv_path is None:
        csv_path = os.path.join(DATA_DIR, 'pln_history.csv')
    
    if not os.path.exists(csv_path):
        logging.error(f"[PLN] CSV文件不存在: {csv_path}")
        return []
    
    results = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append({
                    'period': row['period'],
                    'numbers': [
                        int(row['num1']), int(row['num2']), int(row['num3']),
                        int(row['num4']), int(row['num5']), int(row['num6'])
                    ],
                    'special': int(row['special'])
                })
        # 按期限倒序
        results.sort(key=lambda x: x['period'], reverse=True)
        return results[:count]
    except Exception as e:
        logging.error(f"[PLN] 读取CSV失败: {e}")
        return []

def load_ltn_history(csv_path=None, count=15):
    """从CSV加载LTN历史数据"""
    if csv_path is None:
        csv_path = os.path.join(DATA_DIR, 'ltn_history.csv')
    
    if not os.path.exists(csv_path):
        logging.error(f"[LTN] CSV文件不存在: {csv_path}")
        return []
    
    results = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append({
                    'period': row['period'],
                    'front': [
                        int(row['front1']), int(row['front2']), int(row['front3']),
                        int(row['front4']), int(row['front5'])
                    ],
                    'back': [int(row['back1']), int(row['back2'])]
                })
        results.sort(key=lambda x: x['period'], reverse=True)
        return results[:count]
    except Exception as e:
        logging.error(f"[LTN] 读取CSV失败: {e}")
        return []

def generate_pln_recommendations():
    """生成威力彩推荐 — 调用games/pln.py"""
    try:
        from games.pln import get_pln_recommendations
        recs = get_pln_recommendations()
        if not recs:
            return "## 台湾威力彩(PLN) 生成失败：无推荐结果\n"
        
        lines = ["## 台湾威力彩(PLN) 推荐\n"]
        # 尝试获取最近开奖
        try:
            from games.pln import fetch_pln_history
            history = fetch_pln_history(1)
            if history:
                h = history[0]
                lines.append(f"**最近开奖**: {h['period']} → {h['numbers']} + 特号{h.get('special', '?')}\n")
        except:
            pass
        
        lines.append("**今日推荐(5注)**:")
        for i, rec in enumerate(recs[:5]):
            nums = rec.get('numbers', [])
            if len(nums) >= 6:
                main = nums[:6]
                special = nums[6] if len(nums) > 6 else '?'
                lines.append(f"  - 注{i+1}: {main} + 特号{special} [{rec.get('strategy', 'unknown')}]")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"[PLN] 生成失败: {e}")
        return f"## 台湾威力彩(PLN) 生成失败: {e}\n"

def generate_ltn_recommendations():
    """生成大乐透推荐 — 调用games/ltn.py"""
    try:
        from games.ltn import get_ltn_recommendations
        recs = get_ltn_recommendations()
        if not recs:
            return "## 台湾大乐透(LTN) 生成失败：无推荐结果\n"
        
        lines = ["\n## 台湾大乐透(LTN) 推荐\n"]
        # 尝试获取最近开奖
        try:
            from games.ltn import fetch_ltn_history
            history = fetch_ltn_history(1)
            if history:
                h = history[0]
                lines.append(f"**最近开奖**: {h['period']} → 前区{h['front']} 后区{h['back']}\n")
        except:
            pass
        
        lines.append("**今日推荐(5注)**:")
        for i, rec in enumerate(recs[:5]):
            nums = rec.get('numbers', [])
            if len(nums) >= 7:
                front = nums[:5]
                back = nums[5:7]
                lines.append(f"  - 注{i+1}: 前区{front} 后区{back} [{rec.get('strategy', 'unknown')}]")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"[LTN] 生成失败: {e}")
        return f"## 台湾大乐透(LTN) 生成失败: {e}\n"

if __name__ == '__main__':
    game_type = sys.argv[1] if len(sys.argv) > 1 else 'PLN'
    
    if game_type.upper() == 'PLN':
        print(generate_pln_recommendations())
    elif game_type.upper() == 'LTN':
        print(generate_ltn_recommendations())
    elif game_type.upper() == 'ALL':
        print(generate_pln_recommendations())
        print(generate_ltn_recommendations())
    else:
        print(f"未知类型: {game_type}")
        print("用法: python3 generate_taiwan.py [PLN|LTN|ALL]")
