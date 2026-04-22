#!/usr/bin/env python3
"""
Toku Agent 自动运营脚本 — 计然负责
功能：
1. 监控Open Jobs，自动竞标匹配的Job
2. 自动回复DM消息
3. 自动交付已完成Job的结果
4. 每日运营报告
部署：GitHub Actions，每天运行2次（8:00, 20:00 CST）
"""
import os
import sys
import re
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# ============ 配置 ============
TOKU_API_KEY = os.environ.get('TOKU_API_KEY', '')
WP_API_KEY = os.environ.get('WP_API_KEY', '')        # WorkProtocol
NEAR_API_KEY = os.environ.get('NEAR_API_KEY', '')    # NEAR AI Market
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
TOKU_BASE_URL = 'https://www.toku.agency/api'
WP_BASE_URL = 'https://workprotocol.ai/api'
NEAR_BASE_URL = 'https://market.near.ai/v1'

# 服务ID映射（竞标时用）
OUR_SERVICES = {
    'development': {'id': 'cmo9dqs7d000cjp04twskdfak', 'name': 'Code Audit Pro'},
    'research': {'id': 'cmo9dr2v90001jv0479jvr9p8', 'name': 'Investment Research Brief'},
    'data': {'id': 'cmo9drguq0001jv04uplfsguy', 'name': 'Data Scrape and Analysis'},
}

# 竞标匹配关键词
BID_KEYWORDS = {
    'development': ['code review', 'code audit', 'security audit', 'bug', 'python', 'javascript',
                    'refactor', 'code quality', 'testing', 'pr review', 'code analysis',
                    'bug fix', 'debug', 'performance', 'optimization'],
    'research': ['investment', 'market research', 'market analysis', 'industry analysis',
                 'financial analysis', 'trend analysis', 'competitive analysis',
                 'sector analysis', 'due diligence', 'stock analysis', 'crypto'],
    'data': ['scrape', 'scraping', 'data extraction', 'data mining', 'web scraping',
             'data collection', 'crawl', 'parse', 'data pipeline', 'etl',
             'data analysis', 'visualization', 'report generation'],
}

# 竞标策略
MAX_BID_PRICE_CENTS = 3000   # 最高竞标$30
MIN_BID_PRICE_CENTS = 300    # 最低竞标$3
INTRO_BID_DISCOUNT = 0.5     # 首单5折引流（前3单）

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


# ============ Toku API ============

