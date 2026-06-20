#!/usr/bin/env python3
"""step2_generate.py — v8.6 分步执行: 调混元API生成6板块

用法: python3 step2_generate.py
依赖: cache/{date}_raw.json (step1 产出)
输出: cache/{date}_ai.md    (AI生成的6板块内容)

被杀后重跑: 如果当天 cache 已存在则跳过（除非 --force）
"""
import os
import sys
import json
import logging

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from generate_full_daily import generate_sections_ai, today_str

CACHE_DIR = os.path.join(PROJECT_DIR, 'cache')
RAW_PATH = os.path.join(CACHE_DIR, f'{today_str}_raw.json')
AI_PATH = os.path.join(CACHE_DIR, f'{today_str}_ai.md')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def main():
    force = '--force' in sys.argv

    if os.path.exists(AI_PATH) and not force:
        logging.info(f"[step2] 缓存已存在: {AI_PATH}（用 --force 强制重生成）")
        print(f"✅ step2 跳过（缓存已存在）: {AI_PATH}")
        return

    if not os.path.exists(RAW_PATH):
        logging.error(f"[step2] 找不到 {RAW_PATH}，请先运行 step1_fetch.py")
        print(f"❌ step2 失败: 缺少依赖 {RAW_PATH}")
        sys.exit(1)

    logging.info(f"========== step2 AI生成6板块 {today_str} ==========")

    with open(RAW_PATH, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)

    all_raw = cache_data['all_raw']
    top_items = cache_data['top_items']

    logging.info(f"[step2] 读取缓存: {len(all_raw)} 条原始, {len(top_items)} 条过滤")

    content = generate_sections_ai(all_raw, top_items)

    with open(AI_PATH, 'w', encoding='utf-8') as f:
        f.write(content)

    logging.info(f"[step2] ✅ AI内容写入: {AI_PATH} ({len(content)}字符)")
    print(f"✅ step2 完成: {len(content)}字符 → {AI_PATH}")


if __name__ == '__main__':
    main()
