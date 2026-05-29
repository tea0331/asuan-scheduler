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

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.163.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USER = os.getenv('SMTP_USER', 'tea0331@163.com')
SMTP_PASS = os.getenv('SMTP_PASSWORD', os.getenv('SMTP_PASS', ''))
SMTP_TO = os.getenv('SMTP_TO', 'tea0331@163.com')

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
    if not SMTP_PASS:
        logging.warning("[邮件] SMTP密码未配置，跳过发送")
        return False
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
    """基于RSS+热搜抓取原始素材，统一由AI生成高质量分析型日报
    
    v3: 不再手动拼接标题+摘要，而是把原始素材喂给AI，
    让AI按用户画像(算力/AI/创业/信息差)和分析框架输出四大板块。
    """
    logging.info("[新闻] 开始抓取真实新闻(RSS+热搜)...")

    # 数据源
    KR36_RSS = 'https://36kr.com/feed'
    ITHOME_RSS = 'https://www.ithome.com/rss/'

    # ---- 抓取原始数据 ----
    ithome_raw = _fetch_rss(ITHOME_RSS, 15)
    kr36_raw = _fetch_rss(KR36_RSS, 20)
    hot_raw = _fetch_baidu_hot(20)

    total_raw = len(ithome_raw) + len(kr36_raw) + len(hot_raw)
    logging.info(f"[新闻] 抓取原始素材{total_raw}条(36氪{len(kr36_raw)}+IT之家{len(ithome_raw)}+热搜{len(hot_raw)})")

    # ---- 画像过滤 + 去重 ----
    all_filtered = filter_by_profile(ithome_raw + kr36_raw + hot_raw, min_score=-1, top_n=30)
    # 按标题去重
    seen_titles = set()
    unique = []
    for n in all_filtered:
        t = n['title'].strip()[:30]
        if t not in seen_titles:
            seen_titles.add(t)
            unique.append(n)

    # 构建素材文本（喂给AI）
    material_lines = []
    for i, n in enumerate(unique[:25], 1):
        score = score_news(n)
        title = n['title'].strip()
        summary = n.get('summary', '').strip()[:150]
        line = f"{i}. [{score}分] {title}"
        if summary:
            line += f"\n   摘要：{summary}"
        material_lines.append(line)

    material = "\n".join(material_lines)

    if not material.strip() or len(material) < 100:
        logging.warning("[新闻] 新闻素材过少，跳过AI生成")
        return _fallback_news_section(ithome_raw, kr36_raw, hot_raw)

    # ---- AI生成四大板块 ----
    prompt = f"""你是刘海蟾点金的商业分析师，为一位专注算力/AI/创业的投资人写日报。

## 用户画像
- 核心关注：算力芯片、英伟达产业链、AI大模型、创业投资
- 商业偏好：供需错配、政策红利、技术降维、跨境信息差、蓝海机会
- 不关心：娱乐圈八卦、体育赛事、明星绯闻
- 分析框架：天之道损有余补不足（关注"不足"=缺口=机会）

## 今日原始新闻素材（已按画像打分排序）
{material}

## 输出要求
直接输出markdown，包含四大板块（从"## 一、每日资讯"开始），格式如下：

## 一、每日资讯
分3个小节，每个小节3-4条新闻：
### 🤖 AI/科技
### 💰 商业/金融  
### 🔥 热搜/时事

每条新闻格式：
- 🔥**标题**（提炼核心，不要照搬原标题）
  > 一句话精华点评（不是摘要，是你对这条新闻的价值判断）

## 二、市场缺口扫描
### 固定领域缺口
- **算力芯片**：有缺口时写缺口描述+机会，无则写"供给平稳，暂无缺口"
- **AI应用**：同上
- **跨境电商**：同上

### 动态缺口
从新闻中挖掘2-3个隐藏的供需错配、政策红利或技术降维机会。
不要用"暂无明显"这种废话，每条必须有具体分析。

## 三、逆潮观察
找出1-3个"反直觉信号"——表面利空但暗藏机会，或表面利好但隐含风险。
每条包含：现象 + 逆潮逻辑 + 行动建议。
不要输出万能废话（如"需警惕产能过剩"），必须结合今日具体新闻。

## 四、深度分析
### 新闻推演
选2条最重要新闻，做5层传导分析 + 天之道解读：
- 第1层：事件本身
- 第2层：直接影响  
- 第3层：市场反应
- 第4层：中期演变(3-6个月)
- 第5层：长期格局(1-2年)
- 天之道：损什么(有余)？补什么(不足)？

### 创业机会
基于上述缺口，推荐3个创业方向，每个含：
- 方向名称 + 一句话描述
- 成本 | 风险(低/中/高) | 回报倍数 | 退出路径

重要规则：
1. 每条分析必须基于今日具体新闻，不要空谈
2. 缺口和逆潮必须有数据或事件支撑
3. 语言简洁有力，不要车轱辘话
4. 不要用"值得关注""需警惕"等套话"""

    api_key = "[HUNYUAN_API_KEY]"
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
        "temperature": 0.7,
    }

    try:
        logging.info("[新闻] 调用混元生成四大板块日报...")
        # 最多重试2次，间隔5秒
        content = None
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=90)
                if resp.status_code == 200:
                    result = resp.json()
                    content = result['choices'][0]['message']['content']
                    break
                elif resp.status_code == 429:
                    logging.warning(f"[新闻] 混元API限流(尝试{attempt+1}/3)，等待5秒...")
                    import time; time.sleep(5)
                else:
                    logging.warning(f"[新闻] 混元API失败: {resp.status_code}")
                    break
            except requests.exceptions.Timeout:
                logging.warning(f"[新闻] 混元API超时(尝试{attempt+1}/3)")
                if attempt < 2:
                    import time; time.sleep(3)

        if content:
            # 清理可能的markdown代码块包裹
            content = content.strip()
            if content.startswith('```markdown'):
                content = content[len('```markdown'):]
            if content.startswith('```'):
                content = content[len('```'):]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()
            logging.info(f"[新闻] ✅ AI日报生成成功: {len(content)}字符")
            return content
        else:
            logging.warning("[新闻] AI日报生成失败，使用降级模式")
            return _fallback_news_section(ithome_raw, kr36_raw, hot_raw)
    except Exception as e:
        logging.warning(f"[新闻] 混元API异常: {e}")
        return _fallback_news_section(ithome_raw, kr36_raw, hot_raw)


