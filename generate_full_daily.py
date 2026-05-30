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
from concurrent.futures import ThreadPoolExecutor, TimeoutError

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
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
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
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
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
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
    except Exception as e:
        logging.warning(f"[新闻] 百度热搜抓取失败: {e}")
        return []



def _run_with_timeout(func, timeout=60):
    """用线程池执行func，超时则跳过"""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        return future.result(timeout=timeout)
def generate_news_section():
    """基于RSS+热搜抓取原始素材，统一由AI生成高质量分析型日报
    
    v3: 不再手动拼接标题+摘要，而是把原始素材喂给AI，
    让AI按用户画像(算力/AI/创业/信息差)和分析框架输出四大板块。
    """
    logging.info("[新闻] 开始抓取真实新闻(RSS+热搜)...")

    # 数据源（多源增加素材量）
    RSS_SOURCES = {
        '36氪': 'https://36kr.com/feed',
        'IT之家': 'https://www.ithome.com/rss/',
        '虎嗅': 'https://www.huxiu.com/rss/0.xml',
        '钛媒体': 'https://www.tmtpost.com/rss.xml',
    }

    # ---- 抓取原始数据 ----
    all_raw = []
    source_stats = {}
    for name, url in RSS_SOURCES.items():
        raw = _fetch_rss(url, 15)
        all_raw.extend(raw)
        source_stats[name] = len(raw)
    hot_raw = _fetch_baidu_hot(20)
    source_stats['百度热搜'] = len(hot_raw)
    all_raw.extend(hot_raw)

    total_raw = len(all_raw)
    logging.info(f"[新闻] 抓取原始素材{total_raw}条({'+'.join(f'{k}{v}' for k,v in source_stats.items())})")

    # ---- 画像过滤 + 去重 ----
    all_filtered = filter_by_profile(all_raw, min_score=-1, top_n=35)
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
    for i, n in enumerate(unique[:30], 1):
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
        return _fallback_news_section(all_raw)

    # ---- AI生成六大板块 ----
    # system消息：人设+铁律+范例（固定不变，告诉AI什么level的内容是读者要的）
    system_msg = """你是刘海蟾点金的邪修分析师——专门做中间人流水生意的操盘手，不是摆地摊的。
你的生意模式：不碰货、不碰生产、只站在资金流和信息流中间收过路费。你经手的项目，流水以百万计，你抽3-8个点就是几十万。

你懂的生意长这样（范例，不是让你照搬，是让你知道什么level）：
- 🟡 资金过桥：企业贷款批了但还没放款，你垫资7天收日息0.15%，月流水3000万，你赚40万。合同签"财务顾问费"，用有限合伙做通道，资金不过你个人账
- 🟡 资质挂靠：有资质的建筑公司闲着，没资质的施工队要接项目，你做挂靠中介收3-5%/年管理费。主体用工程咨询公司签"管理服务合同"，发票开"咨询费"
- 🔴 跨境资金通道：跨境电商要结汇但额度不够，你用多个个人账户拆单走款收1.5%手续费。红线是《外汇管理条例》第39条"非法买卖外汇"，规避：走第三方支付机构通道而非私人对敲
- 🟡 数据掮客：A公司有行业数据想变现，B公司愿花钱买，你做撮合抽20%。红线是《数据安全法》第32条，规避：只做数据供需撮合不碰数据本身，合同签"数据咨询服务"
- 🟡 AI算力转租：你有海外GPU资源渠道，国内AI公司租不起英伟达官方价格，你做转租赚30%差价。合同签"云计算资源服务"，用香港公司签约

底层OS：
1. 真正的中间人赚的是"结构差"——信息不对称+资质不对等+资金不匹配，三项占一项就能吃
2. 监管滞后3-5年=窗口期，立法周期=收壳窗口
3. 规避=设计：同样的业务换壳就合规——换主体/改合同名目/走保税区/用海外签约
4. 红线不碰灰线贴着走——判例法：没人因XX被判过=实践中不认为是罪
5. 先吃肉再合规——比政策快半步

铁律：
- 必须基于今日新闻，不空谈
- 敢说偏门但标红线
- 规避路径具体到：什么主体签什么合同开什么发票怎么走账
- 落地动作是操盘级别的：注册什么主体/签什么协议/对接哪类客户/走什么资金通道——不是"去闲鱼收显卡"这种摆地摊动作
- 灰度诚实🟢🟡🔴不混淆
- 禁用废话：值得关注/需警惕/赋能/生态/数字化转型——出现一个扣10分"""

    # user消息：素材+格式要求
    user_msg = f"""## 今日新闻素材（已按画像打分排序）
{material}

## 输出格式（六大板块，直接输出markdown）

## 一、每日资讯（3小节，每节3-4条，只选跟读者有资金关系的）
### 🤖 AI/算力
### 🌐 出海/商业
### 🔥 热搜/时事
每条：
- **标题**（搞钱角度，不照抄原标题）
  > 💰 落地动作：资金流怎么走——谁付钱/付多少/怎么收/合同叫什么名字（不是"去闲鱼收显卡"，是"注册XX主体签XX合同走XX通道"）
  > 🕳️ 缺口：资金断裂/资质壁垒/信息不对称在哪

## 二、市场/中间人缺口扫描（2-3个缺口）
核心：不碰货只碰资金流和信息流，站在供需之间收过路费。每个缺口写全：

**缺口名称**（够野够精准，如"AI合规检测资金过桥"而非"AI机会"）
- 类型：资金过桥/资质挂靠/跨境资金通道/数据掮客/算力转租/政策套利
- 邪修逻辑：谁卡在资金/资质/信息上过不去→你在中间架桥→收过桥费
- 收钱模型：
  - 谁付钱/付多少/什么频率（如"施工队付3%管理费/年，一个项目均价200万=6万/项目"）
  - 月流水预估/你净赚多少
- 第一步：今天注册什么主体/签什么协议/对接哪类客户
- ⚖️ 风险与规避：
  - 灰度🟢🟡🔴 + 法律红线（哪条法哪个局管+有无判例）
  - 主体设计：用有限公司/有限合伙/香港公司/个人？为什么选这个
  - 合规包装：合同叫什么名目/发票开什么/资金怎么走账（公对公/第三方支付/分账）
  - 风险隔离：灰色业务和干净业务怎么分开（不同主体/不同账户/不同合同体系）
  - 窗口期：多久/什么信号出现说明要收壳

## 三、逆潮观察（1-3个反直觉信号）
格式：
- 📉/📈 现象
- 🔮 邪修真相（逻辑+先例/判例支撑）
- ⚡ 行动（操盘级动作，不是"发朋友圈"）

## 四、深度分析（5层传导+天之道）
选1条最重要的新闻：
- 第1层：事件（一句话）
- 第2层：谁吃亏→让出什么资金流→你插在哪个节点收过路费
- 第3层：规则缝隙（具体法规+执法部门+哪里有洞+有无判例先例）
- 第4层：窗口期（多久+什么信号=该收壳）
- 第5层：终局（占位的人吃到什么规模的利润）
- 🔮 天之道邪修解读：
  - 损(有余)：被砍/被限/被整=正规军撤退=偏门进场
  - 补(不足)：被渴求/被短缺=资金缺口=暴利区
  - 邪修之道：打压A→需求还在→转向B→B的具体操作模式→B月流水多少→你抽多少

## 五、避坑提醒（1-2个陷阱）
- 🪤 诱惑 + 💀 为什么是坑（真实案例/判例/执法趋势）+ 🛑 红线 + ✅ 非要碰怎么剥离灰色只吃合规那块

## 六、今日邪修金句
💭 一句话，有攻击性和行动力"""

    api_key = "sk-TjZgBJKZJA1FjrkMHIotwyBafg8gXnRdYBLDvyHNkGSkQAcq"
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": 9000,
        "temperature": 0.75,
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
            return _fallback_news_section(all_raw)
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
    except Exception as e:
        logging.warning(f"[新闻] 混元API异常: {e}")
        return _fallback_news_section(all_raw)


