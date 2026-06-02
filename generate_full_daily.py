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
    """用subprocess执行AI调用，超时则跳过（避免线程池卡死）"""
    import multiprocessing
    with multiprocessing.Pool(processes=1) as pool:
        result = pool.apply_async(func)
        try:
            return result.get(timeout=timeout)
        except multiprocessing.TimeoutError:
            raise TimeoutError(f"AI调用超时({timeout}秒)")


# ============================================================
# 用户画像: 关键词权重 (正=感兴趣, 负=不感兴趣)
# ============================================================
USER_PROFILE_V7 = {
    # ====== 大宗商品/价格信号 (传导预判核心) ======
    '涨价': 5, '暴跌': 5, '缺货': 5, '断供': 5, '停产': 5,
    '铜价': 5, '铝价': 5, '钢价': 4, '油价': 4, '煤价': 4,
    '硫酸': 5, '硫磺': 5, '磷肥': 4, '钛白粉': 4, '锂价': 4,
    '期货': 4, '现货': 4, '库存': 4, '减产': 4, '扩产': 3,
    '加工费': 4, '替代': 4, '供给': 4, '需求': 3,
    '出口禁令': 5, '出口管制': 5, '制裁': 4, '关税': 4,
    '冶炼': 3, '矿': 3, '废铜': 3, '废钢': 3, '回收': 3,
    # ====== AI/大模型 ======
    'AI': 4, '人工智能': 4, '大模型': 4, 'DeepSeek': 4,
    'GPT': 3, 'Claude': 3, 'AGI': 3, 'LLM': 3, '开源模型': 3,
    'AI应用': 3, 'AI Agent': 3, '智能体': 3, '自动化': 2,
    # ====== 算力/芯片 ======
    '算力': 4, 'GPU': 4, '英伟达': 3, 'NVIDIA': 3, '黄仁勋': 2,
    '芯片': 3, '半导体': 3, '台积电': 3, '光刻': 2, '晶圆': 2,
    'H100': 2, 'H200': 2, 'B200': 2, 'CUDA': 2,
    # ====== 新能源/电动车 ======
    '新能源': 4, '电动车': 4, '电池': 3, '充电桩': 3,
    '光伏': 3, '储能': 3, '碳中和': 2, '电网': 4,
    # ====== 搞钱/进出口/出海 ======
    '进出口': 4, '出口': 4, '进口': 3, '外贸': 4,
    '出海': 4, '跨境': 4, '跨境电商': 3, '汇率': 4,
    '副业': 3, '搞钱': 3, '赚钱': 3, '信息差': 4,
    '创业': 2, '融资': 2, '上市': 2, '投资': 2, '营收': 2,
    '蓝海': 3, '供需': 4, '缺口': 5, '垄断': 2,
    '供应链': 4, '代工': 2, '贴牌': 2, 'OEM': 2,
    # ====== 政策/宏观 ======
    '政策': 4, '补贴': 3, '免税': 3, '减税': 2, '新规': 4,
    '央行': 4, '降息': 4, '加息': 4, '流动性': 3,
    '裁员': 2, '亏损': 3, '逆势': 3, '关停': 4,
    # ====== 科技/产业（调整） ======
    '手机': 1, '华为': 2, '小米': 1, '苹果': 1,
    '机器人': 3, '无人驾驶': 2, '自动驾驶': 2,
    '5G': 1, '通信': 1, '数字化': 1,
    '腾讯': 4, '互联网大厂': 3, '平台经济': 3, '社交电商': 3,

    # ====== V7新增: 台湾/两岸套利（刘老板专属战场） ======
    '台湾': 5, '台北': 4, '高雄': 3, '台中': 3, '台南': 3,
    '两岸': 5, '台海': 4, '陆资': 4, '台资': 3, '台商': 4,
    '小三通': 4, '金门': 4, '马祖': 3, '福建': 3,
    '汇差': 4, '人民币': 5, '新台币': 4, '跨境汇款': 4,
    '自由行': 3, '观光': 3, '夜市': 2, '小吃': 3,
    '台湾旅游': 4, '台湾签证': 3, '健保': 3,

    # ====== V7新增: 直销/分销/餐饮商业模式 ======
    '直销': 5, '分销': 5, '层级': 4, '加盟': 5, '代理': 5,
    '餐饮': 5, '甜品': 4, '冰淇淋': 4, '绵绵冰': 5, '冷链': 4,
    '食品': 4, '饮品': 4, '奶茶': 3, '小吃连锁': 4,
    '尚赫': 5, '安利': 3, '如新': 3, '多层次': 4,
    '直销牌照': 5, '团队计酬': 4, '金字塔': 3,
    '中央厨房': 4, '预制菜': 3, '餐饮出海': 5,

    # ====== V7新增: 威士忌/酒类 ======
    '威士忌': 5, 'Kavalan': 5, '金车': 5, '噶玛兰': 5,
    '单一麦芽': 4, '桶强': 4, '雪莉桶': 4, '波本桶': 4,
    '葡萄酒桶': 4, '白兰地桶': 4, '勾兑': 4, '年份': 4,
    '蒸馏': 3, '橡木桶': 3, '烈酒': 3, '原酒': 4,
    '威士忌收藏': 5, '威士忌投资': 5, '拍卖': 3,

    # ====== V7新增: 信仰经济 ======
    '庙宇': 5, '供奉': 5, '开光': 5, '法会': 5, '香火': 4,
    '线上庙宇': 5, '财神': 5, '赵公明': 5, '祈福': 3,
    '信仰经济': 5, '供奉品': 4, '线上供养': 4,
    '刘海蟾': 5, '金蟾': 4, '财神爷': 4, '线上法会': 5,

    # ====== V7修正: 彩票/博彩产业（从-2→+5） ======
    '彩票': 5, '博彩': 3, '彩券': 5, '威力彩': 5, '大乐透': 5,
    '公益彩券': 4, '台彩': 5, '中国体育彩票': 4, '双色球': 4,
    '七星彩': 4, '乐透': 4, '刮刮乐': 2, '派彩': 4,
    '台彩公司': 5, '彩券商': 5, '彩票经销': 5, '运动彩券': 3,

    # ====== 负面: 不感兴趣（保持不变） ======
    '明星': -3, '综艺': -3, '恋情': -3, '离婚': -3, '出轨': -3,
    '八卦': -4, '饭圈': -4, '偶像': -3, '选秀': -3, '粉丝': -2,
    '娱乐圈': -4, '网红': -2, '直播带货': -1,
    '体育': -1, '足球': -1, '篮球': -1, 'NBA': -1, '世界杯': -1,
    '赌博': -3,  # 赌博仍然负面，彩票已单独提升
    '剧情': -2, '电视剧': -2, '电影': -1, '追剧': -2,
    '减肥': -1, '美容': -1, '美妆': -1,
}


