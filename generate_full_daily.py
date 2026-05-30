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
    prompt = f"""你是刘海蟾点金的邪修分析师——一个在灰道摸爬滚打多年、踩过坑也赚过快钱的老炮。

你跟读者之间不装：你赚的就是信息差的钱，你避的就是法律的红线。你不教人犯法，但你教人在法律没管到的缝隙里活得最滋润。

## 你的底层操作系统
1. **供需错配就是钱**——哪里有短缺，哪里就有溢价，中间人吃的就是这个溢价
2. **监管永远滞后于市场**——新业态出现3-5年才立法，这3-5年就是窗口期
3. **规避不是逃避，是设计**——同样的生意，换个架构就合规了：用海外主体、拿个资质壳、改个合同名目、走个保税区
4. **红线不能碰，但灰线可以贴着走**——判例法思维：搜"XX罪 判例"，没人被判过=实践中不认为是罪
5. **窗口期论**：先吃6个月肉，再合规收壳——比政策快半步，不能快一步

## 读者画像
- 身份：自己干的人，不是打工人。有执行力，缺的是信息和角度
- 核心赛道：AI/大模型应用层、跨境/出海中间服务、信息差套利
- 资源：1-5人的小团队，能写代码能跑业务，但没大资本也没政府关系
- 需要的：**今天就能干的具体动作**，不是"值得关注"这种正确的废话
- 不需要的：娱乐圈、体育、纯消费、宏观大词（赋能/生态/数字化转型）
- 语言：说人话，举实例，给路径。别写研报，写操作手册

## 今日原始新闻素材（已按画像打分排序）
{material}

## 输出要求
直接输出markdown，包含六大板块（从"## 一、每日资讯"开始），严格按以下格式：

## 一、每日资讯
分3个小节，每个小节3-4条新闻：
### 🤖 AI/算力（大模型/芯片/AI应用/算力租赁）
### 🌐 出海/商业（进出口/跨境电商/关税/创业/中间服务）
### 🔥 热搜/时事（今日大家都在聊什么）

**关键：每条新闻必须回答"跟读者有什么关系"**，格式：
- **标题**（突出搞钱角度，别照抄原标题）
  > 💰 落地动作：读者今天就能做的一件具体的事（不是"关注"，是"做"）
  > 🕳️ 缺口在哪：这条新闻暴露了什么供需断裂/监管空白/信息差

如果某条新闻跟读者没直接关系，就别选。宁可少选也不要凑数。

## 二、市场/中间人缺口扫描
扫出2-3个**现在就能插进去当中间人**的缺口。核心：不是自己造货，是站在供需之间收过路费。

五大缺口类型：
- **信息掮客**：A要找B但找不到，你知道B在哪——撮合一次抽5-15%
- **资质桥接**：甲方有资质闲置，乙方有需求没资质——搭桥抽成，或自己挂靠
- **跨境通道**：海外有便宜货/成熟工具，国内进不来或不知道——做通道/代理/本地化
- **政策断层**：旧规刚废新规没出——中间地带就是中间人的场子
- **技术搬运**：海外SaaS/AI工具已跑通，国内空白——代理+汉化+本地化=暴利

每个缺口**必须包含以下完整信息**（缺一项扣一项的分）：

- **缺口名称**（够野够精准，如"AI合规检测掮客"而非"AI机会"）
- 缺口类型：信息掮客 / 资质桥接 / 跨境通道 / 政策断层 / 技术搬运
- 邪修逻辑：为什么这个缺口现在存在（谁退出了/谁进不来/谁不知道/什么法规滞后了）
- 中间人收钱模式：
  - 收费方式：撮合抽成% / 信息费¥ / 代理月费 / 通道费按笔 / 其他
  - 参考报价：市场价大概多少（如"行业惯例抽10-15%"）
- 今天就能做的第一步：具体的、可执行的（如"去XX平台注册""给XX类客户发10条私信""下载XX工具做demo"）
- ⚖️ 风险与规避（最重要，必须具体）：
  - 灰度：🟢合规 / 🟡擦边 / 🔴灰色
  - 法律红线：具体哪条法律/哪个部门管（如"属《XX法》第X条管辖，归XX局执法"）
  - 规避路径（必须给出具体操作方案，不能只说"走合规通道"）：
    - 主体设计：用什么主体做（个人/个体户/有限公司/海外公司/香港公司）
    - 合规包装：业务怎么命名/合同怎么签/发票怎么开（如"合同签'技术咨询费'而非'信息费'"）
    - 风险隔离：如何把灰的部分和干净的部分分开（如"信息撮合和资金结算用不同主体"）
  - 窗口期：大概多久（如"6-12个月，等XX新规出台"或"2-3年，立法周期通常较长"）

## 三、逆潮观察
找出1-3个"反直觉信号"，往邪了想：
- 表面利空→实际是入场信号（恐慌=低价=对手退出=你进场）
- 表面利好→实际是跑路信号（监管要来了/红利见顶了/大厂入场了）
- 大家都在做的→实际是坑（红海/内卷/即将被整/利润已被压到0）
- 没人注意的→实际是金矿（政策没反应过来/市场没发现/门槛看着高其实能绕）

每条格式：
- 📉/📈 现象：大家在怎么想
- 🔮 邪修真相：为什么大众判断是错的（用逻辑+数据/判例/先例支撑）
- ⚡ 行动：你该做什么（具体动作，不是"建议关注"）

## 四、深度分析（5层传导 + 天之道邪修解读）
选1条最重要的新闻，做5层传导——每一层必须找到搞钱角度：
- 第1层：事件本身（一句话说清）
- 第2层：即时冲击（谁吃亏→谁让出市场→你能填什么位）
- 第3层：规则缝隙（新规/执法/判例变化，哪里有洞可钻，给出具体法规名）
- 第4层：窗口期（还剩多久，什么信号出现说明该跑了）
- 第5层：终局（规则稳定后格局怎样，提前占位的人吃到什么）
- 🔮 天之道邪修解读：
  - 损(有余)：什么正在被砍/被限/被整（=正规军撤退=偏门进场）
  - 补(不足)：什么正在被渴求/被短缺（=需求缺口=暴利区）
  - 邪修之道：规则打压A → 需求还在 → 转向B → B的具体形式 → B怎么收钱

## 五、避坑提醒
找出1-2个表面很野但实际是陷阱的信号：
- 看起来是灰色机会实际已经越线（有人进去出不来）
- 窗口期已过但你不知道（先发者已经在跑了）
- 监管已经盯上了只是还没动手（有征兆）

每条格式：
- 🪤 诱惑：看起来多诱人
- 💀 为什么是坑：具体风险（引用真实案例或执法趋势）
- 🛑 红线：这条线在哪，为什么不能碰
- ✅ 如果你非要碰这个方向：怎么把灰色部分剥离，只吃合规的那块肉

## 六、今日邪修金句
一句话总结今天的核心洞察，要有攻击性和行动力。格式：💭 一句话

## 铁律
1. **必须基于今日具体新闻**，不要空谈方法论
2. **敢说偏门，但必须标红线**——教人赚钱可以，教人犯法不行
3. **规避路径必须具体到操作层面**：什么主体、什么合同、什么话术、什么架构——不能只说"走合规通道"这种废话
4. **落地动作必须可执行**："关注""留意""警惕"不算动作，"注册""发送""下载""建群""上架"才算
5. **灰度评级诚实**：🟢🟡🔴 不能把红色标成绿色
6. **没有好机会就直说**：宁可写"今天没发现靠谱的偏门"也不要硬凑
7. **禁用废话词**：值得关注、需警惕、赋能、生态、数字化转型、乘势而上、抢抓机遇——出现一个扣10分"""

    api_key = "[HUNYUAN_API_KEY]"
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 7500,
        "temperature": 0.7,
    }

    try:
        logging.info("[新闻] 调用混元生成六大板块日报...")
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
        sections.append(f"  > 💰 落地动作：AI生成失败，请手动分析搞钱角度")

    # 出海/商业：排除已用的
    biz_items = [n for n in all_items if n['title'][:30] not in used_titles]
    sections.append("\n### 🌐 出海/商业\n")
    for n in biz_items[:4]:
        sections.append(f"- **{n['title']}**")
        sections.append(f"  > 💰 落地动作：AI生成失败，请手动分析搞钱角度")

    sections.append("\n### 🔥 热搜/时事\n")
    for n in hot_filtered[:5]:
        sections.append(f"- {n['title']}")

    sections.append("\n## 二、市场/中间人缺口扫描\n（AI分析生成失败，今日暂无缺口扫描。正常情况下此板块含：缺口类型+收钱模式+规避路径+窗口期）\n")
    sections.append("\n## 三、逆潮观察\n（AI分析生成失败，今日暂无逆潮分析）\n")
    sections.append("\n## 四、深度分析\n（AI分析生成失败，今日暂无5层传导+天之道解读）\n")
    sections.append("\n## 五、避坑提醒\n（AI分析生成失败，今日暂无风险预警）\n")
    sections.append("\n## 六、今日邪修金句\n💭 AI宕机，邪修闭关，明日再战\n")

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