def _fallback_news_section(all_raw_items):
    """API失败时的降级方案：用画像过滤的原始标题兜底"""
    logging.info("[新闻] 降级模式：用画像过滤原始标题")
    sections = ["## 一、每日资讯\n"]

    all_items = filter_by_profile(all_raw_items, min_score=0, top_n=15)
    hot_items = [n for n in all_raw_items if n.get('source') == '百度热搜']
    hot_filtered = filter_by_profile(hot_items, min_score=-1, top_n=5)

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
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐生成失败: JinZhu初始化异常({e})\n---\n"

    # v9.0-JinZhu: 核心大脑闭环+展示一体化
    try:
        daily_result = jz.daily_run()
        logging.info(f"[日报] ✅ JinZhu闭环完成: settle={bool(daily_result.get('settle'))}, evolve={bool(daily_result.get('evolve'))}")
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
    except Exception as e:
        logging.warning(f"[日报] ⚠️ JinZhu闭环异常(不阻塞): {e}")
        daily_result = {}

    # 由JinZhu核心大脑统一生成展示内容
    try:
        return jz.generate_daily_section(daily_result)
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
    except Exception as e:
        logging.error(f"[日报] ⚠️ JinZhu展示生成异常: {e}")
        return f"\n---\n## 🎰 彩票推荐\n（展示生成异常: {e}，推荐数据已正常生成）\n---\n"


if __name__ == '__main__':
    logging.info(f"========== 生成完整日报 {today_str} ==========")

    # 1. 生成新闻分析部分（带异常保护）
    try:
        news_content = _run_with_timeout(generate_news_section, timeout=60)
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
    except Exception as e:
        logging.error(f"[P1] 新闻生成异常: {e}")
        news_content = "## 一、每日资讯\n（今日新闻生成异常，下次自动恢复）\n"

    # 2. 生成彩票部分（带异常保护）
    try:
        lottery_content = generate_lottery_section()
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
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
    except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
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
        except TimeoutError:
        logging.warning("新闻生成超时(60秒)，跳过")
        news_content = ""
    except Exception as e:
            logging.error(f"[P1] 邮件发送异常: {e}")

    logging.info(f"========== 完成 {today_str} ==========")
