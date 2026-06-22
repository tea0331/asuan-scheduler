#!/usr/bin/env python3
"""
真实数据采集脚本 v3 - 直接解析期号中的号码
彩种：SSQ, DLT, QXC, LTN, PLN
"""

import json
import re
import urllib.request
import time
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "raw"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://datachart.500.com/",
}

def fetch_url(url: str, timeout=10) -> str:
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("gb2312", errors="ignore")
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)
    return ""

def parse_ssq_from_html(html: str) -> list:
    """从HTML解析双色球：期号格式 2607003060814262708（后2位蓝球，前6位红球）"""
    # 抓所有期号行
    pattern = r'(\d{8})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+.*?(\d{4}-\d{2}-\d{2})'
    matches = re.findall(pattern, html)
    data = []
    for m in matches[:100]:
        issue = m[0]
        nums = [int(x) for x in m[1:7]]  # 红球
        blue = int(m[7])  # 蓝球
        date = m[8]
        data.append({"lottery": "SSQ", "issue": issue, "date": date, "numbers": nums + [blue], "sales": 0, "pool": 0})
    return data

def parse_dlt_from_html(html: str) -> list:
    """大乐透：期号+前5后2"""
    pattern = r'(\d{8})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+.*?(\d{4}-\d{2}-\d{2})'
    matches = re.findall(pattern, html)
    data = []
    for m in matches[:100]:
        issue = m[0]
        fronts = [int(x) for x in m[1:6]]
        backs = [int(m[6]), int(m[7])]
        date = m[8]
        data.append({"lottery": "DLT", "issue": issue, "date": date, "numbers": fronts + backs, "sales": 0, "pool": 0})
    return data

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    
    # 简化：直接用之前web_fetch拿到的内容解析
    print("⏳ 正在采集 SSQ...")
    try:
        html = fetch_url("https://datachart.500.com/ssq/history/newinc/history.php?start=26001&end=26200")
        data = parse_ssq_from_html(html)
        if data:
            with open(RAW_DIR / "SSQ.json", "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  ✅ SSQ.json: {len(data)}条, 首期={data[0]['issue']}, 尾期={data[-1]['issue']}")
    except Exception as e:
        print(f"  ❌ SSQ 失败: {e}")
    
    time.sleep(1)
    
    print("⏳ 正在采集 DLT...")
    try:
        html = fetch_url("https://datachart.500.com/dlt/history/newinc/history.php?start=26001&end=26200")
        data = parse_dlt_from_html(html)
        if data:
            with open(RAW_DIR / "DLT.json", "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  ✅ DLT.json: {len(data)}条, 首期={data[0]['issue']}, 尾期={data[-1]['issue']}")
    except Exception as e:
        print(f"  ❌ DLT 失败: {e}")
    
    print("\n完成")

if __name__ == "__main__":
    main()
