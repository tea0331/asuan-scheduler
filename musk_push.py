#!/usr/bin/env python3
"""
马斯克 v2 升级 - 第四步：马斯克自进化引擎（真实推演版）
功能：
1. 读取日报 output/{date}.md
2. 调用 hy3-review 生成真实推演
3. 自评估推演质量（5个维度）
4. 根据评估结果自动调整下次推演策略
5. 输出 musk-push.json（含推演+自评估）
"""

import json
import os
import re
import sys
import requests
from datetime import datetime
from collections import Counter

# 配置
DATA_DIR = 'data/musk'
GAP_CASES_PATH = os.path.join(DATA_DIR, 'gap-cases.json')
PATTERN_REPORT_PATH = os.path.join(DATA_DIR, 'pattern-discovery-report.json')
OUTPUT_DIR = 'output'
MUSK_PUSH_PATH = os.path.join(DATA_DIR, 'musk-push.json')

# hy3-review 配置
HY3_API_URL = os.getenv("HUNYUAN_BASE_URL", os.getenv("HUNYUAN_BASE_URL", ""))
HY3_API_KEY = "sk-tp-FQyZqE8FIA5MLqn7JRNDPrmvU1AMvEICqL38CWF7XflfbA7D"
HY3_MODEL = "hy3-preview"

# 10大领域
DOMAINS = [
    '指标套利', '流水业务', '税筹结构', '牌照套利', '数据套利',
    '流量套利', '灰产洗白', '情绪套利', '补贴套利', '监管套利'
]

