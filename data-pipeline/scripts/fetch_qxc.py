#!/usr/bin/env python3
"""
抓取七星彩 QXC 历史数据 - 阿算智能引擎 (阶段一)
数据源：https://api.ruseo.cn/api/lottery?type=qxc&issue=260622089
"""

import json
import time
import urllib.request
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "raw"

def fetch_qxc_page(page: int = 1) -> list:
    """按页抓取数据"""
    url = f"https://api.ruseo.cn/api/lottery?type=qxc&count=100&page={page}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            item = data["data"]["data"]["list"][0]
            return {
                "lottery": "QXC",
                "issue": item["issue"],
                "date": item["date"],
                "numbers": [int(n) for n in item["winning_numbers"]],
                "sales": 0,
                "pool": 0,
            }
    except Exception as e:
        pass
    return None

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    
    # 七星彩期号规律：260622089（2026年06月22日第089期）
    # 倒序循环获取历史数据
    print("⏳ 抓取 QXC 历史数据...")
    
    all_data = []
    seen = set()
    
    # 从最新期开始，往前推300期
    latest_issue = 260622089  # 2026-06-22
    for offset in range(0, 300):
        issue = latest_issue - offset
        issue_str = str(issue)
        
        data = fetch_qxc_by_issue(issue_str)
        if data and data["issue"] not in seen:
            seen.add(data["issue"])
            all_data.append(data)
            if len(all_data) % 50 == 0:
                print(f"  已抓 {len(all_data)} 期...")
        time.sleep(0.3)  # 避免请求过快
    
    # 按期号排序（从小到大）
    all_data.sort(key=lambda x: x["issue"])
    
    out_path = RAW_DIR / "QXC.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ QXC.json: {len(all_data)} 条")
    if all_data:
        print(f"   首期: {all_data[0]['issue']} ({all_data[0]['date']})")
        print(f"   尾期: {all_data[-1]['issue']} ({all_data[-1]['date']})")

if __name__ == "__main__":
    main()
