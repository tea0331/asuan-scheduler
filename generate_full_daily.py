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
    # ===== AI/大模型（核心关注，权重最高）=====
    'AI': 4, '人工智能': 4, '大模型': 4, 'DeepSeek': 4,
    'GPT': 3, 'Claude': 3, 'AGI': 3, 'LLM': 3, '开源模型': 3,
    'AI应用': 3, 'AI Agent': 3, '智能体': 3, '自动化': 2,
    # ===== 算力/芯片（核心产业链）=====
    '算力': 4, 'GPU': 4, '英伟达': 3, 'NVIDIA': 3, '黄仁勋': 2,
    '芯片': 3, '半导体': 3, '台积电': 3, '光刻': 2, '晶圆': 2,
    'H100': 2, 'H200': 2, 'B200': 2, 'CUDA': 2,
    # ===== 搞钱/进出口/出海（搞钱核心）=====
    '进出口': 4, '出口': 4, '进口': 3, '外贸': 4, '关税': 3,
    '出海': 4, '跨境': 4, '跨境电商': 4, '汇率': 3,
    '副业': 4, '搞钱': 3, '赚钱': 3, '信息差': 3,
    '创业': 3, '融资': 3, '上市': 2, '投资': 2, '营收': 2,
    '蓝海': 3, '供需': 3, '缺口': 3, '垄断': 2,
    '供应链': 3, '代工': 2, '贴牌': 2, 'OEM': 2,
    # ===== 新能源/电动车（产业机会）=====
    '新能源': 3, '电动车': 3, '电池': 2, '充电桩': 2,
    '光伏': 2, '储能': 2, '碳中和': 2,
    # ===== 科技/产业 =====
    '手机': 2, '华为': 2, '小米': 2, '苹果': 2,
    '机器人': 3, '无人驾驶': 2, '自动驾驶': 2,
    '5G': 2, '通信': 2, '数字化': 2,
    # ===== 政策/商业 =====
    '政策': 2, '补贴': 2, '免税': 3, '减税': 2, '新规': 2,
    '暴跌': 2, '裁员': 2, '亏损': 2, '逆势': 2, '关停': 2,
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

    # ---- AI生成六大板块 ----
    prompt = f"""你是刘海蟾点金的邪修分析师——一个敢于看透规则、利用规则、在规则缝隙中找到搞钱机会的人。

你的信条：
- 天之道损有余补不足——"不足"的地方就是钱
- 规则没说不行就是行，法律没禁止就是自由区
- 别人恐惧你贪婪，别人合规你找漏洞，别人等政策你抢窗口期
- 正道走不通走偏门，偏门走不通走邪道，邪道走不通就创造新道
- 第一批吃螃蟹的人赚最多，第一批被查的人罚最重——所以要比政策快半步，不能快一步

## 读者画像
- 身份：在AI/出海赛道找偏门搞钱的人，不是循规蹈矩的打工人
- 核心关注：AI/大模型/算力芯片、进出口/跨境电商/出海、政策灰色地带的信息差
- 投资思维：供需错配=套利空间，监管滞后=窗口期，法律空白=先发优势
- 不关心：娱乐圈八卦、体育赛事、纯消费生活类
- 语言风格：狠、准、直，不说废话，敢说别人不敢说的角度

## 今日原始新闻素材（已按画像打分排序）
{material}

## 输出要求
直接输出markdown，包含六大板块（从"## 一、每日资讯"开始），格式如下：

## 一、每日资讯
分3个小节，每个小节3-4条新闻：
### 🤖 AI/算力（大模型/芯片/英伟达/DeepSeek/AI应用）
### 🌐 出海/商业（进出口/跨境电商/关税/创业/投融资）
### 🔥 热搜/时事（今日大家都在聊什么）

每条新闻格式：
- **标题**（提炼核心，突出搞钱角度或规则漏洞）
  > 邪修点评：从偏门角度看这条新闻——哪里有信息差？哪里有监管空白？哪里有窗口期？

## 二、搞钱雷达
扫出2-3个**现在就能下手**的机会，重点找：
- 政策还没管到的灰色地带（先做=合规，后做=违规，中间=暴利）
- 监管过渡期的窗口红利（新规落地前的抢跑机会）
- 信息差套利（国内知道的人少、海外已经跑通的玩法）
- 擦边但没越线的商业模式

每个含：
- **机会名称**（名字要够野）
- 邪修逻辑：为什么这个机会现在存在（政策滞后/信息差/供需错配/监管空白）
- 怎么入手：今天就能开始的第一步
- 灰度评级：🟢合规 / 🟡擦边 / 🔴灰色（标明法律边界在哪，红线不能碰）

## 三、逆潮观察
找出1-3个"反直觉信号"，要往邪了想：
- 表面利空→实际是入场信号（恐慌=低价=机会）
- 表面利好→实际是跑路信号（监管要来了/红利见顶了）
- 大家都在做的→实际是坑（红海/内卷/即将被整）
- 没人注意的→实际是金矿（政策还没反应过来/市场还没发现）

每条包含：现象 + 邪修逻辑（为什么大众判断是错的）+ 行动建议

## 四、深度分析（5层传导 + 天之道邪修解读）
选1-2条最重要的新闻，做5层传导分析——每一层都要找搞钱角度：
- 第1层：事件本身（一句话）
- 第2层：即时冲击（谁吃亏=谁让出市场=你能填上）
- 第3层：规则变化（新规/新政策/新执法，哪里有缝隙）
- 第4层：中期演变(3-6个月)（窗口期还有多久，什么时候该跑）
- 第5层：长期格局(1-2年)（规则稳定后谁吃肉谁喝汤）
- 🔮 天之道邪修解读：
  - 损什么(有余)？——什么正在被削减、被限制、被整肃（=正规军撤退=偏门进场）
  - 补什么(不足)？——什么正在被需要、被渴求、被短缺（=需求缺口=暴利区）
  - 邪修之道：规则打压A→需求还在→转向B→B是现在的合法暴利区

## 五、避坑提醒
找出1-2个表面很野但实际是陷阱的信号：
- 看起来是灰色机会实际已经越线（别进去就出不来了）
- 窗口期已过但你不知道（别人已经在跑了）
- 监管已经盯上了只是还没动手

每个含：诱惑在哪 + 为什么是坑 + 红线在哪

## 六、今日邪修金句
用一句话总结今天的核心洞察，要有攻击性和行动力。格式：💭 一句话

重要规则：
1. 必须基于今日具体新闻，不要空谈
2. 敢说偏门角度，但必须标明法律红线——教人赚钱可以，教人犯法不行
3. 灰度评级必须诚实：🟢🟡🔴 不能把红色标成绿色
4. 没有好机会就直说"今天没发现靠谱的偏门"
5. 绝对不要用"值得关注""需警惕""赋能""生态"等正确但无用的废话"""

    api_key = "[HUNYUAN_API_KEY]"
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 6000,
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

    # AI/算力：优先匹配AI关键词
    ai_keywords = ['AI', '人工智能', '芯片', '模型', '大模型', '英伟达', '算力', 'DeepSeek', 'GPT', 'NVIDIA', 'GPU', '机器人', '智能体']
    ai_items = [n for n in all_items if any(kw.lower() in n['title'].lower() for kw in ai_keywords)]
    if not ai_items:
        ai_items = all_items[:4]
    used_titles = set(n['title'][:30] for n in ai_items)

    sections.append("### 🤖 AI/算力\n")
    for n in ai_items[:4]:
        sections.append(f"- **{n['title']}**")

    # 出海/商业：排除已用的
    biz_items = [n for n in all_items if n['title'][:30] not in used_titles]
    sections.append("\n### 🌐 出海/商业\n")
    for n in biz_items[:4]:
        sections.append(f"- **{n['title']}**")

    sections.append("\n### 🔥 热搜/时事\n")
    for n in hot_filtered[:5]:
        sections.append(f"- {n['title']}")

    sections.append("\n## 二、搞钱雷达\n（AI分析生成失败，今日暂无搞钱机会分析）\n")
    sections.append("\n## 三、逆潮观察\n（AI分析生成失败，今日暂无逆潮分析）\n")
    sections.append("\n## 四、深度分析\n（AI分析生成失败，今日暂无深度分析）\n")
    sections.append("\n## 五、避坑提醒\n（AI分析生成失败，今日暂无风险预警）\n")
    sections.append("\n## 六、今日金句\n💭 明天继续\n")

    return "\n".join(sections)


def generate_lottery_section():
    """生成彩票部分：由JinZhu核心大脑统一生成展示内容"""
    global yesterday, today
    try:
        from jin_zhu import JinZhu
        jz = JinZhu()
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐生成失败: JinZhu初始化异常({e})\n---\n"

    # v9.0-JinZhu: 核心大脑闭环+展示一体化
    try:
        daily_result = jz.daily_run()
        logging.info(f"[日报] ✅ JinZhu闭环完成: settle={bool(daily_result.get('settle'))}, evolve={bool(daily_result.get('evolve'))}")
    except Exception as e:
        logging.warning(f"[日报] ⚠️ JinZhu闭环异常(不阻塞): {e}")
        daily_result = {}

    # 由JinZhu核心大脑统一生成展示内容
    try:
        return jz.generate_daily_section(daily_result)
    except Exception as e:
        logging.error(f"[日报] ⚠️ JinZhu展示生成异常: {e}")
        return f"\n---\n## 🎰 彩票推荐\n（展示生成异常: {e}，推荐数据已正常生成）\n---\n"


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