def _fallback_news_section(ithome_raw, kr36_raw, hot_raw):
    """API失败时的降级方案：用画像过滤的原始标题兜底"""
    logging.info("[新闻] 降级模式：用画像过滤原始标题")
    sections = ["## 一、每日资讯\n"]

    all_items = filter_by_profile(ithome_raw + kr36_raw, min_score=0, top_n=15)
    hot_filtered = filter_by_profile(hot_raw, min_score=-1, top_n=5)

    # AI/科技：优先匹配AI关键词
    ai_keywords = ['AI', '人工智能', '芯片', '模型', '大模型', '英伟达', '华为', '算力', 'DeepSeek', 'GPT', 'NVIDIA', 'GPU', '机器人']
    ai_items = [n for n in all_items if any(kw.lower() in n['title'].lower() for kw in ai_keywords)]
    if not ai_items:
        ai_items = all_items[:4]
    used_titles = set(n['title'][:30] for n in ai_items)

    sections.append("### 🤖 AI/科技\n")
    for n in ai_items[:4]:
        sections.append(f"- **{n['title']}**")

    # 商业/金融：排除已用的
    biz_items = [n for n in all_items if n['title'][:30] not in used_titles]
    sections.append("\n### 💰 商业/金融\n")
    for n in biz_items[:4]:
        sections.append(f"- **{n['title']}**")

    sections.append("\n### 🔥 热搜/时事\n")
    for n in hot_filtered[:5]:
        sections.append(f"- {n['title']}")

    sections.append("\n## 二、市场缺口扫描\n（AI分析生成失败，今日暂无缺口分析）\n")
    sections.append("\n## 三、逆潮观察\n（AI分析生成失败，今日暂无逆潮分析）\n")
    sections.append("\n## 四、深度分析\n（今日AI分析生成失败，下次自动恢复）\n")

    return "\n".join(sections)


