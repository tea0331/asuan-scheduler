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
    """从RSS源获取新闻（用requests带timeout下载，xml.etree解析，无网络重试）"""
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if resp.status_code != 200:
            logging.warning(f"[新闻] RSS下载失败({url}): HTTP {resp.status_code}")
            return []
        # 用xml解析RSS（feedparser会发起额外网络请求，容易卡死）
        root = ET.fromstring(resp.content)
        results = []
        for item in root.findall('.//item')[:count]:
            title = item.findtext('title', '').strip()
            summary = item.findtext('description', '').strip()
            if summary:
                from bs4 import BeautifulSoup
                summary = BeautifulSoup(summary, 'html.parser').get_text(strip=True)
            if title:
                results.append({
                    'title': title,
                    'source': url.split('/')[2],
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
    """用curl抓取百度热搜榜（不依赖requests，避免超时卡死）"""
    try:
        import re, subprocess
        url = "https://top.baidu.com/board?tab=realtime"
        headers = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        curl_cmd = ['curl', '-s', '-H', headers, url]
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        html = result.stdout
        # 提取热搜标题
        titles = re.findall(r'<div class="c-single-text-ellipsis">([^<]+)</div>', html)
        if not titles:
            titles = re.findall(r'title="([^"]+)"', html)[:20]
        results = []
        for t in titles[:count]:
            t = t.strip()
            if t:
                results.append({'title': t, 'source': '百度热搜', 'summary': ''})
        return results
    except Exception as e:
        logging.warning(f"[新闻] 百度热搜抓取失败: {e}")
        return []


def _call_hunyuan_api(system_msg, user_msg, timeout=45):
    """调用混元API，单次调用带timeout，返回生成内容或None"""
    api_key = os.getenv('HUNYUAN_API_KEY', '[HUNYUAN_API_KEY]')
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
        elif resp.status_code == 429 or (resp.status_code == 400 and 'rate_limit' in resp.text):
            logging.warning("[新闻] 混元API限流，等待5秒重试...")
            import time; time.sleep(5)
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                result = resp.json()
                return result['choices'][0]['message']['content'].strip()
            else:
                logging.warning(f"[新闻] 重试仍失败: {resp.status_code} {resp.text[:200]}")
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
        all_raw.extend(hot_raw)
        source_stats['百度热搜'] = len(hot_raw)

    logging.info(f"[新闻] RSS+热搜抓取完成: {source_stats}, 共{len(all_raw)}条")

    # 按画像过滤并排序
    scored = [(item, score_news(item)) for item in all_raw]
    filtered = [(item, sc) for item, sc in scored if sc >= 1]  # 门槛分1
    filtered.sort(key=lambda x: x[1], reverse=True)
    top_items = [item for item, sc in filtered[:20]]  # 取TOP20

    logging.info(f"[新闻] 画像过滤后TOP20: {[item['title'][:30] for item, sc in filtered[:5]]}")

    # ---- 构造AI提示词 ----
    system_msg = """你是有10年投研经验的分析师，专注"搞钱机会识别"。

**任务**：基于新闻素材，生成"每日资讯"板块（约800字）。

**输出格式**：
## 一、每日资讯

### 🤖 AI/算力
- **标题**
  > 💰 落地动作：（具体可执行的搞钱动作，含数字/仓位/止损）

### 🏦 金融/政策
...

### 🚀 创业/商业
...

### 🌐 出海/跨境
...

### 🔥 热搜/时事
...

**要求**：
1. 每条新闻后必须跟"💰 落地动作"（具体可执行，含数字）
2. 优先AI/科技/金融/创业，过滤体育/娱乐/社会
3. 从"搞钱角度"分析（低买高卖/信息差/政策套利/中间人角色）
4. 总字数800-1000字"""

    user_msg = """今日新闻素材（已按画像打分排序）：

""" + "\n".join([
        f"【{item.get('source','')}】{item['title']} (分:{score_news(item)})"
        for item in top_items
    ]) + "\n\n请生成今日【每日资讯】板块。"

    # ---- 调用AI（外层120秒超时兜底，API内部60秒）----
    try:
        content = _run_with_timeout(
            lambda: _call_hunyuan_api(system_msg, user_msg, timeout=90),
            timeout=150
        )
        if content:
            logging.info(f"[新闻] ✅ AI日报生成成功: {len(content)}字符")
            return content
        else:
            logging.warning("[新闻] AI日报生成返回空，使用降级模式")
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
        # 检查是否有 generate_daily_section 方法
        if hasattr(jz, 'generate_daily_section'):
            return jz.generate_daily_section(daily_result)
        else:
            # 降级：读取 lottery-predictions.json 并格式化
            import json
            pred_file = os.path.join(os.path.dirname(__file__), 'lottery-predictions.json')
            today_str = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
            yesterday_str = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=1)).strftime('%Y-%m-%d')
            if os.path.exists(pred_file):
                with open(pred_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                lines = ['\n---\n## 🎰 彩票号码推荐 — 刘海蟾点金', '> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n']
                # 格式1: list of dicts，每个dict含 date + ssq_recs/dlt_recs/qxc_recs
                if isinstance(data, list):
                    # 找今天的推荐（优先）或昨天的
                    recs_today = {}
                    recs_yesterday = {}
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        if item.get('date') == today_str:
                            recs_today = item
                        elif item.get('date') == yesterday_str:
                            recs_yesterday = item
                    recs = recs_today or recs_yesterday
                    for game_key, game_label in [('ssq_recs', '🔴 双色球'), ('dlt_recs', '🔵 大乐透'), ('qxc_recs', '🟢 七星彩')]:
                        game_recs = recs.get(game_key, [])
                        if game_recs:
                            lines.append(f'### {game_label}')
                            for i, rec in enumerate(game_recs[:5]):
                                digits = rec.get('digits', rec.get('numbers', rec))
                                if isinstance(digits, list):
                                    fmt = ' '.join(str(int(d)) for d in digits)
                                else:
                                    fmt = str(rec)
                                lines.append(f'注{i+1}: {fmt}  [{rec.get("strategy", "策略")}]')
                            lines.append('')
                    if not recs:
                        lines.append('（推荐数据暂未同步，下次自动恢复）\n')
                    return '\n'.join(lines)
                # 格式2: dict 格式
                elif isinstance(data, dict):
                    preds = data.get('predictions', data)
                    for game, recs in preds.items():
                        lines.append(f'### {game.upper()}')
                        for i, rec in enumerate(recs[:5]):
                            lines.append(f'注{i+1}: {rec}')
                    return '\n'.join(lines)
                else:
                    return '\n---\n## 🎰 彩票推荐\n（数据格式未知）\n---\n'
            else:
                return '\n---\n## 🎰 彩票推荐\n（lottery-predictions.json 未找到）\n---\n'
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
