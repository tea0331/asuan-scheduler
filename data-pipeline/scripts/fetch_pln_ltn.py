#!/usr/bin/env python3
"""
抓取 PLN/LTN 真实数据 - 阿算智能引擎 (阶段一)
数据源：gdf99.com（台湾彩券网站）
"""

import json
import re
import urllib.request
import time
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "raw"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://gdf99.com/",
}

def fetch_gdf99(game_key: str, period_start: int, periods: int = 500) -> list:
    """从 gdf99.com 按期号倒序抓取"""
    results = []
    current = period_start
    while len(results) < periods:
        url = f"https://gdf99.com/lottery/{game_key}/no/{current}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            
            # 解析号码（7位：6+1 或 6+特别号）
            balls = re.findall(r'class="[^"]*ball[^"]*"[^>]*>\s*(\d{1,2})\s*</', html)
            if not balls or len(balls) < 7:
                balls = re.findall(r'(\d{1,2})\s*</td>', html)
            
            if len(balls) >= 7:
                numbers = [int(b) for b in balls[:7]]
                results.append({
                    "lottery": "PLN" if game_key == "super" else "LTN",
                    "issue": str(current),
                    "date": "",  # gdf99 页面无日期，后续补
                    "numbers": numbers,
                    "sales": 0,
                    "pool": 0,
                })
            
            current -= 1
            time.sleep(0.3)
            
            if len(results) % 100 == 0:
                print(f"  已抓 {len(results)} 期...")
        
        except Exception as e:
            print(f"  期号 {current} 失败: {e}")
            current -= 1
    
    return results

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. PLN（台湾威力彩，super）
    print("⏳ 抓取 PLN（台湾威力彩）...")
    pln_data = fetch_gdf99("super", 115000999, periods=500)
    if pln_data:
        with open(RAW_DIR / "PLN.json", "w", encoding="utf-8") as f:
            json.dump(pln_data, f, ensure_ascii=False, indent=2)
        print(f"  ✅ PLN.json: {len(pln_data)} 条")
    else:
        print("  ❌ PLN: 未获取到数据")
    
    # 2. LTN（台湾大乐透，big）
    print("⏳ 抓取 LTN（台湾大乐透）...")
    ltn_data = fetch_gdf99("big", 115000999, periods=500)
    if ltn_data:
        with open(RAW_DIR / "LTN.json", "w", encoding="utf-8") as f:
            json.dump(ltn_data, f, ensure_ascii=False, indent=2)
        print(f"  ✅ LTN.json: {len(ltn_data)} 条")
    else:
        print("  ❌ LTN: 未获取到数据")
    
    print("\n完成")

if __name__ == "__main__":
    main()