def score_news(item):
    """根据用户画像给新闻打分"""
    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
    score = 0
    for keyword, weight in USER_PROFILE_V7.items():
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
    # ====== 通用大宗/科技传导链（保留，调整为9条） ======
    {'trigger': ['铜价', '铜', '铜矿'], 'chain': ['铜矿减产/涨价', '冶炼加工费压缩', 'PCB/电机成本上升', '电动车/家电涨价', '替代材料(铝)需求增'], 'gap': '铜铝价差套利/废铜回收/台湾冶炼厂中间人', 'tide': '铜价涨→大家看空需求→实际中国基建托底'},
    {'trigger': ['AI', '算力', 'GPU', '英伟达'], 'chain': ['大模型训练需求爆发', 'GPU/HBM供不应求', '散热/电源/PCB配套涨', '数据中心建设加速', '电力消耗激增→核电/绿电'], 'gap': '算力中间商/散热材料/数据中心电力', 'tide': 'AI概念过热→短期回调→但算力需求是实打实的'},
    {'trigger': ['锂价', '电池', '新能源'], 'chain': ['锂价暴跌/暴涨', '电池成本变化', '电动车定价策略', '传统车企转型压力', '充电桩/储能配套'], 'gap': '锂价波动对冲/电池回收/储能系统集成', 'tide': '锂价跌→短期看空→但储能需求是新增量'},
    {'trigger': ['出口', '关税', '制裁', '贸易'], 'chain': ['出口管制/关税调整', '供应链被迫重组', '转口贸易/第三国中转', '合规成本上升', '替代市场开拓'], 'gap': '转口贸易服务商/合规咨询/替代供应链', 'tide': '制裁加码→短期恐慌→但转口贸易利润更高'},
    {'trigger': ['汇率', '人民币', '美元'], 'chain': ['汇率波动', '出口企业利润变化', '跨境结算需求', '对冲工具需求', '海外资产配置'], 'gap': '跨境结算服务商/汇率对冲咨询', 'tide': '人民币贬值→短期利好出口→但通胀压力'},
    {'trigger': ['磷肥', '硫酸', '硫磺'], 'chain': ['硫磺/硫酸供应紧张', '磷肥生产成本上升', '粮食生产成本增加', '化肥替代/减量技术', '粮食安全政策'], 'gap': '硫酸替代技术/磷肥中间商/粮食套利', 'tide': '化肥涨价→短期恐慌→但替代技术正在成熟'},
    {'trigger': ['光伏', '储能', '电网'], 'chain': ['光伏装机量激增', '储能配套不足', '电网调度压力', '虚拟电厂需求', '电力市场化交易'], 'gap': '储能系统集成/虚拟电厂/电力交易', 'tide': '光伏产能过剩→短期看空→但消纳瓶颈催生新业态'},
    {'trigger': ['半导体', '芯片', '台积电'], 'chain': ['芯片制程突破/受限', '代工产能重新分配', '国产替代加速', '设备/材料需求', '终端产品成本变化'], 'gap': '国产替代中间人/设备维护/材料供应', 'tide': '制程受限→短期看空→但国产替代是长期趋势'},

    # ====== V2新增: 刘老板专属战场 ======
    # 链9: 台湾两岸套利
    {'trigger': ['台湾', '两岸', '小三通', '金门', '台海'],
     'chain': ['两岸政策松动/收紧', '小三通/直航流量变化', '金门中转仓储角色', '台商资金流调整', '大陆商品→台湾渠道重组或台湾→大陆反套利'],
     'gap': '两岸小额贸易中间人/跨境支付渠道/金门仓储中转/台币人民币汇差套利',
     'tide': '政策收紧→短期恐慌→但民间灰色渠道利润更高；政策宽松→表面利好→但竞争加剧'},

    # 链10: 直销→餐饮连锁转型
    {'trigger': ['直销', '分销', '加盟', '尚赫', '安利', '如新'],
     'chain': ['直销牌照审批/行业整顿', '多层分销模式合规成本上升', '代理体系被迫转型社交电商', '线下体验+线上裂变融合', '餐饮/食品连锁加盟成新载体'],
     'gap': '直销转型加盟咨询服务/合规架构设计/供应链金融垫资/培训体系输出',
     'tide': '直销被打压→短期看空→但百万直销人员转型需求催生千亿级服务市场'},

    # 链11: 大陆餐饮→台湾出海
    {'trigger': ['餐饮', '甜品', '绵绵冰', '冰淇淋', '奶茶', '冷链'],
     'chain': ['大陆餐饮品牌寻找出海第一站', '台湾作跳板测试华人市场', '冷链/中央厨房本地化', '加盟代理体系铺设', '品牌溢价→台湾本地消费升级'],
     'gap': '跨境餐饮品牌代理权/冷链物流共享仓/中央厨房代运营/加盟商招募',
     'tide': '大陆品牌出海热→短期抢渠道→但供应链和本地化才是壁垒'},

    # 链12: 威士忌年份/桶型套利
    {'trigger': ['威士忌', 'Kavalan', '噶玛兰', '金车', '单一麦芽', '桶强'],
     'chain': ['原酒进口成本或国产替代加速', '特定桶型/年份减产→稀缺溢价', '收藏级威士忌拍卖市场', '消费税/关税政策调整', '高端消费收缩→反而是抄底窗口'],
     'gap': '年份酒跨市场价差套利/桶装原酒投资/特定桶型囤货/限量版代购',
     'tide': '消费降级→短期看空威士忌→但高端稀缺性反而加强，k型分化'},

    # 链13: 信仰经济变现
    {'trigger': ['线上庙宇', '信仰经济', '供奉', '开光', '法会', '财神', '赵公明'],
     'chain': ['线上信仰服务平台涌现', '用户付费意愿验证（ARPU高得惊人）', '平台抽成/佣金/会员模式', '线下寺庙被迫数字化', '信仰+电商/直播/AI开光新形态'],
     'gap': '线上供养平台代运营/庙宇数字化SaaS/信仰商品供应链/AI法会技术输出',
     'tide': '线上信仰→被看作小众→但复购率和客单价远超预期，沉默的百亿市场'},

    # 链14: 彩票产业套利
    {'trigger': ['彩票', '彩券', '威力彩', '大乐透', '台彩', '公益彩券'],
     'chain': ['彩券销量/政策变化', '经销牌照价值变动', '线上/线下渠道博弈', '奖池累积→衍生金融工具', '跨境代购/合买组织兴起'],
     'gap': '台彩经销权转售/跨区套利/线上合买平台/赔率差套利',
     'tide': '彩票被看作负和游戏→但经销和平台是稳赚不赔的收税模式'},
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
    """加载邪修记忆库（冷启动自动初始化）"""
    if os.path.exists(XIE_XIU_MEMORY_PATH):
        try:
            with open(XIE_XIU_MEMORY_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'chains' in data and 'quotes' in data:
                    return data
        except Exception:
            pass

    # 冷启动: 初始化记忆库种子
    seed_memory = {
        'chains': [
            {'date': '2026-06-02', 'trigger': '系统冷启动', 'chain': '初始化→画像V7→台湾切入→邪修专属战场→每日进化'},
        ],
        'quotes': [
            "邪修之道：在有余和不足之间收过路费",
            "天之道损有余补不足，邪修之道损有余为己用",
            "所有人看新闻，邪修看新闻背后的钱流",
        ],
        'validated_patterns': [],
    }
    # 写回磁盘
    _save_xie_xiu_memory(seed_memory)
    logging.info("[邪修] 记忆库冷启动: 已初始化种子数据")
    return seed_memory


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
    # V7新增: 台湾视角新闻源
    '中央社': 'https://www.cna.com.tw/rss/cna/rss.aspx?topic=first',
    '经济日报': 'https://money.udn.com/rssfeed/news/1001/5588/12040?ch=money',
}

    all_raw = []
    source_stats = {}
    with ThreadPoolExecutor(max_workers=7) as pool:
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

