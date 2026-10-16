#!/usr/bin/env python3
"""
每日寓言生成模块（独立脚本，可单独跑，也可挂主流程）

功能：
1. 从 data/parable_topics.json 主题池里按序取一个概念（记录已用，避免重复）
2. 调用 DeepSeek V4 Flash 生成"寓言故事 + 概念解释 + 隐喻对应表"
3. 追加到日报 output/YYYY-MM-DD.md 末尾

用法：
    python3 add_parable.py [YYYY-MM-DD]

风格约束（对齐刘老板偏好）：
- 全程不点破概念名，直到最后一小段
- 结构化输出：寓言 + ①概念解释 ②逐条隐喻拆解
- 极简硬核，拒绝意义空话

v26.2 修复（2026-10-17）：
- API_MODEL 改为与主流程一致的 deepseek-v4-flash（原 deepseek-chat 存在模型名不一致的静默失败风险）
- 显式关闭 reasoning（对齐 b478d81 的根治方案，避免推理爆表导致 content 为空）
- temperature 1.0 → 0.8（写作任务降随机性，稳定质量）
- content 为空时带强约束自动重试一次（复用主流程同款策略）
- 修正主流程误导日志：返回码为 0 不等于真写入（可能是"已存在跳过"）
- 主题池用完的重置逻辑：保留最近 RESET_KEEP 条，避免刚讲完又重讲
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
# 与 generate_full_daily.py 主流程保持一致，避免模型名漂移导致静默失败。
# 可用环境变量 DEEPSEEK_MODEL 覆盖，默认 deepseek-v4-flash。
API_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-v4-flash')
API_TEMPERATURE = 0.8

# 主题池全轮完后，保留最近 N 条已用记录，避免"刚讲完的概念又第一个冒出来"
RESET_KEEP = 12


def _load_env():
    env_path = os.path.join(MODULE_DIR, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _read_used():
    if os.path.exists(USED_PATH):
        try:
            with open(USED_PATH, encoding='utf-8') as f:
                return json.load(f).get('used', [])
        except Exception:
            return []
    return []


def _pick_topic():
    """按序取一个未用过的主题；全用完则重置（保留最近 RESET_KEEP 条，避免立刻重复）"""
    with open(TOPICS_PATH, encoding='utf-8') as f:
        topics = json.load(f)['topics']

    used = _read_used()
    used_set = set(used)

    for t in topics:
        key = f"{t['domain']}::{t['concept']}"
        if key not in used_set:
            return t, key, used, topics

    # 全部用过：重置，但保留最近 RESET_KEEP 条，让新一轮不会从 topics[0] 立刻重讲
    kept = used[-RESET_KEEP:] if len(used) > RESET_KEEP else []
    return topics[0], f"{topics[0]['domain']}::{topics[0]['concept']}", kept, topics


def _mark_used(key, base_used=None):
    used = list(base_used) if base_used is not None else _read_used()
    if key not in used:
        used.append(key)
    with open(USED_PATH, 'w', encoding='utf-8') as f:
        json.dump({"used": used}, f, ensure_ascii=False, indent=2)


def _call_deepseek(system_msg, user_msg, timeout=180):
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY 未配置')

    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': API_MODEL,
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': user_msg},
        ],
        'temperature': API_TEMPERATURE,
        'max_tokens': 4000,
        # 关闭思考模式：DeepSeek V4 Flash 默认开启思考，不传参即会推理并吃满预算，
        # 导致 finish_reason=length、content 为空。正确参数是 thinking.type=disabled，
        # 而 reasoning.enabled=False 是 OpenAI 系写法，DeepSeek 通道不识别（实测无效）。
        'thinking': {'type': 'disabled'},
    }

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    content = (resp.json()['choices'][0]['message'].get('content') or '').strip()

    # content 为空（推理爆表/被截断）时，带强约束重试一次拿正文
    if not content:
        sys2 = system_msg + (
            "\n\n⚠️ 直接输出最终正文。严禁输出任何思路/推理/规划/草稿/元注释，"
            "不要以'好的''我来''用户给了'开头，直接从故事第一句开始写成品。"
        )
        retry_payload = dict(payload)
        retry_payload['messages'] = [
            {'role': 'system', 'content': sys2},
            {'role': 'user', 'content': user_msg},
        ]
        retry_payload['max_tokens'] = 3500
        r2 = requests.post(API_URL, headers=headers, json=retry_payload, timeout=timeout)
        if r2.status_code == 200:
            content = (r2.json()['choices'][0]['message'].get('content') or '').strip()

    if not content:
        raise RuntimeError('模型返回 content 为空（重试后仍为空）')

    return content


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
    topic, key, base_used, _ = _pick_topic()
    domain = topic['domain']
    concept = topic['concept']

    user_msg = (
        f"请为「{domain}」领域的核心概念「{concept}」写一则研究生难度的寓言故事，"
        f"并按要求附带【模块一】概念解释和【模块二】隐喻拆解表。"
    )

    output_path = os.path.join(OUTPUT_DIR, f'{date_str}.md')
    if not os.path.exists(output_path):
        print(f'❌ 日报不存在，无法追加: {output_path}')
        return False

    with open(output_path, 'r', encoding='utf-8') as f:
        old = f.read()

    if '今日寓言' in old or '【寓言】' in old:
        print('[寓言] 已存在，跳过')
        return False

    print(f"[寓言] 生成中: {domain} / {concept} (model={API_MODEL})")
    content = _call_deepseek(SYSTEM_MSG, user_msg)

    section = f"\n\n---\n\n## 🧩 今日寓言：{domain}·{concept}\n\n{content}\n"

    with open(output_path, 'a', encoding='utf-8') as f:
        f.write(section)

    _mark_used(key, base_used)
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
