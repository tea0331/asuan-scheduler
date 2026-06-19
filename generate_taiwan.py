#!/usr/bin/env python3
"""
生成台湾威力彩(PLN)和台湾大乐透(LTN)推荐
直接调用games/目录下的分析逻辑，不依赖JinZhu
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

CST = timezone(timedelta(hours=8))
today = datetime.now(CST)
today_str = today.strftime('%Y-%m-%d')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


def generate_pln_recommendations():
    """生成威力彩推荐 — 直接调用games/pln.py"""
    try:
        from games.pln import generate_recs_pln, fetch_pln_history
        
        # 抓取历史数据
        history = fetch_pln_history(15)
        if not history:
            return "\n---\n## 台湾威力彩(PLN) 生成失败：无法获取历史数据\n---\n"
        
        # 生成推荐
        recs = generate_recs_pln(history)
        if not recs:
            return "\n---\n## 台湾威力彩(PLN) 生成失败：无推荐结果\n---\n"
        
        lines = ["\n---\n## 台湾威力彩(PLN) 推荐\n"]
        # 最近开奖
        if history:
            h = history[0]
            lines.append(f"**最近开奖**: {h['period']} → {h['numbers']} + 特号{h.get('special', '?')}\n")
        
        lines.append("**今日推荐(5注):**")
        for i, rec in enumerate(recs[:5]):
            nums = rec.get('numbers', [])
            if len(nums) >= 6:
                main = nums[:6]
                special = nums[6] if len(nums) > 6 else '?'
                lines.append(f"  注{i+1}: {main} + 特号{special} [{rec.get('strategy', 'unknown')}]")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"[PLN] 生成失败: {e}")
        return f"\n---\n## 台湾威力彩(PLN) 生成失败: {e}\n---\n"


def generate_ltn_recommendations():
    """生成大乐透推荐 — 直接调用games/ltn.py

    v8.4: LTN 格式从 front(5)+back(2) 改为 main(6)+special(1)
    """
    try:
        from games.ltn import get_ltn_recommendations

        # 使用一键获取推荐（内部会自动 fetch → analyze → generate）
        recs = get_ltn_recommendations()
        if not recs:
            return "\n---\n## 台湾大乐透(LTN) 生成失败：无推荐结果\n---\n"

        # 获取历史数据用于显示最近开奖
        from games.ltn import fetch_ltn_history
        history = fetch_ltn_history(15)

        lines = ["\n---\n## 台湾大乐透(LTN) 推荐\n"]
        # 最近开奖
        if history:
            h = history[0]
            main = h.get('main', [])
            special = h.get('special', '?')
            lines.append(f"**最近开奖**: {h['period']} → 主号{main} 特别号{special}\n")

        lines.append("**今日推荐(5注):**")
        for i, rec in enumerate(recs[:5]):
            # v8.4 格式: {'main': [6个], 'special': 1个, 'strategy': '...'}
            main = rec.get('main', [])
            special = rec.get('special', '?')

            if len(main) >= 6:
                lines.append(f"  注{i+1}: 主号{main} 特别号{special} [{rec.get('strategy', 'unknown')}]")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"[LTN] 生成失败: {e}")
        return f"\n---\n## 台湾大乐透(LTN) 生成失败: {e}\n---\n"


if __name__ == '__main__':
    print("生成台湾彩票推荐...")
    print("\n" + "="*50)
    print(generate_pln_recommendations())
    print("\n" + "="*50)
    print(generate_ltn_recommendations())
