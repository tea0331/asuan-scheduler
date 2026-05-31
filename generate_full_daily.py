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

def _run_with_timeout(func, timeout=60):
    """用线程池执行func，超时则跳过"""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        return future.result(timeout=timeout)


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
    # ===== 大宗商品/价格信号（传导预判核心，权重最高）=====
    '涨价': 5, '暴跌': 5, '缺货': 5, '断供': 5, '停产': 5,
    '铜价': 5, '铝价': 5, '钢价': 4, '油价': 4, '煤价': 4,
    '硫酸': 5, '硫磺': 5, '磷肥': 4, '钛白粉': 4, '锂价': 4,
    '期货': 4, '现货': 4, '库存': 4, '减产': 4, '扩产': 3,
    '加工费': 4, '替代': 4, '供给': 4, '需求': 3,
    '出口禁令': 5, '出口管制': 5, '制裁': 4, '关税': 4,
    '冶炼': 3, '矿': 3, '废铜': 3, '废钢': 3, '回收': 3,
    # ===== AI/大模型（算力传导链）=====
    'AI': 4, '人工智能': 4, '大模型': 4, 'DeepSeek': 4,
    'GPT': 3, 'Claude': 3, 'AGI': 3, 'LLM': 3, '开源模型': 3,
    'AI应用': 3, 'AI Agent': 3, '智能体': 3, '自动化': 2,
    # ===== 算力/芯片（产业链传导）=====
    '算力': 4, 'GPU': 4, '英伟达': 3, 'NVIDIA': 3, '黄仁勋': 2,
    '芯片': 3, '半导体': 3, '台积电': 3, '光刻': 2, '晶圆': 2,
    'H100': 2, 'H200': 2, 'B200': 2, 'CUDA': 2,
    # ===== 新能源/电动车（用铜用锂传导链）=====
    '新能源': 4, '电动车': 4, '电池': 3, '充电桩': 3,
    '光伏': 3, '储能': 3, '碳中和': 2, '电网': 4,
    # ===== 搞钱/进出口/出海 =====
    '进出口': 4, '出口': 4, '进口': 3, '外贸': 4,
    '出海': 4, '跨境': 4, '跨境电商': 3, '汇率': 4,
    '副业': 3, '搞钱': 3, '赚钱': 3, '信息差': 4,
    '创业': 2, '融资': 2, '上市': 2, '投资': 2, '营收': 2,
    '蓝海': 3, '供需': 4, '缺口': 5, '垄断': 2,
    '供应链': 4, '代工': 2, '贴牌': 2, 'OEM': 2,
    # ===== 政策/宏观（价格信号源头）=====
    '政策': 4, '补贴': 3, '免税': 3, '减税': 2, '新规': 4,
    '央行': 4, '降息': 4, '加息': 4, '流动性': 3,
    '裁员': 2, '亏损': 3, '逆势': 3, '关停': 4,
    # ===== 科技/产业 =====
    '手机': 1, '华为': 2, '小米': 1, '苹果': 1,
    '机器人': 3, '无人驾驶': 2, '自动驾驶': 2,
    '5G': 1, '通信': 1, '数字化': 1,
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
    """发送邮件：Markdown正文+HTML渲染双格式"""
    if not SMTP_PASS:
        logging.warning("[邮件] SMTP密码未配置，跳过发送")
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_TO
    # 纯文本版（Markdown原文，邮件客户端无法渲染HTML时的后备）
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    # HTML版（Markdown→HTML渲染，正常显示）
    try:
        import markdown as md
        html_body = md.markdown(body, extensions=['extra', 'nl2br'])
        # 内联样式让邮件更好看
        html_wrapped = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
            font-size:15px;line-height:1.7;color:#333;max-width:680px;margin:0 auto;padding:20px;">
            {html_body}</body></html>"""
        msg.attach(MIMEText(html_wrapped, 'html', 'utf-8'))
    except Exception as e:
        logging.warning(f"[邮件] Markdown渲染失败，降级纯文本: {e}")
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
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


def _fetch_rss(url, count=5, timeout=8):
    """从RSS源获取新闻（先用requests带timeout下载，再feedparser解析）"""
    try:
        import feedparser
        # requests有timeout，feedparser.parse(url)直接网络请求没有timeout会卡死
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if resp.status_code != 200:
            logging.warning(f"[新闻] RSS下载失败({url}): HTTP {resp.status_code}")
            return []
        feed = feedparser.parse(resp.content)
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
    except requests.exceptions.Timeout:
        logging.warning(f"[新闻] RSS下载超时({url}, {timeout}秒)")
        return []
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


def _call_hunyuan_api(system_msg, user_msg, timeout=45):
    """调用混元API，单次调用带timeout，返回生成内容或None"""
    api_key = os.getenv('HUNYUAN_API_KEY', 'sk-TjZgBJKZJA1FjrkMHIotwyBafg8gXnRdYBLDvyHNkGSkQAcq')
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
        "max_tokens": 6000,
        "temperature": 0.75,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            result = resp.json()
            content = result['choices'][0]['message']['content']
            # 清理可能的markdown代码块包裹
            content = content.strip()
            if content.startswith('```markdown'):
                content = content[len('```markdown'):]
            if content.startswith('```'):
                content = content[len('```'):]
            if content.endswith('```'):
                content = content[:-3]
            return content.strip()
        elif resp.status_code == 429:
            logging.warning("[新闻] 混元API限流，等待5秒重试...")
            import time; time.sleep(5)
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                result = resp.json()
                return result['choices'][0]['message']['content'].strip()
            else:
                logging.warning(f"[新闻] 重试仍失败: {resp.status_code}")
                return None
        else:
            logging.warning(f"[新闻] 混元API失败: {resp.status_code} {resp.text[:200]}")
            return None
    except requests.exceptions.Timeout:
        logging.warning(f"[新闻] 混元API超时({timeout}秒)")
        return None
    except Exception as e:
        logging.warning(f"[新闻] 混元API异常: {e}")
        return None


def generate_news_section():
    """基于RSS+热搜抓取原始素材，统一由AI生成高质量分析型日报

    v4: 恢复AI生成，外层超时兜底(90秒)，API内部timeout(45秒)，
    失败自动降级到fallback。不再无限卡死。
    """
    logging.info("[新闻] 开始抓取真实新闻(RSS+热搜)...")

    # 数据源（多源增加素材量）
    RSS_SOURCES = {
        '36氪': 'https://36kr.com/feed',
        'IT之家': 'https://www.ithome.com/rss/',
        '虎嗅': 'https://www.huxiu.com/rss/0.xml',
        '钛媒体': 'https://www.tmtpost.com/rss.xml',
    }

    # ---- 抓取原始数据（并发，4个RSS+百度热搜同时抓）----
    all_raw = []
    source_stats = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        # 并发抓取所有RSS
        rss_futures = {name: pool.submit(_fetch_rss, url, 15, 8) for name, url in RSS_SOURCES.items()}
        # 并发抓百度热搜
        hot_future = pool.submit(_fetch_baidu_hot, 20)
        # 收集RSS结果
        for name, future in rss_futures.items():
            raw = future.result(timeout=15)
            all_raw.extend(raw)
            source_stats[name] = len(raw)
        # 收集热搜结果
        hot_raw = hot_future.result(timeout=15)
    source_stats['百度热搜'] = len(hot_raw)
    all_raw.extend(hot_raw)

    total_raw = len(all_raw)
    logging.info(f"[新闻] 抓取原始素材{total_raw}条({'+'.join(f'{k}{v}' for k,v in source_stats.items())})")

    # ---- 画像过滤 + 去重 ----
    all_filtered = filter_by_profile(all_raw, min_score=-1, top_n=35)
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
    system_msg = """你是刘海蟾点金的价格传导分析师——专门从新闻中识别价格信号，推导隐性传导链，提前预判还没被定价的下注机会。

