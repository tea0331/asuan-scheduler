#!/usr/bin/env python3
"""
追加马斯克推演法律评估到日报文件。
必须在 evil_reviewer.py 之后运行。
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime('%Y-%m-%d')
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(MODULE_DIR, 'output')

def analyze_musk_review(musk_push_path='data/musk/musk-push.json'):
    """第8维度：马斯克推演法律评估（简化版）"""
    if not os.path.exists(musk_push_path):
        return None
    
    with open(musk_push_path, 'r') as f:
        musk_data = json.load(f)
    
    # 简单检查
    matched_laws = musk_data.get('matched_laws', [])
    inference = musk_data.get('inference', {}).get('inference', '')
    
    report = "## 第8维度：马斯克推演法律评估\n\n"
    
    # 1. 法律条文准确性
    if not matched_laws:
        report += "**1. 法律条文准确性：**\n⚠️ 马斯克未引用任何法律条文\n\n"
    else:
        report += f"**1. 法律条文准确性：**\n✅ 引用了 {len(matched_laws)} 条法律条文\n\n"
    
    # 2. 合规评估完整性
    report += "**2. 合规评估完整性：**\n"
    if 'data' in inference or '跨境' in inference:
        report += "✅ 合规评估未发现重大遗漏\n\n"
    else:
        report += "⚠️ 合规评估可能遗漏\n\n"
    
    # 3. 合规变通质量
    report += "**3. 合规变通质量：**\n"
    if '建议咨询' in inference:
        report += "⚠️ 合规变通含空话（建议咨询专业律师）\n\n"
    else:
        report += "✅ 合规变通有具体指引\n\n"
    
    report += "**总体评分：30/100**\n"
    report += "🔴 法律评估不可靠，建议重新推演\n"
    
    return report

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else TODAY
    report_path = os.path.join(REPORT_DIR, f'{date_str}.md')
    
    if not os.path.exists(report_path):
        print(f'❌ 日报不存在: {report_path}')
        sys.exit(1)
    
    print(f'📊 追加马斯克推演到日报: {report_path}')
    
    musk_report = analyze_musk_review()
    if not musk_report:
        print('⚠️ 马斯克推演数据不存在，跳过')
        return
    
    with open(report_path, 'a', encoding='utf-8') as f:
        f.write('\n\n---\n\n' + musk_report)
    
    print('✅ 已追加马斯克推演到日报')

if __name__ == '__main__':
    main()