**⏰ 当前日期: {today_str}** — 所有窗口期、时间节点必须基于此日期推算，禁止使用2024/2025等过期年份。

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
  - 窗口期: [从{today_str}起算，大概多久，什么信号消失就撤。必须用2026年的日期，禁止用2024/2025]

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
7. ⏰ 所有时间节点（窗口期/周期/截止日）必须基于当前日期{today_str}推算，禁止出现2024/2025等过期年份
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
    """降级: 缺口扫描 — V7版基于关键词推断，含资金匹配+行动标志"""
    lines = ["## 二、市场/中间人缺口扫描\n"]
    lines.append("> （降级模式）基于今日新闻关键词的供需缺口推断:\n")

    # 从新闻中提取关键信号词
    signal_keywords = _extract_signal_keywords(top_items)

    gaps_found = 0
    for kw, context in signal_keywords.items():
        if gaps_found >= 2:
            break

        # 基于关键词推断缺口
        if kw in ['台湾', '两岸', '小三通']:
            lines.append(f"- **缺口类型**: 两岸渠道 — {context[:30]}")
            lines.append("  - 收钱模式: 小额贸易中间撮合/跨境支付通道/汇差套利")
            lines.append("  - 规避路径: 关注两岸政策风向，合法合规为前提，先小额试点")
            lines.append("  - 窗口期: 政策窗口通常3-6个月，下一次ECFA/小三通评估节点为关键信号")
            lines.append(f"  - 💰 资金匹配: 200-300万级别，可分3批入场，首期50万测试渠道")
        elif kw in ['直销', '分销', '加盟', '尚赫']:
            lines.append(f"- **缺口类型**: 直销转型服务 — {context[:30]}")
            lines.append("  - 收钱模式: 合规架构咨询/代理体系重设计/培训+供应链输出")
            lines.append("  - 规避路径: 避开纯拉人头模式，绑定实体产品（如餐饮）做合规防火墙")
            lines.append("  - 窗口期: 牌照审批周期6-12个月，在窗口期内抢占转型客户")
            lines.append(f"  - 💰 资金匹配: 100-200万启动咨询+样板店，ROI 6-12月验证期")
        elif kw in ['餐饮', '甜品', '绵绵冰', '冷链']:
            lines.append(f"- **缺口类型**: 餐饮跨境代理/供应链 — {context[:30]}")
            lines.append("  - 收钱模式: 品牌区域代理费/中央厨房代运营/冷链共享仓收费")
            lines.append("  - 规避路径: 先签独家代理条款，锁定区域避免品牌直营后踢掉代理")
            lines.append("  - 窗口期: 大陆品牌出海热预计持续12-18个月，首批代理跑通后品牌会直营")
            lines.append(f"  - 💰 资金匹配: 150-250万含加盟费+装修+首年运营，6个月内盈亏平衡")
        elif kw in ['威士忌', 'Kavalan', '噶玛兰', '单一麦芽']:
            lines.append(f"- **缺口类型**: 年份酒/桶型套利 — {context[:30]}")
            lines.append("  - 收钱模式: 限量版跨市场价差/桶装原酒投资/拍卖代拍费")
            lines.append("  - 规避路径: 假酒风险是最大坑，必须通过官方渠道或认证拍卖行")
            lines.append("  - 窗口期: 特定桶型停产到市场消化约3-6个月，拍卖季前后价差最大")
            lines.append(f"  - 💰 资金匹配: 单瓶5-30万，组合投资50-200万，年化8-15%预期")
        elif kw in ['线上庙宇', '信仰经济', '供奉', '开光']:
            lines.append(f"- **缺口类型**: 信仰数字化服务 — {context[:30]}")
            lines.append("  - 收钱模式: 平台抽成15-30%/SaaS年费/信仰商品供应链差价")
            lines.append("  - 规避路径: 宗教合规是前提，避开政治敏感的庙宇，聚焦财神/祈福类")
            lines.append("  - 窗口期: 线上信仰窗口还在早期，预计2-3年跑出头部平台")
            lines.append(f"  - 💰 资金匹配: 50-100万可启动MVP，3-6月验证ARPU，再追加")
        elif kw in ['彩票', '彩券', '台彩', '威力彩']:
            lines.append(f"- **缺口类型**: 彩票经销/渠道套利 — {context[:30]}")
            lines.append("  - 收钱模式: 台彩经销权转让/线上合买平台抽佣/跨境代购服务费")
            lines.append("  - 规避路径: 台彩经销权转让需经台彩公司批准，注意合规风险")
            lines.append("  - 窗口期: 合买/代购模式处于灰色地带，政策明朗前快速收割")
            lines.append(f"  - 💰 资金匹配: 经销权30-100万，平台50-150万启动，月流水可达百万")
        elif kw in ['涨价', '缺货', '断供', '铜', '铝', '钢', '硫酸', '锂']:
            lines.append(f"- **缺口类型**: 供应链价差/替代套利 — {context[:30]}")
            lines.append("  - 收钱模式: 信息撮合/替代材料推荐/废料回收差价")
            lines.append("  - 规避路径: 别赌单方向，做中间人收撮合费而不是持仓")
            lines.append("  - 窗口期: 供给冲击信号出现后2-4周最活跃，替代方案出现后窗口关闭")
            lines.append(f"  - 💰 资金匹配: 50-100万流动资金做撮合，不做库存持仓")
        else:
            lines.append(f"- **缺口类型**: 信息差套利 — {context[:30]}")
            lines.append("  - 收钱模式: 产业链上下游信息撮合/中间人佣金")
            lines.append("  - 规避路径: 不持仓、不囤货，只收信息撮合费")
            lines.append("  - 窗口期: 新闻热度持续期间，通常1-3周")
            lines.append(f"  - 💰 资金匹配: 10-50万流动资金即可运作")

        gaps_found += 1

    # 如果不足2个缺口，补充通用缺口
    while gaps_found < 2:
        lines.append(f"- **缺口类型**: 跨领域信息差 (基于综合新闻推断)")
        lines.append("  - 收钱模式: 信息撮合/咨询服务/中介抽佣")
        lines.append("  - 规避路径: 先收定金再服务，避免白嫖咨询")
        lines.append("  - 窗口期: 2-4周持续评估")
        lines.append(f"  - 💰 资金匹配: 知识变现为主，资金需求低")
        gaps_found += 1

    # 用户当前可行动标记
    lines.append(f"\n> 📍 **当前可行动**: 刘老板在台湾(至6/16-17)，以上缺口涉及台湾的项优先考察，"
                 f"大陆相关的项先标记等回沪后启动。")

    return "\n".join(lines)


