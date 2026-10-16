#!/usr/bin/env python3
"""
每日寓言生成模块（独立脚本，可单独跑，也可挂主流程）

功能：
1. 从 data/parable_topics.json 主题池里按序取一个概念（记录已用，避免重复）
2. 调用 DeepSeek V4 生成"寓言故事 + 概念解释 + 隐喻对应表"
3. 追加到日报 output/YYYY-MM-DD.md 末尾

用法：
    python3 add_parable.py [YYYY-MM-DD]

风格约束（对齐刘老板偏好）：
- 全程不点破概念名，直到最后一小段
- 结构化输出：寓言 + ①概念解释 ②逐条隐喻拆解
- 极简硬核，拒绝意义空话
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(MODULE_DIR, 'data')
OUTPUT_DIR = os.path.join(MODULE_DIR, 'output')
TOPICS_PATH = os.path.join(DATA_DIR, 'parable_topics.json')
USED_PATH = os.path.join(DATA_DIR, 'parable_used.json')

API_URL = "https://api.deepseek.com/v1/chat/completions"
API_MODEL = "deepseek-chat"


def _load_env():
    env_path = os.path.join(MODULE_DIR, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _pick_topic():
    """按序取一个未用过的主题；全用完则按日期哈希取，避免立刻重复"""
    with open(TOPICS_PATH, encoding='utf-8') as f:
        topics = json.load(f)['topics']

    used = []
    if os.path.exists(USED_PATH):
        try:
            with open(USED_PATH, encoding='utf-8') as f:
                used = json.load(f).get('used', [])
        except Exception:
            used = []

    used_set = set(used)
    for t in topics:
        key = f"{t['domain']}::{t['concept']}"
        if key not in used_set:
            return t, key, used, topics

    # 全部用过：重置，从头再来
    return topics[0], f"{topics[0]['domain']}::{topics[0]['concept']}", [], topics


def _mark_used(key):
    used = []
    if os.path.exists(USED_PATH):
        try:
            with open(USED_PATH, encoding='utf-8') as f:
                used = json.load(f).get('used', [])
        except Exception:
            used = []
    if key not in used:
        used.append(key)
    with open(USED_PATH, 'w', encoding='utf-8') as f:
        json.dump({"used": used}, f, ensure_ascii=False, indent=2)


def _call_deepseek(system_msg, user_msg, timeout=180):
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY 未配置')
    resp = requests.post(
        API_URL,
        headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': API_MODEL,
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg},
            ],
            'temperature': 1.0,
            'max_tokens': 4000,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content'].strip()


SYSTEM_MSG = (
    "你是一位擅长把硬核专业概念讲透的写作者，风格极简硬核，拒绝意义空话。"
    "你要用原创寓言故事讲清一个专业概念，要求："
    "1. 故事全程不得在开头或中段点明概念名称，直到最后一小段才让读者自然意识到；"
    "2. 故事要具体、有角色、有情节冲突，不空泛说教；"
    "3. 故事之后，必须分两个模块："
    "   【模块一】用通俗直白的语言解释这个概念的定义、核心逻辑、实际应用场景；"
    "   【模块二】用 markdown 表格逐条拆解故事里的角色/情节/设定分别对应哪个知识点，讲透隐喻对应关系。"
    "输出用 markdown，不要有多余客套。"
)


def generate(date_str):
    _load_env()
    topic, key, _, _ = _pick_topic()
    domain = topic['domain']
    concept = topic['concept']

    user_msg = (
        f"请为「{domain}」领域的核心概念「{concept}」写一则研究生难度的寓言故事，"
        f"并按要求附带【模块一】概念解释和【模块二】隐喻拆解表。"
    )

    print(f"[寓言] 生成中: {domain} / {concept}")
    content = _call_deepseek(SYSTEM_MSG, user_msg)

    section = f"\n\n---\n\n## 🧩 今日寓言：{domain}·{concept}\n\n{content}\n"

    output_path = os.path.join(OUTPUT_DIR, f'{date_str}.md')
    if not os.path.exists(output_path):
        print(f'❌ 日报不存在，无法追加: {output_path}')
        return False

    with open(output_path, 'r', encoding='utf-8') as f:
        old = f.read()

    if '今日寓言' in old or '【寓言】' in old:
        print('[寓言] 已存在，跳过')
        return False

    with open(output_path, 'a', encoding='utf-8') as f:
        f.write(section)

    _mark_used(key)
    print(f'✅ [寓言] 已追加: {output_path} ({len(section)}字符)')
    return True


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(CST).strftime('%Y-%m-%d')
    try:
        generate(date_str)
    except Exception as e:
        print(f'❌ [寓言] 生成失败: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
