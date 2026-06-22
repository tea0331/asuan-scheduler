#!/usr/bin/env python3
"""
真实数据采集脚本 v2 - 阿算智能引擎 (阶段一)
彩种：SSQ, DLT, QXC, LTN, PLN
"""

import json
import re
import urllib.request
import urllib.error
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

def parse_table(html: str) -> list:
    """通用表格解析：提取所有tr，返回每行的td列表"""
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    result = []
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if cells:
            result.append(cells)
    return result

def fetch_ssq() -> list:
    """双色球：https://datachart.500.com/ssq/"""
    url = "https://datachart.500.com/ssq/history/newinc/history.php?start=26001&end=26200"
    html = fetch_url(url)
    rows = parse_table(html)
    data = []
    for cells in rows:
        if len(cells) < 9:
            continue
        issue = re.sub(r'\D', '', cells[0])
        if not issue:
            continue
        date = cells[1]
        try:
            reds = [int(re.sub(r'\D', '', cells[i])) for i in range(2, 8)]
            blue = int(re.sub(r'\D', '', cells[8]))
            numbers = reds + [blue]
        except:
            continue
        data.append({"lottery": "SSQ", "issue": issue, "date": date, "numbers": numbers, "sales": 0, "pool": 0})
    return data

def fetch_dlt() -> list:
    """大乐透：https://datachart.500.com/dlt/"""
    url = "https://datachart.500.com/dlt/history/newinc/history.php?start=26001&end=26200"
    html = fetch_url(url)
    rows = parse_table(html)
    data = []
    for cells in rows:
        if len(cells) < 9:
            continue
        issue = re.sub(r'\D', '', cells[0])
        if not issue:
            continue
        date = cells[1]
        try:
            fronts = [int(re.sub(r'\D', '', cells[i])) for i in range(2, 7)]
            backs = [int(re.sub(r'\D', '', cells[i])) for i in range(7, 9)]
            numbers = fronts + backs
        except:
            continue
        data.append({"lottery": "DLT", "issue": issue, "date": date, "numbers": numbers, "sales": 0, "pool": 0})
    return data

def fetch_qxc() -> list:
    """七星彩：https://datachart.500.com/qxc/"""
    url = "https://datachart.500.com/qxc/history/newinc/history.php?start=26001&end=26200"
    html = fetch_url(url)
    rows = parse_table(html)
    data = []
    for cells in rows:
        if len(cells) < 10:
            continue
        issue = re.sub(r'\D', '', cells[0])
        if not issue:
            continue
        date = cells[1]
        try:
            numbers = [int(re.sub(r'\D', '', cells[i])) for i in range(2, 9)]
        except:
            continue
        data.append({"lottery": "QXC", "issue": issue, "date": date, "numbers": numbers, "sales": 0, "pool": 0})
    return data

def fetch_ltn() -> list:
    """台湾大乐透 - 使用 gdf99.com 数据源"""
    # 台湾彩种用 gdf99.com
    url = "https://www.gdf99.com/tw/dlt/"
    try:
        html = fetch_url(url)
        rows = parse_table(html)
        data = []
        for cells in rows[:100]:
            if len(cells) < 8:
                continue
            issue = re.sub(r'\D', '', cells[0])
            if not issue:
                continue
            date = cells[1] if len(cells) > 1 else ""
            try:
                numbers = [int(re.sub(r'\D', '', cells[i])) for i in range(2, min(9, len(cells)))]
            except:
                continue
            data.append({"lottery": "LTN", "issue": issue, "date": date, "numbers": numbers, "sales": 0, "pool": 0})
        return data
    except:
        return []

def fetch_pln() -> list:
    """台湾威力彩 - 使用 gdf99.com 数据源"""
    url = "https://www.gdf99.com/tw/pln/"
    try:
        html = fetch_url(url)
        rows = parse_table(html)
        data = []
        for cells in rows[:100]:
            if len(cells) < 6:
                continue
            issue = re.sub(r'\D', '', cells[0])
            if not issue:
                continue
            date = cells[1] if len(cells) > 1 else ""
            try:
                numbers = [int(re.sub(r'\D', '', cells[i])) for i in range(2, min(7, len(cells)))]
            except:
                continue
            data.append({"lottery": "PLN", "issue": issue, "date": date, "numbers": numbers, "sales": 0, "pool": 0})
        return data
    except:
        return []

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    
    tasks = [
        ("SSQ", fetch_ssq),
        ("DLT", fetch_dlt),
        ("QXC", fetch_qxc),
        ("LTN", fetch_ltn),
        ("PLN", fetch_pln),
    ]
    
    results = {}
    for name, fetcher in tasks:
        print(f"⏳ 正在抓取 {name}...")
        try:
            data = fetcher()
            if data:
                out_path = RAW_DIR / f"{name}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"  ✅ {name}.json: {len(data)}条, 首期={data[0]['issue']}, 尾期={data[-1]['issue']}")
                results[name] = len(data)
            else:
                print(f"  ⚠️  {name}: 未获取到数据")
                results[name] = 0
        except Exception as e:
            print(f"  ❌ {name}: 抓取失败 - {e}")
            results[name] = 0
        time.sleep(1)
    
    print(f"\n完成: {sum(1 for v in results.values() if v > 0)}/5 个彩种采集成功")
    print(f"详情: {results}")

if __name__ == "__main__":
    main()