def _fallback_contra_tide(top_items):
    """降级: 逆潮观察 — V7版基于新闻关键词推断逆向下注方向"""
    lines = ["## 三、逆潮观察\n"]
    lines.append("> （降级模式）基于今日新闻的逆向信号检测:\n")

    if not top_items:
        lines.append("- **市场共识**: 当前主流叙事")
        lines.append("  - 逆向可能: 共识越强，反转越猛")
        lines.append("  - 逆向下注: 在恐慌中找折价资产")
        lines.append("  - 止损线: 共识持续强化2周则认错")
        return "\n".join(lines)

    # 从最高分新闻出发推断逆潮
    top = top_items[0]
    title = top.get('title', '')
    title_lower = title.lower()

    # 检测共识倾向
    if any(kw in title_lower for kw in ['暴涨', '疯抢', '热', '爆发', 'ALL IN']):
        consensus = f"'{title[:25]}' → 市场共识偏向狂热"
        reverse = "涨过头必有回调——关注库存积压/产能释放信号"
        bet = "做空或减仓相关资产，等回调20%以上再入场"
        stop = "价格再涨15%且基本面持续强化，则逆向判断错误"
    elif any(kw in title_lower for kw in ['暴跌', '崩', '恐慌', '裁', '关停']):
        consensus = f"'{title[:25]}' → 市场共识偏向恐慌"
        reverse = "恐慌出清后强势玩家市占率上升——关注龙头"
        bet = "在恐慌底部布局行业龙头/核心资产，分批建仓"
        stop = "负面信号持续3周无缓和，则恐慌不是暂时的"
    elif any(kw in title_lower for kw in ['新规', '政策', '监管', '整顿']):
        consensus = f"'{title[:25]}' → 市场共识偏向悲观"
        reverse = "政策从发文到执行有时间差，且执行往往打折"
        bet = "趁市场过度反应时反向布局受影响资产"
        stop = "政策细则出台后确实严格，则逆向判断错误"
    else:
        consensus = f"'{title[:25]}' → 市场共识尚未形成明确方向"
        reverse = "不确定性本身就是机会——多数人在等确定性时，邪修先布局"
        bet = "小仓位试探性下注，等共识形成后反向操作"
        stop = "方向明确后价格已跑出20%以上则追不划算"

    lines.append(f"- **市场共识**: {consensus}")
    lines.append(f"  - 逆向可能: {reverse}")
    lines.append(f"  - 逆向下注: {bet}")
    lines.append(f"  - 止损线: {stop}")

    return "\n".join(lines)