def toku_get(endpoint, params=None):
    """GET请求Toku API"""
    headers = {'Authorization': f'Bearer {TOKU_API_KEY}'}
    try:
        resp = requests.get(f'{TOKU_BASE_URL}{endpoint}', headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            logging.warning(f"GET {endpoint} 返回 {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"GET {endpoint} 失败: {e}")
        return None


def toku_post(endpoint, data):
    """POST请求Toku API"""
    headers = {
        'Authorization': f'Bearer {TOKU_API_KEY}',
        'Content-Type': 'application/json'
    }
    try:
        resp = requests.post(f'{TOKU_BASE_URL}{endpoint}', headers=headers, json=data, timeout=30)
        if resp.status_code in (200, 201):
            return resp.json()
        else:
            logging.warning(f"POST {endpoint} 返回 {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"POST {endpoint} 失败: {e}")
        return None


def toku_patch(endpoint, data):
    """PATCH请求Toku API"""
    headers = {
        'Authorization': f'Bearer {TOKU_API_KEY}',
        'Content-Type': 'application/json'
    }
    try:
        resp = requests.patch(f'{TOKU_BASE_URL}{endpoint}', headers=headers, json=data, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            logging.warning(f"PATCH {endpoint} 返回 {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"PATCH {endpoint} 失败: {e}")
        return None


# ============ DeepSeek 调用 ============

def call_deepseek(system_prompt, user_prompt, max_tokens=4000):
    """调用DeepSeek生成内容"""
    headers = {
        'Authorization': f'Bearer {DASHSCOPE_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': 'deepseek-chat',  # 用V3，快且便宜
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ],
        'max_tokens': max_tokens,
        'temperature': 0.5
    }
    try:
        resp = requests.post(
            f'{DASHSCOPE_BASE_URL}/chat/completions',
            headers=headers,
            json=payload,
            timeout=120
        )
        data = resp.json()
        if 'error' in data:
            logging.error(f"DeepSeek API错误: {data['error']}")
            return None
        content = data['choices'][0]['message']['content']
        # 过滤think标签
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return content
    except Exception as e:
        logging.error(f"DeepSeek调用失败: {e}")
        return None


# ============ 核心业务 ============

def get_our_jobs_completed():
    """获取我们已完成的订单数"""
    profile = toku_get('/agents/me')
    if profile and 'agent' in profile:
        return profile['agent'].get('jobsCompleted', 0)
    return 0


def find_matching_category(text):
    """根据Job文本匹配我们的服务类别"""
    text_lower = text.lower()
    scores = {}
    for category, keywords in BID_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[category] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


def calculate_bid_price(category, budget_cents=None):
    """计算竞标价格"""
    jobs_completed = get_our_jobs_completed()

    # 基础价格（按类别）
    base_prices = {
        'development': 1500,  # $15
        'research': 2000,     # $20
        'data': 1200,         # $12
    }
    price = base_prices.get(category, 1000)

    # 首单引流折扣
    if jobs_completed < 3:
        price = int(price * INTRO_BID_DISCOUNT)
        logging.info(f"首单引流折扣: 原价${price/INTRO_BID_DISCOUNT/100:.0f} → 折后${price/100:.0f}")

    # 如果有预算参考，不超过预算的80%
    if budget_cents and budget_cents > 0:
        price = min(price, int(budget_cents * 0.8))

    # 限制范围
    price = max(MIN_BID_PRICE_CENTS, min(MAX_BID_PRICE_CENTS, price))
    return price


def monitor_and_bid():
    """监控Open Jobs并自动竞标"""
    logging.info("🔍 开始扫描Open Jobs...")

    # 获取Open Jobs
    jobs_data = toku_get('/agents/jobs', {'status': 'OPEN', 'limit': 20})
    if not jobs_data:
        logging.warning("无法获取Open Jobs")
        return []

    jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get('jobs', jobs_data.get('data', []))
    if not jobs:
        logging.info("没有Open Jobs")
        return []

    logging.info(f"找到 {len(jobs)} 个Open Jobs")

    bids_placed = []
    for job in jobs[:10]:  # 每次最多处理10个
        job_id = job.get('id', '')
        title = job.get('title', '')
        description = job.get('description', '') or ''
        budget = job.get('budgetCents', 0)
        bid_count = job.get('bidCount', 0) or 0
        category = job.get('category', '')

        # 组合匹配文本
        match_text = f"{title} {description} {category}"
        matched_cat = find_matching_category(match_text)

        if not matched_cat:
            logging.info(f"  跳过(不匹配): {title[:50]}")
            continue

        # 检查是否已竞标
        existing_bids = job.get('bids', [])
        our_bid = any(b.get('agentId', '').startswith('cmo9dq2p') for b in (existing_bids or []))
        if our_bid:
            logging.info(f"  跳过(已竞标): {title[:50]}")
            continue

        # 竞标数太多（>50）则跳过，性价比低
        if bid_count > 50:
            logging.info(f"  跳过(竞标过多{bid_count}): {title[:50]}")
            continue

        # 计算价格
        price = calculate_bid_price(matched_cat, budget)

        # 生成竞标提案
        service = OUR_SERVICES[matched_cat]
        bid_message = generate_bid_proposal(matched_cat, title, description, price)

        if not bid_message:
            logging.warning(f"  跳过(提案生成失败): {title[:50]}")
            continue

        # 提交竞标
        bid_data = {
            'priceCents': price,
            'deliveryDays': 2,
            'proposal': bid_message,
        }

        result = toku_post(f'/agents/jobs/{job_id}/bids', bid_data)

        if result:
            logging.info(f"  ✅ 竞标成功: {title[:50]} | ${price/100:.0f} | {service['name']}")
            bids_placed.append({
                'job_id': job_id,
                'title': title,
                'category': matched_cat,
                'price': price,
                'service': service['name']
            })
        else:
            logging.warning(f"  ❌ 竞标失败: {title[:50]}")

        # 间隔1秒，避免过快
        time.sleep(1)

    return bids_placed


def generate_bid_proposal(category, title, description, price_cents):
    """用DeepSeek生成竞标提案"""
    service = OUR_SERVICES[category]

    system_prompt = f"""You are AsuanAI, an AI agent on toku.agency. You are writing a bid proposal for a job.
Your service: {service['name']}
Be concise, professional, and specific about what you will deliver. Keep it under 150 words.
Do NOT mention lottery, gambling, or any related topics."""

    user_prompt = f"""Job Title: {title}
Job Description: {description[:500]}
Your Bid Price: ${price_cents/100:.0f}

Write a compelling bid proposal explaining:
1. Why you're a great fit
2. What you'll deliver specifically
3. Timeline
Keep it professional and concise."""

    return call_deepseek(system_prompt, user_prompt, max_tokens=300)


def handle_dm_messages():
    """处理DM消息，自动回复"""
    logging.info("💬 检查DM消息...")

    conversations = toku_get('/agents/dm')
    if not conversations:
        logging.info("无DM消息")
        return []

    convos = conversations if isinstance(conversations, list) else conversations.get('conversations', conversations.get('data', []))
    if not convos:
        logging.info("无DM消息")
        return []

    replies = []
    for conv in convos[:5]:
        # 检查未读
        unread = conv.get('unreadCount', 0)
        if not unread:
            continue

        from_name = conv.get('agentName', conv.get('with', 'Unknown'))
        from_id = conv.get('agentId', conv.get('withId', ''))

        # 获取消息内容
        messages = toku_get(f'/agents/dm?with={from_name}')
        if not messages:
            continue

        msgs = messages if isinstance(messages, list) else messages.get('messages', messages.get('data', []))
        if not msgs:
            continue

        # 取最新消息
        latest_msg = msgs[-1] if msgs else None
        if not latest_msg:
            continue

        msg_text = latest_msg.get('message', latest_msg.get('content', ''))

        # 生成自动回复
        reply = generate_dm_reply(from_name, msg_text)
        if reply:
            result = toku_post('/agents/dm', {
                'to': from_name,
                'message': reply
            })
            if result:
                logging.info(f"  ✅ 回复DM给 {from_name}")
                replies.append({'to': from_name, 'message': reply[:50]})
            time.sleep(1)

    return replies


def generate_dm_reply(sender_name, message):
    """生成DM自动回复"""
    system_prompt = """You are AsuanAI, an AI agent on toku.agency. You specialize in code audit, investment research, and data scraping.
Reply to DMs professionally and helpfully. Be concise. If someone asks about hiring you, guide them to your services.
Do NOT mention lottery, gambling, or any related topics."""

    user_prompt = f"""Message from {sender_name}: {message}

Write a brief professional reply (under 100 words)."""

    return call_deepseek(system_prompt, user_prompt, max_tokens=200)


def handle_active_jobs():
    """处理进行中的Job：自动接受、交付"""
    logging.info("📋 检查进行中的Job...")

    jobs_data = toku_get('/jobs', {'role': 'provider', 'status': 'ACCEPTED'})
    if not jobs_data:
        return []

    jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get('jobs', jobs_data.get('data', []))
    if not jobs:
        logging.info("无进行中的Job")
        return []

    handled = []
    for job in jobs[:5]:
        job_id = job.get('id', '')
        status = job.get('status', '')
        service_title = job.get('serviceTitle', job.get('service', {}).get('title', 'Unknown'))
        input_text = job.get('input', '')

        if status == 'REQUESTED':
            # 自动接受
            result = toku_patch(f'/jobs/{job_id}', {'action': 'accept'})
            if result:
                logging.info(f"  ✅ 接受Job: {service_title}")
                handled.append({'job_id': job_id, 'action': 'accepted'})

        elif status == 'ACCEPTED' or status == 'IN_PROGRESS':
            # 开始工作并交付
            result = toku_patch(f'/jobs/{job_id}', {'action': 'start'})
            delivery = generate_job_delivery(service_title, input_text)
            if delivery:
                deliver_result = toku_patch(f'/jobs/{job_id}', {'action': 'deliver', 'output': delivery})
                if deliver_result:
                    logging.info(f"  ✅ 交付Job: {service_title}")
                    handled.append({'job_id': job_id, 'action': 'delivered'})

        time.sleep(1)

    return handled


def generate_job_delivery(service_title, input_text):
    """生成Job交付内容"""
    # 确定服务类型
    category = None
    for cat, svc in OUR_SERVICES.items():
        if svc['name'].lower() in service_title.lower():
            category = cat
            break

    if category == 'development':
        system_prompt = """You are AsuanAI performing a code audit. Provide a professional code review report in markdown.
Include: Summary, Security Issues, Performance Issues, Best Practices, Recommendations.
Be specific and actionable. Do NOT mention lottery or gambling."""
    elif category == 'research':
        system_prompt = """You are AsuanAI performing investment research. Provide a professional research brief in markdown.
Include: Executive Summary, Market Overview, Key Trends, Opportunities, Risks, Recommendations.
Be data-driven and actionable. Do NOT mention lottery or gambling."""
    else:  # data
        system_prompt = """You are AsuanAI performing data scraping and analysis. Provide a professional data report in markdown.
Include: Data Sources, Methodology, Key Findings, Data Summary, Recommendations.
Be specific and structured. Do NOT mention lottery or gambling."""

    user_prompt = f"""Service: {service_title}
Client Request: {input_text[:1000]}

Deliver a professional report based on the request above."""

    return call_deepseek(system_prompt, user_prompt, max_tokens=4000)


def check_wallet():
    """查看钱包余额"""
    wallet = toku_get('/agents/wallet')
    if wallet:
        balance = wallet.get('balanceCents', wallet.get('balance', 0))
        if isinstance(balance, str):
            balance = int(balance)
        logging.info(f"💰 钱包余额: ${balance/100:.2f}")
        return balance
    return 0


def daily_report(bids, replies, jobs_handled):
    """生成每日运营报告"""
    profile = toku_get('/agents/me')
    agent_info = profile.get('agent', {}) if profile else {}

    now_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M')

    report = f"""# 🤖 AsuanAI Toku运营日报 — {now_str}

## Agent状态
- 名称: {agent_info.get('name', 'AsuanAI')}
- 评分: {agent_info.get('rating', 0)}
- 完成订单: {agent_info.get('jobsCompleted', 0)}

## 今日操作

### 竞标 ({len(bids)}个)
"""
    for b in bids:
        report += f"- {b['service']} | ${b['price']/100:.0f} | {b['title'][:40]}\n"

    if not bids:
        report += "- 无新竞标\n"

    report += f"""
### DM回复 ({len(replies)}个)
"""
    for r in replies:
        report += f"- → {r['to']}: {r['message']}\n"

    if not replies:
        report += "- 无新回复\n"

    report += f"""
### Job处理 ({len(jobs_handled)}个)
"""
    for j in jobs_handled:
        report += f"- {j['action']}: {j['job_id'][:12]}\n"

    if not jobs_handled:
        report += "- 无新Job\n"

    wallet = toku_get('/agents/wallet')
    balance = 0
    if wallet:
        balance = wallet.get('balanceCents', wallet.get('balance', 0))
        if isinstance(balance, str):
            balance = int(balance)
    report += f"""
## 钱包
- 余额: ${balance/100:.2f}

---
*由计然自动生成*
"""
    return report


def monitor_wp_jobs():
    """监控WorkProtocol Open Jobs并竞标"""
    if not WP_API_KEY:
        logging.info("⏭️ WorkProtocol: 跳过（无API Key）")
        return []

    WP_AGENT_ID = '6393138f-4d52-468a-9b6a-a2445f8613e6'
    logging.info("🔍 WorkProtocol: 扫描Open Jobs...")
    headers = {'Authorization': f'Bearer {WP_API_KEY}'}
    try:
        # 查看自己profile
        prof = requests.get(f'{WP_BASE_URL}/agents/{WP_AGENT_ID}', headers=headers, timeout=30)
        if prof.status_code == 200:
            pdata = prof.json().get('agent', prof.json())
            logging.info(f"  Profile: Jobs={pdata.get('totalJobs',0)} Earned=${pdata.get('totalEarned','0')}")
        else:
            logging.warning(f"  WorkProtocol profile返回 {prof.status_code}")

        # 获取jobs列表
        resp = requests.get(f'{WP_BASE_URL}/jobs', headers=headers, params={'status': 'open', 'limit': 10}, timeout=30)
        if resp.status_code != 200:
            logging.warning(f"  WorkProtocol jobs返回 {resp.status_code}: {resp.text[:100]}")
            return []
        data = resp.json()
        jobs = data if isinstance(data, list) else data.get('jobs', data.get('data', []))
        if not jobs:
            logging.info("  无Open Jobs")
            return []

        bids = []
        for job in jobs[:5]:
            title = job.get('title', '')
            description = job.get('description', '') or ''
            match_text = f"{title} {description}"
            matched_cat = find_matching_category(match_text)
            if not matched_cat:
                continue

            price = calculate_bid_price(matched_cat)
            proposal = generate_bid_proposal(matched_cat, title, description, price)
            if not proposal:
                continue

            bid_data = {'priceCents': price, 'proposal': proposal, 'deliveryDays': 2}
            bid_resp = requests.post(
                f'{WP_BASE_URL}/jobs/{job.get("id", "")}/bids',
                headers={**headers, 'Content-Type': 'application/json'},
                json=bid_data, timeout=30
            )
            if bid_resp.status_code in (200, 201):
                logging.info(f"  ✅ WP竞标: {title[:50]} | ${price/100:.0f}")
                bids.append({'platform': 'WorkProtocol', 'title': title, 'price': price})
            time.sleep(1)
        return bids
    except Exception as e:
        logging.error(f"  WorkProtocol失败: {e}")
        return []


def monitor_near_jobs():
    """监控NEAR AI Market Jobs并竞标"""
    if not NEAR_API_KEY:
        logging.info("⏭️ NEAR AI Market: 跳过（无API Key）")
        return []

    logging.info("🔍 NEAR AI Market: 扫描Open Jobs...")
    headers = {'Authorization': f'Bearer {NEAR_API_KEY}'}
    try:
        resp = requests.get(f'{NEAR_BASE_URL}/jobs', headers=headers, params={'status': 'open', 'limit': 10}, timeout=30)
        if resp.status_code != 200:
            logging.warning(f"  NEAR API返回 {resp.status_code}")
            return []
        data = resp.json()
        jobs = data if isinstance(data, list) else data.get('jobs', data.get('data', []))
        if not jobs:
            logging.info("  无Open Jobs")
            return []

        bids = []
        for job in jobs[:5]:
            title = job.get('title', '')
            description = job.get('description', '') or ''
            match_text = f"{title} {description}"
            matched_cat = find_matching_category(match_text)
            if not matched_cat:
                continue

            # NEAR用NEAR代币计价，转换约0.5 NEAR起步
            price_near = 0.5
            proposal = generate_bid_proposal(matched_cat, title, description, int(price_near * 100))
            if not proposal:
                continue

            bid_data = {'price': str(price_near), 'token': 'NEAR', 'proposal': proposal, 'delivery_hours': 48}
            bid_resp = requests.post(
                f'{NEAR_BASE_URL}/jobs/{job.get("id", "")}/bids',
                headers={**headers, 'Content-Type': 'application/json'},
                json=bid_data, timeout=30
            )
            if bid_resp.status_code in (200, 201):
                logging.info(f"  ✅ NEAR竞标: {title[:50]} | {price_near} NEAR")
                bids.append({'platform': 'NEAR', 'title': title, 'price_near': price_near})
            time.sleep(1)
        return bids
    except Exception as e:
        logging.error(f"  NEAR AI Market失败: {e}")
        return []


# ============ 主函数 ============

def main():
    if not TOKU_API_KEY:
        print("❌ 缺少TOKU_API_KEY环境变量")
        sys.exit(1)
    if not DASHSCOPE_API_KEY:
        print("❌ 缺少DASHSCOPE_API_KEY环境变量")
        sys.exit(1)

    logging.info("=" * 50)
    logging.info("🤖 AsuanAI 多平台自动运营启动 — 计然管理")
    logging.info("=" * 50)

    all_bids = []

    # === 平台1: Toku ===
    logging.info("\n📌 [Toku.agency]")
    toku_bids = monitor_and_bid()
    replies = handle_dm_messages()
    jobs_handled = handle_active_jobs()
    check_wallet()
    all_bids.extend([{'platform': 'Toku', **b} for b in toku_bids])

    # === 平台2: WorkProtocol ===
    logging.info("\n📌 [WorkProtocol]")
    wp_bids = monitor_wp_jobs()
    all_bids.extend(wp_bids)

    # === 平台3: NEAR AI Market ===
    logging.info("\n📌 [NEAR AI Market]")
    near_bids = monitor_near_jobs()
    all_bids.extend(near_bids)

    # 生成多平台运营报告
    report = daily_report(toku_bids, replies, jobs_handled)

    # 追加多平台汇总
    report += f"""
## 多平台汇总

| 平台 | 竞标数 | 状态 |
|------|--------|------|
| Toku | {len(toku_bids)} | {'✅' if TOKU_API_KEY else '❌'} |
| WorkProtocol | {len(wp_bids)} | {'✅' if WP_API_KEY else '⏭️'} |
| NEAR AI Market | {len(near_bids)} | {'✅' if NEAR_API_KEY else '⏭️'} |

---
*由计然自动生成 | 多平台运营*
"""

    report_path = os.environ.get('REPO_DIR', '.')
    with open(os.path.join(report_path, 'toku-daily-report.md'), 'w') as f:
        f.write(report)

    logging.info(f"\n📊 多平台运营报告已生成")
    logging.info(f"  总竞标: {len(all_bids)}个 | Toku={len(toku_bids)} WP={len(wp_bids)} NEAR={len(near_bids)}")


if __name__ == '__main__':
    main()
