#!/usr/bin/env python3
"""
计然自动审计脚本 — 在GitHub Actions上免费运行
读取lottery_analyzer.py和scheduler.py，调DeepSeek-R1做代码审计，生成报告
"""
import os
import sys
import re
import json
import requests
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

def read_file(path):
    with open(path, 'r') as f:
        return f.read()

def call_deepseek(system_prompt, user_prompt, max_tokens=8000):
    headers = {
        'Authorization': f'Bearer {DASHSCOPE_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': 'deepseek-r1',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ],
        'max_tokens': max_tokens,
        'temperature': 0.3
    }
    resp = requests.post(
        f'{DASHSCOPE_BASE_URL}/chat/completions',
        headers=headers,
        json=payload,
        timeout=300
    )
    data = resp.json()
    if 'error' in data:
        return f"API错误: {data['error']}"
    content = data['choices'][0]['message']['content']
    # 过滤think标签
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    return content

def main():
    repo_dir = os.environ.get('REPO_DIR', '.')
    
    # 读取核心文件
    files_to_audit = {}
    for fname in ['lottery_analyzer.py', 'scheduler.py']:
        fpath = os.path.join(repo_dir, fname)
        if os.path.exists(fpath):
            files_to_audit[fname] = read_file(fpath)
    
    # 读取weight-config和回测数据
    for fname in ['weight-config.json', 'lottery-backtest.json', 'lottery-predictions.json']:
        fpath = os.path.join(repo_dir, fname)
        if os.path.exists(fpath):
            files_to_audit[fname] = read_file(fpath)
    
    if not files_to_audit:
        print("没有找到可审计的文件")
        return
    
    # 构建审计prompt
    system_prompt = """你是计然，一个严谨的代码审计AI。你的任务是：
1. 审查代码中的bug、逻辑错误、边界问题
2. 检查安全性问题（密钥泄露、注入风险等）
3. 评估算法正确性（特别是彩票分析算法）
4. 检查数据源解析的健壮性
5. 发现性能优化机会

输出格式为markdown，包含：
- 🔴 严重问题（必须修复）
- 🟡 中等问题（建议修复）
- 🟢 轻微问题（可选优化）
- 每个问题给出行号、描述、修复建议"""

    user_prompt = f"""请审计以下代码文件（日期：{datetime.now(CST).strftime('%Y-%m-%d')}）：

"""
    for fname, content in files_to_audit.items():
        # 截断过长的文件（保留关键部分）
        if len(content) > 5000:
            content = content[:2500] + "\n... (中间省略) ...\n" + content[-2500:]
        user_prompt += f"\n## {fname}\n```python\n{content}\n```\n"
    
    user_prompt += "\n\n请重点检查：\n1. 彩票算法（WeightedAnalyzer）的正确性\n2. 数据源解析的健壮性\n3. 定时任务调度的可靠性\n4. 安全性问题"
    
    # 调用DeepSeek
    print("计然开始审计...")
    report = call_deepseek(system_prompt, user_prompt)
    
    if not report or len(report) < 100:
        print("审计结果为空或过短")
        return
    
    # 写入报告文件
    report_path = os.path.join(repo_dir, 'audit-report.md')
    with open(report_path, 'w') as f:
        f.write(f"# 📋 计然审计报告 — {datetime.now(CST).strftime('%Y-%m-%d')}\n\n")
        f.write(report)
    
    print(f"审计完成，报告已写入 {report_path} ({len(report)}字符)")

if __name__ == '__main__':
    main()
