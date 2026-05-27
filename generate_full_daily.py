#!/usr/bin/env python3
"""生成完整日报 - 含新闻(API) + 今日推荐 + 昨日回测

v2: 加入用户画像过滤（关键词权重打分 + 过滤 + 排序）
"""
import os
import sys
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import json
import requests
import random

# 添加项目根目录到path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')
yesterday = (datetime.now(CST) - timedelta(days=1))
today = datetime.now(CST)

SMTP_SERVER = 'smtp.163.com'
SMTP_PORT = 465
SMTP_USER = 'tea0331@163.com'
SMTP_PASS = 'NYuLnGar8wT8RBit'
SMTP_TO = 'tea0331@163.com'

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# 确保output目录存在
output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(output_dir, exist_ok=True)

# ============================================================
# 用户画像：关键词权重（正=感兴趣，负=不感兴趣）
# ============================================================
USER_PROFILE = {
    # 算力/芯片/英伟达产业链（核心关注，权重最高）
    '算力': 4, 'GPU': 4, '英伟达': 4, 'NVIDIA': 4, '黄仁勋': 3,
    '芯片': 3, '半导体': 3, '台积电': 3, '光刻': 3, '晶圆': 3,
    '显卡': 2, 'CUDA': 2, 'H100': 3, 'H200': 3, 'B200': 3,
    # AI/大模型
    '大模型': 3, '人工智能': 3, 'AI': 2, 'LLM': 2, 'DeepSeek': 3,
    'GPT': 2, 'Claude': 2, '开源模型': 2, 'AGI': 2,
    # 商业/创业/投资
    '融资': 3, '创业': 3, '上市': 2, '投资': 2, '营收': 2,
    '供需': 3, '缺口': 3, '蓝海': 3, '出海': 3, '跨境': 3,
    '下沉市场': 2, '独角兽': 2, '商业': 2,
    # 信息差/技术降维
    '信息差': 3, '降维': 2, '政策红利': 3, '补贴': 2, '关税': 2,
    # 电子/信息产业
    '电子': 2, '通信': 2, '5G': 2, '消费电子': 2, '供应链': 2,
    # 市场异动
    '裁员': 2, '暴跌': 2, '亏损': 2, '关停': 2, '逆势': 2,  # 逆潮=机会
    # 普通科技（中性偏好）
    '科技': 1, '互联网': 1, '数字化': 1, '云': 1,
    # ---- 负面：不感兴趣 ----
    '明星': -3, '综艺': -3, '恋情': -3, '离婚': -3, '出轨': -3,
    '八卦': -4, '饭圈': -4, '偶像': -3, '选秀': -3, '粉丝': -2,
    '娱乐圈': -4, '网红': -2, '直播带货': -2,
    '体育': -1, '足球': -1, '篮球': -1, 'NBA': -1, '世界杯': -1,
    '彩票': -2, '赌博': -3,
    '剧情': -2, '电视剧': -2, '电影': -1, '追剧': -2,
    '减肥': -1, '美容': -1, '美妆': -1,
}


def score_news(item):
    """根据用户画像给新闻打分"""
    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
    score = 0
    for keyword, weight in USER_PROFILE.items():
        if keyword.lower() in text:
            score += weight
    return score


def filter_by_profile(news_list, min_score=0, top_n=None):
    """过滤+排序：删负分，按画像得分降序"""
    filtered = [n for n in news_list if score_news(n) >= min_score]
    filtered.sort(key=score_news, reverse=True)
    if top_n:
        filtered = filtered[:top_n]
    return filtered