def load_json(path):
    """加载JSON文件"""
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_daily_report(date):
    """读取日报文件"""
    path = os.path.join(OUTPUT_DIR, f'{date}.md')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def call_hy3_review(prompt):
    """调用 hy3-review 模型"""
    headers = {
        "Authorization": f"Bearer {HY3_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": HY3_MODEL,
        "messages": [
            {"role": "system", "content": "你是马斯克系统，专门分析套利缺口模式。基于日报内容，识别有操作空间的新闻，生成结构化推演分析。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2000
    }
    
    try:
        response = requests.post(HY3_API_URL, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"❌ API调用失败: {e}")
        return None

def real_inference(daily_content):
    """真实推演：调用 hy3-review 分析日报"""
    if not daily_content:
        return {
            'inference_text': '日报不存在，无法推演',
            'domain': '未知',
            'gap_type': '未知',
            'method': '',
            'red_line': '',
            'sustainability': '',
            'who_needs': ''
        }
    
    # 构建prompt（限制日报长度）
    prompt = f"""请基于以下阿算日报内容，识别有操作空间的缺口模式，生成推演分析。

日报内容（节选）：
{daily_content[:3000]}

要求：
1. 识别3个最有操作空间的缺口模式
2. 每个模式包含：
   - 缺口描述（具体因果链）
   - 需求方（具体角色+KPI）
   - 操作路径（具体步骤，用→连接）
   - 红线位置（具体法律边界）
   - 可持续原因（为什么这个缺口长期存在）
3. 输出格式：Markdown，结构化
4. 总字数：800-1200字

附加要求：
- 如果新闻涉及资源短缺，推演必须包含"短缺传导路径"（从短缺端到过剩端的完整链条）
- 如果操作路径有坑，合规评估必须包含"具体止损方式"（不是"建议咨询专业律师"这种空话）

输出："""
    
    print(f"   - 正在调用 {HY3_MODEL}...")
    inference_text = call_hy3_review(prompt)
    
    if not inference_text:
        return {
            'inference_text': 'API调用失败',
            'domain': '未知',
            'gap_type': '未知',
            'method': '',
            'red_line': '',
            'sustainability': '',
            'who_needs': ''
        }
    
    # 简单解析领域
    domain = []
    if '监管' in inference_text or '合规' in inference_text:
        domain.append('监管套利')
    if '数据' in inference_text or '爬虫' in inference_text:
        domain.append('数据套利')
    if '洗钱' in inference_text or '帮信' in inference_text:
        domain.append('灰产洗白')
    if '税筹' in inference_text or '发票' in inference_text:
        domain.append('税筹结构')
    if '牌照' in inference_text or '无证' in inference_text:
        domain.append('牌照套利')
    if '补贴' in inference_text or '骗补' in inference_text:
        domain.append('补贴套利')
    if '情绪' in inference_text or '焦虑' in inference_text:
        domain.append('情绪套利')
    if '流量' in inference_text or '刷单' in inference_text:
        domain.append('流量套利')
    if '流水' in inference_text or 'GMV' in inference_text:
        domain.append('流水业务')
    if '指标' in inference_text or 'KPI' in inference_text:
        domain.append('指标套利')
    
    return {
        'inference_text': inference_text,
        'domain': ', '.join(domain) if domain else '未知',
        'gap_type': '规则缺口',
        'method': '待解析',
        'red_line': '待解析',
        'sustainability': '待解析',
        'who_needs': '待解析'
    }

def self_evaluate_inference(inference_result, gap_cases):
    """自评估推演质量（5个维度）"""
    text = inference_result['inference_text']
    method = inference_result['method']
    red_line = inference_result['red_line']
    who_needs = inference_result['who_needs']
    
    scores = {}
    suggestions = {}
    
    # 1. 缺口深度（0-20分）：推演文本长度
    text_len = len(text)
    if text_len >= 800:
        scores['gap_depth'] = 20
        suggestions['gap_depth'] = '✓ 缺口深度足够'
    elif text_len >= 500:
        scores['gap_depth'] = 15
        suggestions['gap_depth'] = '△ 缺口深度一般，建议展开多层分析'
    else:
        scores['gap_depth'] = 10
        suggestions['gap_depth'] = '✗ 缺口深度不足，需深化（<500字）'
    
    # 2. 需求方明确度（0-20分）
    if 'KPI' in text and ('操盘手' in text or '负责人' in text or '公司' in text):
        scores['demand_clarity'] = 20
        suggestions['demand_clarity'] = '✓ 需求方明确（含角色+KPI）'
    elif 'KPI' in text or '需求方' in text:
        scores['demand_clarity'] = 15
        suggestions['demand_clarity'] = '△ 需求方部分明确，建议补充具体角色'
    else:
        scores['demand_clarity'] = 10
        suggestions['demand_clarity'] = '✗ 需求方不明确，需注入需求方画像'
    
    # 3. 新颖性（0-20分）：检查是否有新关键词
    new_keywords = ['公司化运作', '链上交易', '分布式爬虫', '跨境监管', '虚拟货币']
    found_new = sum(1 for kw in new_keywords if kw in text)
    if found_new >= 3:
        scores['novelty'] = 20
        suggestions['novelty'] = '✓ 新颖性高（含多个新关键词）'
    elif found_new >= 1:
        scores['novelty'] = 15
        suggestions['novelty'] = '△ 新颖性一般，建议切换分析角度'
    else:
        scores['novelty'] = 10
        suggestions['novelty'] = '✗ 新颖性不足，需强制切换分析角度'
    
    # 4. 操作路径具体度（0-20分）
    if '→' in text and text.count('→') >= 3:
        scores['operation_concreteness'] = 20
        suggestions['operation_concreteness'] = '✓ 操作路径具体（含多步骤）'
    elif '→' in text or '步骤' in text:
        scores['operation_concreteness'] = 15
        suggestions['operation_concreteness'] = '△ 操作路径一般，建议追加具体步骤'
    else:
        scores['operation_concreteness'] = 10
        suggestions['operation_concreteness'] = '✗ 操作路径不具体，需追加"红线边缘可做什么"'
    
    # 5. 案例匹配度（0-20分）
    case_titles = [c['title'] for c in gap_cases] if gap_cases else []
    matched_cases = [t for t in case_titles if t in text]
    if len(matched_cases) >= 2:
        scores['case_match'] = 20
        suggestions['case_match'] = f'✓ 案例匹配度高（引用{len(matched_cases)}个案例）'
    elif len(matched_cases) >= 1:
        scores['case_match'] = 15
        suggestions['case_match'] = '△ 案例匹配度一般，建议匹配更多相关案例'
    else:
        scores['case_match'] = 10
        suggestions['case_match'] = '✗ 未引用任何案例，需从案例库自动匹配2个'
    
    total_score = sum(scores.values())
    
    return {
        'scores': scores,
        'suggestions': suggestions,
        'total_score': total_score,
        'grade': 'A' if total_score >= 90 else 'B' if total_score >= 75 else 'C' if total_score >= 60 else 'D',
        'matched_cases': matched_cases
    }

def generate_evolution_strategy(evaluation):
    """根据评估结果生成进化策略"""
    strategy = {
        'next_analysis_angle': 'gap',
        'prompt_injections': [],
        'case_match_required': False
    }
    
    if evaluation['scores']['novelty'] < 15:
        angles = ['gap', 'compliance', 'demand']
        current = strategy['next_analysis_angle']
        strategy['next_analysis_angle'] = angles[(angles.index(current) + 1) % 3]
        strategy['prompt_injections'].append(f"切换分析角度至：{strategy['next_analysis_angle']}端")
    
    if evaluation['scores']['demand_clarity'] < 15:
        strategy['prompt_injections'].append("注入需求方画像：具体角色+KPI+操作动机")
    
    if evaluation['scores']['operation_concreteness'] < 15:
        strategy['prompt_injections'].append("追加思考要求：在红线边缘可做什么？具体步骤？")
    
    if evaluation['scores']['case_match'] < 15:
        strategy['case_match_required'] = True
        strategy['prompt_injections'].append("强制匹配2个相关案例到推演上下文")
    
    return strategy

def main(date=None):
    """主函数"""
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"=== 马斯克自进化引擎（真实推演版）- {date} ===\n")
    
    # 1. 加载数据
    print("1. 加载数据...")
    gap_cases = load_json(GAP_CASES_PATH)
    pattern_report = load_json(PATTERN_REPORT_PATH)
    
    if not gap_cases:
        print(f"❌ 错误：无法加载 {GAP_CASES_PATH}")
        return
    
    print(f"   - 已加载 {len(gap_cases)} 个案例")
    
    # 2. 读取日报
    print(f"\n2. 读取日报 {date}.md...")
    daily_content = load_daily_report(date)
    if daily_content:
        print(f"   - 日报长度: {len(daily_content)} 字符")
    else:
        print(f"   - 日报不存在，退出")
        return
    
    # 3. 执行真实推演
    print(f"\n3. 执行真实推演（调用 {HY3_MODEL}）...")
    inference_result = real_inference(daily_content)
    
    print(f"   - 推演文本长度: {len(inference_result['inference_text'])} 字符")
    print(f"   - 识别领域: {inference_result['domain']}")
    
    # 4. 自评估推演质量
    print(f"\n4. 自评估推演质量...")
    evaluation = self_evaluate_inference(inference_result, gap_cases)
    
    print(f"   - 总评分: {evaluation['total_score']}/100 (等级: {evaluation['grade']})")
    for dim, score in evaluation['scores'].items():
        print(f"     · {dim}: {score}/20 - {evaluation['suggestions'][dim]}")
    
    # 5. 生成进化策略
    print(f"\n5. 生成进化策略...")
    strategy = generate_evolution_strategy(evaluation)
    
    print(f"   - 下次分析角度: {strategy['next_analysis_angle']}端")
    if strategy['prompt_injections']:
        print(f"   - Prompt注入:")
        for inj in strategy['prompt_injections']:
            print(f"     · {inj}")
    if strategy['case_match_required']:
        print(f"   - 强制案例匹配: 是")
    
    # 6. 输出 musk-push.json
    print(f"\n6. 输出 musk-push.json...")
    
    musk_push = {
        'date': date,
        'generated_at': datetime.now().isoformat(),
        'inference': inference_result,
        'self_evaluation': {
            'scores': evaluation['scores'],
            'total_score': evaluation['total_score'],
            'grade': evaluation['grade'],
            'suggestions': evaluation['suggestions'],
            'matched_cases': evaluation['matched_cases']
        },
        'evolution_strategy': strategy,
        'next_prompt_injections': strategy['prompt_injections']
    }
    
    with open(MUSK_PUSH_PATH, 'w', encoding='utf-8') as f:
        json.dump(musk_push, f, ensure_ascii=False, indent=2)
    
    print(f"   ✓ 已保存到 {MUSK_PUSH_PATH}")
    
    # 7. 打印推演摘要
    print(f"\n=== 推演结果摘要 ===")
    print(f"日期: {date}")
    print(f"推演文本长度: {len(inference_result['inference_text'])} 字符")
    print(f"总评分: {evaluation['total_score']}/100 (等级: {evaluation['grade']})")
    print(f"\n推演内容（节选前500字）:")
    print(inference_result['inference_text'][:500] + "...")
    
    print(f"\n✓ 马斯克自进化引擎运行完成")

if __name__ == '__main__':
    date = sys.argv[1] if len(sys.argv) > 1 else None
    main(date)

# === 新增：法律合规评估功能 ===
import sqlite3

def ask_hy3_for_law(inference_text):
    """让 hy3-review 判断推演触及哪条法律"""
    prompt = f"""基于以下推演内容，判断最可能触及的中国法律条文：

推演内容：
{inference_text[:1000]}

要求：
1. 找出3-5条最相关的法律条文（法律名称+条文编号+风险等级）
2. 风险等级：🟢合规/🟡擦边/🔴越线
3. 格式（JSON数组）：
[
  {
    "law_name": "法律名称",
    "article_number": "条文编号（如：第21条）",
    "risk": "🟢合规/🟡擦边/🔴越线",
    "reason": "为什么触及这条法律（20字内）"
  },
  ...
]

只返回JSON数组，不要其他文字。"""
    
    url = "https://api.lkeap.cloud.tencent.com/plan/v3/chat/completions"
    headers = {
        "Authorization": "Bearer sk-tp-***bA7D",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hy3-preview",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        text = result['choices'][0]['message']['content']
        
        json_start = text.find('[')
        json_end = text.rfind(']') + 1
        if json_start >= 0 and json_end > json_start:
            json_str = text[json_start:json_end]
            law_refs = json.loads(json_str)
            return law_refs
    except Exception as e:
        print(f"⚠️ hy3调用失败: {e}")
    
    return []

def query_laws_by_ref(law_refs):
    """根据 hy3 返回的法律引用，精确匹配 laws 表"""
    conn = sqlite3.connect('legal-knowledge/legal.db')
    cursor = conn.cursor()
    
    matched_laws = []
    for ref in law_refs:
        law_name = ref.get('law_name', '')
        article_number = ref.get('article_number', '')
        
        # 精确匹配
        cursor.execute("""
            SELECT d.name, l.law_name, l.article_number, l.content, l.effective_date
            FROM domains d
            JOIN laws l ON d.id = l.domain_id
            WHERE l.law_name = ? AND l.article_number = ?
        """, (law_name, article_number))
        
        row = cursor.fetchone()
        if row:
            matched_laws.append({
                'domain': row[0],
                'law_name': row[1],
                'article_number': row[2],
                'content': row[3],
                'effective_date': row[4],
                'risk': ref.get('risk', '🟢合规'),
                'reason': ref.get('reason', '')
            })
        else:
            # 模糊匹配法律名称
            cursor.execute("""
                SELECT d.name, l.law_name, l.article_number, l.content, l.effective_date
                FROM domains d
                JOIN laws l ON d.id = l.domain_id
                WHERE l.law_name LIKE ?
                LIMIT 1
            """, (f'%{law_name}%',))
            row = cursor.fetchone()
            if row:
                matched_laws.append({
                    'domain': row[0],
                    'law_name': row[1],
                    'article_number': row[2],
                    'content': row[3],
                    'effective_date': row[4],
                    'risk': ref.get('risk', '🟢合规'),
                    'reason': ref.get('reason', '')
                })
    
    conn.close()
    return matched_laws

def extract_keywords(text):
    """从推演文本提取关键词（简单版）"""
    keywords = []
    # 领域关键词
    domain_keywords = ['算力', '跨境', '税收', '补贴', '关联交易', '数据', '牌照', '指标', '流水', '灰产']
    for dk in domain_keywords:
        if dk in text:
            keywords.append(dk)
    
    # 法律关键词
    law_keywords = ['公司', '合同', '借款', '租赁', '劳动', '婚姻', '继承', '专利', '商标', '增值税', '个人所得税']
    for lk in law_keywords:
        if lk in text:
            keywords.append(lk)
    
    return keywords[:5]  # 最多5个关键词

def assess_compliance(inference_text, laws):
    """生成合规评估"""
    if not laws:
        return None
    
    assessment = "\n⚖️ 合规评估：\n"
    for law in laws:
        # 简单风险判断
        risk = '🟢合规'
        if any(word in inference_text for word in ['洗钱', '逃税', '欺诈', '非法集资']):
            risk = '🔴越线'
        elif any(word in inference_text for word in ['跨境', '补贴', '关联交易']):
            risk = '🟡擦边'
        
        assessment += f"- 涉及法律：{law['law_name']} {law['article_number']}条\n"
        assessment += f"  条文内容：{law['content'][:50]}...\n"
        assessment += f"  风险等级：{risk}\n"
        assessment += f"  红线位置：{law['content'][:30]}...\n"
        assessment += f"  合规变通：建议咨询专业律师\n"
    
    return assessment

# 修改 main 函数，加入合规评估
if __name__ == '__main__':
    # ... 原有代码 ...
    
    # 在推演完成后，加入合规评估
    # 1. 提取关键词
    keywords = extract_keywords(inference_text)
    # 2. 检索法律条文
    matched_laws = query_laws_by_keywords(keywords)
    # 3. 生成合规评估
    compliance = assess_compliance(inference_text, matched_laws)
    
    # 4. 追加到输出
    if compliance:
        inference_text += compliance
        print(f"✓ 已追加合规评估（{len(matched_laws)}条法律条文）")
    
    # ... 后续保存代码 ...


# === 主程序（含合规评估）===
if __name__ == '__main__':
    # 1. 找最新日报
    today = datetime.now().strftime('%Y-%m-%d')
    report_path = f'output/{today}.md'
    if not os.path.exists(report_path):
        # 用最新日报
        import glob
        reports = glob.glob('output/*.md')
        reports.sort(reverse=True)
        report_path = reports[0] if reports else None
    
    if not report_path:
        print("❌ 找不到日报")
        sys.exit(1)
    
    # 2. 找 jinzhu_analysis.json
    jinzhu_path = 'data/jinzhu_analysis.json'
    if not os.path.exists(jinzhu_path):
        print("⚠️ 找不到 jinzhu_analysis.json，用空数据")
        jinzhu = {}
    else:
        with open(jinzhu_path, 'r') as f:
            jinzhu = json.load(f)
    
    # 3. 调用 API 推演
    print(f"开始推演：{report_path}")
    result = call_hy3_api(open(report_path).read(), jinzhu)
    
    # 4. 解析结果
    parsed = parse_inference_result(result)
    inference_text = parsed.get('inference', '')
    
    # 5. 自评估
    self_eval = self_evaluate(parsed, open(report_path).read(), jinzhu)
    
    # 6. 法律合规评估（修复版）
    law_refs = ask_hy3_for_law(inference_text)
    matched_laws = query_laws_by_ref(law_refs)
    compliance = assess_compliance_v2(inference_text, law_refs, matched_laws)
    
    if compliance:
        inference_text += compliance
        print(f"✓ 已追加合规评估（{len(matched_laws)}条法律条文）")
    
    # 7. 保存结果
    output = {
        'date': today,
        'inference': parsed,
        'self_evaluation': self_eval,
        'compliance_assessment': compliance,
        'matched_laws': matched_laws,
        'raw_response': result
    }
    
    output_path = os.path.join(DATA_DIR, 'musk-push.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✓ 推演完成，结果保存到 {output_path}")
    print(f"推演文本（前500字）：\n{inference_text[:500]}")
