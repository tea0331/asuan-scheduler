#!/usr/bin/env python3
"""
真实数据采集脚本 - 阿算智能引擎 (阶段一)
使用 datachart.500.com 接口采集真实历史开奖数据
"""

import json
import re
import urllib.request
import urllib.error
import time
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "raw"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://datachart.500.com/",
}

def fetch_url(url: str, timeout=10) -> str:
    """带重试的URL抓取"""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("gb2312", errors="ignore")
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)

def parse_ssq(html: str) -> list:
    """解析双色球HTML"""
    rows = re.findall(r'<tr[^>]*class="[^"]*t_tr1[^"]*"[^>]*>(.*?)</tr>', html, re.DOTALL)
    results = []
    for row in rows[:100]:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 8:
            continue
        issue = re.sub(r'\D', '', cells[0])
        date = cells[1].strip()
        # 红球6个 + 蓝球1个
        reds = [int(re.sub(r'\D', '', cells[i])) for i in range(2, 8)]
        blue = int(re.sub(r'\D', '', cells[8]) if len(cells) > 8 else cells[-1])
        numbers = reds + [blue]
        results.append({
            "lottery": "SSQ",
            "issue": issue,
            "date": date,
            "numbers": numbers,
            "sales": 0,
            "pool": 0,
        })
    return results

def parse_dlt(html: str) -> list:
    """解析大乐透HTML"""
    rows = re.findall(r'<tr[^>]*class="[^"]*t_tr1[^"]*"[^>]*>(.*?)</tr>', html, re.DOTALL)
    results = []
    for row in rows[:100]:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 10:
            continue
        issue = re.sub(r'\D', '', cells[0])
        date = cells[1].strip()
        # 前区5个 + 后区2个
        fronts = [int(re.sub(r'\D', '', cells[i])) for i in range(2, 7)]
        backs = [int(re.sub(r'\D', '', cells[i])) for i in range(7, 9)]
        numbers = fronts + backs
        results.append({
            "lottery": "DLT",
            "issue": issue,
            "date": date,
            "numbers": numbers,
            "sales": 0,
            "pool": 0,
        })
    return results

def parse_pln(html: str) -> list:
    """解析排列3/5 HTML"""
    rows = re.findall(r'<tr[^>]*class="[^"]*t_tr1[^"]*"[^>]*>(.*?)</tr>', html, re.DOTALL)
    results = []
    for row in rows[:100]:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 5:
            continue
        issue = re.sub(r'\D', '', cells[0])
        date = cells[1].strip()
        nums = [int(re.sub(r'\D', '', cells[i])) for i in range(2, 5)]
        results.append({
            "lottery": "PLN",
            "issue": issue,
            "date": date,
            "numbers": nums,
            "sales": 0,
            "pool": 0,
        })
    return results

def parse_3d(html: str) -> list:
    """解析3D HTML（同排列3格式）"""
    rows = re.findall(r'<tr[^>]*class="[^"]*t_tr1[^"]*"[^>]*>(.*?)</tr>', html, re.DOTALL)
    results = []
    for row in rows[:100]:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 5:
            continue
        issue = re.sub(r'\D', '', cells[0])
        date = cells[1].strip()
        nums = [int(re.sub(r'\D', '', cells[i])) for i in range(2, 5)]
        results.append({
            "lottery": "3D",
            "issue": issue,
            "date": date,
            "numbers": nums,
            "sales": 0,
            "pool": 0,
        })
    return results

def fetch_and_save(url: str, parser, output_name: str):
    """抓取并保存"""
    print(f"⏳ 正在抓取 {output_name}...")
    try:
        html = fetch_url(url)
        data = parser(html)
        if not data:
            print(f"  ⚠️  未解析到数据，尝试备用方案")
            return False
        out_path = RAW_DIR / f"{output_name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  ✅ {output_name}.json: {len(data)}条, 首期={data[0]['issue']}, 尾期={data[-1]['issue']}")
        return True
    except Exception as e:
        print(f"  ❌ 抓取失败: {e}")
        return False

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    tasks = [
        # 双色球
        ("https://datachart.500.com/ssq/history/newinc/history.php?start=26001&end=26200", parse_ssq, "SSQ"),
        # 大乐透
        ("https://datachart.500.com/dlt/history/newinc/history.php?start=26001&end=26200", parse_dlt, "DLT"),
        # 排列3
        ("https://datachart.500.com/pls/history/newinc/history.php?start=26001&end=26200", parse_pln, "PLN"),
        # 排列5
        ("https://datachart.500.com/plw/history/newinc/history.php?start=26001&end=26200", parse_pln, "PLT"),
        # 3D
        ("https://datachart.500.com/sd/history/newinc/history.php?start=24001&end=24200", parse_3d, "3D"),
    ]

    success = 0
    for url, parser, name in tasks:
        if fetch_and_save(url, parser, name):
            success += 1
        time.sleep(1)

    print(f"\n完成: {success}/{len(tasks)} 个彩种采集成功")

if __name__ == "__main__":
    main()
