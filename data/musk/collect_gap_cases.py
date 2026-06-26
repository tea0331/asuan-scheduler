#!/usr/bin/env python3
"""
采集10个缺口案例，写入 gap-cases.json
模型: hy3-preview (Hy Token Plan)
"""
import os
import json
import time
import requests
import logging

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

API_KEY = "sk-tp-FQyZqE8FIA5MLqn7JRNDPrmvU1AMvEICqL38CWF7XflfbA7D"
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

SYSTEM_PROMPT = """你是一个中国商业缺口研究分析师，熟悉体制、市场、人性、规则四类缺口。
你的任务是根据指定领域，生成1个真实、具体、有据可查的缺口案例。
案例必须：
1. 基于真实存在的商业现象或已公开案例
2. 具体到操作手法、参与角色、红线边界
3. 不编造数据，不确定的用"约/据公开报道"标注
4. 来源尽量具体（裁判文书网案号、财新/第一财经日期、知乎链接等）

输出严格按 JSON 格式，不要加任何解释文字。"""

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
        "temperature": 0.7,
        "max_tokens": 800
    }
    resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def collect_one(domain, desc):
    prompt = f"""领域：{domain}
背景：{desc}

请生成1个该领域的缺口案例，按以下 JSON 格式输出：
{{
 "title": "案例名",
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
        # 提取 JSON
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        obj = json.loads(raw)
        logging.info(f"[OK] {domain}: {obj.get('title', '?')}")
        return obj
    except Exception as e:
        logging.error(f"[FAIL] {domain}: {e}")
        return None

def main():
    results = []
    for i, (domain, desc) in enumerate(DOMAINS, 1):
        logging.info(f"[{i}/10] 采集: {domain}")
        case = collect_one(domain, desc)
        if case:
            results.append(case)
        time.sleep(2)  # 避免速率限制
    
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logging.info(f"完成！共采集 {len(results)} 个案例，存入 {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
