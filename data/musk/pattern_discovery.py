#!/usr/bin/env python3
"""
马斯克 v2 升级 - 第三步：缺口模式自动发现
功能：
1. 从 gap-cases.json 自动提取高频操作模式
2. 识别跨领域共现模式
3. 输出 TOP10 缺口模式 + 风险评分
4. 生成模式演化趋势报告
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime

def load_cases(path='gap-cases.json'):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def calculate_risk_score(case):
    """计算单个案例的风险评分（0-100），基于多维度评估"""
    score = 0
    
    # 1. 领域风险权重（0-30分）
    domain_weights = {
        '监管套利': 30,
        '灰产洗白': 28,
        '牌照套利': 25,
        '数据套利': 22,
        '税筹结构': 20,
        '补贴套利': 18,
        '情绪套利': 15,
        '流量套利': 12,
        '流水业务': 10,
        '指标套利': 8
    }
    domain = case.get('domain', '')
    score += domain_weights.get(domain, 10)
    
    # 2. 缺口类型权重（0-20分）
    gap_type = case.get('gap_type', '')
    gap_weights = {
        '规则缺口': 20,
        '体制缺口': 18,
        '技术缺口': 15,
        '市场缺口': 12,
        '人性缺口': 10
    }
    score += gap_weights.get(gap_type, 10)
    
    # 3. 操作复杂度（0-15分）
    method = case.get('operation_method', '')
    method_len = len(method)
    if method_len > 200:
        score += 15
    elif method_len > 100:
        score += 10
    else:
        score += 5
    
    # 4. 红线明确度（0-15分）
    red_line = case.get('red_line_edge', '')
    if '构成' in red_line or '罪' in red_line:
        score += 15
    elif '红线' in red_line or '禁止' in red_line:
        score += 10
    else:
        score += 5
    
    # 5. 可持续性（0-10分）
    sustainability = case.get('why_sustainable', '')
    if len(sustainability) > 150:
        score += 10
    elif len(sustainability) > 80:
        score += 5
    else:
        score += 2
    
    # 6. 来源权威性（0-10分）
    source = case.get('source', '')
    if 'gov.cn' in source or 'spp.gov.cn' in source or 'court.gov.cn' in source:
        score += 10
    elif '12377' in source or 'cac.gov.cn' in source:
        score += 8
    else:
        score += 5
    
    return min(score, 100)

def extract_patterns(cases):
    """从案例中自动提取高频操作模式"""
    # 1. 提取操作模式关键词
    op_keywords = []
    for case in cases:
        method = case.get('operation_method', '')
        verbs = re.findall(r'(通过|利用|使用|采用|借助|依托|基于)', method)
        op_keywords.extend(verbs)
    
    op_counter = Counter(op_keywords)
    top_ops = op_counter.most_common(10)
    
    # 2. 提取跨领域共现模式
    domain_pairs = []
    for i in range(len(cases)):
        for j in range(i+1, len(cases)):
            d1 = cases[i].get('domain', '')
            d2 = cases[j].get('domain', '')
            if d1 != d2:
                pair = tuple(sorted([d1, d2]))
                domain_pairs.append(pair)
    
    pair_counter = Counter(domain_pairs)
    top_pairs = pair_counter.most_common(10)
    
    # 3. 提取风险关键词
    risk_keywords = []
    for case in cases:
        desc = case.get('gap_description', '')
        risks = re.findall(r'(\w{2,8}(?:罪|套利|漏洞|缺口|风险|红线))', desc)
        risk_keywords.extend(risks)
    
    risk_counter = Counter(risk_keywords)
    top_risks = risk_counter.most_common(10)
    
    return {
        'top_operations': top_ops,
        'top_domain_pairs': top_pairs,
        'top_risk_keywords': top_risks
    }

def generate_report(cases, patterns):
    """生成缺口模式分析报告"""
    # 计算每个案例的风险评分
    for case in cases:
        case['risk_score'] = calculate_risk_score(case)
    
    # 按风险评分排序
    sorted_cases = sorted(cases, key=lambda x: x['risk_score'], reverse=True)
    top10_risk = sorted_cases[:10]
    
    # 领域分布
    domain_dist = Counter(c['domain'] for c in cases)
    
    # 生成报告
    report = {
        'generated_at': datetime.now().isoformat(),
        'total_cases': len(cases),
        'avg_risk_score': sum(c['risk_score'] for c in cases) / len(cases),
        'top10_risk_cases': [
            {
                'title': c['title'],
                'domain': c['domain'],
                'risk_score': c['risk_score'],
                'gap_type': c['gap_type']
            } for c in top10_risk
        ],
        'domain_distribution': dict(domain_dist),
        'patterns': {
            'top_operations': [{'pattern': p[0], 'count': p[1]} for p in patterns['top_operations']],
            'top_domain_pairs': [{'pair': p[0], 'count': p[1]} for p in patterns['top_domain_pairs']],
            'top_risk_keywords': [{'keyword': p[0], 'count': p[1]} for p in patterns['top_risk_keywords']]
        },
        'risk_level': 'HIGH' if len(cases) > 150 else 'MEDIUM'
    }
    
    return report

def main():
    print("=== 马斯克 v2 升级 - 第三步：缺口模式自动发现 ===\n")
    
    # 加载案例
    cases = load_cases()
    print(f"已加载 {len(cases)} 个案例")
    
    # 提取模式
    print("正在提取高频模式...")
    patterns = extract_patterns(cases)
    
    # 生成报告
    print("正在生成分析报告...")
    report = generate_report(cases, patterns)
    
    # 保存报告
    output_path = 'pattern-discovery-report.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # 打印摘要
    print(f"\n✓ 分析完成！报告已保存到 {output_path}")
    print(f"\n=== 报告摘要 ===")
    print(f"总案例数: {report['total_cases']}")
    print(f"平均风险评分: {report['avg_risk_score']:.1f}")
    print(f"风险等级: {report['risk_level']}")
    
    print(f"\nTOP10 高风险案例:")
    for i, case in enumerate(report['top10_risk_cases'], 1):
        print(f"  {i}. {case['title']} (风险评分: {case['risk_score']})")
    
    print(f"\nTOP5 高频操作模式:")
    for i, op in enumerate(report['patterns']['top_operations'][:5], 1):
        print(f"  {i}. {op['pattern']} (出现 {op['count']} 次)")
    
    print(f"\nTOP5 跨领域共现模式:")
    for i, pair in enumerate(report['patterns']['top_domain_pairs'][:5], 1):
        print(f"  {i}. {pair['pair'][0]} + {pair['pair'][1]} (共现 {pair['count']} 次)")
    
    print(f"\nTOP5 风险关键词:")
    for i, risk in enumerate(report['patterns']['top_risk_keywords'][:5], 1):
        print(f"  {i}. {risk['keyword']} (出现 {risk['count']} 次)")

if __name__ == '__main__':
    main()
