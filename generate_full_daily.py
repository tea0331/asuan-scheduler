#!/usr/bin/env python3
"""生成完整日报 V6 — 6板块齐全 + 邪修进化引擎

V6 核心升级:
  1. AI一次生成全部6板块(不是只生成板块一)
  2. 降级也有6板块(关键词推断，不是空壳占位)
  3. 邪修进化: 传导链记忆 + 缺口信号匹配 + 逆潮模式库
  4. 板块完整性守护: 发送前自动验证

架构:
  generate_all_sections()  → AI生成6板块 (主路径)
  _fallback_all_sections() → 关键词推断6板块 (降级路径)
  generate_lottery_section() → JinZhu彩票闭环
  generate_taiwan_section()  → 台湾彩种(PLN/LTN)
"""
import os
import sys
import json
import logging
import hashlib
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import requests


# ============================================================
# 基础配置
# ============================================================
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')
yesterday_str = (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d')
today = datetime.now(CST)

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.163.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USER = os.getenv('SMTP_USER', 'tea0331@163.com')
SMTP_PASS = os.getenv('SMTP_PASSWORD', os.getenv('SMTP_PASS', ''))
SMTP_TO = os.getenv('SMTP_TO', 'tea0331@163.com')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(output_dir, exist_ok=True)

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def _run_with_timeout(func, timeout=60):
    """用线程池执行func，超时则跳过"""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        return future.result(timeout=timeout)


# ============================================================
# 用户画像: 关键词权重 (正=感兴趣, 负=不感兴趣)
# ============================================================
USER_PROFILE = {
    # 大宗商品/价格信号 (传导预判核心)
    '涨价': 5, '暴跌': 5, '缺货': 5, '断供': 5, '停产': 5,
    '铜价': 5, '铝价': 5, '钢价': 4, '油价': 4, '煤价': 4,
    '硫酸': 5, '硫磺': 5, '磷肥': 4, '钛白粉': 4, '锂价': 4,
    '期货': 4, '现货': 4, '库存': 4, '减产': 4, '扩产': 3,
    '加工费': 4, '替代': 4, '供给': 4, '需求': 3,
    '出口禁令': 5, '出口管制': 5, '制裁': 4, '关税': 4,
    '冶炼': 3, '矿': 3, '废铜': 3, '废钢': 3, '回收': 3,
    # AI/大模型
    'AI': 4, '人工智能': 4, '大模型': 4, 'DeepSeek': 4,
    'GPT': 3, 'Claude': 3, 'AGI': 3, 'LLM': 3, '开源模型': 3,
    'AI应用': 3, 'AI Agent': 3, '智能体': 3, '自动化': 2,
    # 算力/芯片
    '算力': 4, 'GPU': 4, '英伟达': 3, 'NVIDIA': 3, '黄仁勋': 2,
    '芯片': 3, '半导体': 3, '台积电': 3, '光刻': 2, '晶圆': 2,
    'H100': 2, 'H200': 2, 'B200': 2, 'CUDA': 2,
    # 新能源/电动车
    '新能源': 4, '电动车': 4, '电池': 3, '充电桩': 3,
    '光伏': 3, '储能': 3, '碳中和': 2, '电网': 4,
    # 搞钱/进出口/出海
    '进出口': 4, '出口': 4, '进口': 3, '外贸': 4,
    '出海': 4, '跨境': 4, '跨境电商': 3, '汇率': 4,
    '副业': 3, '搞钱': 3, '赚钱': 3, '信息差': 4,
    '创业': 2, '融资': 2, '上市': 2, '投资': 2, '营收': 2,
    '蓝海': 3, '供需': 4, '缺口': 5, '垄断': 2,
    '供应链': 4, '代工': 2, '贴牌': 2, 'OEM': 2,
    # 政策/宏观
    '政策': 4, '补贴': 3, '免税': 3, '减税': 2, '新规': 4,
    '央行': 4, '降息': 4, '加息': 4, '流动性': 3,
    '裁员': 2, '亏损': 3, '逆势': 3, '关停': 4,
    # 科技/产业
    '手机': 1, '华为': 2, '小米': 1, '苹果': 1,
    '机器人': 3, '无人驾驶': 2, '自动驾驶': 2,
    '5G': 1, '通信': 1, '数字化': 1,
    # 负面: 不感兴趣
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
    """过滤+排序: 删负分，按画像得分降序"""
    filtered = [n for n in news_list if score_news(n) >= min_score]
    filtered.sort(key=score_news, reverse=True)
    if top_n:
        filtered = filtered[:top_n]
    return filtered


# ============================================================
# 邪修进化引擎 — 传导链记忆 + 缺口信号 + 逆潮模式
# ============================================================
XIE_XIU_MEMORY_PATH = os.path.join(MODULE_DIR, 'xie_xiu_memory.json')

# 传导链模板库: 从信号到终端的完整路径
CHAIN_TEMPLATES = [
    {'trigger': ['铜价', '铜', '铜矿'], 'chain': ['铜矿减产/涨价', '冶炼加工费压缩', 'PCB/电机成本上升', '电动车/家电涨价', '替代材料(铝)需求增'], 'gap': '铜铝价差套利/废铜回收/台湾冶炼厂中间人', 'tide': '铜价涨→大家看空需求→实际中国基建托底'},
    {'trigger': ['AI', '算力', 'GPU', '英伟达'], 'chain': ['大模型训练需求爆发', 'GPU/HBM供不应求', '散热/电源/PCB配套涨', '数据中心建设加速', '电力消耗激增→核电/绿电'], 'gap': '算力中间商/散热材料/数据中心电力', 'tide': 'AI概念过热→短期回调→但算力需求是实打实的'},
    {'trigger': ['锂价', '电池', '新能源'], 'chain': ['锂价暴跌/暴涨', '电池成本变化', '电动车定价策略', '传统车企转型压力', '充电桩/储能配套'], 'gap': '锂价波动对冲/电池回收/储能系统集成', 'tide': '锂价跌→短期看空→但储能需求是新增量'},
    {'trigger': ['出口', '关税', '制裁', '贸易'], 'chain': ['出口管制/关税调整', '供应链被迫重组', '转口贸易/第三国中转', '合规成本上升', '替代市场开拓'], 'gap': '转口贸易服务商/合规咨询/替代供应链', 'tide': '制裁加码→短期恐慌→但转口贸易利润更高'},
    {'trigger': ['汇率', '人民币', '美元'], 'chain': ['汇率波动', '出口企业利润变化', '跨境结算需求', '对冲工具需求', '海外资产配置'], 'gap': '跨境结算服务商/汇率对冲咨询', 'tide': '人民币贬值→短期利好出口→但通胀压力'},
    {'trigger': ['磷肥', '硫酸', '硫磺'], 'chain': ['硫磺/硫酸供应紧张', '磷肥生产成本上升', '粮食生产成本增加', '化肥替代/减量技术', '粮食安全政策'], 'gap': '硫酸替代技术/磷肥中间商/粮食套利', 'tide': '化肥涨价→短期恐慌→但替代技术正在成熟'},
    {'trigger': ['光伏', '储能', '电网'], 'chain': ['光伏装机量激增', '储能配套不足', '电网调度压力', '虚拟电厂需求', '电力市场化交易'], 'gap': '储能系统集成/虚拟电厂/电力交易', 'tide': '光伏产能过剩→短期看空→但消纳瓶颈催生新业态'},
    {'trigger': ['半导体', '芯片', '台积电'], 'chain': ['芯片制程突破/受限', '代工产能重新分配', '国产替代加速', '设备/材料需求', '终端产品成本变化'], 'gap': '国产替代中间人/设备维护/材料供应', 'tide': '制程受限→短期看空→但国产替代是长期趋势'},
]

# 逆潮模式库: 市场共识 vs 逆向可能
CONTRA_TIDE_PATTERNS = [
    {'consensus': '涨', 'reverse': '跌', 'logic': '涨过头必有回调，关注库存积压信号'},
    {'consensus': '跌', 'reverse': '涨', 'logic': '恐慌出清后供给收缩，关注减产信号'},
    {'consensus': '政策利好', 'reverse': '执行打折', 'logic': '政策从发文到落地有时间差和执行衰减'},
    {'consensus': '产能过剩', 'reverse': '龙头垄断', 'logic': '过剩淘汰小厂，龙头市占率反升'},
    {'consensus': '技术突破', 'reverse': '商业化迟缓', 'logic': '实验室到量产有3-5年鸿沟'},
    {'consensus': '需求萎缩', 'reverse': '替代需求', 'logic': '旧需求萎缩常伴随新需求爆发'},
]


def _load_xie_xiu_memory():
    """加载邪修记忆库"""
    if os.path.exists(XIE_XIU_MEMORY_PATH):
        try:
            with open(XIE_XIU_MEMORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'chains': [], 'quotes': [], 'validated_patterns': []}


def _save_xie_xiu_memory(memory):
    """保存邪修记忆库"""
    try:
        with open(XIE_XIU_MEMORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"[邪修] 记忆保存失败: {e}")


def _match_chains(news_items):
    """从新闻中匹配传导链模板，返回相关传导链上下文"""
    all_text = ' '.join([item.get('title', '') for item in news_items[:20]])
    matched = []
    for template in CHAIN_TEMPLATES:
        hit_count = sum(1 for trigger in template['trigger'] if trigger in all_text)
        if hit_count > 0:
            matched.append({**template, 'hit_count': hit_count})
    matched.sort(key=lambda x: x['hit_count'], reverse=True)
    return matched[:3]  # 最多取3条最相关的


def _build_xie_xiu_context(news_items):
    """为AI生成邪修上下文: 匹配的传导链 + 历史金句 + 逆潮模式"""
    memory = _load_xie_xiu_memory()
    matched_chains = _match_chains(news_items)

    ctx = {
        'matched_chains': matched_chains,
        'recent_quotes': memory.get('quotes', [])[-5:],
        'validated_patterns': memory.get('validated_patterns', []),
    }

    # 传导链上下文 (供AI参考，不强制使用)
    chain_ctx = ""
    if matched_chains:
        chain_ctx = "\n\n【邪修传导链参考】(以下为今日新闻匹配到的传导链，必须结合今日具体新闻内容生成传导分析，禁止照搬):\n"
        for i, ch in enumerate(matched_chains):
            chain_ctx += f"\n链{i+1}: {' → '.join(ch['chain'])}\n"
            chain_ctx += f"  缺口: {ch['gap']}\n"
            chain_ctx += f"  逆潮: {ch['tide']}\n"

    # 避免重复金句
    used_quotes = memory.get('quotes', [])[-7:]

    return chain_ctx, used_quotes


def _record_xie_xiu_content(sections_text):
    """记录今日邪修内容到记忆库(传导链+金句)"""
    memory = _load_xie_xiu_memory()

    # 提取金句
    import re
    quote_match = re.search(r'六、今日邪修金句\s*(.*?)$', sections_text, re.MULTILINE)
    if quote_match:
        quote = quote_match.group(1).strip()
        if quote and '💭' in quote:
            quote = quote.replace('💭', '').strip()
            if quote and quote not in memory.get('quotes', []):
                memory.setdefault('quotes', []).append(quote)
                # 只保留最近30条
                memory['quotes'] = memory['quotes'][-30:]

    _save_xie_xiu_memory(memory)


# ============================================================
# 新闻抓取
# ============================================================
def _fetch_rss(url, count=15, timeout=8):
    """从RSS源获取新闻"""
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if resp.status_code != 200:
            logging.warning(f"[新闻] RSS下载失败({url}): HTTP {resp.status_code}")
            return []
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


def _fetch_baidu_hot(count=20):
    """抓取百度热搜榜"""
    try:
        import re, subprocess
        url = "https://top.baidu.com/board?tab=realtime"
        headers = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        curl_cmd = ['curl', '-s', '-H', headers, url]
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        html = result.stdout
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


def fetch_raw_materials():
    """并发抓取所有新闻素材，返回(raw_items, source_stats)"""
    RSS_SOURCES = {
        '36氪': 'https://36kr.com/feed',
        'IT之家': 'https://www.ithome.com/rss/',
        '虎嗅': 'https://www.huxiu.com/rss/0.xml',
        '钛媒体': 'https://www.tmtpost.com/rss.xml',
    }

    all_raw = []
    source_stats = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        rss_futures = {name: pool.submit(_fetch_rss, url, 15, 8) for name, url in RSS_SOURCES.items()}
        hot_future = pool.submit(_fetch_baidu_hot, 20)

        for name, future in rss_futures.items():
            try:
                raw = future.result(timeout=15)
                all_raw.extend(raw)
                source_stats[name] = len(raw)
            except Exception:
                source_stats[name] = 0

        try:
            hot_raw = hot_future.result(timeout=15)
            all_raw.extend(hot_raw)
            source_stats['百度热搜'] = len(hot_raw)
        except Exception:
            source_stats['百度热搜'] = 0

    logging.info(f"[新闻] 抓取完成: {source_stats}, 共{len(all_raw)}条")
    return all_raw, source_stats


# ============================================================
# AI调用
# ============================================================
def _call_hunyuan_api(system_msg, user_msg, timeout=90):
    """调用混元API，单次调用带timeout"""
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
            content = content.strip()
            # 清理markdown代码块包裹
            if content.startswith('```markdown'):
                content = content[len('```markdown'):]
            if content.startswith('```'):
                content = content[len('```'):]
            if content.endswith('```'):
                content = content[:-3]
            return content.strip()
        elif resp.status_code == 429 or (resp.status_code == 400 and 'rate_limit' in resp.text):
            logging.warning("[AI] 混元API限流，等待5秒重试...")
            import time; time.sleep(5)
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                result = resp.json()
                return result['choices'][0]['message']['content'].strip()
            else:
                logging.warning(f"[AI] 重试仍失败: {resp.status_code}")
                return None
        else:
            logging.warning(f"[AI] 混元API失败: {resp.status_code} {resp.text[:200]}")
            return None
    except requests.exceptions.Timeout:
        logging.warning(f"[AI] 混元API超时({timeout}秒)")
        return None
    except Exception as e:
        logging.warning(f"[AI] 混元API异常: {e}")
        return None


# ============================================================
# 核心: 生成全部6板块
# ============================================================
def generate_all_sections():
    """生成日报全部6大板块 — V6核心函数

    主路径: AI一次生成6板块
    降级路径: 基于关键词推断生成6板块
    """
    # 1. 抓取新闻素材
    all_raw, source_stats = fetch_raw_materials()

    # 2. 画像过滤排序
    scored = [(item, score_news(item)) for item in all_raw]
    filtered = [(item, sc) for item, sc in scored if sc >= 1]
    filtered.sort(key=lambda x: x[1], reverse=True)
    top_items = [item for item, sc in filtered[:20]]

    logging.info(f"[日报] 画像过滤TOP20: {[item['title'][:20] for item, _ in filtered[:5]]}")

    # 3. 构建邪修上下文
    chain_ctx, used_quotes = _build_xie_xiu_context(top_items)

    # 4. 构建AI Prompt — 6板块完整版
    news_digest = "\n".join([
        f"【{item.get('source', '')}】{item['title']} (画像分:{score_news(item)})"
        + (f" — {item.get('summary', '')[:60]}" if item.get('summary') else "")
        for item in top_items
    ])

    used_quotes_warn = ""
    if used_quotes:
        used_quotes_warn = f"\n\n⚠️ 以下金句近期已使用，禁止重复:\n" + "\n".join([f"- {q}" for q in used_quotes])

    system_msg = f"""你是有10年投研经验的邪修分析师，专注"新闻→价格→搞钱机会"的隐秘传导链。

**你的身份**: 邪修 — 不是主流分析师，是看穿市场幻象的人。天之道损有余补不足，邪修之道是找到"有余"在哪然后收钱。

**任务**: 基于今日新闻素材，生成完整6板块日报（约2500字）。

**输出格式** (严格遵守标题格式):

## 一、每日资讯

### 🤖 AI/算力
- **新闻标题**
  > 💰 落地动作：（具体可执行的搞钱动作，含方向/仓位/止损线）

### 🏦 金融/政策
...

### 🚀 创业/商业
...

### 🌐 出海/跨境
...

### 🔥 热搜/时事
...

## 二、市场/中间人缺口扫描

> 扫描今日新闻中的供需缺口，找出"中间人"可以收钱的位置。

- **缺口类型**: [具体品类/环节]
  - 收钱模式: [信息差撮合/供应链整合/合规中介]
  - 规避路径: [可能的风险点和绕开方法]
  - 窗口期: [大概多久，什么信号消失就撤]

（至少2个缺口，每个缺口含上述4要素）

## 三、逆潮观察

> 市场共识可能在错，找到逆向下注的方向。

- **市场共识**: [多数人怎么看]
  - 逆向可能: [为什么多数人可能错]
  - 逆向下注: [如果逆向成立，该怎么收钱]
  - 止损线: [什么信号说明逆向判断错]

（至少1个逆潮信号）

## 四、深度传导分析

> 从今日最高分新闻出发，推导5层传导链。必须结合今日具体新闻，禁止用通用模板。

- 第1层（事件）: [今日具体新闻事件]
- 第2层（直接影响）: [对什么产业/价格的第一波冲击]
- 第3层（产业链传导）: [上游/下游如何连锁反应]
- 第4层（跨产业传导）: [如何扩散到看似无关的领域]
- 第5层（终局推演）: [最终谁受益、谁受损]

🔮 **天之道**: 损有余补不足 — [具体谁有余、谁不足]
⚡ **邪修之道**: [如何在"有余"和"不足"之间收过路费]

## 五、避坑提醒

> 看似机会实际是坑的下注，提醒自己别冲动。

- ⚠️ **陷阱**: [看似搞钱机会，实则是坑]
  - 为什么是坑: [真实原因]
  - 止损建议: [如果已经入局，怎么撤]

（至少1个避坑提醒）

## 六、今日邪修金句

💭 [1句话，结合今日新闻主题生成，要有洞察力、有画面感、有邪修味道。禁止鸡汤。]{used_quotes_warn}

**核心要求**:
1. 6板块缺一不可，每板块必须有实质内容
2. 传导链必须结合今日新闻具体内容，禁止用通用模板
3. 缺口扫描必须给出具体品类和收钱模式
4. 逆潮必须给出逆向下注方向和止损线
5. 金句必须每天不同，结合当日新闻主题
6. 总字数2500-3500字
{chain_ctx}"""

    user_msg = f"""今日新闻素材（已按画像打分排序）:

{news_digest}

请生成今日完整6板块日报。"""

    # 5. 调用AI生成 (外层超时180秒)
    try:
        content = _run_with_timeout(
            lambda: _call_hunyuan_api(system_msg, user_msg, timeout=120),
            timeout=180
        )
        if content and len(content) > 500:
            # 验证6板块是否齐全
            section_headers = [
                "一、每日资讯",
                "二、市场/中间人缺口扫描",
                "三、逆潮观察",
                "四、深度传导分析",
                "五、避坑提醒",
                "六、今日邪修金句",
            ]
            missing = [h for h in section_headers if h not in content]
            if not missing:
                logging.info(f"[日报] ✅ AI生成6板块齐全: {len(content)}字符")
                # 记录邪修内容
                _record_xie_xiu_content(content)
                return content
            else:
                logging.warning(f"[日报] AI生成缺板块: {missing}，补齐后使用")
                # 补齐缺失板块
                content = _patch_missing_sections(content, top_items, missing)
                _record_xie_xiu_content(content)
                return content
        else:
            logging.warning("[日报] AI生成内容过短或为空，使用降级模式")
            return _fallback_all_sections(all_raw, top_items)
    except TimeoutError:
        logging.warning("[日报] AI生成超时(180秒)，使用降级模式")
        return _fallback_all_sections(all_raw, top_items)
    except Exception as e:
        logging.warning(f"[日报] AI生成异常: {e}，使用降级模式")
        return _fallback_all_sections(all_raw, top_items)


def _patch_missing_sections(content, top_items, missing_headers):
    """补齐AI生成中缺失的板块"""
    for header in missing_headers:
        if header == "二、市场/中间人缺口扫描":
            patch = _fallback_gap_scan(top_items)
        elif header == "三、逆潮观察":
            patch = _fallback_contra_tide(top_items)
        elif header == "四、深度传导分析":
            patch = _fallback_deep_chain(top_items)
        elif header == "五、避坑提醒":
            patch = _fallback_pitfall(top_items)
        elif header == "六、今日邪修金句":
            patch = _fallback_quote(top_items)
        else:
            continue
        content += "\n\n" + patch
    return content


# ============================================================
# 降级路径: 基于关键词推断生成6板块
# ============================================================
def _fallback_all_sections(all_raw, top_items):
    """降级模式: 关键词推断6板块(有内容不是空壳)"""
    logging.info("[日报] 降级模式: 关键词推断6板块")

    # 画像过滤
    filtered_all = filter_by_profile(all_raw, min_score=0, top_n=15)
    hot_items = [n for n in all_raw if n.get('source') == '百度热搜']
    hot_filtered = filter_by_profile(hot_items, min_score=-1, top_n=5)

    # AI关键词
    ai_keywords = ['AI', '人工智能', '芯片', '模型', '大模型', '英伟达', '算力', 'DeepSeek', 'GPT', 'NVIDIA', 'GPU', '机器人', '智能体']
    ai_items = [n for n in filtered_all if any(kw.lower() in n['title'].lower() for kw in ai_keywords)]
    if not ai_items:
        ai_items = filtered_all[:4]
    used_titles = set(n['title'][:30] for n in ai_items)

    # 板块一: 每日资讯
    sections = ["## 一、每日资讯\n"]
    sections.append("### 🤖 AI/算力\n")
    for n in ai_items[:4]:
        sections.append(f"- **{n['title']}**")
        # 基于关键词推断传导信号
        signal = _infer_signal(n['title'])
        sections.append(f"  > 💰 落地动作: {signal}")

    biz_items = [n for n in filtered_all if n['title'][:30] not in used_titles]
    sections.append("\n### 🌐 出海/商业\n")
    for n in biz_items[:4]:
        sections.append(f"- **{n['title']}**")
        signal = _infer_signal(n['title'])
        sections.append(f"  > 💰 落地动作: {signal}")

    sections.append("\n### 🔥 热搜/时事\n")
    for n in hot_filtered[:5]:
        sections.append(f"- {n['title']}")

    # 板块二: 缺口扫描
    sections.append("\n\n" + _fallback_gap_scan(top_items))

    # 板块三: 逆潮观察
    sections.append("\n" + _fallback_contra_tide(top_items))

    # 板块四: 深度传导
    sections.append("\n" + _fallback_deep_chain(top_items))

    # 板块五: 避坑提醒
    sections.append("\n" + _fallback_pitfall(top_items))

    # 板块六: 邪修金句
    sections.append("\n" + _fallback_quote(top_items))

    return "\n".join(sections)


def _infer_signal(title):
    """基于标题关键词推断传导信号"""
    title_lower = title.lower()
    if any(kw in title_lower for kw in ['铜', '铝', '钢', '矿']):
        return '关注相关大宗商品期货多单，止损3%'
    elif any(kw in title_lower for kw in ['ai', '算力', 'gpu', '大模型']):
        return '关注算力租赁/散热材料供应链，止损5%'
    elif any(kw in title_lower for kw in ['出口', '关税', '制裁']):
        return '关注转口贸易服务商，止损10%'
    elif any(kw in title_lower for kw in ['锂', '电池', '新能源']):
        return '关注锂价波动对冲/储能集成，止损8%'
    elif any(kw in title_lower for kw in ['降息', '央行', '利率']):
        return '关注利率敏感型资产(地产/券商)，止损5%'
    elif any(kw in title_lower for kw in ['光伏', '储能', '电网']):
        return '关注储能系统集成商，止损10%'
    else:
        return '关注产业链上下游价差套利，止损5%'


def _fallback_gap_scan(top_items):
    """降级: 缺口扫描"""
    matched = _match_chains(top_items)
    lines = ["## 二、市场/中间人缺口扫描\n"]
    lines.append("> （降级模式）基于今日新闻关键词推断的供需缺口:\n")

    if matched:
        for i, ch in enumerate(matched[:2]):
            lines.append(f"- **缺口类型**: {ch['chain'][0]} → {ch['chain'][-1]}")
            lines.append(f"  - 收钱模式: {ch['gap']}")
            lines.append(f"  - 规避路径: 关注政策反转信号，设置2周观察期")
            lines.append(f"  - 窗口期: 2-4周，传导链末端信号出现后收网")
    else:
        lines.append("- **缺口类型**: 供应链中间环节 (基于新闻综合推断)")
        lines.append("  - 收钱模式: 信息差撮合/供应链整合")
        lines.append("  - 规避路径: 关注政策反转信号")
        lines.append("  - 窗口期: 2-4周")

    return "\n".join(lines)


def _fallback_contra_tide(top_items):
    """降级: 逆潮观察"""
    matched = _match_chains(top_items)
    lines = ["## 三、逆潮观察\n"]
    lines.append("> （降级模式）基于传导链模板的逆向思考:\n")

    if matched:
        ch = matched[0]
        lines.append(f"- **市场共识**: {ch['chain'][0]}是主要方向")
        lines.append(f"  - 逆向可能: {ch['tide']}")
        lines.append(f"  - 逆向下注: 在传导链末端寻找反向机会")
        lines.append(f"  - 止损线: 传导信号连续3天弱化则撤")
    else:
        lines.append("- **市场共识**: 当前主流叙事")
        lines.append("  - 逆向可能: 共识越强，反转越猛")
        lines.append("  - 逆向下注: 在恐慌中找折价资产")
        lines.append("  - 止损线: 共识持续强化2周则认错")

    return "\n".join(lines)


def _fallback_deep_chain(top_items):
    """降级: 深度传导分析"""
    matched = _match_chains(top_items)
    lines = ["## 四、深度传导分析\n"]
    lines.append("> （降级模式）基于传导链模板的5层推导:\n")

    if matched:
        ch = matched[0]
        for i, step in enumerate(ch['chain'][:5], 1):
            lines.append(f"- 第{i}层: {step}")
        lines.append(f"\n🔮 **天之道**: 损有余补不足 — {ch['chain'][0]}有余，{ch['chain'][-1]}不足")
        lines.append(f"⚡ **邪修之道**: 在有余和不足之间做中间人收过路费")
    else:
        lines.append("- 第1层: 今日核心事件 (AI分析暂不可用)")
        lines.append("- 第2层: 第一波冲击波")
        lines.append("- 第3层: 产业链传导")
        lines.append("- 第4层: 跨产业扩散")
        lines.append("- 第5层: 终局推演")
        lines.append("\n🔮 **天之道**: 损有余补不足")
        lines.append("⚡ **邪修之道**: 在有余和不足之间收过路费")

    return "\n".join(lines)


def _fallback_pitfall(top_items):
    """降级: 避坑提醒"""
    lines = ["## 五、避坑提醒\n"]
    lines.append("> （降级模式）通用避坑提醒:\n")

    # 基于最高分新闻推断可能的坑
    if top_items:
        top_title = top_items[0]['title']
        lines.append(f"- ⚠️ **陷阱**: 「{top_title[:30]}」可能被过度解读")
        lines.append(f"  - 为什么是坑: 新闻热度≠投资机会，多数人在热点最高潮入场")
        lines.append(f"  - 止损建议: 热度消退后3天内离场")
    else:
        lines.append("- ⚠️ **陷阱**: 追热点容易在山顶站岗")
        lines.append("  - 为什么是坑: 热度最高时往往价格最高")
        lines.append("  - 止损建议: 入场前设5%止损线")

    return "\n".join(lines)


def _fallback_quote(top_items):
    """降级: 邪修金句"""
    memory = _load_xie_xiu_memory()
    used_quotes = memory.get('quotes', [])[-7:]

    # 基于新闻主题生成降级金句
    if top_items:
        top_title = top_items[0]['title']
        # 用标题的hash选一个金句模板
        h = int(hashlib.md5(top_title.encode()).hexdigest()[:8], 16)
        templates = [
            f"所有人都在看{top_title[:10]}的时候，邪修在看谁在为这个消息付钱",
            f"新闻是果不是因——{top_title[:10]}背后的钱流方向才是邪修的方向",
            f"天之道让{top_title[:8]}回归均值，邪修之道在均值回归前收手",
            f"当{top_title[:10]}成了所有人的共识，就是邪修反向布局的时候",
            f"信息差不是知道更多，是比别人早一步知道{top_title[:8]}意味着什么",
        ]
        quote = templates[h % len(templates)]
        # 避免和近期金句重复
        if quote in used_quotes:
            quote = f"看穿{top_title[:10]}的本质——谁在赚钱，谁在亏钱，邪修跟赚钱的人走"
    else:
        quote = "看不见的手在调价，邪修在手经过的地方收过路费"

    return f"## 六、今日邪修金句\n\n💭 {quote}"


# ============================================================
# 邮件发送
# ============================================================
def send_email(subject, body):
    """发送邮件: Markdown正文+HTML渲染双格式"""
    if not SMTP_PASS:
        logging.warning("[邮件] SMTP密码未配置，跳过发送")
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_TO
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    try:
        import markdown as md
        html_body = md.markdown(body, extensions=['extra', 'nl2br'])
        html_wrapped = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
            font-size:15px;line-height:1.7;color:#333;max-width:680px;margin:0 auto;padding:20px;">
            {html_body}</body></html>"""
        msg.attach(MIMEText(html_wrapped, 'html', 'utf-8'))
    except Exception as e:
        logging.warning(f"[邮件] Markdown渲染失败，降级纯文本: {e}")
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


# ============================================================
# 彩票部分
# ============================================================
def generate_lottery_section():
    """生成彩票部分: 由JinZhu核心大脑统一生成展示内容"""
    try:
        from jin_zhu import JinZhu
        jz = JinZhu()
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐生成失败: JinZhu初始化异常({e})\n---\n"

    # JinZhu闭环: 结算→进化→生成推荐
    try:
        daily_result = jz.daily_run()
        logging.info(f"[彩票] ✅ JinZhu闭环完成: settle={bool(daily_result.get('settle'))}, evolve={bool(daily_result.get('evolve'))}")
    except Exception as e:
        logging.warning(f"[彩票] ⚠️ JinZhu闭环异常(不阻塞): {e}")
        daily_result = {}

    # 由JinZhu核心大脑统一生成展示内容
    try:
        if hasattr(jz, 'generate_daily_section'):
            return jz.generate_daily_section(daily_result)
        else:
            return _fallback_lottery_display()
    except Exception as e:
        logging.error(f"[彩票] ⚠️ JinZhu展示生成异常: {e}")
        return _fallback_lottery_display()


def _fallback_lottery_display():
    """降级: 从lottery-predictions.json读取展示"""
    pred_file = os.path.join(MODULE_DIR, 'lottery-predictions.json')
    if not os.path.exists(pred_file):
        return "\n---\n## 🎰 彩票推荐\n（lottery-predictions.json 未找到）\n---\n"

    try:
        with open(pred_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        lines = ['\n---\n## 🎰 彩票号码推荐 — 刘海蟾点金',
                 '> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n']

        if isinstance(data, list):
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
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐\n（数据读取异常: {e}）\n---\n"


# ============================================================
# 台湾彩种
# ============================================================
def generate_taiwan_section():
    """生成台湾威力彩(PLN)和大乐透(LTN)推荐"""
    try:
        from generate_taiwan import generate_pln_recommendations, generate_ltn_recommendations
        pln = generate_pln_recommendations()
        ltn = generate_ltn_recommendations()
        return f"\n{pln}\n\n{ltn}"
    except Exception as e:
        logging.warning(f"[台湾彩] 生成失败: {e}")
        return "\n---\n## 🎰 台湾彩种\n（生成异常，下次自动恢复）\n---\n"


# ============================================================
# 主流程
# ============================================================
if __name__ == '__main__':
    logging.info(f"========== 生成完整日报 V6 {today_str} ==========")

    # 1. 生成6板块新闻分析 (主路径: AI, 降级: 关键词推断)
    try:
        news_content = _run_with_timeout(generate_all_sections, timeout=200)
    except TimeoutError:
        logging.warning("[P1] 新闻生成超时(200秒)")
        news_content = _fallback_all_sections([], [])
    except Exception as e:
        logging.error(f"[P1] 新闻生成异常: {e}")
        news_content = _fallback_all_sections([], [])

    # 2. 生成彩票部分
    try:
        lottery_content = generate_lottery_section()
    except Exception as e:
        logging.error(f"[P1] 彩票生成异常: {e}")
        lottery_content = "## 🎰 彩票推荐\n（今日彩票生成异常，下次自动恢复）\n"

    # 3. 生成台湾彩种
    try:
        taiwan_content = generate_taiwan_section()
    except Exception as e:
        logging.warning(f"[P1] 台湾彩种异常: {e}")
        taiwan_content = ""

    # 4. 拼接完整日报
    full_content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}{taiwan_content}"

    # 5. 质量守护 — 发送前验证
    try:
        from daily_report_guard import validate_report
        guard_result = validate_report(full_content)
        if guard_result['valid']:
            logging.info(f"[守护] ✅ 日报质量通过 (得分: {guard_result['score']}/100)")
        else:
            logging.warning(f"[守护] ⚠️ 日报质量问题: {guard_result['errors']}")
            # 仍然发送，但记录问题
    except Exception as e:
        logging.warning(f"[守护] 验证异常(不阻塞): {e}")

    # 6. 写文件
    output_path = os.path.join(output_dir, f"{today_str}.md")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        logging.info(f"✅ 已写入: {output_path} ({len(full_content)}字符)")
    except Exception as e:
        logging.error(f"[P0] 写入日报文件失败: {e}")
        try:
            fallback_path = f"/tmp/daily-report-{today_str}.md"
            with open(fallback_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            logging.info(f"✅ 兜底写入: {fallback_path}")
        except Exception as e2:
            logging.error(f"[P0] 兜底写入也失败: {e2}")

    # 7. 发邮件
    if not SMTP_PASS:
        logging.warning("[P1] SMTP密码未配置，跳过邮件发送")
    else:
        try:
            subject = '阿算帮刘老板发财日报 | ' + today_str
            send_email(subject, full_content)
        except Exception as e:
            logging.error(f"[P1] 邮件发送异常: {e}")

    logging.info(f"========== 完成 {today_str} ==========")
