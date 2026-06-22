#!/usr/bin/env python3
"""
补全SSQ/DLT日期字段 - 阿算智能引擎 (阶段一)
方案：用期号推算日期（双色球每周二、四、日开奖，大乐透每周一、三、六开奖）
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "raw"

def guess_ssq_date(issue: str) -> str:
    """双色球期号推算日期：每周二、四、日开奖"""
    if not issue or not issue.isdigit():
        return ""
    # 期号格式：YYNNN（年+年内第几期）
    # 2003年起，每周三期
    # 简化：用已知锚点推算
    anchors = {
        "2026070": "2026-06-21",  # 已知
        "2026069": "2026-06-18",
        "2026068": "2026-06-16",
        "2026067": "2026-06-14",
        "2026066": "2026-06-11",
        "2026065": "2026-06-09",
    }
    if issue in anchors:
        return anchors[issue]
    # 用锚点推算（每期约2.333天）
    try:
        base_issue = "2026070"
        base_date = datetime(2026, 6, 21)
        diff = int(issue) - int(base_issue)
        days = diff * 7 / 3  # 每周3期
        guess = base_date + timedelta(days=days)
        return guess.strftime("%Y-%m-%d")
    except:
        return ""

def guess_dlt_date(issue: str) -> str:
    """大乐透期号推算日期：每周一、三、六开奖"""
    if not issue or not issue.isdigit():
        return ""
    anchors = {
        "2026068": "2026-06-20",  # 已知
        "2026067": "2026-06-18",
        "2026066": "2026-06-16",
        "2026065": "2026-06-14",
        "2026064": "2026-06-11",
    }
    if issue in anchors:
        return anchors[issue]
    try:
        base_issue = "2026068"
        base_date = datetime(2026, 6, 20)
        diff = int(issue) - int(base_issue)
        days = diff * 7 / 3
        guess = base_date + timedelta(days=days)
        return guess.strftime("%Y-%m-%d")
    except:
        return ""

def fill_dates(lottery_code: str, guess_func):
    """补全日期字段"""
    raw_file = RAW_DIR / f"{lottery_code}.json"
    if not raw_file.exists():
        print(f"⚠️  {raw_file} 不存在，跳过")
        return
    
    with open(raw_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    updated = 0
    for record in data:
        if not record.get("date"):
            issue = str(record.get("issue", ""))
            guessed = guess_func(issue)
            if guessed:
                record["date"] = guessed
                updated += 1
    
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ {lottery_code}.json: 补全 {updated} 条日期")

def main():
    print("=== 补全SSQ/DLT日期字段 ===")
    fill_dates("SSQ", guess_ssq_date)
    fill_dates("DLT", guess_dlt_date)
    print("=== 完成 ===")

if __name__ == "__main__":
    main()