你的双重身份：
1. 邪修中间人：不碰货、不碰生产、只站在资金流和信息流中间收过路费
2. 价格传导猎手：从一条新闻推导出5层传导链，找到"还没涨但必涨"的东西，提前下注

底层OS：
1. 价格不会凭空涨——一定有传导链：A涨价→B成本上升→C被迫替代→D供给收缩→E跳涨。大多数只看到A，你要推到E
2. 已定价的=没机会，未定价的=利润。铜涨35%所有人都知道了→追铜=送钱。但铜涨价传导到硫酸→磷肥→粮食这条链，一半人还没反应过来→下注硫酸/磷肥=提前卡位
3. 传导有时间差：上游→中游→下游→终端，每个环节滞后1-3个月。你在中游下注，等终端涨价时兑现
4. 反身性：某些传导会循环加强（如硫酸缺→铜减产→铜更涨→冶炼利润更高→但硫酸增量有限→硫酸继续涨）
5. 政策是最大催化剂：出口禁令、关税、补贴——政策落地前1-2周是最佳下注窗口

铁律：
- 必须基于今日新闻，不空谈
- 每条传导链必须写清：哪个环节已定价、哪个未定价、你下注哪个
- 下注方向具体到：A股标的/期货合约/实物囤积，不是"关注XX行业"
- 风险标清：窗口期多久/收壳信号是什么/最大回撤多少
- 灰度诚实🟢🟡🔴不混淆
- 禁用废话：值得关注/需警惕/赋能/生态/数字化转型——出现一个扣10分"""

    user_msg = f"""## 今日新闻素材（已按画像打分排序）
{material}