def _fallback_deep_chain(top_items):
    """降级: 深度传导分析 — V7版基于新闻逐层推导5层，非模板填充"""
    lines = ["## 四、深度传导分析\n"]
    lines.append("> （降级模式）基于今日新闻的5层传导推导:\n")

    if not top_items:
        lines.append("- 第1层: 今日核心事件 (数据不足)")
        lines.append("- 第2层: 第一波冲击波")
        lines.append("- 第3层: 产业链传导")
        lines.append("- 第4层: 跨产业扩散")
        lines.append("- 第5层: 终局推演")
        lines.append("\n🔮 **天之道**: 损有余补不足")
        lines.append("⚡ **邪修之道**: 在有余和不足之间收过路费")
        return "\n".join(lines)

    top = top_items[0]
    title = top.get('title', '')
    title_lower = title.lower()
    source = top.get('source', '')

    # 基于新闻关键词推断5层传导（非模板，逐层推导）
    if '台湾' in source or any(kw in title_lower for kw in ['台湾', '两岸', '台']):
        layer1 = f"第1层（事件）: {title}"
        layer2 = "第2层（直接影响）: 两岸人流/物流/资金流短期调整"
        layer3 = "第3层（产业链传导）: 台商资金重新配置→大陆台资工厂产能调整→替代供应链"
        layer4 = "第4层（跨产业传导）: 两岸服务业(旅游/餐饮/金融)→汇率避险需求→人民币/台币跨境结算"
        layer5 = "第5层（终局推演）: 民间灰色渠道受益 > 官方渠道，小额高频交易取代大宗贸易"
        tian_dao = "天之道: 损两岸官方之有余，补民间通道之不足"
        xie_xiu = "邪修之道: 在两岸官方壁垒之间做民间桥梁，收过桥费"
    elif any(kw in title_lower for kw in ['涨价', '跌', '价', '铜', '铝', '硫酸', '锂']):
        layer1 = f"第1层（事件）: {title}"
        layer2 = "第2层（直接影响）: 相关下游产品成本变化→终端消费品定价调整"
        layer3 = "第3层（产业链传导）: 替代材料需求上升→替代品供应商利润→新供应商格局"
        layer4 = "第4层（跨产业传导）: 成本上升传导至物流/包装→电商平台→消费者"
        layer5 = "第5层（终局推演）: 第一个找到替代方案的人赚最多，中间撮合者稳赚不赔"
        tian_dao = "天之道: 损涨价商品之有余，补替代方案之不足"
        xie_xiu = "邪修之道: 不在价格涨跌上赌方向，在供需断裂处做中间人"
    elif any(kw in title_lower for kw in ['直销', '分销', '加盟', '餐饮', '甜品']):
        layer1 = f"第1层（事件）: {title}"
        layer2 = "第2层（直接影响）: 商业模式合规评估→行业洗牌→强者恒强"
        layer3 = "第3层（产业链传导）: 供应链金融需求→培训/系统服务商→物流冷链配套"
        layer4 = "第4层（跨产业传导）: 餐饮出海→品牌管理→加盟商融资→房产租赁"
        layer5 = "第5层（终局推演）: 有实体产品的分销体系存活，纯拉人头的出局"
        tian_dao = "天之道: 损纯拉人头之有余，补产品+服务之不足"
        xie_xiu = "邪修之道: 在模式转型的混乱期，帮人从旧模式切到新模式收转型税"
    elif any(kw in title_lower for kw in ['威士忌', '酒', 'Kavalan', '噶玛兰']):
        layer1 = f"第1层（事件）: {title}"
        layer2 = "第2层（直接影响）: 特定品类稀缺溢价→收藏市场反应→拍卖价格波动"
        layer3 = "第3层（产业链传导）: 酒厂扩产/减产→橡木桶供应→包装/物流"
        layer4 = "第4层（跨产业传导）: 高端消费→体验经济→旅游/品鉴→社交货币"
        layer5 = "第5层（终局推演）: 品牌价值和稀缺性决定长期回报，短期波动是入场窗口"
        tian_dao = "天之道: 损短期炒作之有余，补长期稀缺之不足"
        xie_xiu = "邪修之道: 在恐慌抛售时接盘，在狂热追高时出货"
    elif any(kw in title_lower for kw in ['AI', '算力', '大模型', 'GPU']):
        layer1 = f"第1层（事件）: {title}"
        layer2 = "第2层（直接影响）: 算力需求激增→GPU供不应求→配套产业链"
        layer3 = "第3层（产业链传导）: 散热/电源/PCB→数据中心→电力→核能/绿电"
        layer4 = "第4层（跨产业传导）: AI应用落地→各行业效率提升→岗位替代→新工种"
        layer5 = "第5层（终局推演）: 卖铲子的(算力/工具)稳赚，淘金的(AI应用)99%会死"
        tian_dao = "天之道: 损AI概念股之有余，补算力基础设施之不足"
        xie_xiu = "邪修之道: 不赌哪个AI公司赢，在算力链条每个环节收过路费"
    elif any(kw in title_lower for kw in ['信仰', '庙宇', '供奉', '法会', '开光']):
        layer1 = f"第1层（事件）: {title}"
        layer2 = "第2层（直接影响）: 线上信仰平台流量→用户付费转化→内容/服务供给"
        layer3 = "第3层（产业链传导）: 数字供养品→信仰电商→AI加持→线下联动"
        layer4 = "第4层（跨产业传导）: 心理慰藉经济→冥想/正念→酒店/旅游→文化IP"
        layer5 = "第5层（终局推演）: 信仰+技术的结合是超长坡厚雪赛道，复购率碾压SaaS"
        tian_dao = "天之道: 损线下庙宇之有余，补线上信仰之不足"
        xie_xiu = "邪修之道: 在信仰的刚需上建平台抽成，比任何SaaS都稳"
    else:
        layer1 = f"第1层（事件）: {title}"
        layer2 = "第2层（直接影响）: 对相关产业的第一波冲击"
        layer3 = "第3层（产业链传导）: 上游/下游连锁反应"
        layer4 = "第4层（跨产业传导）: 扩散至看似无关的领域"
        layer5 = "第5层（终局推演）: 谁受益、谁受损"
        tian_dao = "天之道: 损有余补不足"
        xie_xiu = "邪修之道: 在有余和不足之间收过路费"

    lines.append(f"- {layer1}")
    lines.append(f"- {layer2}")
    lines.append(f"- {layer3}")
    lines.append(f"- {layer4}")
    lines.append(f"- {layer5}")
    lines.append(f"\n🔮 **{tian_dao}**")
    lines.append(f"⚡ **{xie_xiu}**")

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
    """降级: 邪修金句 — V7版结合新闻内容+记忆库去重"""
    memory = _load_xie_xiu_memory()
    used_quotes = memory.get('quotes', [])[-10:]  # 扩大去重窗口到10条

    if not top_items:
        quote = _gen_unique_quote("眼前的信息", used_quotes)
        return f"## 六、今日邪修金句\n\n💭 {quote}"

    top = top_items[0]
    title = top.get('title', '未知')
    # 提取标题核心名词（5-8字）
    core = title[:12] if len(title) >= 8 else title

    title_lower = title.lower()

    # 基于新闻主题从多个金句角度尝试，取第一个不重复的
    candidates = []

    if any(kw in title_lower for kw in ['台湾', '两岸', '小三通']):
        candidates = [
            f"两岸之间的空隙不是障碍——是邪修的收钱通道",
            f"{core}的新闻出来时，邪修已经在算两岸价差",
            f"政策筑墙越高，墙两边愿意付过墙费的人越多",
        ]
    elif any(kw in title_lower for kw in ['涨价', '跌', '铜', '铝', '硫酸']):
        candidates = [
            f"所有人都在看{core}的价格，邪修在看谁在为这个价格买单",
            f"价格波动是果不是因——{core}背后的供需断裂才是邪修的入场信号",
            f"当{core}成了新闻，大多数人已经错过了最好的窗口",
        ]
    elif any(kw in title_lower for kw in ['直销', '分销', '加盟', '餐饮']):
        candidates = [
            f"{core}的商业模式在变——转型的混乱期就是邪修的收税期",
            f"看得见的是{core}的新闻，看不见的是百万人在找新出路",
            f"旧模式死了新模式还没站稳——中间那个阶段，邪修在收过渡费",
        ]
    elif any(kw in title_lower for kw in ['威士忌', '酒', 'Kavalan']):
        candidates = [
            f"等{core}上了新闻再出手，邪修已经少赚了一轮",
            f"一瓶酒的价格里，只有20%是酒，80%是故事——邪修卖的是故事",
            f"恐慌时接盘{core}的人，和狂热时追高的人，不是同一批人",
        ]
    elif any(kw in title_lower for kw in ['AI', '算力', '大模型']):
        candidates = [
            f"{core}的淘金热里，邪修不淘金——邪修卖铲子和水",
            f"AI泡沫破裂时，卖算力的照收租金——邪修就站在那个位置",
            f"每次{core}上头条，就意味着有一批人已经赚完走了",
        ]
    elif any(kw in title_lower for kw in ['信仰', '庙宇', '供奉', '法会']):
        candidates = [
            f"信徒供养的不是庙——是安全感，邪修做的是安全感的中介",
            f"{core}的复购率比任何SaaS都高——因为信仰不欠费",
            f"科技的尽头是玄学，玄学的尽头是稳定的现金流",
        ]
    else:
        candidates = [
            f"新闻是水面上的波纹，邪修在水下看谁在搅动水流",
            f"{core}——大多数人看标题，邪修看标题背后的钱流方向",
            f"不是所有新闻都是机会，但每条新闻都有人因此赚到钱",
            f"天之道让一切回归均值，邪修之道在回归前离场",
            f"信息差不是知道更多，是比别人早一步知道{core}意味着什么",
        ]

    quote = _gen_unique_quote(core, used_quotes, candidates)

    return f"## 六、今日邪修金句\n\n💭 {quote}"


