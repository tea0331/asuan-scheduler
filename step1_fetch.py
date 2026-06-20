#!/usr/bin/env python3
"""step1_fetch.py — v8.6 分步执行: 抓取新闻素材 + 领域配额过滤

用法: python3 step1_fetch.py
输出: cache/{date}_raw.json  (all_raw + top_items)

被杀后重跑: 如果当天 cache 已存在则跳过（除非 --force）
"""
import os
import sys
import json
import logging

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from generate_full_daily import fetch_and_filter, today_str

CACHE_DIR = os.path.join(PROJECT_DIR, 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_PATH = os.path.join(CACHE_DIR, f'{today_str}_raw.json')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def main():
    force = '--force' in sys.argv

    if os.path.exists(CACHE_PATH) and not force:
        logging.info(f"[step1] 缓存已存在: {CACHE_PATH}（用 --force 强制重抓）")
        print(f"✅ step1 跳过（缓存已存在）: {CACHE_PATH}")
        return

    logging.info(f"========== step1 抓取新闻素材 {today_str} ==========")

    all_raw, top_items, source_stats, domain_stats = fetch_and_filter()

    cache_data = {
        'date': today_str,
        'source_stats': source_stats,
        'domain_stats': domain_stats,
        'all_raw': all_raw,
        'top_items': top_items,
    }

    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    logging.info(f"[step1] ✅ 缓存写入: {CACHE_PATH}")
    logging.info(f"[step1] 原始新闻 {len(all_raw)} 条, 过滤后 {len(top_items)} 条")
    print(f"✅ step1 完成: {len(all_raw)} 条原始 → {len(top_items)} 条过滤 → {CACHE_PATH}")


if __name__ == '__main__':
    main()
