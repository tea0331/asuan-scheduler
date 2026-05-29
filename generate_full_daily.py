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
    # ===== 民生/接地气（核心关注，权重最高）=====
    '房价': 4, '房贷': 4, '楼市': 3, '公积金': 3, '限购': 3,
    '就业': 4, '招聘': 3, '裁员': 3, '涨薪': 3, '社保': 3, '医保': 3, '退休': 3,
    '物价': 4, '通胀': 3, '涨价新': 3, '降价': 3, '补贴': 3, '消费券': 3,
    '教育': 3, '高考': 3, '考研': 2, '学区': 3, '双减': 2,
    '新规': 3, '政策': 3, '改革': 2, '免税': 3, '减税': 3,
    '养老': 3, '生育': 3, '三胎': 2, '育儿': 2,
    # ===== 赚钱/副业/搞钱（普通人最关心）=====
    '副业': 4, '兼职': 3, '搞钱': 3, '赚钱': 3, '省钱': 3,
    '创业': 3, '融资': 2, '上市': 2, '投资': 2, '营收': 2,
    '蓝海': 3, '出海': 3, '跨境': 3, '信息差': 3, '供需': 2,
    # ===== 科技/AI（保留但降低权重，面向普通人）=====
    'AI': 2, '人工智能': 2, '大模型': 2, 'DeepSeek': 2,
    '芯片': 2, '算力': 2, '英伟达': 1, 'NVIDIA': 1,
    '手机': 2, '华为': 2, '小米': 2, '苹果': 2,
    '新能源': 2, '电动车': 3, '充电桩': 2, '电池': 2,
    # ===== 消费/生活（普通人日常）=====
    '汽车': 2, '油价': 3, '油价调整': 3,
    '旅游': 2, '机票': 2, '酒店': 2,
    '食品': 2, '外卖': 2, '电商': 2,
    '保险': 2, '理财': 2, '存款': 3, '利率': 3,
    '装修': 1, '家电': 1, '家具': 1,
    # ===== 市场异动 =====
    '暴跌': 2, '亏损': 2, '关停': 2, '逆势': 2,
    # ---- 负面：不感兴趣 ----
    '明星': -3, '综艺': -3, '恋情': -3, '离婚': -3, '出轨': -3,
    '八卦': -4, '饭圈': -4, '偶像': -3, '选秀': -3, '粉丝': -2,
    '娱乐圈': -4, '网红': -2, '直播带货': -1,
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
    prompt = f"""你是刘海蟾点金的日报编辑，为一位关心钱袋子的普通人写日报。

## 读者画像
- 身份：普通打工人/小老板，关心怎么省钱、怎么搞钱、政策对自己有什么影响
- 最关心：房价/就业/物价/社保/副业/省钱攻略/政策变化对钱包的影响
- 也关注：AI怎么改变工作、新能源车值不值得买、什么行业在招人
- 不关心：娱乐圈八卦、体育赛事、明星绯闻
- 语言风格：说人话，不用术语，让大妈都能看懂。不要"赋能""抓手""闭环"这种词

## 今日原始新闻素材（已按画像打分排序）
{material}

## 输出要求
直接输出markdown，包含四大板块（从"## 一、每日资讯"开始），格式如下：

## 一、每日资讯
分3个小节，每个小节3-4条新闻：
### 🏠 民生/政策（房价/就业/社保/新规/补贴——跟钱袋子直接相关的）
### 💡 科技/产业（AI/新能源/手机/汽车——跟生活和工作相关的）
### 🔥 热搜/时事（今日大家都在聊什么）

每条新闻格式：
- **标题**（提炼核心，不要照搬原标题，让人一看就知道跟自己有什么关系）
  > 一句话点评：这条新闻对你有什么影响？能省钱？能赚钱？还是得避坑？

## 二、搞钱雷达
扫出2-3个普通人能抓住的机会，每个含：
- **机会名称**
- 具体是什么：用大白话说清楚
- 怎么入手：给一个普通人今天就能开始的第一步
- 投入（时间/金钱）| 风险（低/中/高）| 预期回报

如果没有好机会就说"今天没发现靠谱机会"，别硬编。

## 三、避坑提醒
找出1-3个表面光鲜但暗藏风险的信号，每个含：
- 现象：什么看起来很好
- 真相：为什么可能是坑
- 怎么办：普通人该怎么保护自己

如果没有明显风险信号就说"今天暂无明显风险预警"。

## 四、深度分析
选1条今天最重要的新闻，用大白话讲清楚：
- 发生了什么（一句话）
- 对你有什么影响（省钱/花钱/赚钱/就业/房价）
- 接下来会怎么发展（3-6个月内）
- 你现在该做什么（具体行动，别写"持续关注"这种废话）

重要规则：
1. 必须基于今日具体新闻，不要空谈
2. 说人话！不要"值得关注""需警惕""赋能""生态"等套话
3. 每条分析必须回答"跟我有什么关系"
4. 没有好机会就直说，不要硬编"""

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

    # 民生/政策：优先匹配民生关键词
    minsheng_keywords = ['房价', '房贷', '就业', '社保', '医保', '物价', '补贴', '新规', '政策', '利率', '存款', '退休', '教育', '高考', '养老', '油价']
    minsheng_items = [n for n in all_items if any(kw in n['title'] for kw in minsheng_keywords)]
    if not minsheng_items:
        minsheng_items = all_items[:4]
    used_titles = set(n['title'][:30] for n in minsheng_items)

    sections.append("### 🏠 民生/政策\n")
    for n in minsheng_items[:4]:
        sections.append(f"- **{n['title']}**")

    # 科技/产业：排除已用的
    tech_items = [n for n in all_items if n['title'][:30] not in used_titles]
    sections.append("\n### 💡 科技/产业\n")
    for n in tech_items[:4]:
        sections.append(f"- **{n['title']}**")

    sections.append("\n### 🔥 热搜/时事\n")
    for n in hot_filtered[:5]:
        sections.append(f"- {n['title']}")

    sections.append("\n## 二、搞钱雷达\n（AI分析生成失败，今日暂无搞钱机会分析）\n")
    sections.append("\n## 三、避坑提醒\n（AI分析生成失败，今日暂无风险预警）\n")
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

    # 开奖日历（周几开什么奖）
    ssq_days = {1, 3, 6}   # 二四日
    dlt_days = {0, 2, 5}   # 一三五
    qxc_days = {1, 4, 6}   # 二五日

    # ===== 辅助：从algo_bets读取昨日推荐记录 =====
    def _read_yesterday_recs(game):
        """从lottery-predictions.json或algo_bets读取昨日推荐"""
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        recs = []
        # 优先从predictions文件读
        try:
            predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
            if os.path.exists(predictions_path):
                with open(predictions_path, 'r', encoding='utf-8') as f:
                    predictions = json.load(f)
                for item in predictions:
                    if item.get('date') == yesterday_str:
                        recs = item.get(f'{game}_recs', [])
                        break
        except Exception:
            pass
        # fallback从algo_bets读
        if not recs:
            try:
                from algo_module import AlgoDB
                _db = AlgoDB()
                _conn = _db._get_conn()
                rows = _conn.execute(
                    "SELECT rec_data FROM algo_bets WHERE date=? AND game=?",
                    (yesterday_str, game)
                ).fetchall()
                _conn.close()
                for row in rows:
                    try:
                        data = json.loads(row['rec_data']) if isinstance(row['rec_data'], str) else row['rec_data']
                        if data:
                            recs.append(data)
                    except Exception:
                        pass
            except Exception:
                pass
        return recs

    # ===== 双色球 =====
    try:
        ssq_data = jz._fetch_history('ssq')
        section += "### 🔴 双色球\n\n"

        # 最近开奖
        section += "**最近开奖**:\n\n"
        section += "| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
        for d in ssq_data[:3]:
            reds = d.get('reds', [])
            blue = d.get('blue', 0)
            section += f"| {d.get('period')} | {' '.join(map(str, reds))} | {blue:02d} |\n"

        # 今日推荐
        ssq_recs = daily_result.get('ssq', [])
        if not ssq_recs:
            ssq_recs = jz.generate_recs('ssq')
        if ssq_recs:
            section += f"\n**今日推荐({len(ssq_recs)}注)**:\n"
            for rec in ssq_recs:
                rec_reds = rec.get('reds', [])
                rec_blue = rec.get('blue', 0)
                section += f"  - {rec.get('strategy', '未知')}: 红={' '.join(f'{x:02d}' for x in rec_reds)} + 蓝={rec_blue:02d}\n"

        # 回测（昨日有开奖时展示）
        if yesterday_weekday in ssq_days and ssq_data:
            latest = ssq_data[0]
            section += f"\n**昨日开奖回测** (第{latest.get('period')}期):\n"
            section += f"开奖号码: 红={' '.join(f'{x:02d}' for x in latest.get('reds', []))} + 蓝={latest.get('blue', 0):02d}\n"
            y_recs = _read_yesterday_recs('ssq')
            if y_recs:
                section += f"\n刘海蟾昨日推荐({len(y_recs)}注):\n"
                for rec in y_recs:
                    rec_reds = rec.get('reds', [])
                    rec_blue = rec.get('blue', 0)
                    hit_reds = set(rec_reds) & set(latest.get('reds', []))
                    hit_blue = rec_blue == latest.get('blue', 0)
                    hit_count = len(hit_reds) + (1 if hit_blue else 0)
                    section += f"  - {rec.get('strategy', '未知')}: 红={' '.join(f'{x:02d}' for x in rec_reds)} + 蓝={rec_blue:02d} "
                    if hit_count > 0:
                        section += f"→ 中{len(hit_reds)}红"
                        if hit_blue:
                            section += "+1蓝"
                        section += f"({hit_count}码)"
                    else:
                        section += "→ 未中"
                    section += "\n"
            else:
                section += "\n（昨日推荐记录暂未同步，回测数据下期补全）\n"
        section += "\n"
    except Exception as e:
        section += f"[双色球] 错误: {e}\n\n"

    # ===== 大乐透 =====
    try:
        dlt_data = jz._fetch_history('dlt')
        section += "### 🟡 大乐透\n\n"

        section += "**最近开奖**:\n\n"
        section += "| 期号 | 前区 | 后区 |\n|------|------|------|\n"
        for d in dlt_data[:3]:
            front = d.get('front', [])
            back = d.get('back', [])
            section += f"| {d.get('period')} | {' '.join(f'{x:02d}' for x in front)} | {' '.join(f'{x:02d}' for x in back)} |\n"

        dlt_recs = daily_result.get('dlt', [])
        if not dlt_recs:
            dlt_recs = jz.generate_recs('dlt')
        if dlt_recs:
            section += f"\n**今日推荐({len(dlt_recs)}注)**:\n"
            for rec in dlt_recs:
                rec_front = rec.get('front', [])
                rec_back = rec.get('back', [])
                section += f"  - {rec.get('strategy', '未知')}: 前={' '.join(f'{x:02d}' for x in rec_front)} + 后={' '.join(f'{x:02d}' for x in rec_back)}\n"

        if yesterday_weekday in dlt_days and dlt_data:
            latest = dlt_data[0]
            section += f"\n**昨日开奖回测** (第{latest.get('period')}期):\n"
            section += f"开奖号码: 前={' '.join(f'{x:02d}' for x in latest.get('front', []))} + 后={' '.join(f'{x:02d}' for x in latest.get('back', []))}\n"
            y_recs = _read_yesterday_recs('dlt')
            if y_recs:
                section += f"\n刘海蟾昨日推荐({len(y_recs)}注):\n"
                for rec in y_recs:
                    rec_front = rec.get('front', [])
                    rec_back = rec.get('back', [])
                    hit_front = set(rec_front) & set(latest.get('front', []))
                    hit_back = set(rec_back) & set(latest.get('back', []))
                    hit_count = len(hit_front) + len(hit_back)
                    section += f"  - {rec.get('strategy', '未知')}: 前={' '.join(f'{x:02d}' for x in rec_front)} + 后={' '.join(f'{x:02d}' for x in rec_back)} "
                    if hit_count > 0:
                        section += f"→ 中{len(hit_front)}前+{len(hit_back)}后({hit_count}码)"
                    else:
                        section += "→ 未中"
                    section += "\n"
            else:
                section += "\n（昨日推荐记录暂未同步，回测数据下期补全）\n"
        section += "\n"
    except Exception as e:
        section += f"[大乐透] 错误: {e}\n\n"

    # ===== 七星彩 =====
    try:
        qxc_data = jz._fetch_history('qxc')
        section += "### 🟢 七星彩\n\n"

        section += "**最近开奖**:\n\n"
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
                section += f"  - {rec.get('strategy', '未知')}: 号码={' '.join(map(str, rec.get('digits', [])))}\n"

        if yesterday_weekday in qxc_days and qxc_data:
            latest = qxc_data[0]
            latest_digits = latest.get('digits', latest.get('numbers', []))
            section += f"\n**昨日开奖回测** (第{latest.get('period')}期):\n"
            section += f"开奖号码: {' '.join(map(str, latest_digits))}\n"
            y_recs = _read_yesterday_recs('qxc')
            if y_recs:
                section += f"\n刘海蟾昨日推荐({len(y_recs)}注):\n"
                for rec in y_recs:
                    rec_digits = rec.get('digits', rec.get('numbers', []))
                    hit_count = sum(1 for i in range(min(len(rec_digits), len(latest_digits))) if rec_digits[i] == latest_digits[i])
                    section += f"  - {rec.get('strategy', '未知')}: 号码={' '.join(map(str, rec_digits))} "
                    if hit_count > 0:
                        section += f"→ 中{hit_count}位"
                    else:
                        section += "→ 未中"
                    section += "\n"
            else:
                section += "\n（昨日推荐记录暂未同步，回测数据下期补全）\n"
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