def generate_lottery_section():
    """生成彩票部分：今日推荐 + 昨日回测（统一走 JinZhu 核心大脑）"""
    global yesterday, today
    try:
        from jin_zhu import JinZhu
        jz = JinZhu()
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐生成失败: JinZhu初始化异常({e})\n---\n"

    # 🔴 v4.0-JinZhu: 核心大脑统一生成推荐
    try:
        daily_result = jz.daily_run()
        logging.info(f"[日报] ✅ JinZhu闭环完成: settle={bool(daily_result.get('settle'))}, evolve={bool(daily_result.get('evolve'))}")
    except Exception as e:
        logging.warning(f"[日报] ⚠️ JinZhu闭环异常(不阻塞): {e}")
        daily_result = {}

    section = "\n---\n\n## 🎰 彩票号码推荐 — 刘海蟾点金·金主引擎（仅供娱乐参考）\n\n"
    section += "> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n\n"

    yesterday_weekday = yesterday.weekday()
    today_weekday = today.weekday()

    # ===== 双色球 =====
    try:
        ssq_data = jz._fetch_history('ssq')
        section += "### 🔴 双色球\n\n"
        section += "| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
        for d in ssq_data[:3]:
            reds = d.get('reds', [])
            blue = d.get('blue', 0)
            section += f"| {d.get('period')} | {' '.join(map(str, reds))} | {blue:02d} |\n"

        # 从 JinZhu 结果取推荐
        ssq_recs = daily_result.get('ssq', [])
        if not ssq_recs:
            ssq_recs = jz.generate_recs('ssq')
        if ssq_recs:
            section += f"\n**今日推荐({len(ssq_recs)}注)**:\n"
            for rec in ssq_recs:
                rec_reds = rec.get('reds', [])
                rec_blue = rec.get('blue', 0)
                section += f"  - {rec.get('strategy', '未知')}: 红={rec_reds} 蓝={rec_blue:02d}\n"

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
                            y_recs = item.get('ssq_recs', [])
                            if y_recs:
                                section += f"\n刘海蟾推荐({len(y_recs)}注):\n"
                                for rec in y_recs:
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

    # ===== 大乐透 =====
    try:
        dlt_data = jz._fetch_history('dlt')
        section += "### 🟡 大乐透\n\n"
        section += "| 期号 | 前区 | 后区 |\n|------|------|------|\n"
        for d in dlt_data[:3]:
            front = d.get('front', [])
            back = d.get('back', [])
            section += f"| {d.get('period')} | {' '.join(map(str, front))} | {' '.join(map(str, back))} |\n"

        dlt_recs = daily_result.get('dlt', [])
        if not dlt_recs:
            dlt_recs = jz.generate_recs('dlt')
        if dlt_recs:
            section += f"\n**今日推荐({len(dlt_recs)}注)**:\n"
            for rec in dlt_recs:
                rec_front = rec.get('front', [])
                rec_back = rec.get('back', [])
                section += f"  - {rec.get('strategy', '未知')}: 前={rec_front} 后={rec_back}\n"

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
                            y_recs = item.get('dlt_recs', [])
                            if y_recs:
                                section += f"\n刘海蟾推荐({len(y_recs)}注):\n"
                                for rec in y_recs:
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

    # ===== 七星彩 =====
    try:
        qxc_data = jz._fetch_history('qxc')
        section += "### 🟢 七星彩\n\n"
        section += "| 期号 | 号码 |\n|------|------|\n"
        for d in qxc_data[:3]:
            digits = d.get('digits', d.get('numbers', []))
            section += f"| {d.get('period')} | {' '.join(map(str, digits))} |\n"

        qxc_recs = daily_result.get('qxc', [])
        if not qxc_recs:
            qxc_recs = jz.generate_recs('qxc')
        if qxc_recs:
            section += f"\n**今日推荐({len(qxc_recs)}注)**:\n"
            for rec in qxc_recs:
                section += f"  - {rec.get('strategy', '未知')}: 号码={rec.get('digits', [])}\n"

        if yesterday_weekday in [1, 4, 6]:
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 七星彩\n"
            if qxc_data:
                latest = qxc_data[0]
                latest_digits = latest.get('digits', latest.get('numbers', []))
                section += f"第{latest.get('period')}期: 号码={latest_digits}\n"
                try:
                    predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
                    with open(predictions_path, 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            y_recs = item.get('qxc_recs', [])
                            if y_recs:
                                section += f"\n刘海蟾推荐({len(y_recs)}注):\n"
                                for rec in y_recs:
                                    rec_digits = rec.get('digits', rec.get('numbers', []))
                                    hit_count = sum(1 for i in range(min(len(rec_digits), len(latest_digits))) if i < len(rec_digits) and i < len(latest_digits) and rec_digits[i] == latest_digits[i])
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

    # JinZhu 闭环状态摘要
    settle = daily_result.get('settle', {})
    evolve = daily_result.get('evolve', {})
    
    # 从algo_settlements读取昨日结算数据（即使settle返回"无待结算"也能展示）
    settle_summary_parts = []
    yesterday = (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d')
    try:
        from algo_module import AlgoDB
        _db = AlgoDB()
        _conn = _db._get_conn()
        for g in ['ssq', 'dlt', 'qxc']:
            gname = {'ssq': '双色球', 'dlt': '大乐透', 'qxc': '七星彩'}[g]
            # 查昨日该彩种的bets
            bet_rows = _conn.execute(
                "SELECT id, cost FROM algo_bets WHERE date=? AND game=? AND status='settled'",
                (yesterday, g)
            ).fetchall()
            if not bet_rows:
                continue
            bet_ids = [r['id'] for r in bet_rows]
            total_cost = sum(r['cost'] or 2 for r in bet_rows)
            # 查settlements
            placeholders = ','.join(['?'] * len(bet_ids))
            s_rows = _conn.execute(
                f"SELECT prize_amount, prize_name FROM algo_settlements WHERE bet_id IN ({placeholders})",
                bet_ids
            ).fetchall()
            total_prize = sum(r['prize_amount'] for r in s_rows)
            wins = [r['prize_name'] for r in s_rows if r['prize_amount'] > 0]
            roi = ((total_prize - total_cost) / max(total_cost, 1)) * 100
            win_str = f"中{len(wins)}注" if wins else "未中奖"
            settle_summary_parts.append(f"{gname}: 投{total_cost}元/{win_str}/中{total_prize}元/ROI={roi:.1f}%")
        _conn.close()
    except Exception as e:
        logging.warning(f"[日报] 读取结算数据异常: {e}")
    
    section += "\n---\n**🧠 金主引擎状态**\n"
    if settle_summary_parts:
        section += "**昨日结算**: " + " | ".join(settle_summary_parts) + "\n"
    elif settle:
        games_settled = [g for g in ['ssq', 'dlt', 'qxc'] if g in settle and 'error' not in settle[g]]
        if games_settled:
            section += f"**昨日结算**: 结算{len(games_settled)}彩种\n"
        else:
            section += "**昨日结算**: 暂无\n"
    else:
        section += "**昨日结算**: 暂无\n"
    
    section += "**进化**: "
    if evolve and evolve.get('status') == '进化完成':
        section += f"进化完成({jz.model.get('algo_version', 'v?')}·第{jz.model.get('version', '?')}次进化)\n"
    elif evolve:
        section += f"进化跳过({evolve.get('status', '未知')})\n"
    else:
        section += "未执行\n"
    section += "**模型**: 参数从weight-config.json读取\n"

    return section


if __name__ == '__main__':
    logging.info(f"========== 生成完整日报 {today_str} ==========")

    # 1. 生成新闻分析部分（带异常保护）
    try:
        news_content = generate_news_section()
    except Exception as e:
        logging.error(f"[P1] 新闻生成异常: {e}")
        news_content = "## 一、每日资讯\n（今日新闻生成异常，下次自动恢复）\n"

    # 2. 生成彩票部分（带异常保护）
    try:
        lottery_content = generate_lottery_section()
    except Exception as e:
        logging.error(f"[P1] 彩票生成异常: {e}")
        lottery_content = "## 🎰 彩票推荐\n（今日彩票生成异常，下次自动恢复）\n"

    # 3. 拼接完整日报
    full_content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}"

    # 4. 写文件（确保一定写出）
    output_path = os.path.join(output_dir, f"{today_str}.md")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        logging.info(f"✅ 已写入: {output_path} ({len(full_content)}字符)")
    except Exception as e:
        logging.error(f"[P0] 写入日报文件失败: {e}")
        # 兜底：写到/tmp
        try:
            fallback_path = f"/tmp/daily-report-{today_str}.md"
            with open(fallback_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            logging.info(f"✅ 兜底写入: {fallback_path}")
        except Exception as e2:
            logging.error(f"[P0] 兜底写入也失败: {e2}")

    # 5. 发邮件（带异常保护，邮件失败不阻塞日报生成）
    if not SMTP_PASS:
        logging.warning("[P1] SMTP密码未配置(SMTP_PASSWORD/SMTP_PASS环境变量均空)，跳过邮件发送")
    else:
        try:
            subject = '阿算帮刘老板发财日报 | ' + today_str
            send_email(subject, full_content)
        except Exception as e:
            logging.error(f"[P1] 邮件发送异常: {e}")

    logging.info(f"========== 完成 {today_str} ==========")
