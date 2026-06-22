#!/usr/bin/env python3
"""
数据清洗脚本 - 阿算智能引擎 (阶段一)
读取 data-pipeline/raw/*.json，标准化后输出到 data-pipeline/processed/*.json
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "processed"

# 彩种代码映射
LOTTERY_CODES = {
    "SSQ": "双色球",
    "DLT": "大乐透",
    "PLN": "排列3",
    "PLT": "排列5",
    "PL3": "排列3",
    "PL5": "排列5",
    "QXC": "七星彩",
    "QLC": "七乐彩",
    "Kuai8": "快乐8",
    "KL8": "快乐8",
    "3D": "3D",
}

def normalize_date(date_str: str) -> str:
    """标准化日期格式为 YYYY-MM-DD"""
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    # 尝试多种格式
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

def normalize_numbers(numbers) -> list:
    """标准化号码格式为 int 列表"""
    if isinstance(numbers, str):
        # 尝试从字符串提取数字
        nums = re.findall(r'\d+', numbers)
        return [int(n) for n in nums if n.isdigit()]
    if isinstance(numbers, list):
        return [int(n) for n in numbers if str(n).isdigit()]
    return []

def normalize_issue(issue) -> str:
    """标准化期号为字符串"""
    return str(issue).strip() if issue else ""

def clean_record(record: dict, lottery_code: str) -> dict:
    """清洗单条记录"""
    return {
        "lottery": lottery_code,
        "issue": normalize_issue(record.get("issue", "")),
        "date": normalize_date(record.get("date", "")),
        "numbers": normalize_numbers(record.get("numbers", [])),
        "sales": int(record.get("sales", 0) or 0),
        "pool": int(record.get("pool", 0) or 0),
        "raw": record,  # 保留原始数据供追溯
    }

def clean_file(raw_file: Path):
    """清洗单个文件"""
    lottery_code = raw_file.stem.upper()
    if lottery_code not in LOTTERY_CODES:
        # 尝试模糊匹配
        for code in LOTTERY_CODES:
            if code.lower() in lottery_code.lower():
                lottery_code = code
                break

    with open(raw_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    if isinstance(raw_data, dict):
        raw_data = [raw_data]
    if not isinstance(raw_data, list):
        raise ValueError(f"未知数据格式: {raw_file}")

    cleaned = [clean_record(r, lottery_code) for r in raw_data]
    out_file = PROCESSED_DIR / f"{lottery_code}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"✅ {raw_file.name} → {out_file.name} ({len(cleaned)} 条)")
    return len(cleaned)

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    raw_files = list(RAW_DIR.glob("*.json"))
    if not raw_files:
        print("⚠️  raw/ 目录为空，无数据可清洗")
        return

    total = 0
    for rf in raw_files:
        try:
            total += clean_file(rf)
        except Exception as e:
            print(f"❌ 清洗失败 {rf.name}: {e}")

    print(f"\n完成: 共清洗 {total} 条记录 → {PROCESSED_DIR}")

if __name__ == "__main__":
    main()