def _gen_unique_quote(context_hint, used_quotes, candidates=None):
    """生成一句不重复的金句"""
    if not candidates:
        candidates = [
            f"所有人都在看{context_hint}的时候，邪修在看谁在为这个消息付钱",
            f"新闻是果不是因——{context_hint}背后的钱流方向才是邪修的方向",
            f"天之道让{context_hint}回归均值，邪修之道在均值回归前收手",
            f"当{context_hint}成了所有人的共识，就是邪修反向布局的时候",
            f"信息差不是知道更多，是比别人早一步知道{context_hint}意味着什么",
            f"看穿{context_hint}的本质——谁在赚钱，谁在亏钱，邪修跟赚钱的人走",
        ]

    # 选第一个不在used_quotes中的
    for q in candidates:
        if q not in used_quotes:
            return q

    # 全部用过？加时间戳微调
    import hashlib
    seed = int(hashlib.md5(context_hint.encode()).hexdigest()[:8], 16)
    # 用seed微调最后一句
    base = candidates[seed % len(candidates)]
    return f"{base}（第{len(used_quotes)+1}日）"


def _extract_signal_keywords(top_items):
    """从新闻中提取关键信号词和上下文"""
    sig = {}
    for item in top_items[:10]:
        title = item.get('title', '')
        title_lower = title.lower()
        for kw_group in [
            '台湾', '两岸', '小三通', '金门',
            '直销', '分销', '加盟', '尚赫',
            '餐饮', '甜品', '绵绵冰', '冷链',
            '威士忌', 'Kavalan', '噶玛兰', '单一麦芽',
            '线上庙宇', '信仰经济', '供奉', '开光',
            '彩票', '彩券', '台彩', '威力彩',
            '涨价', '缺货', '断供', '铜', '铝', '钢', '硫酸', '锂',
        ]:
            if kw_group in sig:
                continue  # 已有一个同类信号
            if kw_group in title_lower:
                sig[kw_group] = title
        if len(sig) >= 3:
            break
    return sig


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