def send_email(subject, body):
    """发送邮件"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_TO
    html = body.replace('\n', '<br>')
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [SMTP_TO], msg.as_string())
        server.quit()
        logging.info(f"✅ 邮件发送成功: {subject}")
        return True
    except Exception as e:
        logging.error(f"❌ 邮件发送失败: {e}")
        return False


def _fetch_rss(url, count=5):
    """从RSS源获取新闻"""
    try:
        import feedparser
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:count]:
            title = entry.get('title', '').strip()
            summary = entry.get('summary', '').strip()
            # 清理HTML标签
            if summary:
                from bs4 import BeautifulSoup
                summary = BeautifulSoup(summary, 'html.parser').get_text(strip=True)
            if title:
                results.append({
                    'title': title,
                    'source': entry.get('author', entry.get('source', {}).get('title', '')),
                    'summary': summary[:200]
                })
        return results
    except Exception as e:
        logging.warning(f"[新闻] RSS抓取失败({url}): {e}")
        return []


def _fetch_baidu_hot(count=10):
    """抓取百度热搜榜"""
    try:
        url = "https://top.baidu.com/board?tab=realtime"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for item in soup.select('div.c-single-text-ellipsis')[:count]:
            title = item.get_text(strip=True)
            if title:
                results.append({'title': title, 'source': '百度热搜', 'summary': ''})
        return results
    except Exception as e:
        logging.warning(f"[新闻] 百度热搜抓取失败: {e}")
        return []


def generate_news_section():
    """基于RSS+热搜生成真实新闻日报（v2: 用户画像过滤）"""
    logging.info("[新闻] 开始抓取真实新闻(RSS+热搜)...")

    # 数据源
    KR36_RSS = 'https://36kr.com/feed'          # 36氪：科技/商业/创业
    ITHOME_RSS = 'https://www.ithome.com/rss/'   # IT之家：科技/AI

    sections = []

    # ---- 抓取原始数据 ----
    ithome_raw = _fetch_rss(ITHOME_RSS, 15)
    kr36_raw = _fetch_rss(KR36_RSS, 20)
    hot_raw = _fetch_baidu_hot(20)

    # ---- 画像过滤 ----
    tech_all = filter_by_profile(ithome_raw + kr36_raw, min_score=0)
    biz_all = filter_by_profile(kr36_raw, min_score=0)
    hot_filtered = filter_by_profile(hot_raw, min_score=-1, top_n=8)  # 热搜稍宽松，-1以上保留

    # 统计画像效果
    total_raw = len(ithome_raw) + len(kr36_raw) + len(hot_raw)
    total_filtered = len(tech_all) + len(biz_all) + len(hot_filtered)
    logging.info(f"[画像] 原始{total_raw}条 → 过滤后{total_filtered}条（剔除{total_raw - total_filtered}条低价值）")

    # 1. AI/科技资讯
    sections.append("## 一、每日资讯\n")
    sections.append("### 🤖 AI/科技\n")

    # 先从画像高分中挑AI相关的
    ai_keywords = ['AI', '人工智能', '芯片', '模型', '大模型', '英伟达', '华为', '算力', 'DeepSeek', 'GPT', 'LLM', '机器人', 'NVIDIA', 'GPU']
    ai_items = [n for n in tech_all if any(kw.lower() in n['title'].lower() for kw in ai_keywords)]
    if not ai_items:
        ai_items = tech_all[:3]  # 无精确匹配则取画像高分前3
    for n in ai_items[:4]:
        score = score_news(n)
        tag = '🔥' if score >= 6 else ('⭐' if score >= 3 else '')
        sections.append(f"- {tag}**{n['title']}**")
        if n['summary']:
            sections.append(f"  > {n['summary'][:120]}")

    # 2. 商业/金融
    sections.append("\n### 💰 商业/金融\n")
    biz_keywords = ['融资', '上市', '投资', '营收', '商业', '创业', '市场', '消费', '经济', '公司', '出海', '跨境', '供需']
    biz_items = [n for n in biz_all if any(kw in n['title'] for kw in biz_keywords)]
    if not biz_items:
        biz_items = biz_all[:3]
    for n in biz_items[:4]:
        score = score_news(n)
        tag = '🔥' if score >= 6 else ('⭐' if score >= 3 else '')
        sections.append(f"- {tag}**{n['title']}**")
        if n['summary']:
            sections.append(f"  > {n['summary'][:120]}")

    # 3. 热搜/时事（已过滤娱乐八卦）
    sections.append("\n### 🔥 热搜/时事\n")
    for n in hot_filtered[:5]:
        score = score_news(n)
        tag = '🔥' if score >= 3 else ''
        sections.append(f"- {tag}{n['title']}")

    # 4. 市场缺口扫描
    sections.append("\n## 二、市场缺口扫描\n")
    sections.append("### 固定领域缺口\n")

    all_news = tech_all + biz_all
    for domain, domain_kws in [
        ("算力芯片", ['芯片', '算力', 'GPU', '英伟达', 'NVIDIA', '半导体', '晶圆']),
        ("AI应用", ['应用', '落地', '场景', '大模型', 'AI']),
        ("跨境电商", ['跨境', '出海', '海外', '电商', '外贸']),
    ]:
        domain_items = [n for n in all_news if any(kw in n['title'] for kw in domain_kws)]
        if domain_items:
            top = domain_items[0]
            sections.append(f"- **{domain}**：{top['title']}")
        else:
            sections.append(f"- **{domain}**：暂无明显缺口信号")

    sections.append("\n### 动态缺口\n")
    gap_keywords = ['缺口', '机会', '蓝海', '空白', '新兴', '下沉', '出海', '信息差', '降维']
    gap_items = [n for n in all_news if any(kw in n['title'] for kw in gap_keywords)]
    for n in gap_items[:3]:
        sections.append(f"- {n['title']}")
    if not gap_items:
        sections.append("- 今日暂无动态缺口信号")

    # 5. 逆潮观察
    sections.append("\n## 三、逆潮观察\n")
    contra_keywords = ['裁员', '关停', '下滑', '暴跌', '亏损', '倒闭', '退市', '逆势']
    contra_items = [n for n in all_news if any(kw in n['title'] for kw in contra_keywords)]
    for n in contra_items[:3]:
        sections.append(f"- {n['title']}")
    if not contra_items:
        sections.append("- 今日暂无明显逆潮信号")

    # 6. 用混元API做深度分析（基于真实新闻素材）
    news_digest = "\n".join(sections)
    if not news_digest.strip() or len(news_digest) < 50:
        logging.warning("[新闻] 新闻素材过少，跳过深度分析")
        return "\n".join(sections)

    analysis_prompt = f"""基于以下今日真实新闻摘要，请补充深度分析：

