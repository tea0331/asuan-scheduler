#!/usr/bin/env python3
"""
马斯克推演引擎 v1
读日报 → 提取有操作空间的新闻 → 调 hy3-preview 推演 → 输出 musk-push.json + 追加到日报
"""
import json
import os
import re
import requests
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────
OPENCLAW_CONFIG = os.path.expanduser('~/.openclaw/openclaw.json')
API_URL = "https://api.lkeap.cloud.tencent.com/plan/v3/chat/completions"
MODEL = "hy3-preview"

OUTPUT_DIR = "/root/asuan-scheduler/output"
MUSK_DIR  = "/root/asuan-scheduler/data/musk"
METHODOLOGY_PATH = os.path.join(MUSK_DIR, "methodology-engine.json")
MOOD_PATH = os.path.join(MUSK_DIR, "social-mood-report.json")


# ── 工具函数 ──────────────────────────────────────────
def load_api_key():
    with open(OPENCLAW_CONFIG) as f:
        cfg = json.load(f)
    providers = cfg.get('models', {}).get('providers', {})
    if isinstance(providers, dict):
        pk = providers.get('tencenthytokenplan', {}).get('apiKey')
        if pk:
            return pk
    raise RuntimeError("找不到 tencenthytokenplan 的 apiKey")


def extract_news_from_daily_md(md_path):
    """从日报提取有操作空间的新闻（带因果链、含政策/供需/地缘关键词）"""
    with open(md_path, encoding='utf-8') as f:
        content = f.read()

    news_list = []
    # 提取「一、每日资讯」区块
    m = re.search(r'## 一、每日资讯(.*?)## 二、', content, re.DOTALL)
    if not m:
        return news_list

    block = m.group(1)
    # 每条新闻：- **标题** > 因果链
    pattern = re.compile(r'-\s+\*\*(.*?)\*\*.*?>\s*(.*?)(?=\n-\s+\*\*|\n\n|\n##)', re.DOTALL)
    for title, chain in pattern.findall(block):
        title = title.strip()
        chain = re.sub(r'\s+', ' ', chain).strip()
        if len(chain) < 50:
            continue
        # 过滤关键词
        kw = ['政策','补贴','监管','考核','指标','跨境','出口管制','关税',
               '算力','GPU','短缺','缺口','断供','渠道','审批','套利',
               '税收','优惠','牌照','支付','资金','洗钱','FDI','GDP',
               '情绪','焦虑','副业','搞钱','内卷','骗局','杀猪盘','灰色产业']
        if any(k in title+chain for k in kw):
            news_list.append({'title': title, 'chain': chain})
    return news_list[:3]


def build_prompt(news_item, methodology, mood_report):
    title = news_item['title']
    chain = news_item['chain']

    pattern_names = [p['pattern_name'] for p in methodology['gap_patterns']]
    roles = [n['role'] for n in methodology['need_personas']]
    mood_summary = json.dumps(mood_report['mood_distribution'], ensure_ascii=False)

    prompt = f"""你是「马斯克」——社会心态缺口推演引擎。

## 任务
对这条新闻做深度推演，必须回答两个核心问题：
① 这个信息暴露了什么系统性缺口？
② 谁有需求填这个缺口？

## 新闻
标题：{title}
因果链：{chain}

## 已知上下文
缺口模式库：{pattern_names}
需求方画像库：{roles}
B站社会心态（情绪分布）：{mood_summary}

## 推演要求（禁止模板化）
- 自由输出，不限字数、不限段落、不限结构
- 必须回答：①缺口是什么？②谁需要填？
- 参考方向（不强制）：缺口是暂时还是永久？填缺口要突破什么规则？谁已经在填了？上游/下游还有谁有需求？
- 邪修不是做传统业务——流水业务满足企业缺业绩，FDI指标满足政府缺指标，以此类推
- 不要写「【缺口分析】」「【推演】」固定标题，直接写

输出纯文本推演内容。
"""
    return prompt


def call_hy3(prompt, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']


def append_to_daily_md(md_path, pushes):
    """把推演结果追加到日报末尾（东方朔之前）"""
    with open(md_path, encoding='utf-8') as f:
        content = f.read()

    musk_block = "\n━━━━━━━━━━━━━━━━━━━━━\n【马斯克推演】\n━━━━━━━━━━━━━━━━━━━━━\n"
    for p in pushes:
        musk_block += f"\n▶ 新闻：{p['news_title']}\n"
        musk_block += f"推演：\n{p['musk_insight']}\n"
        musk_block += "━━━━━━━━━━━━━━━━━━━━━\n"

    marker = "【东方朔邪修评价】"
    if marker in content:
        parts = content.split(marker)
        new_content = parts[0] + musk_block + "\n\n" + marker + parts[1]
    else:
        new_content = content + "\n\n" + musk_block

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(new_content)


def main():
    api_key = load_api_key()

    # 今天日报路径
    today = datetime.now().strftime('%Y-%m-%d')
    md_path = os.path.join(OUTPUT_DIR, f"{today}.md")
    if not os.path.exists(md_path):
        files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith('.md')], reverse=True)
        if files:
            md_path = os.path.join(OUTPUT_DIR, files[0])
            today = files[0].replace('.md', '')
        else:
            print("[马斯克] 无日报文件，退出")
            return

    print(f"[马斯克推演] 读取日报: {md_path}")
    news_items = extract_news_from_daily_md(md_path)
    print(f"[马斯克推演] 提取到 {len(news_items)} 条可推演新闻")
    for i, n in enumerate(news_items, 1):
        print(f"  {i}. {n['title'][:60]}...")

    if not news_items:
        print("[马斯克推演] 无符合条件的新闻，退出")
        return

    with open(METHODOLOGY_PATH) as f:
        methodology = json.load(f)
    with open(MOOD_PATH) as f:
        mood_report = json.load(f)

    pushes = []
    for item in news_items:
        print(f"\n[推演中] {item['title'][:50]}...")
        prompt = build_prompt(item, methodology, mood_report)
        try:
            result = call_hy3(prompt, api_key)
            pushes.append({
                'news_title': item['title'],
                'gap_analysis': result,
                'musk_insight': result
            })
            print(f"  ✓ 推演完成（{len(result)}字）")
        except Exception as e:
            print(f"  ✗ 推演失败: {e}")
            pushes.append({
                'news_title': item['title'],
                'gap_analysis': f'推演失败: {e}',
                'musk_insight': ''
            })

    # 写 musk-push.json
    push_data = {'date': today, 'pushes': pushes}
    push_path = os.path.join(MUSK_DIR, f"musk-push-{today}.json")
    with open(push_path, 'w', encoding='utf-8') as f:
        json.dump(push_data, f, ensure_ascii=False, indent=2)
    print(f"\n[马斯克推演] 输出: {push_path}")

    # 追加到日报
    append_to_daily_md(md_path, pushes)
    print(f"[马斯克推演] 已追加到日报: {md_path}")


if __name__ == '__main__':
    main()