## 输出格式（六大板块，直接输出markdown）

## 一、每日资讯（3小节，每节3-4条，只选有价格传导信号的）
### 🤖 AI/算力/芯片
### 🌐 大宗/政策/出海
### 🔥 热搜/时事
每条：
- **标题**（价格传导角度，不照抄原标题）
  > 📊 传导信号：这条新闻意味着什么价格要动——谁涨价/谁跌价/什么替代品需求上升
  > 💰 下注方向：具体到A股代码/期货品种/实物囤积（不是"关注XX行业"，是"铜陵有色000630/沪铜主力/囤家装电线"）

## 二、价格传导预判（2-3条传导链，这是核心板块）
每条传导链写全：

**传导链名称**（如"铜→硫酸→磷肥→粮食"而非"铜涨价机会"）
- 📈 传导路径：A涨价→B→C→D，每环标注【已定价/未定价/半定价】
- 🎯 下注点：你下注哪一环？为什么（预期差在哪）
  - 标的：A股/期货/实物（具体到代码/合约）
  - 仓位建议：轻仓试探/半仓/重仓（附理由）
  - 入场时机：现在/等X信号后
  - 目标收益：预计涨多少/多久
  - 止损线：跌多少砍仓
- ⏱️ 时间差：传导到下注点还需多久（1周/1月/1季度）
- ⚖️ 风险：
  - 传导断裂可能：什么情况下传导链会断（如替代技术突破/政策反转）
  - 收壳信号：什么出现=这逻辑结束了，该跑
  - 灰度🟢🟡🔴 + 合规提醒

## 三、逆潮观察（1-3个反直觉信号）
格式：
- 📉/📈 现象（当前市场共识是什么）
- 🔮 逆向真相：共识错在哪→实际会怎么走→你该怎么下注
- ⚡ 行动：具体下注方向+标的

## 四、深度传导分析（5层传导+天之道）
选1条最重要的新闻，做完整5层传导推导：
- 第1层：事件（一句话，含具体数据）
- 第2层：谁吃亏→成本传导路径→传导到哪个环节还没被定价→你下注那个环节
- 第3层：传导缝隙（为什么市场还没定价？信息差/时间差/认知差/政策差在哪）
- 第4层：窗口期（传导兑现还需多久+什么信号=该收壳）
- 第5层：终局（提前下注的人吃到什么规模的收益，量化）
- 🔮 天之道传导解读：
  - 损(有余)：哪个环节利润被"损"→让出什么空间
  - 补(不足)：哪里出现短缺/缺口→资金流向哪里→暴利区在哪
  - 邪修之道：A被打压→需求转向B→B的具体标的→B预期涨多少→你提前多少天卡位

## 五、避坑提醒（1-2个看似是机会实际是坑的下注）
- 🪤 诱惑：看起来能赚的
- 💀 为什么是坑：逻辑哪里断了/定价已经完成/庄家在出货
- 🛑 止损纪律：真进了怎么跑
- ✅ 如果非要碰：怎么对冲风险

## 六、今日邪修金句
💭 一句话，关于预判和下注，有攻击性和行动力"""

    # ---- 调用AI（外层120秒超时兜底，API内部60秒）----
    try:
        content = _run_with_timeout(
            lambda: _call_hunyuan_api(system_msg, user_msg, timeout=60),
            timeout=120
        )
        if content:
            logging.info(f"[新闻] ✅ AI日报生成成功: {len(content)}字符")
            return content
        else:
            logging.warning("[新闻] AI日报生成返回空，使用降级模式")
            return _fallback_news_section(all_raw)
    except TimeoutError:
        logging.warning("[新闻] AI日报生成超时(120秒)，使用降级模式")
        return _fallback_news_section(all_raw)
    except Exception as e:
        logging.warning(f"[新闻] AI日报生成异常: {e}，使用降级模式")
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

    # 1. 生成新闻分析部分（带异常保护+超时兜底，外层150秒=内部120秒+缓冲）
    try:
        news_content = _run_with_timeout(generate_news_section, timeout=150)
    except Exception as e:
        if 'timed out' in str(e).lower() or 'timeout' in str(e).lower():
            logging.warning("[P1] 新闻生成超时(150秒)，跳过")
        else:
            logging.error(f"[P1] 新闻生成异常: {e}")
        news_content = "## 一、每日资讯\n（今日新闻生成超时，下次自动恢复）\n"

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