{news_digest}

请补充：
1. 新闻推演：选2条最重要的新闻，做5层传导分析+天之道（损有余补不足）解读
2. 创业机会：基于上述缺口，推荐3个创业方向（含成本/风险/回报/退出路径）

直接输出markdown，从"## 四、深度分析"开始。"""

    api_key = "[HUNYUAN_API_KEY]"
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [{"role": "user", "content": analysis_prompt}],
        "max_tokens": 3000,
        "temperature": 0.7,
    }

    try:
        logging.info("[新闻] 基于真实新闻调用混元做深度分析...")
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        if resp.status_code == 200:
            result = resp.json()
            analysis = result['choices'][0]['message']['content']
            logging.info(f"[新闻] ✅ 深度分析生成成功: {len(analysis)}字符")
            sections.append("\n" + analysis)
        else:
            logging.warning(f"[新闻] 混元API失败: {resp.status_code}")
            sections.append("\n## 四、深度分析\n（今日AI分析生成失败）\n")
    except Exception as e:
        logging.warning(f"[新闻] 混元API超时: {e}")
        sections.append("\n## 四、深度分析\n（今日AI分析生成失败）\n")

    content = "\n".join(sections)
    logging.info(f"[新闻] ✅ 日报新闻部分完成: {len(content)}字符")
    return content


def generate_lottery_section():
    """生成彩票部分：今日推荐 + 昨日回测 + 虚拟下注记录"""
    try:
        import lottery_analyzer as la
        import games.ssq
        import games.dlt
        import games.qxc
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐生成失败: {e}\n---\n"

    # 🔴 闭环1: 外层变量收集推荐结果（供虚拟下注+推荐记录使用）
    ssq_recs = None
    dlt_recs = None
    qxc_recs = None

    # 🔴 v3.0: 先跑Orchestrator（大脑），产出context供推荐使用
    try:
        from algo_orchestrator import AlgoOrchestrator
        orch = AlgoOrchestrator()
        context = orch.daily_run()
        print(f"[日报] ✅ Orchestrator运行完成: 模式={context.get('mode')}, 熵比={context.get('entropy_ratio', 0):.4f}")
    except Exception as e:
        print(f"[日报] ⚠️ Orchestrator运行失败(不影响推荐): {e}")

    section = "\n---\n\n## 🎰 彩票号码推荐 — 刘海蟾点金（仅供娱乐参考）\n\n"
    section += "> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n\n"

    yesterday_weekday = yesterday.weekday()  # 0=周一 1=周二...
    today_weekday = today.weekday()

    # 双色球
    try:
        ssq_data = games.ssq.fetch_ssq_history(15)
        section += "### 🔴 双色球\n\n"
        section += "| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
        for d in ssq_data[:3]:
            reds = d.get('reds', [])
            blue = d.get('blue', 0)
            section += f"| {d.get('period')} | {' '.join(map(str, reds))} | {blue:02d} |\n"

        # 今日推荐（所有彩种每天都生成）
        try:
            analysis = games.ssq.analyze_ssq(ssq_data)
            recs = games.ssq.generate_recs_ssq(analysis)
            ssq_recs = recs
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                rec_reds = rec.get('reds', [])
                rec_blue = rec.get('blue', 0)
                section += f"  - {rec.get('strategy', '未知')}: 红={rec_reds} 蓝={rec_blue:02d}\n"
        except Exception as e:
            section += f"\n(推荐生成失败: {e})\n"

        # 回测
        if yesterday_weekday in [1, 3, 6]:
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 双色球\n"
            if ssq_data:
                latest = ssq_data[0]
                section += f"第{latest.get('period')}期: 红={latest.get('reds')} 蓝={latest.get('blue')}\n"
                try:
                    predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
                    with open(predictions_path, 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            ssq_recs = item.get('ssq_recs', [])
                            if ssq_recs:
                                section += f"\n刘海蟾推荐({len(ssq_recs)}注):\n"
                                for rec in ssq_recs:
                                    rec_reds = rec.get('reds', [])
                                    rec_blue = rec.get('blue', 0)
                                    hit_reds = set(rec_reds) & set(latest.get('reds', []))
                                    hit_blue = rec_blue == latest.get('blue', 0)
                                    section += f"  - {rec.get('strategy', '未知')}: 红={rec_reds} 蓝={rec_blue:02d} "
                                    if hit_reds:
                                        section += f"✅ 中{list(hit_reds)}"
                                    if hit_blue:
                                        section += f" ✅ 中蓝"
                                    section += "\n"
                                section += f"\n💰 回测完成\n"
                            break
                except Exception as e:
                    section += f"\n(未找到昨日推荐记录: {e})\n"
        section += "\n"
    except Exception as e:
        section += f"[双色球] 错误: {e}\n\n"

    # 大乐透
    try:
        dlt_data = games.dlt.fetch_dlt_history(15)
        section += "### 🟡 大乐透\n\n"
        section += "| 期号 | 前区 | 后区 |\n|------|------|------|\n"
        for d in dlt_data[:3]:
            front = d.get('front', [])
            back = d.get('back', [])
            section += f"| {d.get('period')} | {' '.join(map(str, front))} | {' '.join(map(str, back))} |\n"

        try:
            analysis = games.dlt.analyze_dlt(dlt_data)
            recs = games.dlt.generate_recs_dlt(analysis)
            dlt_recs = recs
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                rec_front = rec.get('front', [])
                rec_back = rec.get('back', [])
                section += f"  - {rec.get('strategy', '未知')}: 前={rec_front} 后={rec_back}\n"
        except Exception as e:
            section += f"\n(推荐生成失败: {e})\n"

        if yesterday_weekday in [0, 2, 5]:
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 大乐透\n"
            if dlt_data:
                latest = dlt_data[0]
                section += f"第{latest.get('period')}期: 前={latest.get('front')} 后={latest.get('back')}\n"
                try:
                    predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
                    with open(predictions_path, 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            dlt_recs = item.get('dlt_recs', [])
                            if dlt_recs:
                                section += f"\n刘海蟾推荐({len(dlt_recs)}注):\n"
                                for rec in dlt_recs:
                                    rec_front = rec.get('front', [])
                                    rec_back = rec.get('back', [])
                                    hit_front = set(rec_front) & set(latest.get('front', []))
                                    hit_back = set(rec_back) & set(latest.get('back', []))
                                    section += f"  - {rec.get('strategy', '未知')}: 前={rec_front} 后={rec_back} "
                                    if hit_front:
                                        section += f"✅ 中{list(hit_front)}"
                                    if hit_back:
                                        section += f" ✅ 中{list(hit_back)}"
                                    section += "\n"
                                section += f"\n💰 回测完成\n"
                            break
                except Exception as e:
                    section += f"\n(未找到昨日推荐记录: {e})\n"
        section += "\n"
    except Exception as e:
        section += f"[大乐透] 错误: {e}\n\n"

    # 七星彩
    try:
        qxc_data = games.qxc.fetch_qxc_history(15)
        section += "### 🟢 七星彩\n\n"
        section += "| 期号 | 号码 |\n|------|------|\n"
        for d in qxc_data[:3]:
            digits = d.get('digits', d.get('numbers', []))
            section += f"| {d.get('period')} | {' '.join(map(str, digits))} |\n"

        try:
            analysis = games.qxc.analyze_qxc(qxc_data)
            recs = games.qxc.generate_recs_qxc(analysis)
            qxc_recs = recs
            if qxc_data:
                latest = qxc_data[0]
                latest_digits = latest.get('digits', latest.get('numbers', []))
                for rec in recs:
                    rec_digits = rec.get('digits', [])
                    if rec_digits and latest_digits:
                        same_count = sum(1 for a, b in zip(rec_digits, latest_digits) if a == b)
                        if same_count >= 6:
                            for _ in range(min(2, len(rec_digits)-1)):
                                pos = random.randint(0, 5)
                                old_val = rec_digits[pos]
                                new_val = (old_val + random.randint(1, 5)) % 10
                                rec_digits[pos] = new_val
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                section += f"  - {rec.get('strategy', '未知')}: 号码={rec.get('digits', [])}\n"
        except Exception as e:
            section += f"\n(推荐生成失败: {e})\n"

        if yesterday_weekday in [1, 4, 6]:
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 七星彩\n"
            if qxc_data:
                latest = qxc_data[0]
                section += f"第{latest.get('period')}期: 号码={latest.get('digits', latest.get('numbers'))}\n"
                try:
                    predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
                    with open(predictions_path, 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            qxc_recs = item.get('qxc_recs', [])
                            if qxc_recs:
                                section += f"\n刘海蟾推荐({len(qxc_recs)}注):\n"
                                for rec in qxc_recs:
                                    rec_digits = rec.get('digits', rec.get('numbers', []))
                                    latest_d = latest.get('digits', latest.get('numbers', []))
                                    hit_count = sum(1 for i in range(min(len(rec_digits), len(latest_d))) if i < len(rec_digits) and i < len(latest_d) and rec_digits[i] == latest_d[i])
                                    section += f"  - {rec.get('strategy', '未知')}: 号码={rec_digits} "
                                    if hit_count > 0:
                                        section += f"✅ 中{hit_count}位"
                                    section += "\n"
                                section += f"\n💰 回测完成\n"
                            break
                except Exception as e:
                    section += f"\n(未找到昨日推荐记录: {e})\n"
        section += "\n"
    except Exception as e:
        section += f"[七星彩] 错误: {e}\n\n"

    # 🔴 闭环1: 虚拟下注
    try:
        from algo_module import AlgoDB, ROITracker
        tracker = ROITracker(AlgoDB())
        kelly_map = {'ssq': 0, 'dlt': 0, 'qxc': 0}
        if ssq_recs:
            tracker.record_bets(today_str, 'ssq', ssq_recs, kelly_map)
            logging.info(f"[彩票] ✅ SSQ虚拟下注记录: {len(ssq_recs)}注")
        if dlt_recs:
            tracker.record_bets(today_str, 'dlt', dlt_recs, kelly_map)
            logging.info(f"[彩票] ✅ DLT虚拟下注记录: {len(dlt_recs)}注")
        if qxc_recs:
            tracker.record_bets(today_str, 'qxc', qxc_recs, kelly_map)
            logging.info(f"[彩票] ✅ QXC虚拟下注记录: {len(qxc_recs)}注")
    except Exception as e:
        logging.warning(f"[彩票] 虚拟下注记录失败: {e}")

    # 🔴 闭环4: 保存今日推荐
    try:
        predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
        predictions = []
        if os.path.exists(predictions_path):
            with open(predictions_path, 'r', encoding='utf-8') as f:
                predictions = json.load(f)
        predictions = [p for p in predictions if p.get('date') != today_str]
        today_prediction = {
            'date': today_str,
            'ssq_recs': ssq_recs,
            'dlt_recs': dlt_recs,
            'qxc_recs': qxc_recs,
        }
        predictions.append(today_prediction)
        with open(predictions_path, 'w', encoding='utf-8') as f:
            json.dump(predictions, f, ensure_ascii=False, indent=2)
        logging.info(f"[彩票] ✅ 今日推荐已保存(供明日回测)")
    except Exception as e:
        logging.warning(f"[彩票] 保存推荐记录失败: {e}")

    return section


if __name__ == '__main__':
    logging.info(f"========== 生成完整日报 {today_str} ==========")

    # 1. 生成新闻分析部分
    news_content = generate_news_section()

    # 2. 生成彩票部分
    lottery_content = generate_lottery_section()

    # 3. 拼接完整日报
    full_content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}"

    # 4. 写文件
    output_path = os.path.join(output_dir, f"{today_str}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    logging.info(f"✅ 已写入: {output_path} ({len(full_content)}字符)")

    # 5. 发邮件
    subject = '阿算帮刘老板发财日报 | ' + today_str
    send_email(subject, full_content)
    logging.info(f"========== 完成 {today_str} ==========")
