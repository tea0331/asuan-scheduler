#!/usr/bin/env python3
"""
马斯克推演引擎 v2.1
功能：
1. 读取日报 output/{date}.md
2. 调用 hy3-preview 生成推演
3. 法律合规评估（查 legal.db）
4. 自评估推演质量
5. 输出 musk-push.json
6. 追加到日报末尾（东方朔之前）
"""

import json
import os
import sys
import re
import sqlite3
import requests
from datetime import datetime, timezone, timedelta

# 加载 .env
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

CST = timezone(timedelta(hours=8))
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(MODULE_DIR, 'data', 'musk')
OUTPUT_DIR = os.path.join(MODULE_DIR, 'output')
GAP_CASES_PATH = os.path.join(DATA_DIR, 'gap-cases.json')
MUSK_PUSH_PATH = os.path.join(DATA_DIR, 'musk-push.json')
LEGAL_DB_PATH = os.path.join(MODULE_DIR, 'legal-knowledge', 'legal.db')

# API 配置（和 generate_full_daily.py 一致）
API_URL = "https://api.lkeap.cloud.tencent.com/plan/v3/chat/completions"
API_KEY = os.getenv('HUNYUAN_API_KEY', '')
MODEL = "hy3-preview"


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def call_hy3(system_msg, user_msg, max_tokens=2000, temperature=0.3):
    """调用混元 API — 和 generate_full_daily.py 同一套配置"""
    if not API_KEY:
        print("❌ HUNYUAN_API_KEY 未设置")
        return None
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=90)
        if resp.status_code == 200:
            result = resp.json()
            return result['choices'][0]['message']['content'].strip()
        else:
            print(f"❌ API返回 {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"❌ API调用失败: {e}")
        return None


def extract_news_from_report(md_text):
    """从日报中提取有操作空间的新闻标题"""
    # 提取加粗标题
    titles = re.findall(r'\*\*(.+?)\*\*', md_text)
    # 过滤掉板块标题和无关内容
    skip = {'每日资讯', '逆潮观察', '深度传导分析', '今日邪修金句', '资源短缺预警',
            '避坑提醒', '因果链', '三角机会', '彩票号码推荐', '台湾彩种推荐',
            '东方朔邪修评价', '马斯克推演', '刘海蟾点金'}
    news = [t for t in titles if t not in skip and len(t) > 5 and not t.startswith('##')]
    return news[:10]  # 最多10条


def run_inference(daily_content, gap_cases):
    """执行推演"""
    # 从案例库提取关键模式作为上下文
    case_summary = ""
    if gap_cases:
        sample_cases = gap_cases[:10]
        case_summary = "\n".join([
            f"- {c.get('title', '')}: {c.get('gap_description', '')[:60]}"
            for c in sample_cases
        ])

    system_msg = """你是马斯克系统，专门分析市场缺口和套利空间。

核心原则：
- 邪修不是做传统业务——流水业务满足企业缺业绩，FDI指标满足政府缺指标
- 找系统性缺口（体制的/市场的/人性的/规则的）
- 找谁有需求填这个缺口（具体到角色和KPI）
- 在规则边缘找操作路径
- 禁止模板化输出，每次推演都要独特

必须回答两个问题：
1. 这个信息暴露了什么系统性缺口？
2. 谁有需求填这个缺口？

如果新闻涉及资源短缺，推演必须包含"短缺传导路径"。
如果操作路径有坑，必须给出"具体止损方式"。"""

    user_msg = f"""基于以下阿算日报内容，识别3个最有操作空间的缺口模式，生成推演分析。

日报内容（节选）：
{daily_content[:3000]}

参考案例库：
{case_summary}

要求：
1. 识别3个最有操作空间的缺口模式
2. 每个模式包含：
   - 缺口描述（具体因果链）
   - 需求方（具体角色+KPI）
   - 操作路径（具体步骤，用→连接）
   - 红线位置（具体法律边界）
   - 可持续原因（为什么这个缺口长期存在）
3. 输出格式：Markdown，结构化
4. 总字数：800-1500字"""

    return call_hy3(system_msg, user_msg, max_tokens=2500, temperature=0.4)


def ask_hy3_for_law(inference_text):
    """让 hy3 判断推演触及哪条法律"""
    system_msg = "你是法律分析助手。根据推演内容判断最可能触及的中国法律条文。"
    user_msg = f"""基于以下推演内容，判断最可能触及的中国法律条文：

推演内容：
{inference_text[:1500]}

要求：
1. 找出2-3条最相关的法律条文
2. 风险等级：🟢合规/🟡擦边/🔴越线
3. 格式（JSON数组）：
[
  {{
    "law_name": "法律名称",
    "article_number": "条文编号（如：第31条）",
    "risk": "🟢合规/🟡擦边/🔴越线",
    "reason": "为什么触及这条法律（20字内）",
    "compliance_path": "合规变通方案（具体操作，不要写"建议咨询律师"）"
  }}
]

只返回JSON数组，不要其他文字。"""

    result = call_hy3(system_msg, user_msg, max_tokens=500, temperature=0.2)
    if not result:
        return []

    # 提取JSON
    json_start = result.find('[')
    json_end = result.rfind(']') + 1
    if json_start >= 0 and json_end > json_start:
        try:
            return json.loads(result[json_start:json_end])
        except:
            return []
    return []


def query_laws_db(law_refs):
    """根据 hy3 返回的法律引用，查 legal.db 匹配条文"""
    if not os.path.exists(LEGAL_DB_PATH):
        return []
    conn = sqlite3.connect(LEGAL_DB_PATH)
    cursor = conn.cursor()
    matched = []
    for ref in law_refs:
        law_name = ref.get('law_name', '')
        article = ref.get('article_number', '')
        # 精确匹配
        cursor.execute("""
            SELECT d.name, l.law_name, l.article_number, l.content
            FROM domains d JOIN laws l ON d.id = l.domain_id
            WHERE l.law_name LIKE ? AND l.article_number LIKE ?
            LIMIT 1
        """, (f'%{law_name[:6]}%', f'%{article}%' if article else '%'))
        row = cursor.fetchone()
        if row:
            matched.append({
                'domain': row[0], 'law_name': row[1],
                'article_number': row[2], 'content': row[3],
                'risk': ref.get('risk', '🟢合规'),
                'reason': ref.get('reason', ''),
                'compliance_path': ref.get('compliance_path', '')
            })
    conn.close()
    return matched


def self_evaluate(inference_text, gap_cases):
    """自评估推���质量（5维度）"""
    scores = {}
    suggestions = {}

    # 1. 缺口深度
    text_len = len(inference_text)
    if text_len >= 800:
        scores['gap_depth'] = 20
        suggestions['gap_depth'] = '✓ 深度足够'
    elif text_len >= 500:
        scores['gap_depth'] = 15
        suggestions['gap_depth'] = '△ 深度一般'
    else:
        scores['gap_depth'] = 10
        suggestions['gap_depth'] = '✗ 深度不足（<500字）'

    # 2. 需求方明确度
    if 'KPI' in inference_text or '考核' in inference_text:
        scores['demand_clarity'] = 20
        suggestions['demand_clarity'] = '✓ 需求方明确'
    elif any(kw in inference_text for kw in ['需求方', '谁有需求', '谁需要']):
        scores['demand_clarity'] = 15
        suggestions['demand_clarity'] = '△ 部分明确'
    else:
        scores['demand_clarity'] = 10
        suggestions['demand_clarity'] = '✗ 不明确'

    # 3. 新颖性
    new_keywords = ['公司化', '链上', '分布式', '跨境监管', '虚拟货币', 'AI', '算力', '碳积分']
    found = sum(1 for kw in new_keywords if kw in inference_text)
    scores['novelty'] = min(20, 10 + found * 3)
    suggestions['novelty'] = f'✓ 含{found}个新关键词' if found >= 2 else '△ 新颖性不足'

    # 4. 操作路径具体度
    arrow_count = inference_text.count('→')
    if arrow_count >= 3:
        scores['operation'] = 20
        suggestions['operation'] = '✓ 路径具体'
    elif arrow_count >= 1:
        scores['operation'] = 15
        suggestions['operation'] = '△ 路径一般'
    else:
        scores['operation'] = 10
        suggestions['operation'] = '✗ 路径不具体'

    # 5. 案例匹配度
    case_titles = [c.get('title', '') for c in gap_cases] if gap_cases else []
    matched = [t for t in case_titles if t and t in inference_text]
    scores['case_match'] = min(20, 10 + len(matched) * 5)
    suggestions['case_match'] = f'✓ 引用{len(matched)}个案例' if matched else '✗ 未引用案例'

    total = sum(scores.values())
    grade = 'A' if total >= 90 else 'B' if total >= 75 else 'C' if total >= 60 else 'D'
    return {'scores': scores, 'suggestions': suggestions, 'total_score': total, 'grade': grade}


def format_for_report(inference_text, matched_laws, evaluation):
    """格式化追加到日报的内容"""
    lines = ['\n\n---\n\n━━━━━━━━━━━━━━━━━━━━\n【马斯克推演】\n━━━━━━━━━━━━━━━━━━━━\n']
    lines.append(inference_text)
    lines.append('')

    if matched_laws:
        lines.append('⚖️ 合规评估：')
        for law in matched_laws:
            lines.append(f"- 涉及法律：{law['law_name']} {law['article_number']}")
            lines.append(f"  风险等级：{law['risk']}")
            lines.append(f"  触及原因：{law.get('reason', '')}")
            if law.get('compliance_path'):
                lines.append(f"  合规变通：{law['compliance_path']}")
            lines.append('')
    else:
        lines.append('⚖️ 合规评估：本次推演未检索到相关法律条文\n')

    lines.append(f'📊 推演自评估：{evaluation["total_score"]}/100（{evaluation["grade"]}级）')
    lines.append('━━━━━━━━━━━━━━━━━━━━\n')
    return '\n'.join(lines)


def main(date=None):
    if date is None:
        date = datetime.now(CST).strftime('%Y-%m-%d')

    print(f"=== 马斯克推演引擎 - {date} ===")

    # 1. 加载数据
    gap_cases = load_json(GAP_CASES_PATH) or []
    print(f"  案例库: {len(gap_cases)} 个案例")

    # 2. 读取日报
    report_path = os.path.join(OUTPUT_DIR, f'{date}.md')
    if not os.path.exists(report_path):
        print(f"❌ 日报不存在: {report_path}")
        return
    with open(report_path, 'r', encoding='utf-8') as f:
        daily_content = f.read()
    print(f"  日报长度: {len(daily_content)} 字符")

    # 3. 推演
    print("  调用 hy3-preview 推演...")
    inference_text = run_inference(daily_content, gap_cases)
    if not inference_text:
        inference_text = "（推演失败，API调用异常）"
    print(f"  推演完成: {len(inference_text)} 字符")

    # 4. 法律合规评估
    print("  法律合规评估...")
    law_refs = ask_hy3_for_law(inference_text)
    matched_laws = query_laws_db(law_refs)
    print(f"  匹配法律: {len(matched_laws)} 条")

    # 5. 自评估
    evaluation = self_evaluate(inference_text, gap_cases)
    print(f"  自评估: {evaluation['total_score']}/100（{evaluation['grade']}）")

    # 6. 输出 musk-push.json
    musk_push = {
        'date': date,
        'generated_at': datetime.now(CST).isoformat(),
        'inference_text': inference_text,
        'matched_laws': matched_laws,
        'self_evaluation': evaluation
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MUSK_PUSH_PATH, 'w', encoding='utf-8') as f:
        json.dump(musk_push, f, ensure_ascii=False, indent=2)
    print(f"  ✓ musk-push.json 已保存")

    # 7. 追加到日报
    formatted = format_for_report(inference_text, matched_laws, evaluation)
    with open(report_path, 'a', encoding='utf-8') as f:
        f.write(formatted)
    print(f"  ✓ 已追加到日报: {report_path}")

    # 8. 打印摘要
    print(f"\n=== 推演摘要 ===")
    print(inference_text[:500])
    if matched_laws:
        print(f"\n⚖️ 法律评估:")
        for law in matched_laws:
            print(f"  - {law['law_name']} {law['article_number']} [{law['risk']}]")


if __name__ == '__main__':
    date = sys.argv[1] if len(sys.argv) > 1 else None
    main(date)
