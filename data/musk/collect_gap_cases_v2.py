#!/usr/bin/env python3
"""
补全50个缺口案例，追加到已有 gap-cases.json
每个领域新增4个，共40个
模型: hy3-preview（腾讯混元 Hy Token Plan）
"""
import os
import json
import time
import requests
import logging
import sys

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s', stream=sys.stdout)

# 从 scheduler.py 里提取的 key
API_KEY = "***"
BASE_URL = "https://api.lkeap.cloud.tencent.com/plan/v3"
MODEL = "hy3-preview"

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "gap-cases.json")

DOMAINS = [
    ("指标套利", "FDI指标、GDP指标被地方政府通过结构设计满足"),
    ("流水业务", "企业走流水满足银行考核"),
    ("税筹结构", "霍尔果斯、灵活用工平台的税收筹划"),
    ("牌照套利", "支付牌照、基金销售牌照的出租出借"),
    ("数据套利", "爬虫数据转合规数据中台的演化"),
    ("流量套利", "私域裂变绕过平台规则"),
    ("灰产洗白", "话费充值洗钱链路"),
    ("情绪套利", "焦虑付费、知识付费的恐惧营销"),
    ("补贴套利", "消费券套现、新能源补贴"),
    ("监管套利", "同一业务在不同管辖区的合规差异"),
]

SYSTEM_PROMPT = """你是中国商业缺口研究分析师，熟悉体制/市场/人性/规则四类缺口。
任务：根据领域生成不重复的缺口案例。
要求：
1. 基于真实商业现象或已公开案例
2. 操作手法、参与角色、红线边界具体
3. 不编造数据，不确定用"约/据公开报道"标注
4. 来源具体（裁判文书网案号/财新/第一财经日期）
5. 与已有案例不重复，手法/行业/缺口子类型有差异
只输出JSON，不要其他文字。"""

def call_hy3(prompt):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 800
    }
    resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]

def extract_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    return json.loads(raw)

def collect_one(domain, desc, existing_titles, existing_summaries):
    titles_str = "\n".join(f"- {t}" for t in existing_titles) or "（无）"
    summaries_str = "\n".join(f"- {s}" for s in existing_summaries) or "（无）"
    
    prompt = f"""领域：{domain}
背景：{desc}

已有案例标题（必须避开，不能重复）：
{titles_str}

已有案例操作手法（不能雷同）：
{summaries_str}

请生成1个该领域新的、不重复的缺口案例，要求：
- 操作手法、行业、缺口子类型与已有案例有明确差异
- who_has_need 具体到角色和KPI（数字）
- 按以下 JSON 格式输出：

{{
 "title": "案例名（简洁，不超过30字）",
 "domain": "{domain}",
 "gap_type": "体制缺口/市场缺口/人性缺口/规则缺口（选最贴切的一个）",
 "gap_description": "缺口是什么，为什么会存在",
 "who_has_need": "谁有需求填这个缺口，具体到角色和KPI",
 "operation_method": "怎么操作的，在什么红线边缘",
 "red_line_edge": "红线具体在哪",
 "why_sustainable": "为什么缺口不会被填上",
 "source": "来源URL或出处（尽量具体）"
}}

只输出JSON，不要其他文字。"""
    
    try:
        raw = call_hy3(prompt)
        obj = extract_json(raw)
        for k in ["title", "domain", "gap_type", "gap_description", "who_has_need", "operation_method", "red_line_edge", "why_sustainable", "source"]:
            if k not in obj:
                raise ValueError(f"缺少字段: {k}")
        logging.info(f"  [OK] {obj['title']}")
        return obj
    except Exception as e:
        logging.error(f"  [FAIL] {e}")
        return None

def main():
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        existing = json.load(f)
    
    existing_titles = set(c["title"] for c in existing)
    logging.info(f"已有 {len(existing)} 个案例，开始补全到50个...")
    
    new_cases = []
    for domain, desc in DOMAINS:
        domain_existing = [c for c in existing if c["domain"] == domain]
        domain_titles = [c["title"] for c in domain_existing]
        domain_summaries = [f"{c['title']}：{c['operation_method'][:60]}" for c in domain_existing]
        needed = 5 - len(domain_existing)
        
        if needed <= 0:
            logging.info(f"[跳过] {domain} 已有 {len(domain_existing)} 个")
            continue
        
        logging.info(f"[{domain}] 已有 {len(domain_existing)} 个，需新增 {needed} 个")
        
        for i in range(needed):
            logging.info(f"  [{i+1}/{needed}] 采集中...")
            case = collect_one(domain, desc, domain_titles + [c["title"] for c in new_cases], domain_summaries)
            if case and case["title"] not in existing_titles:
                new_cases.append(case)
                existing_titles.add(case["title"])
                domain_titles.append(case["title"])
                time.sleep(2)
            else:
                logging.warning(f"  [重复/失败] 重试...")
                time.sleep(3)
    
    all_cases = existing + new_cases
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=2)
    
    logging.info(f"完成！新增 {len(new_cases)} 个，共 {len(all_cases)} 个案例")

if __name__ == "__main__":
    main()
