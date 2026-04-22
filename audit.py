#!/usr/bin/env python3
"""
计然自动审计 + Toku运营策略脚本
功能：
1. 代码审计（原有功能）
2. 审查Toku运营数据，给出改善和增收建议
3. 每周一生成策略讨论报告
"""
import os
import sys
import re
import json
import requests
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
TOKU_API_KEY = os.environ.get('TOKU_API_KEY', '')
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
TOKU_BASE_URL = 'https://www.toku.agency/api'


def read_file(path):
    with open(path, 'r') as f:
        return f.read()


def call_deepseek(system_prompt, user_prompt, max_tokens=8000, model='deepseek-r1'):
    headers = {
        'Authorization': f'Bearer {DASHSCOPE_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ],
        'max_tokens': max_tokens,
        'temperature': 0.3
    }
    try:
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
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return content
    except Exception as e:
        return f"API调用失败: {e}"


def toku_get(endpoint, params=None):
    """GET请求Toku API"""
    headers = {'Authorization': f'Bearer {TOKU_API_KEY}'}
    try:
        resp = requests.get(f'{TOKU_BASE_URL}{endpoint}', headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        return None
    except:
        return None


# ============ 代码审计 ============

def run_code_audit(repo_dir):
    """运行代码审计"""
    files_to_audit = {}
    for fname in ['lottery_analyzer.py', 'scheduler.py', 'toku_agent.py']:
        fpath = os.path.join(repo_dir, fname)
        if os.path.exists(fpath):
            files_to_audit[fname] = read_file(fpath)

    for fname in ['weight-config.json', 'lottery-backtest.json', 'lottery-predictions.json']:
        fpath = os.path.join(repo_dir, fname)
        if os.path.exists(fpath):
            files_to_audit[fname] = read_file(fpath)

    if not files_to_audit:
        print("没有找到可审计的文件")
        return None

    system_prompt = """你是计然，一个严谨的代码审计AI。你的任务是：
1. 审查代码中的bug、逻辑错误、边界问题
2. 检查安全性问题（密钥泄露、注入风险等）
3. 评估算法正确性
4. 检查数据源解析的健壮性
5. 审查Toku Agent脚本的竞标逻辑是否合理

输出格式为markdown，包含：
- 🔴 严重问题（必须修复）
- 🟡 中等问题（建议修复）
- 🟢 轻微问题（可选优化）
- 每个问题给出行号、描述、修复建议"""

    user_prompt = f"请审计以下代码文件（日期：{datetime.now(CST).strftime('%Y-%m-%d')}）：\n\n"
    for fname, content in files_to_audit.items():
        if len(content) > 5000:
            content = content[:2500] + "\n... (中间省略) ...\n" + content[-2500:]
        user_prompt += f"\n## {fname}\n```python\n{content}\n```\n"

    user_prompt += "\n\n请重点检查：\n1. 核心算法正确性\n2. 数据源解析健壮性\n3. Toku Agent竞标策略合理性\n4. 安全性问题"

    print("计然开始代码审计...")
    return call_deepseek(system_prompt, user_prompt)


# ============ Toku运营分析 ============

def get_toku_stats():
    """获取Toku运营数据"""
    stats = {
        'profile': None,
        'wallet': None,
        'jobs_as_provider': [],
        'recent_bids': [],
        'open_jobs_count': 0,
    }

    # Agent Profile
    profile = toku_get('/agents/me')
    if profile and 'agent' in profile:
        stats['profile'] = profile['agent']

    # Wallet
    wallet = toku_get('/agents/wallet')
    if wallet:
        stats['wallet'] = wallet

    # Jobs as provider
    jobs = toku_get('/jobs', {'role': 'provider', 'limit': 10})
    if jobs:
        job_list = jobs if isinstance(jobs, list) else jobs.get('jobs', jobs.get('data', []))
        stats['jobs_as_provider'] = job_list

    # Open Jobs
    open_jobs = toku_get('/agents/jobs', {'status': 'OPEN', 'limit': 5})
    if open_jobs:
        oj_list = open_jobs if isinstance(open_jobs, list) else open_jobs.get('jobs', open_jobs.get('data', []))
        stats['open_jobs_count'] = len(oj_list) if oj_list else 0

    return stats


def generate_toku_strategy(stats):
    """生成Toku运营策略建议"""
    profile = stats.get('profile') or {}
    wallet = stats.get('wallet') or {}
    jobs = stats.get('jobs_as_provider', [])

    balance = wallet.get('balanceCents', wallet.get('balance', 0))
    if isinstance(balance, str):
        balance = int(balance)

    jobs_completed = profile.get('jobsCompleted', 0)
    rating = profile.get('rating', 0)

    system_prompt = """你是计然，负责AsuanAI在Toku.agency平台的运营策略。你的职责：
1. 分析当前运营数据，给出具体改善建议
2. 提出增收策略（新服务、定价调整、营销手段）
3. 发现竞品动态和平台趋势
4. 每次给出3-5个可执行的具体建议（不是空话）

输出格式：markdown，包含：
- 📊 数据概览
- 📈 改善建议（具体+可执行）
- 💰 增收策略
- 🔍 下周重点行动

注意：绝不能提及"刘海蟾点金"或任何彩票相关内容。"""

    user_prompt = f"""日期：{datetime.now(CST).strftime('%Y-%m-%d')}
当前运营数据：
- 完成订单：{jobs_completed}
- 评分：{rating}
- 钱包余额：${balance/100:.2f}
- 进行中Job：{len(jobs)}个
- 平台Open Jobs：{stats.get('open_jobs_count', '?')}个

已有服务：
1. Code Audit Pro ($10/$25/$50)
2. Investment Research Brief ($15/$35/$70)
3. Data Scrape and Analysis ($8/$20/$40)

请分析并给出：
1. 当前定价是否合理？要不要调整？
2. 有什么新服务方向可以上架？
3. 如何提高首单成交率（目前0单）？
4. 平台上的热门需求是什么？我们怎么切入？
5. 下周3个最重要的行动项"""

    return call_deepseek(system_prompt, user_prompt, model='deepseek-chat')


# ============ 主函数 ============

def main():
    repo_dir = os.environ.get('REPO_DIR', '.')

    print("=" * 50)
    print("计然开始工作")
    print("=" * 50)

    # 1. 代码审计
    audit_report = run_code_audit(repo_dir)

    # 2. Toku运营分析
    print("\n获取Toku运营数据...")
    toku_stats = get_toku_stats()
    strategy_report = generate_toku_strategy(toku_stats)

    # 3. 合并报告
    full_report = f"# 📋 计然综合报告 — {datetime.now(CST).strftime('%Y-%m-%d')}\n\n"

    if audit_report and len(audit_report) > 100:
        full_report += "## 一、代码审计\n\n"
        full_report += audit_report
        full_report += "\n\n"
    else:
        full_report += "## 一、代码审计\n\n⚠️ 审计结果为空或过短\n\n"

    if strategy_report and len(strategy_report) > 100:
        full_report += "## 二、Toku运营策略\n\n"
        full_report += strategy_report
        full_report += "\n\n"
    else:
        full_report += "## 二、Toku运营策略\n\n⚠️ 策略报告为空或过短\n\n"

    # 4. 写入报告
    report_path = os.path.join(repo_dir, 'audit-report.md')
    with open(report_path, 'w') as f:
        f.write(full_report)

    print(f"\n计然报告已写入 {report_path} ({len(full_report)}字符)")


if __name__ == '__main__':
    main()
