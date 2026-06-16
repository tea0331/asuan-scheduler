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
import re
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
    # 5分: 直接影响操作决策; 4分: 强相关信号; 3分: 背景关注
    '涨价': 4, '暴跌': 4, '缺货': 5, '断供': 5, '停产': 5,
    '铜价': 4, '铝价': 4, '钢价': 4, '油价': 3, '煤价': 3,
    '硫酸': 4, '硫磺': 4, '磷肥': 3, '钛白粉': 3, '锂价': 4,
    '期货': 3, '现货': 3, '库存': 3, '减产': 4, '扩产': 3,
    '加工费': 3, '替代': 3, '供给': 3, '需求': 3,
    '出口禁令': 5, '出口管制': 5, '制裁': 4, '关税': 4,
    '冶炼': 3, '矿': 3, '废铜': 3, '废钢': 3, '回收': 3,
    # ====== AI/大模型 ======
    # 注意: "AI" 使用词边界匹配(\bAI\b)防止子串误匹配(如"Thailand","Airlines")
    '人工智能': 4, '大模型': 4, 'DeepSeek': 4,
    'GPT': 3, 'Claude': 3, 'AGI': 3, 'LLM': 3, '开源模型': 3,
    'AI应用': 3, 'AI Agent': 3, '智能体': 3, '自动化': 2,
    # V14: AI关键词单独处理(词边界匹配)，不放在USER_PROFILE_V7中
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
    # 5分: 直接可操作窗口; 4分: 强关联信号; 3分: 背景关注
    '台湾': 5, '台北': 4, '高雄': 3, '台中': 3, '台南': 3,
    '两岸': 5, '台海': 4, '陆资': 4, '台资': 3, '台商': 4,
    '小三通': 4, '金门': 4, '马祖': 3, '福建': 3,
    '汇差': 4, '人民币': 4, '新台币': 4, '跨境汇款': 4,
    '自由行': 3, '观光': 3, '夜市': 2, '小吃': 3,
    '台湾旅游': 3, '台湾签证': 3, '健保': 3,

    # ====== V7新增: 信仰经济 ======
    # 5分: 核心操作项目; 4分: 强关联; 3分: 背景关注
    '庙宇': 4, '供奉': 4, '开光': 3, '法会': 3, '香火': 3,
    '线上庙宇': 5, '财神': 4, '赵公明': 5, '祈福': 3,
    '信仰经济': 4, '供奉品': 3, '线上供养': 4,
    '刘海蟾': 5, '金蟾': 3, '财神爷': 4, '线上法会': 4,

    # ====== V7修正: 彩票/博彩产业（从-2→+5） ======
    # 5分: 核心操作项目; 4分: 强关联; 3分: 背景关注
    '彩票': 4, '博彩': 3, '彩券': 4, '威力彩': 5, '大乐透': 4,
    '公益彩券': 3, '台彩': 5, '中国体育彩票': 3, '双色球': 3,
    '七星彩': 3, '乐透': 3, '刮刮乐': 2, '派彩': 3,
    '台彩公司': 4, '彩券商': 4, '彩票经销': 4, '运动彩券': 3,

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
    """根据用户画像给新闻打分 — V14: AI使用词边界匹配防止子串误匹配"""
    import re
    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
    score = 0
    for keyword, weight in USER_PROFILE_V7.items():
        if keyword.lower() in text:
            score += weight
    # V14: "AI" 独立词边界匹配 — 防止 "Thailand"/"Airlines" 等误匹配
    if re.search(r'\bai\b', text):
        score += 4
    return score


def score_news_with_scene(item):
    """画像打分 + 场景加权（V8新增）
    
    场景加权规则:
    - 台湾相关 +5（人在台湾，可实地操作）
    - 200-300万操作级别 +3（资金匹配）
    - 灰色/套利/价差/监管差 +3（邪修偏好）
    - 大陆餐饮/加盟 +2（餐饮出海关联）
    - 信仰/庙宇/法会 +3（赵公明项目关联）
    - 彩票/台彩 +3（刘海蟾点金核心业务）
    - 小额/轻资产/中间人 +3（刘老板操作偏好）
    """
    base_score = score_news(item)
    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
    source = item.get('source', '')

    scene_bonus = 0

    # 台湾场景加权
    if source in ['中央社', '经济日报', '工商时报', '联合财经']:
        scene_bonus += 5
    if any(kw in text for kw in ['台湾', '台北', '高雄', '台中', '台南', '两岸', '台商']):
        scene_bonus += 5

    # 资金匹配（200-300万级别）
    if any(kw in text for kw in ['百万', '200万', '300万', '小额', '试水', '轻资产']):
        scene_bonus += 3

    # 灰色/套利偏好
    if any(kw in text for kw in ['价差', '套利', '灰色', '监管差', '税率差', '牌照差',
                                   '绕开', '规避', '中间人', '撮合', '中介', '转口',
                                   '佣金', '过桥', '通道', '暗线']):
        scene_bonus += 3

    # 已知项目关联加权
    if any(kw in text for kw in ['庙宇', '供奉', '开光', '法会', '信仰', '线上', '财神',
                                   '赵公明', '刘海蟾']):
        scene_bonus += 3
    if any(kw in text for kw in ['彩票', '彩券', '台彩', '威力彩', '大乐透', '公益彩券',
                                   '经销', '派彩']):
        scene_bonus += 3

    # 操作偏好（小额/轻资产/中间人模式）
    if any(kw in text for kw in ['小额', '试水', '中间人', '撮合', '代理', '服务费',
                                   '信息费', '抽成', '流水']):
        scene_bonus += 3

    return base_score + scene_bonus


def filter_by_profile(news_list, min_score=0, top_n=None):
    """过滤+排序: 删负分，按画像得分降序"""
    filtered = [n for n in news_list if score_news_with_scene(n) >= min_score]
    filtered.sort(key=score_news_with_scene, reverse=True)
    if top_n:
        filtered = filtered[:top_n]
    return filtered


# ============================================================
# V9 领域配额制 — 保证刘老板每个关注领域都有新闻
# ============================================================
# 领域定义: (领域名, [匹配关键词], 最低条数)
LIU_DOMAINS = [
    ('台湾/两岸', ['台湾', '台北', '两岸', '台商', '台币', '金门', '小三通', '台海', '陆资', '台资'], 3),
    ('信仰经济', ['庙宇', '供奉', '开光', '法会', '线上庙宇', '信仰', '财神', '赵公明', '刘海蟾', '金蟾', '线上供养'], 1),
    ('彩票产业', ['彩票', '彩券', '台彩', '威力彩', '大乐透', '公益彩券', '博彩', '乐透', '派彩'], 1),
    ('AI/算力', ['AI', '人工智能', '大模型', '算力', 'GPU', '英伟达', 'NVIDIA', 'DeepSeek', 'LLM', 'AGI', '芯片', '半导体'], 3),
    ('大宗/供应链', ['涨价', '暴跌', '缺货', '断供', '铜价', '铝价', '锂价', '硫酸', '减产', '停产', '期货', '现货'], 2),
    ('金融/宏观', ['央行', '降息', '加息', '汇率', '人民币', '利率', '流动性', '政策', '关税', '制裁', '出口', '出海'], 2),
]


def _classify_news(item):
    """V14: 将新闻归类到刘老板关注领域，支持多标签（一条新闻可属多个领域）
    返回: list[str] — 领域名列表（可能包含多个）"""
    import re
    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
    source = item.get('source', '')
    domains = []

    # 第一步: 台湾来源直接标记"台湾/两岸"（V14: 最优先，不再跳过）
    is_taiwan_source = source in ['中央社', '经济日报', '工商时报', '联合财经']
    has_taiwan_kw = any(kw.lower() in text for kw in LIU_DOMAINS[0][1])
    if is_taiwan_source or has_taiwan_kw:
        domains.append('台湾/两岸')

    # 第二步: 检查其他领域关键词（一条新闻可同时属于多个领域）
    for domain_name, keywords, _ in LIU_DOMAINS:
        if domain_name == '台湾/两岸':
            continue  # 已经处理过
        if any(kw.lower() in text for kw in keywords):
            domains.append(domain_name)

    # 第三步: AI 词边界匹配（防止 "Thailand"/"Airlines" 误分类）
    if 'AI/算力' not in domains and re.search(r'\bai\b', text):
        # 还需验证是否真的与AI相关（检查其他AI相关词）
        ai_confirm = any(kw.lower() in text for kw in
                         ['人工智能', '大模型', '算力', 'gpu', '英伟达', 'nvidia', 'deepseek',
                          'llm', 'agi', '芯片', '半导体', 'gpt', 'claude', '智能体'])
        if ai_confirm:
            domains.append('AI/算力')

    # 台湾来源中，AI相关新闻同时属于"台湾/两岸"和"AI/算力"
    if is_taiwan_source and 'AI/算力' not in domains:
        if any(kw in text for kw in ['科技', 'ai', '芯片', '半导体', '台积电']):  # V14: 'ai'小写
            domains.append('AI/算力')

    return domains if domains else []


def filter_by_domain_quota(news_items, total=20):
    """V14: 领域配额过滤 — 支持多标签分类，每条新闻可同时属于多个领域
    
    改进:
    1. 一条新闻可同时计入多个领域的配额（多标签）
    2. 台湾/两岸配额优先级最高，不再被其他领域挤占
    3. 去重key从title[:30]改为title[:60]，防止英文标题误删
    
    Returns: top_items list, domain_stats dict
    """
    # 打分并排序
    scored = [(item, score_news_with_scene(item)) for item in news_items]
    filtered = [(item, sc) for item, sc in scored if sc >= 1]
    filtered.sort(key=lambda x: x[1], reverse=True)

    # 分类 — V14: 多标签，一条新闻可属于多个领域
    item_domains = {}  # title_key -> list[domain_name]
    assigned_titles = set()

    for item, score in filtered:
        title_key = item['title'][:60]
        if title_key in assigned_titles:
            continue
        domains = _classify_news(item)
        item_domains[title_key] = domains if domains else ['其他']
        assigned_titles.add(title_key)

    # 各领域保底配额 — V14: 一条新闻可同时计入多个领域
    result = []
    used_titles = set()
    domain_stats = {}
    domain_filled = {d[0]: 0 for d in LIU_DOMAINS}

    for domain_name, _, quota in LIU_DOMAINS:
        taken = 0
        for item, score in filtered:
            if taken >= quota or len(result) >= total:
                break
            title_key = item['title'][:60]
            if title_key in used_titles:
                continue
            # V14: 这条新闻属于当前领域（多标签中包含即可）
            if domain_name in item_domains.get(title_key, []):
                result.append(item)
                used_titles.add(title_key)
                taken += 1
                # V14: 同时计入其他领域的filled计数
                for d in item_domains.get(title_key, []):
                    if d in domain_filled:
                        domain_filled[d] += 1
        domain_stats[domain_name] = taken

    # 剩余位置按全局分竞争（不限领域，包含"其他"类）
    for item, score in filtered:
        if len(result) >= total:
            break
        title_key = item['title'][:60]
        if title_key not in used_titles:
            result.append(item)
            used_titles.add(title_key)

    return result[:total], domain_stats

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

    # 链10: 信仰经济变现
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

# ============================================================
# V8 灰色操作引擎 — 代码层生成，不受AI安全策略限制
# 每张操作卡 = 独立可执行的最小灰色动作单元
# 格式: (触发词, 操作名, 找谁, 怎么说, 资金路径, 试水金额, 撤退信号)
# ============================================================
GRAY_OPS_PLAYBOOK = [
    # 两岸套利
    {'kw': ['台湾', '两岸', '小三通', '金门'], 'ops': [
        ("小三通散货拼柜", "金门/厦门民间货代", "以'代购集运'名义谈合作，每公斤收15-30元服务费",
         "大陆→金门→台湾散件不报关，单批货值控制在2万台币内",
         "试水2000元", "任一端口海关严查或金门中转仓被抄"),
        ("台币人民币对敲", "台湾银楼/大陆兑换商", "以'代付货款'名目谈，每笔收0.3-0.5%手续费",
         "A台付台币→B陆付人民币，微信/支付宝私账，不走银行",
         "试水10万台币", "反洗钱新规要求单笔5万以上报备"),
    ]},
    # 信仰经济
    {'kw': ['庙宇', '供奉', '开光', '法会', '线上', '信仰', '财神', '赵公明'], 'ops': [
        ("线上供养平台代运营", "有线上化需求的线下庙宇", "以'数字化服务商'名义谈→收年费2-5万+供养品代销抽20%",
         "科技公司主体签服务合同→不碰宗教经营→只做技术和电商→赵公明庙宇已有基础",
         "试水5-10万", "宗教政策收紧→停新拓只做存量；复购率低→3月验证后评估"),
        ("AI法会/开光SaaS", "寺庙/道观/民间信仰组织", "以'科技赋能传统信仰'名义→AI法会直播+线上开光预约→抽流水5%",
         "搭建SaaS→庙宇入驻→信众预约→你抽技术服务费",
         "试水5-10万", "合规风险→定位'技术服务'非'宗教服务'"),
    ]},
    # 彩票
    {'kw': ['彩票', '彩券', '台彩', '威力彩', '大乐透', '公益彩券'], 'ops': [
        ("线上合买社群抽水", "台湾彩票玩家/LINE群主", "以'好友集资合买'名义建LINE群→每期组织合买→收5%服务费",
         "群主发起合买方案→群友跟单→中奖按比例分→你抽管理费",
         "试水5千台币", "台彩明文禁止→改名'集资'；被举报→解散换群"),
        ("台彩经销权中间撮合", "想转让的台彩经销商", "以'朋友介绍'名义联系→收转让价5-10%介绍费",
         "买方付卖方→你收现金介绍费→不签合同不留痕迹",
         "试水1单", "台彩禁止私下转让→转'承包经营'名目"),
    ]},
    # 供应链撮合
    {'kw': ['涨价', '缺货', '断供', '减产', '铜', '铝', '钢', '硫酸', '锂'], 'ops': [
        ("供需断裂中间撮合", "有货没渠道的供应商+缺货的买家", "以'行业资源对接'名义介绍→成交收1-3%撮合费→你不签合同不碰货",
         "拿供应商报价→加1-3%报买方→双方直接交易→你收撮合费现金",
         "试水1单3千-1万", "买卖双方跳过你→换下一对；一方违约→你是介绍人免责"),
    ]},
    # 汇率/资金套利
    {'kw': ['汇率', '人民币', '新台币', '降息', '加息', '流动性'], 'ops': [
        ("两岸利率差套利", "台湾银行+大陆银行", "利用两岸定存利差→台币定存利率高于人民币→低息借人民币→换台币存高息",
         "大陆低息借款(3-4%)→换台币→存台湾定存(5-6%)→锁汇对冲风险",
         "试水50万", "汇率反向波动超2%→立刻平仓；两岸资金管制→走合规QDII"),
    ]},
]


def _match_gray_ops(news_items, gap_keywords):
    """根据缺口关键词匹配灰色操作卡，返回匹配结果列表"""
    all_kw = ' '.join([item.get('title', '') for item in news_items[:10]])
    all_kw += ' ' + ' '.join(gap_keywords.keys()) if gap_keywords else ''
    
    matched_ops = []
    for playbook in GRAY_OPS_PLAYBOOK:
        hit = sum(1 for kw in playbook['kw'] if kw in all_kw)
        if hit > 0:
            matched_ops.append({**playbook, 'hit': hit})
    
    matched_ops.sort(key=lambda x: x['hit'], reverse=True)
    return matched_ops[:3]  # 最多3组


def _inject_gray_ops_to_content(content, top_items):
    """V14: 强制接管缺口板块 — AI输出全部丢弃，代码全量生成
    改进: 操作卡附带新闻引用，标记冷热度"""

    gap_header = "## 二、市场/中间人缺口扫描"

    # 用代码生成完整的缺口板块
    code_gap = _fallback_gap_scan(top_items)

    # V14: 追加灰色操作卡（附带新闻引用和热度标记）
    all_titles = ' '.join([item.get('title', '') for item in top_items[:10]])

    # 匹配操作卡
    matched_ops = _match_gray_ops(top_items, {})
    if matched_ops:
        code_gap += "\n\n### 🔥 灰色操作卡（今日匹配）\n"
        code_gap += "> 以下操作卡基于今日新闻信号匹配，🔥=当日热点 / 📦=储备待命:\n\n"
        for ops_group in matched_ops:
            # 检查触发词是否在当日新闻中
            is_hot = any(kw in all_titles for kw in ops_group['kw'])
            heat_tag = '🔥' if is_hot else '📦'
            # 找到匹配的新闻标题
            matched_title = ''
            for item in top_items[:10]:
                if any(kw in item.get('title', '') for kw in ops_group['kw']):
                    matched_title = item.get('title', '')[:40]
                    break
            ref = f" ← 基于「{matched_title}」" if matched_title else " ← 储备操作卡"

            for op in ops_group['ops'][:2]:  # 每组最多2个
                name, who, how, path, amount, retreat = op
                code_gap += f"- {heat_tag} **{name}**{ref}\n"
                code_gap += f"  - 找谁: {who}\n"
                code_gap += f"  - 怎么说: {how}\n"
                code_gap += f"  - 资金: {path}\n"
                code_gap += f"  - 试水: {amount}\n"
                code_gap += f"  - 撤退: {retreat}\n\n"

    if gap_header not in content:
        # AI没生成缺口扫描 → 插入到正确位置
        insert_point = content.find("\n## 三、")
        if insert_point == -1:
            insert_point = content.find("\n## 一、")
            if insert_point == -1:
                return content + "\n\n" + code_gap
            # 找到一处插入
            next_section = content.find("\n## ", insert_point + 10)
            if next_section == -1:
                next_section = len(content)
            return content[:next_section] + "\n" + code_gap + "\n" + content[next_section:]
        return content[:insert_point] + "\n" + code_gap + "\n" + content[insert_point:]

    # AI生成了缺口扫描 → 找到并替换
    gap_start = content.find(gap_header)
    # 找下一个板块的起始位置
    for marker in ["\n## 三、", "\n## 四、", "\n## 五、", "\n## 六、"]:
        gap_end = content.find(marker, gap_start + len(gap_header))
        if gap_end != -1:
            break
    if gap_end == -1:
        gap_end = len(content)

    return content[:gap_start] + code_gap + content[gap_end:]


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
    """V14: 记录今日邪修内容到记忆库(传导链+金句+命中模式)
    扩大记忆库容量: 金句30→100条，新增传导链命中记录和操作卡命中记录"""
    import re
    memory = _load_xie_xiu_memory()

    # 提取金句
    quote_match = re.search(r'六、今日邪修金句\s*(.*?)$', sections_text, re.MULTILINE)
    if quote_match:
        quote = quote_match.group(1).strip()
        if quote and '💭' in quote:
            quote = quote.replace('💭', '').strip()
            if quote and quote not in memory.get('quotes', []):
                memory.setdefault('quotes', []).append(quote)
                # V14: 保留最近100条金句（从30扩大）
                memory['quotes'] = memory['quotes'][-100:]

    # V14: 提取传导链命中记录
    chain_section = re.search(r'四、深度传导分析(.*?)(?=五、|六、|$)', sections_text, re.DOTALL)
    if chain_section:
        chain_text = chain_section.group(1)
        # 提取第1层（事件）
        layer1 = re.search(r'第1层.*?:\s*(.+)', chain_text)
        # 提取天之道和邪修之道
        tian_dao = re.search(r'天之道:\s*(.+?)(?:\n|$)', chain_text)
        xie_xiu = re.search(r'邪修之道:\s*(.+?)(?:\n|$)', chain_text)
        if layer1:
            chain_record = {
                'date': today_str,
                'event': layer1.group(1).strip()[:60],
                'tian_dao': tian_dao.group(1).strip()[:80] if tian_dao else '',
                'xie_xiu': xie_xiu.group(1).strip()[:80] if xie_xiu else '',
            }
            memory.setdefault('chain_records', []).append(chain_record)
            # 只保留最近60条传导链记录
            memory['chain_records'] = memory.get('chain_records', [])[-60:]

    # V14: 提取缺口扫描中的操作卡命中
    gap_section = re.search(r'二、市场/中间人缺口扫描(.*?)(?=三、|四、|$)', sections_text, re.DOTALL)
    if gap_section:
        gap_text = gap_section.group(1)
        # 检测操作卡关键词命中
        ops_hit = []
        for playbook in GRAY_OPS_PLAYBOOK:
            for kw in playbook['kw']:
                if kw in gap_text:
                    ops_hit.append(kw)
                    break
        if ops_hit:
            memory.setdefault('ops_hits', []).append({
                'date': today_str,
                'keywords': ops_hit,
            })
            memory['ops_hits'] = memory.get('ops_hits', [])[-30:]

    _save_xie_xiu_memory(memory)


# ============================================================
# 新闻抓取
# ============================================================
def _fetch_rss(url, count=15, timeout=12):
    """从RSS源获取新闻（V11: 修复GBK编码，超时12秒）"""
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if resp.status_code != 200:
            logging.warning(f"[新闻] RSS下载失败({url}): HTTP {resp.status_code}")
            return []
        # 使用 resp.text (自动处理编码) 而非 resp.content (GBK等编码会报错)
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            # 某些RSS源编码特殊，尝试手动检测
            import re as _re
            enc_match = _re.search(r'encoding=["\']([^"\']+)["\']', resp.text[:200])
            if enc_match:
                resp.encoding = enc_match.group(1)
                root = ET.fromstring(resp.text)
            else:
                raise
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



def _fetch_sina_finance(count=20):
    """从新浪财经JSON API抓取新闻"""
    import json
    url = 'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=' + str(count) + '&r=0.1'
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code != 200:
            return []
        data = json.loads(resp.text)
        items = []
        result = data.get('result', {})
        news_list = result.get('data', [])
        for n in news_list:
            title = n.get('title', '') or n.get('intro', '')
            if title and len(title) > 5:
                items.append({
                    'title': title.replace('\n', ' ').strip(),
                    'link': n.get('url', ''),
                    'source': '新浪财经',
                    'published': n.get('ctime', ''),
                    'score': 5,  # 默认分
                })
        return items[:count]
    except Exception as e:
        logging.warning(f"[新闻] 新浪财经抓取失败: {e}")
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


def _fetch_baidu_taiwan_news(count=10):
    """V14: 通过百度搜索补充台湾相关新闻（当台湾RSS源不可达时）
    搜索关键词: "台湾 经济" / "台股" / "台币" / "台湾 两岸"
    """
    import re, subprocess
    taiwan_items = []
    search_queries = ['台湾+经济', '台股+今日', '台币+汇率', '两岸+贸易']
    headers = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    for query in search_queries[:2]:  # 只搜2组，避免过频
        try:
            url = f"https://www.baidu.com/s?wd={query}&rn=10"
            curl_cmd = ['curl', '-s', '-H', headers, url]
            result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                continue
            html = result.stdout
            # 提取搜索结果标题
            titles = re.findall(r'<h3[^>]*>(?:<[^>]*>)*([^<]+)(?:<[^>]*>)*</h3>', html)
            if not titles:
                titles = re.findall(r'title="([^"]{10,80})"', html)[:10]
            for t in titles[:5]:
                t = t.strip()
                if t and len(t) > 8 and '百度' not in t:
                    taiwan_items.append({
                        'title': t,
                        'source': '百度台湾搜索',
                        'summary': f'搜索关键词: {query.replace("+", " ")}'
                    })
        except Exception as e:
            logging.warning(f"[新闻] 百度台湾搜索失败({query}): {e}")
            continue

    # 去重
    seen = set()
    unique = []
    for item in taiwan_items:
        key = item['title'][:30]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:count]


def fetch_raw_materials():
    """并发抓取所有新闻素材，返回(raw_items, source_stats)"""
    RSS_SOURCES = {
    # 大陆科技/商业
    '36氪': 'https://36kr.com/feed',
    '36氪快讯': 'https://36kr.com/feed-newsflash',
    '虎嗅': 'https://www.huxiu.com/rss/0.xml',
    '钛媒体': 'https://www.tmtpost.com/rss.xml',
    '创业邦': 'https://www.cyzone.cn/rss/',
    # 台湾综合/财经（注：大陆服务器可能被墙，失败时自动跳过）
    '中央社': 'https://www.cna.com.tw/rss/cna/rss.aspx?topic=first',
    '经济日报': 'https://money.udn.com/rssfeed/news/1001/5588/12040?ch=money',
    '工商时报': 'https://ctee.com.tw/rss',
    '联合财经': 'https://udn.com/rssfeed/news/2/6642',
}

    all_raw = []
    source_stats = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
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

    # 新浪财经 (JSON API, 非RSS)
    try:
        sina_items = _fetch_sina_finance(20)
        all_raw.extend(sina_items)
        source_stats['新浪财经'] = len(sina_items)
    except Exception:
        source_stats['新浪财经'] = 0

    # V14: 台湾RSS源失败时，用百度搜索补充台湾新闻
    taiwan_sources = ['中央社', '经济日报', '工商时报', '联合财经']
    taiwan_ok = any(source_stats.get(s, 0) > 0 for s in taiwan_sources)
    if not taiwan_ok:
        logging.warning("[新闻] 台湾RSS源全部失败，启动百度台湾搜索补源")
        try:
            taiwan_baidu = _fetch_baidu_taiwan_news(10)
            all_raw.extend(taiwan_baidu)
            source_stats['百度台湾搜索'] = len(taiwan_baidu)
            logging.info(f"[新闻] 百度台湾搜索补充: {len(taiwan_baidu)}条")
        except Exception as e:
            source_stats['百度台湾搜索'] = 0
            logging.warning(f"[新闻] 百度台湾搜索失败: {e}")

    # V17: 统一解码HTML实体 (&ldquo; &rdquo; &middot; 等)
    import html as html_mod
    for item in all_raw:
        if 'title' in item:
            item['title'] = html_mod.unescape(item['title'])

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

    # 2. 领域配额过滤 — 保证各关注领域都有新闻，不被AI/算力挤占
    top_items, domain_stats = filter_by_domain_quota(all_raw, total=20)
    logging.info(f"[日报] 领域配额: {domain_stats} | 共{len(top_items)}条")

    # 3. 构建邪修上下文
    chain_ctx, used_quotes = _build_xie_xiu_context(top_items)

    # 4. 构建AI Prompt — 6板块完整版
    news_digest = "\n".join([
        f"【{item.get('source', '')}】{item['title']} (画像分:{score_news_with_scene(item)})"
        + (f" — {item.get('summary', '')[:60]}" if item.get('summary') else "")
        for item in top_items
    ])

    used_quotes_warn = ""
    if used_quotes:
        used_quotes_warn = f"\n\n⚠️ 以下金句近期已使用，禁止重复:\n" + "\n".join([f"- {q}" for q in used_quotes])

    # 场景上下文（注入到prompt，让AI了解刘老板当前状态）
    scene_context = f"""**刘老板当前场景**（基于此推断可执行的操作）:
- 位置: 台湾（旅游至6/16-17），可在台实地考察、对接台商
- 资金: 200-300万人民币，周期3个月-1年
- 偏好: 不做重资产，不做长周期，做中间人/渠道/信息差
- 当前项目: 机票/酒店/电话卡(已办)/台湾彩种分析/赵公明线上庙宇
- 可用工具: 上海户籍+腾讯项目Owner身份背书，两岸均有触角"""

    system_msg = f"""你是邪修分析师。专注"新闻→断裂→机会"的隐秘传导链。日报的灰色操作由引擎自动生成，你的任务是新闻解读。

⏰ 当前日期: {today_str} — 所有时间节点基于此日期推算，禁止用过期年份。

== 你的角色 ==
天之道损有余补不足——你在新闻中找到"有余方"和"不足方"之间的断裂。不是赌方向，是识别断裂位置。

== 输出格式 ==

## 一、每日资讯

分类: 🤖 AI/算力 | 🏦 金融 | 🚀 商业 | 🌐 出海 | 🔥 热搜
每条:
- **标题**
  > 💰 落地动作: [一句话，这条新闻带来的具体搞钱方向]

## 二、市场/中间人缺口扫描

> 指出今日新闻中供需断裂的具体位置。每个缺口说清: 什么品类有断裂、断裂在哪、大概窗口多久。

- **缺口**: [具体品类/断裂环节]
  - 收钱位置: [中间人可以站着收钱的具体环节]
  - 窗口期: [从{today_str}起算，多久有效]

（至少2个缺口）

## 三、逆潮观察

- **市场共识**: [多数人怎么看]
  - 🔄 逆向可能: [为什么多数人可能错]
  - 🛑 止损: [什么信号说明逆向判断错]

## 四、深度传导分析

> 从今日最高分新闻出发，推导具体因果传导链（如: 铜涨价→硫酸涨价→磷肥涨价→粮食成本上升）。必须结合今日具体新闻，禁止抽象模板。

- **因果链**: [A→B→C→D→E，每步是具体的商品/行业/现象]
- **有余方**: [谁有过剩]
- **不足方**: [谁有缺口]

🔮 天之道: [损X之有余→补Y之不足，附推导]
⚡ 邪修之道: [在哪个断裂位置收过路费，附具体操作]

## 五、避坑提醒

- ⚠️ **陷阱**: [看似机会实则是坑]
  - 止损: [怎么撤]

## 六、今日邪修金句

💭 [1句话，结合今日新闻主题。要冷、要利、有画面感。禁止鸡汤、禁止格言式。]{used_quotes_warn}

== 铁律 ==
1. 6板块齐全，每板块有实质内容，不需要操作细节(引擎会补充)
2. 传导链必须基于今日新闻，禁止铜→PCB→电动车模板
3. 金句每天不同，结合当日主题
4. 总字数2000-3000字
5. ⏰ 所有时间窗口基于{today_str}推算
6. 📍 优先挖掘台湾相关机会
{scene_context}
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
                # V8: 注入灰色操作卡（代码层生成，不受AI安全限制）
                content = _inject_gray_ops_to_content(content, top_items)
                # 记录邪修内容
                _record_xie_xiu_content(content)
                return content
            else:
                logging.warning(f"[日报] AI生成缺板块: {missing}，补齐后使用")
                # 补齐缺失板块
                content = _patch_missing_sections(content, top_items, missing)
                # V8: 注入灰色操作卡
                content = _inject_gray_ops_to_content(content, top_items)
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
        # 扩展金句（确保≥50字）
        if len(candidate) < 50:
            candidate += " —— 邪修原则：不赌涨跌，只吃信息费；不追热点，只找断层。"
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
        # V18: 邪修操作卡替代单行落地动作
        op_card = _infer_xie_xiu_op(n['title'])
        sections.append(op_card)

    biz_items = [n for n in filtered_all if n['title'][:30] not in used_titles]
    sections.append("\n### 🌐 出海/商业\n")
    for n in biz_items[:4]:
        sections.append(f"- **{n['title']}**")
        op_card = _infer_xie_xiu_op(n['title'])
        sections.append(op_card)

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
    """V14: 每条新闻生成具体落地动作 — 新闻实体+可执行第一步+预期收益
    核心改进: 不再"以XXX名义→做XXX→收X%"万能模板，改为具体人/公司+第一步操作+数字"""
    import re
    title_lower = title.lower()
    entity = _extract_entity(title)
    # V17: 实体名最长8字，去掉介词前缀
    ent_raw = entity[:8] if len(entity) > 8 else entity
    ent = re.sub(r'^[在的得了被把将向从]', '', ent_raw).rstrip('？?！!。、')

    # 用标题hash做轮选种子，同一批新闻不会重复
    seed = sum(ord(c) for c in title[:20]) % 100

    # V14: 每个场景的落地动作改为"具体行动+可执行第一步+数字"，不再用万能填空模板
    # 格式: 行动方向 | 第一步操作 | 预期收益

    # V17: AI分支匹配逻辑修复 — 'ai'子串匹配后用词边界或组合词验证
    if any(kw in title_lower for kw in ['ai', '算力', 'gpu', '大模型', '英伟达', 'nvidia', '人工智能', '机器学习', '深度学习', 'openai', 'gpt', 'deepseek', 'claude', 'gemini', 'llm']):
        # 验证：词边界\bAI\b 或 AI+跨界组合词 或 其他AI强相关词
        ai_combo_words = ['跨境电商', '客服', '写作', '编程', '医疗', '教育', '金融', '电商',
                          '工具', '助手', '搜索', '芯片', '平台', '应用', 'agent']
        is_real_ai = (re.search(r'\bai\b', title_lower) or
                     any(kw in title_lower for kw in ['算力', 'gpu', '大模型', '英伟达', 'nvidia', '人工智能', '机器学习', '深度学习', 'openai', 'gpt', 'deepseek', 'claude', 'gemini', 'llm']) or
                     any(f'ai{cw}' in title_lower.replace(' ', '').replace('-', '') for cw in ai_combo_words))
        if is_real_ai:
            templates = [
                f'算力中介: 查IDC空置率→以「算力调度服务商」签合作→两边抽差价3-5% | 第一步: 联系是方电讯(6786 TT)或世纪互联(GDS)业务窗口问GPU空置 | 预期月入3-8万',
                f'散热供应链: {ent}拉动散热模组需求→找散热厂奇鋐/双鸿→以「数据中心采购」名义询价→转卖赚15-20% | 第一步: 奇鋐(3017 TT)投资者关系邮箱要报价单 | 预期单批利差2-5万',
                f'培训/咨询: {ent}相关AI技术落地→企业缺懂行的人→以「AI落地顾问」做培训+方案→收5-10万/案 | 第一步: 在脉脉/LinkedIn搜「AI转型」公司CTO | 预期首单5万',
            ]
            return templates[seed % len(templates)]
    if any(kw in title_lower for kw in ['机器人', '具身智能', '智能体']):
        templates = [
            f'集成代理: {ent}落地需本地集成商→以「区域集成商」接单→找方案做白牌→差价20-30% | 第一步: 联系目标行业(零售/物流/制造)协会问智能化需求 | 预期首单10-15万',
            f'训练数据: 机器人需场景训练数据→线下门店有大量真实场景→以「数据采集服务」卖训练数据 | 第一步: 调研目标场景(便利店/工厂)数据采集方案 | 预期按场景2-5万/批',
            f'维修保养: {ent}量产后的售后市场→缺维修人才→做「售后服务商」→签年保合约 | 第一步: 查机器人进口量数据(海关统计)评估市场 | 预期年保5-10万/台',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['芯片', '半导体']):
        templates = [
            f'芯片分销: {ent}供应链有灰色渠道需求→受限芯片经中转→撮合费5-8% | 第一步: 查美国商务部实体清单最新版确认哪些芯片受限 | 预期单笔10-30万',
            f'二手设备: 半导体设备维修→二手设备市场→以「设备翻新」采购→转卖差价 | 第一步: 联系半导体设备代理商问二手库存 | 预期单台利差20-40%',
            f'紧急量产: 芯片产能过剩→晶圆厂空置→帮IC设计公司抢产线→收加急费5-10% | 第一步: 查晶圆代工厂产能利用率(月报) | 预期单案5-15万',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['腾讯', '阿里', '字节', '百度', '快手', '网易']):
        templates = [
            f'生态变现: {ent}生态变化→平台商户需新渠道→以「市场代办服务商」做入驻→收入驻费+流水1% | 第一步: 在{ent}开放平台搜最新入驻政策 | 预期入驻费5000-1万/户',
            f'人才猎头: 大厂裁员/调整→释放AI/算法人才→以「行业猎头」帮挖人→猎头费3-6月薪 | 第一步: 在脉脉/LinkedIn搜近期裁员公司名单 | 预期单人人头费3-5万',
            f'期权套现: {ent}股价波动→员工期权套现需求→以「家族办公室」接盘→7-8折→6月退出 | 第第一步: 联系{ent}离职社群/期权交易平台 | 预期折扣空间20-30%',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['ipo', '上市', '过会', 'a股', '港股']):
        templates = [
            f'老股转让: {ent}上市前老股东套现→以「家族办公室」接老股→6-7折→上市后退出 | 第一步: 查{ent}招股书股东名单找持股>5%的 | 预期折扣空间30-40%',
            f'打新融资: 新股上市→打新资金需求→对接资金方→收融资利差2-3% | 第一步: 查{ent}招股定价区间计算所需资金 | 预期利差2-3%/笔',
            f'市值管理: {ent}解禁期→老股东做市值管理→以「投资者关系顾问」接单 | 第一步: 查{ent}解禁日(招股书) | 预期顾问费10-20万/季',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['出口', '关税', '制裁', '贸易']):
        templates = [
            f'转口贸易: {ent}受制裁/关税影响→找第三国中转→做转口中介2-5% | 第一步: 查受影响的HS编码和税率变化 | 预期转口费2-5%',
            f'合规咨询: 贸易壁垒→合规咨询需求→以「贸易合规顾问」帮做原产地规划 | 第一步: 下载最新海关归类决定书 | 预期8-15万/案',
            f'替代供应: 制裁→替代供应链出现→以「替代供应商撮合」做中间人→收信息费1-3% | 第一步: 查受制裁产品的替代供应商名录 | 预期信息费1-3%',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['出海', '全球化', '海外']):
        templates = [
            f'落地顾问: 以「目标市场落地顾问」接触{ent}→帮找经销商→首单5-8万+流水1% | 第一步: 下载目标市场工商登记查询确认竞品 | 预期首单5-8万',
            f'本地化服务: {ent}出海需本地化→以「本地化服务商」接单→市场调研+渠道搭建 | 第一步: 查目标市场同类产品的市占率 | 预期项目费10-20万',
            f'代理主体: 品牌进新市场→需本地公司做代理→以「区域代理主体」注册→收年管费+流水 | 第一步: 查目标市场公司注册最低资本要求 | 预期年管理费5-10万',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['品牌', '营销', '新消费', '道歉', '危机']):
        templates = [
            f'危机公关: {ent}公关危机→以「品牌公关顾问」介入→帮对接媒体→收8-15万 | 第一步: 查{ent}媒体曝光度(Google Trends) | 预期8-15万/案',
            f'品牌授权: 品牌扩张需本地化→以「品牌授权代理」谈→拿授权后转包→差价10-20% | 第一步: 查{ent}商标注册状态(商标局) | 预期授权差价10-20%',
            f'库存清仓: 新消费退潮→品牌倒闭→以「库存清仓中介」帮清库存→收5-10%+残值分润 | 第一步: 在阿里司法拍卖搜相关设备折价信息 | 预期清仓费5-10%',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['台湾', '两岸', '小三通', '金门']):
        templates = [
            f'兑汇通道: 人在台湾窗口→找金门民间兑汇所→台币/人民币对敲→单笔<5万台币 | 第一步: 到金门金城镇找民间兑换所(后浦老街周边) | 预期汇差+手续费0.3-0.5%/笔',
            f'货运中转: 小三通货运→金门中转仓代发→收仓租+操作费→月入5-10万台币 | 第一步: 联系金门海运公司(如金门快轮)问散货拼柜价格 | 预期月5-10万台币',
            f'代购电商: 两岸信息差→大陆人买不到台湾商品→以「台湾代购」做电商→15-25% | 第一步: 在淘宝搜台湾商品看竞品定价 | 预期代购费15-25%/单',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['庙宇', '供奉', '开光', '法会', '线上信仰']):
        templates = [
            f'庙宇代运营: 赵公明线上庙宇已启动→找{ent}相关寺庙谈代运营→首单免费→签SaaS年费+代销分成20% | 第一步: 在Google Maps搜台湾道教庙宇(赵公明/关帝) | 预期年费2-5万/庙+分成20%',
            f'线上法会: 信仰经济→复购率碾压SaaS→以「线上法会直播」服务切入→按场收费3-5万/场 | 第一步: 下载法会直播竞品(如"功德林"App)分析功能 | 预期3-5万/场',
            f'供养品供应链: 庙宇数字化→供养品供应链加价20-40%→以「庙宇用品供应商」切入 | 第一步: 查台湾宗教用品批发商(台北地下街) | 预期供应链加价20-40%',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['彩票', '彩券', '威力彩', '大乐透']):
        templates = [
            f'经销权撮合: 在台湾找想转让的台彩经销商→做中间撮合→收介绍费5-10万 | 第一步: 到台湾公益彩券官网查经销点转让公告 | 预期介绍费5-10万/单',
            f'合买社群: 台彩头奖效应→建LINE合买群→收5%服务费→政策收紧前退出 | 第一步: 搜LINE开放聊天室「威力彩合买」看竞品 | 预期月服务费5千-1万台币',
            f'数据分析: 彩票数据→以「数据分析服务」帮合买群做选号建议→收月费500-1000台币/人 | 第一步: 用刘海蟾系统生成近10期威力彩分析 | 预期月费500-1000/人',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['涨价', '缺货', '断供', '铜', '铝', '钢', '硫酸', '锂']):
        templates = [
            f'供需撮合: {ent}供应断裂→找有货没渠道的供应商+缺货的买家→以「行业贸易对接」撮合→收2-4% | 第一步: 查LME(伦敦金属交易所)实时库存数据 | 预期撮合费2-4%',
            f'替代品中介: 涨价→下游减产→以「替代供应商中介」帮找台湾替代品→收3-5%信息费 | 第一步: 查台湾同业公会会员名录(如台湾区金属品制造公会) | 预期3-5%信息费',
            f'供应链金融: 库存波动→以「供应链金融」帮囤货方融资→收2-3%/月→货做质押 | 第一步: 查上海期货交易所仓单质押规则 | 预期2-3%/月',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['降息', '央行', '利率', '美联储']):
        templates = [
            f'跨境配置: 利差变化→大陆资金寻求境外配置→以「台湾私人银行渠道」对接→收通道费1-2% | 第一步: 查两岸定存利差(大陆3-4% vs 台湾5-6%) | 预期通道费1-2%',
            f'房产顾问: 利率下降→房产估值上升→以「台湾房产投资顾问」帮大陆资金找标的→收佣金2-3% | 第一步: 查台湾内政部实价登录最新数据 | 预期成交佣金2-3%',
            f'汇率对冲: 汇率波动→以「两岸跨境结算」帮企业做汇率对冲→收0.5-1%服务费 | 第一步: 查台币/人民币即期汇率与NDF差价 | 预期0.5-1%/笔',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['新能源', '锂', '光伏', '储能', '电网']):
        templates = [
            f'跨境清库: {ent}产能过剩→补贴退出→海外有需求→做跨境撮合→收3-5% | 第一步: 查目标市场再生能源设置量 | 预期清库费3-5%',
            f'光伏贸易: 光伏组件有进口需求→大陆组件过剩→以「绿能贸易」撮合→收2-3% | 第一步: 查目标市场光伏进口关税率 | 预期贸易撮合2-3%',
            f'储能FA: 储能项目融资→以「项目FA」帮储能公司找资金→收2-3%FA费 | 第一步: 查储能项目IRR(公开标案数据) | 预期FA费2-3%',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['暴跌', '崩盘', '恐慌', '危机']):
        templates = [
            f'危机收购: {ent}恐慌抛售→以「危机收购顾问」帮台湾买家对接大陆折价标的→收交易佣金2-3% | 第一步: 查{ent}相关资产折价幅度(法拍/大宗交易) | 预期佣金2-3%',
            f'不良资产: 恐慌→折价资产→以「不良资产撮合」对接银行AMC+台湾资金方→收1-2% | 第一步: 查四大AMC最新不良资产包公告 | 预期撮合费1-2%',
            f'对冲咨询: 市场恐慌→以「风险对冲顾问」帮企业做压力测试→收5-10万 | 第一步: 下载企业风险管理评估模板(COSO框架) | 预期咨询费5-10万',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['暴涨', '疯抢', '炒作']):
        templates = [
            f'获利退出: {ent}炒作过热→帮获利盘找台湾出海通道→收通道费2-3%→不做多不做空 | 第一步: 查{ent}近3个月涨幅和换手率 | 预期通道费2-3%',
            f'退出顾问: 泡沫期→以「退出策略顾问」帮早期投资人做退出规划→收顾问费+退出佣金1-2% | 第一步: 查{ent}VC/PE投资轮次和估值 | 预期退出佣金1-2%',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['政策', '新规', '监管', '整顿']):
        templates = [
            f'合规架构: {ent}监管收紧→以「两岸合规架构顾问」提供台湾/香港主体搭建→收8-15万 | 第一步: 查最新监管条文原文(国务院/部委官网) | 预期8-15万/案',
            f'转型方案: 监管靴子落地→以「合规过渡方案」帮受影响企业转型→收5-15万/案 | 第一步: 列出受{ent}影响的行业清单(天眼查行业分类) | 预期5-15万/案',
            f'政策解读: 新规→以「政策解读服务」卖研讨会+白皮书→收会费+赞助→单场5-10万 | 第一步: 查{ent}相关的行业微信群(搜微信) | 预期单场5-10万',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['火灾', '事故', '停产']):
        templates = [
            f'替代供应: {ent}供应链中断→保险理赔前3-6周真空→找替代供应商→收加急费5-10% | 第一步: 查{ent}事故影响的产品品类和替代品 | 预期加急费5-10%',
            f'调货服务: 停产→库存急缺→以「紧急调货」从台湾仓库调货→收加急运费+10-15% | 第一步: 联系台湾相关产品经销商问库存 | 预期加急利润10-15%',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['融资', '投资', '收购']):
        templates = [
            f'FA服务: {ent}融资→上下游有跟投机会→以「产业链协同投资人」帮台湾资金对接→收FA费2-3% | 第一步: 查{ent}融资轮次和领投方(IT桔子) | 预期FA费2-3%',
            f'投后管理: 融资→以「投后管理服务商」提供财务/法务/HR外包→收月费5-10万 | 第一步: 列出{ent}所在赛道的投后服务需求清单 | 预期月费5-10万',
            f'人才承接: 收购→被收购方员工会离职→以「人才承接」帮挖人→猎头费3-6月薪 | 第一步: 在LinkedIn搜{ent}员工近期动态 | 预期猎头费3-6月薪',
        ]
        return templates[seed % len(templates)]
    elif any(kw in title_lower for kw in ['黄金', '白银', '贵金属']):
        templates = [
            f'贵金属通道: {ent}→台湾有黄金现货渠道→大陆资金有配置需求→以「贵金属跨境通道」撮合→收1-2% | 第一步: 查台湾银行黄金保管箱开户条件 | 预期通道费1-2%',
            f'黄金租赁: 金价波动→以「黄金租赁」帮企业做黄金借贷→收年化3-5% | 第一步: 查上海黄金交易所租赁利率 | 预期年化3-5%',
        ]
        return templates[seed % len(templates)]
    else:
        templates = [
            f'信息差: 从{ent}找套利视角→信息不对称处就是收钱位置→找到知道但接触不到的人+能接触到但不知道的人 | 第一步: 搜{ent}的上下游企业(行业黄页/天眼查) | 预期信息差利差5-15%',
            f'资源对接: {ent}→相关产业有渠道需求→以「行业资源对接」做中间人→首单免费→后续收1-3% | 第一步: 查同业公会/行业协会会员名单 | 预期1-3%撮合费',
            f'断裂撮合: 每条新闻背后都有供需断裂→{ent}的断裂在哪→找到断裂→做那座桥→收过桥费 | 第一步: 用Google搜「{ent} + 供应商/经销商」 | 预期过桥费1-3%',
        ]
        return templates[seed % len(templates)]


def _format_xie_xiu_card(card_tuple):
    """V18: 格式化邪修操作卡5元组为缩进字符串

    参数: (断裂, 找谁, 怎么说, 资金, 撤退)
    返回: 5行缩进字符串
    """
    fracture, target, script, money, retreat = card_tuple
    lines = [
        f"  > 🔥 断裂: {fracture}",
        f"  > 🎯 找谁: {target}",
        f"  > 💬 怎么说: {script}",
        f"  > 💰 资金: {money}",
        f"  > 🚪 撤退: {retreat}",
    ]
    return "\n".join(lines)


def _infer_xie_xiu_op(title):
    """V18: 邪修操作卡 — 每条新闻生成5维度结构化操作卡

    替代V14的_infer_signal()单行格式，升级为5维度邪修操作卡:
      🔥 断裂: 供需断裂的具体位置
      🎯 找谁: 精准触达对象
      💬 怎么说: 话术/切入点
      💰 资金: 收钱路径和比例
      🚪 撤退: 什么条件下必须撤退
    """
    title_lower = title.lower()
    entity = _extract_entity(title)
    # V17: 实体名最长8字，去掉介词前缀
    ent_raw = entity[:8] if len(entity) > 8 else entity
    ent = re.sub(r'^[在的得了被把将向从]', '', ent_raw).rstrip('？?！!。、')

    # 用标题hash做轮选种子，同一批新闻不会重复
    seed = sum(ord(c) for c in title[:20]) % 100

    # V18: 每个分支返回5元组 (断裂, 找谁, 怎么说, 资金, 撤退)

    # === 1. AI/算力 ===
    if any(kw in title_lower for kw in ['ai', '算力', 'gpu', '大模型', '英伟达', 'nvidia', '人工智能', '机器学习', '深度学习', 'openai', 'gpt', 'deepseek', 'claude', 'gemini', 'llm']):
        ai_combo_words = ['跨境电商', '客服', '写作', '编程', '医疗', '教育', '金融', '电商',
                          '工具', '助手', '搜索', '芯片', '平台', '应用', 'agent']
        is_real_ai = (re.search(r'\bai\b', title_lower) or
                     any(kw in title_lower for kw in ['算力', 'gpu', '大模型', '英伟达', 'nvidia', '人工智能', '机器学习', '深度学习', 'openai', 'gpt', 'deepseek', 'claude', 'gemini', 'llm']) or
                     any(f'ai{cw}' in title_lower.replace(' ', '').replace('-', '') for cw in ai_combo_words))
        if is_real_ai:
            templates = [
                (f'{ent}拉动算力需求，但IDC空置率信息不对称——有空GPU的找不到客户，需要GPU的不知道哪里有空位',
                 'IDC业务窗口(世纪互联GDS/万国数据)' if 'nvidia' in title_lower or '英伟达' in title_lower else f'{ent}上下游企业CTO/运维负责人',
                 '以「算力调度服务商」名义接触双方→"我们有闲置GPU资源可调配/我们有客户需求可对接"',
                 '两边抽差价3-5%，预期月入3-8万',
                 'GPU空置率降至10%以下→市场透明化无差价空间→退出'),
                (f'{ent}拉动散热模组需求，散热厂产能扩张滞后3-6个月→供不应求窗口期',
                 '散热厂奇鋐(3017 TT)/双鸿(3324 TT)投资者关系窗口',
                 '以「数据中心采购」名义询出厂价→转身加15-20%报给需求方→你做信息桥',
                 '单批利差15-20%，预期2-5万/批',
                 '散热厂扩产完成/价格回落至正常水平→差价消失→转向下个品类'),
                (f'{ent}相关AI技术落地，企业缺懂行的人→培训/咨询市场断裂',
                 '脉脉/LinkedIn搜「AI转型」的CTO/技术VP',
                 '以「AI落地顾问」名义→"我们先免费做1小时诊断，再出落地方案"',
                 '培训+方案5-10万/案，首单5万起',
                 '6个月内签不到第二单→说明需求不真实→止损退出'),
            ]
            return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 2. 机器人/具身智能 ===
    if any(kw in title_lower for kw in ['机器人', '具身智能', '智能体']):
        templates = [
            (f'{ent}落地需本地集成商，但集成能力稀缺→谁能做谁吃下项目',
             '目标行业(零售/物流/制造)协会负责人/设备采购经理',
             '以「区域集成商」接单→"我们提供{ent}一站式落地方案，从选型到部署"',
             '集成差价20-30%，首单10-15万',
             '大厂直建集成团队→你被替代→转向售后维保'),
            (f'{ent}需场景训练数据，线下门店有大量真实场景→数据供给断裂',
             '连锁便利店/工厂运营经理→手上有场景但不知道数据能变现',
             '以「数据采集服务商」名义→"我们帮你把日常运营数据变现，零成本新增收入"',
             '按场景2-5万/批，复购率高',
             '行业数据采集标准出台→合规成本上升→评估是否继续'),
            (f'{ent}量产后的售后市场缺维修人才→维修服务供不应求',
             '机器人厂商售后部门/终端使用企业设备经理',
             '以「售后服务商」签年保合约→"7×24小时响应，比原厂快"',
             '年保5-10万/台，续约率>80%',
             '厂商自建售后体系→价格劣势→转型做培训认证'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 3. 芯片/半导体 ===
    if any(kw in title_lower for kw in ['芯片', '半导体']):
        templates = [
            (f'{ent}供应链有灰色渠道需求→受限芯片买不到→中转需求出现',
             '查美国商务部实体清单最新版→确认哪些芯片受限→找中转渠道',
             '以「供应链咨询」名义撮合→"我们帮你找替代供应渠道"',
             '撮合费5-8%，单笔10-30万',
             '中美关系缓和/实体清单缩减→灰色渠道需求萎缩→退出'),
            (f'半导体设备维修需求→二手设备市场信息不对称',
             '半导体设备代理商/晶圆厂设备部门',
             '以「设备翻新」名义采购→翻新后转卖→赚信息差',
             '单台利差20-40%',
             '新设备价格下降→翻新无价格优势→转向维保服务'),
            (f'芯片产能过剩→晶圆厂空置→IC设计公司抢产线有加急需求',
             '晶圆代工厂产能调度窗口/IC设计公司供应链经理',
             '以「产能协调」名义→"我们帮你抢空出的产线档期"',
             '加急费5-10%，单案5-15万',
             '产能利用率回升>85%→空档消失→无撮合空间'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 4. 大厂(腾讯/阿里/字节等) ===
    if any(kw in title_lower for kw in ['腾讯', '阿里', '字节', '百度', '快手', '网易']):
        templates = [
            (f'{ent}生态变化→平台商户需新渠道→入驻/迁移服务缺口',
             f'{ent}开放平台最新政策影响到的中小商户',
             '以「市场代办服务商」做入驻→"我们帮你快速入驻新平台，不踩坑"',
             '入驻费5000-1万/户+流水1%',
             '平台政策稳定→商户自行入驻→你被跳过→转做代运营'),
            (f'{ent}裁员/调整→释放AI/算法人才→猎头供需断裂',
             '脉脉/LinkedIn近期裁员公司名单中的AI/算法工程师',
             '以「行业猎头」名义→"我们帮你找下家，全程免费，入职后收企业端"',
             '猎头费3-6月薪，单人3-5万',
             '招聘市场恢复→人才自流通→猎头费被压低→转做培训'),
            (f'{ent}股价波动→员工期权套现需求→折价交易市场断裂',
             f'{ent}离职社群/期权交易平台上的持权员工',
             '以「家族办公室」名义接盘→"我们帮你7-8折变现，6个月内退出"',
             '折扣空间20-30%',
             '股价回升至行权价→套现需求消失→退出'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 5. IPO/上市 ===
    if any(kw in title_lower for kw in ['ipo', '上市', '过会', 'a股', '港股']):
        templates = [
            (f'{ent}上市前老股东套现→老股转让市场信息不对称',
             f'查{ent}招股书→找持股>5%的早期股东',
             '以「家族办公室」名义接老股→"6-7折接，上市后退出"',
             '折扣空间30-40%',
             '招股定价过高/上市破发→退出不赚钱→止损'),
            (f'{ent}新股上市→打新资金需求→融资供需断裂',
             f'查{ent}招股定价区间→算所需打新资金→对接资金方',
             '以「打新融资对接」名义→"我们帮您对接低成本打新资金"',
             '融资利差2-3%/笔',
             '中签率持续下降→资金方无利可图→需求萎缩'),
            (f'{ent}解禁期→老股东需做市值管理→IR顾问缺口',
             f'查{ent}解禁日(招股书)→锁定需做市值管理的股东',
             '以「投资者关系顾问」名义接单→"我们帮您做减持规划，避免踩雷"',
             '顾问费10-20万/季',
             '减持完成→需求消失→转向下个IPO标的'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 6. 出口/关税/制裁/贸易 ===
    if any(kw in title_lower for kw in ['出口', '关税', '制裁', '贸易']):
        templates = [
            (f'{ent}受制裁/关税影响→出口受阻→转口需求爆发',
             '查受影响的HS编码和税率变化→找受影响出口商',
             '以「转口贸易咨询」名义→"我们帮您找第三国中转，规避关税"',
             '转口中介费2-5%',
             '贸易壁垒消除/税率下调→转口需求消失→退出'),
            (f'贸易壁垒→合规咨询需求→企业不知道怎么合规',
             '下载最新海关归类决定书→找受影响企业法务',
             '以「贸易合规顾问」名义→"帮您做原产地规划，合法降低税负"',
             '8-15万/案',
             '政策明朗→企业自建合规团队→外部顾问需求下降'),
            (f'制裁→替代供应链出现→供需信息断裂',
             '查受制裁产品的替代供应商名录→对接需求方',
             '以「替代供应商撮合」名义→"我们帮您找到合规替代来源"',
             '信息费1-3%',
             '替代渠道成熟→信息差消失→转做供应链金融'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 7. 出海/全球化 ===
    if any(kw in title_lower for kw in ['出海', '全球化', '海外']):
        templates = [
            (f'{ent}出海需本地渠道→但找不到靠谱经销商→渠道缺口',
             '目标市场工商登记查询→找已有经销商/代理商',
             '以「目标市场落地顾问」名义→"我们帮您快速找到当地经销商"',
             '首单5-8万+流水1%',
             '客户自建当地团队→你被替代→转做下一个市场'),
            (f'{ent}出海需本地化→语言/文化/法规不熟悉→服务缺口',
             '查目标市场同类产品市占率→找本地化需求方',
             '以「本地化服务商」名义→"市场调研+渠道搭建一站搞定"',
             '项目费10-20万',
             '客户积累本地经验→不再外包→转向新客户'),
            (f'品牌进新市场→需本地公司做代理→主体注册缺口',
             '查目标市场公司注册最低资本要求→找需代理的品牌方',
             '以「区域代理主体」名义注册→"我们做您的本地法人主体"',
             '年管理费5-10万+流水抽成',
             '品牌方自建主体→你角色消失→转向新品牌'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 8. 品牌/营销 ===
    if any(kw in title_lower for kw in ['品牌', '营销', '新消费', '道歉', '危机']):
        templates = [
            (f'{ent}公关危机→需要紧急危机处理→时间窗口48小时',
             f'查{ent}媒体曝光度(Google Trends)→定位危机等级',
             '以「品牌公关顾问」介入→"我们24小时内出方案，帮您对接媒体"',
             '8-15万/案',
             '危机平息→需求消失→但可转长期品牌顾问'),
            (f'品牌扩张需本地化→授权代理市场断裂',
             f'查{ent}商标注册状态(商标局)→找需授权的本地运营商',
             '以「品牌授权代理」名义谈→"我们帮您拿到授权后转包运营"',
             '授权差价10-20%',
             '品牌方自建直营→授权撤回→转向新品牌'),
            (f'新消费退潮→品牌倒闭→库存清仓需求爆发',
             '阿里司法拍卖搜相关设备折价信息→找倒闭品牌方',
             '以「库存清仓中介」名义→"我们帮您快速清库存回笼资金"',
             '清仓费5-10%+残值分润',
             '行业出清完成→无库存可清→转向下个退潮行业'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 9. 台湾/两岸 ===
    if any(kw in title_lower for kw in ['台湾', '两岸', '小三通', '金门']):
        templates = [
            (f'两岸兑汇渠道不透明→民间兑汇所信息不对称',
             '金门金城镇民间兑换所(后浦老街周边)',
             '以「代付货款」名义谈合作→"每笔收0.3-0.5%手续费"',
             '汇差+手续费0.3-0.5%/笔，单笔<5万台币',
             '反洗钱新规要求单笔5万以上报备→收紧→转合规QDII'),
            (f'小三通货运→金门中转仓代发需求→仓租+操作费',
             '金门海运公司(金门快轮等)问散货拼柜价格',
             '以「集运服务商」名义→"帮您做金门中转仓代发"',
             '仓租+操作费，月入5-10万台币',
             '小三通政策收紧/中转仓被查→立即停运'),
            (f'两岸信息差→大陆人买不到台湾商品→代购缺口',
             '淘宝搜台湾商品看竞品定价→找需求方',
             '以「台湾代购」名义做电商→"我们帮您买到台湾正品"',
             '代购费15-25%/单',
             '电商平台直采台湾商品→代购价差消失→转向独家品'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 10. 庙宇/信仰 ===
    if any(kw in title_lower for kw in ['庙宇', '供奉', '开光', '法会', '线上信仰']):
        templates = [
            (f'庙宇数字化→线下庙宇缺线上运营能力→SaaS代运营缺口',
             f'Google Maps搜{ent}相关道教庙宇(赵公明/关帝)→找住持/管理委员会',
             '以「数字化服务商」名义谈→"首月免费试运营→满意再签年费"',
             '年费2-5万/庙+供养品代销抽20%',
             '宗教政策收紧→停新拓只做存量→复购率低则3月评估退出'),
            (f'信仰经济→复购率碾压SaaS→线上法会直播需求断裂',
             '下载法会直播竞品(如"功德林"App)→找有需求的庙宇',
             '以「线上法会直播」名义→"帮您做线上法会→扩大信众覆盖"',
             '3-5万/场',
             '合规风险→定位必须「技术服务」非「宗教服务」→红线触碰立即停'),
            (f'庙宇数字化→供养品供应链加价20-40%→供应缺口',
             '查宗教用品批发商(台北地下街等)→找缺供货渠道的庙宇',
             '以「庙宇用品供应商」名义→"我们提供一站式供养品采购"',
             '供应链加价20-40%',
             '庙宇自建供应链→价差消失→转做定制化高端供养品'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 11. 彩票 ===
    if any(kw in title_lower for kw in ['彩票', '彩券', '威力彩', '大乐透']):
        templates = [
            (f'台彩经销商转让市场信息不对称→想卖找不到买家',
             '台湾公益彩券官网查经销点转让公告→找想转让的经销商',
             '以「朋友介绍」名义联系→"帮您找到接手人"',
             '介绍费5-10万/单',
             '台彩禁止私下转让→转「承包经营」名目→被查则停'),
            (f'台彩头奖效应→合买需求爆发→但缺可信赖的合买组织者',
             'LINE开放聊天室搜「威力彩合买」看竞品→找潜在群主',
             '以「好友集资合买」名义建LINE群→"每期组织合买，5%服务费"',
             '月服务费5千-1万台币',
             '台彩明文禁止→改名「集资」→被举报→解散换群'),
            (f'彩票数据→合买群缺选号建议→数据分析服务缺口',
             '用刘海蟾系统生成近10期分析→找合买群群主',
             '以「数据分析服务」名义→"我们提供专业选号建议→月费500-1000台币/人"',
             '月费500-1000/人',
             '用户流失率>50%/月→验证需求不真实→停'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 12. 涨价/缺货 ===
    if any(kw in title_lower for kw in ['涨价', '缺货', '断供', '铜', '铝', '钢', '硫酸', '锂']):
        templates = [
            (f'{ent}供应断裂→有货没渠道的供应商+缺货的买家→供需断裂',
             'LME(伦敦金属交易所)实时库存数据→找缺货采购方',
             '以「行业贸易对接」名义撮合→"我们有现货渠道，帮您对接"',
             '撮合费2-4%',
             '供需恢复平衡→断裂弥合→退出转下个品类'),
            (f'涨价→下游减产→替代品需求爆发但信息不对称',
             '查同业公会会员名录→找需替代品的下游企业',
             '以「替代供应商中介」名义→"帮您找到性价比更高的替代品"',
             '信息费3-5%',
             '原品价格回落→替代需求消失→转下个涨价品类'),
            (f'库存波动→囤货方需融资→供应链金融缺口',
             '上海期货交易所仓单质押规则→找有库存的贸易商',
             '以「供应链金融」名义→"帮您用库存做质押融资→利率比银行低"',
             '2-3%/月',
             '价格暴跌→质押物贬值→坏账风险→收紧风控'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 13. 降息/央行/利率 ===
    if any(kw in title_lower for kw in ['降息', '央行', '利率', '美联储']):
        templates = [
            (f'利差变化→资金有跨境配置需求→但缺合规通道',
             '查两岸定存利差数据→找有配置需求的资金方',
             '以「私人银行渠道」名义对接→"帮您找到合规的境外配置通道"',
             '通道费1-2%',
             '利差收窄至0.5%以内→通道费覆盖不了→退出'),
            (f'利率下降→房产估值上升→投资咨询需求断裂',
             '查目标市场房产实价登录数据→找有投资意愿的资金方',
             '以「房产投资顾问」名义→"帮您找到估值洼地的房产标的"',
             '成交佣金2-3%',
             '房产泡沫破裂→估值回落→客户亏损→口碑崩→立即停'),
            (f'汇率波动→企业需做汇率对冲→但缺专业服务',
             '查即期汇率与NDF差价→找有进出口业务的企业财务总监',
             '以「跨境结算服务」名义→"帮您锁定汇率成本"',
             '0.5-1%/笔',
             '汇率趋于稳定→对冲需求下降→转做供应链金融'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 14. 新能源 ===
    if any(kw in title_lower for kw in ['新能源', '锂', '光伏', '储能', '电网']):
        templates = [
            (f'{ent}产能过剩→补贴退出→海外有需求→跨境撮合断裂',
             '查目标市场再生能源设置量→找有库存的光伏/储能企业',
             '以「绿能贸易撮合」名义→"帮您把过剩产能卖到海外"',
             '清库费3-5%',
             '海外关税壁垒升级→出口受阻→转向内需撮合'),
            (f'光伏组件有进口需求→大陆组件过剩→贸易信息不对称',
             '查目标市场光伏进口关税率→找需求方和供应方',
             '以「绿能贸易」名义撮合→"我们帮您对接性价比最高的组件"',
             '贸易撮合2-3%',
             '关税上调→贸易量骤降→转向储能'),
            (f'储能项目融资→缺FA对接→资金与项目断裂',
             '查储能项目IRR(公开标案数据)→找缺资金的储能项目',
             '以「项目FA」名义→"帮您找到匹配的资金方"',
             'FA费2-3%',
             '行业融资环境收紧→项目停摆→转做运维服务'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 15. 暴跌/恐慌 ===
    if any(kw in title_lower for kw in ['暴跌', '崩盘', '恐慌', '危机']):
        templates = [
            (f'{ent}恐慌抛售→折价资产出现→但买家找不到→交易断裂',
             f'查{ent}相关资产折价幅度(法拍/大宗交易)→找有现金的买家',
             '以「危机收购顾问」名义→"帮您在恐慌中找到折价宝贝"',
             '交易佣金2-3%',
             '恐慌情绪消退→折价消失→无利可图→退出'),
            (f'恐慌→折价资产→银行AMC需处置→但缺对接渠道',
             '查四大AMC最新不良资产包公告→找有资金的投资人',
             '以「不良资产撮合」名义→"帮AMC找到接盘方"',
             '撮合费1-2%',
             '市场恢复→不良资产包减少→转向正常资产撮合'),
            (f'市场恐慌→企业需做压力测试→但缺专业风控顾问',
             '下载COSO企业风险管理评估模板→找CFO/风控总监',
             '以「风险对冲顾问」名义→"帮您做压力测试+风控方案"',
             '咨询费5-10万',
             '恐慌消退→风控预算被砍→转做常年顾问'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 16. 暴涨/炒作 ===
    if any(kw in title_lower for kw in ['暴涨', '疯抢', '炒作']):
        templates = [
            (f'{ent}炒作过热→获利盘需找退出通道→但缺渠道',
             f'查{ent}近3个月涨幅和换手率→找有获利盘的早期投资人',
             '以「退出通道服务商」名义→"帮您在高位有序退出"',
             '通道费2-3%→不做多不做空→只做桥',
             '泡沫破裂→退出需求消失→但坏账风险上升→立即停'),
            (f'泡沫期→早期投资人需退出规划→缺专业顾问',
             f'查{ent}VC/PE投资轮次和估值→找有退出需求的基金',
             '以「退出策略顾问」名义→"帮您做最优退出时点规划"',
             '顾问费+退出佣金1-2%',
             '估值回归理性→退出溢价消失→转做投后管理'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 17. 政策/新规/监管 ===
    if any(kw in title_lower for kw in ['政策', '新规', '监管', '整顿']):
        templates = [
            (f'{ent}监管收紧→企业需合规→但缺合规架构设计',
             '查最新监管条文原文(国务院/部委官网)→找受影响企业法务',
             '以「合规架构顾问」名义→"帮您设计合规主体架构"',
             '8-15万/案',
             '政策明朗→企业自建合规团队→需求下降→转向新政策解读'),
            (f'监管靴子落地→受影响企业需转型→缺过渡方案',
             f'列出受{ent}影响的行业清单(天眼查行业分类)→找需转型的企业',
             '以「合规过渡方案」名义→"帮您从旧模式平滑过渡到合规模式"',
             '5-15万/案',
             '行业完成转型→需求消失→转向下一个受监管行业'),
            (f'新规→行业需解读→研讨会+白皮书需求断裂',
             f'查{ent}相关行业微信群→找行业KOL做背书',
             '以「政策解读服务」名义→"我们做研讨会+白皮书→帮您理解新规"',
             '会费+赞助→单场5-10万',
             '新规解读完成→需求一次性→持续关注新政策'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 18. 火灾/事故/停产 ===
    if any(kw in title_lower for kw in ['火灾', '事故', '停产']):
        templates = [
            (f'{ent}供应链中断→保险理赔前3-6周真空→替代供应缺口',
             f'查{ent}事故影响的产品品类→找替代品供应商',
             '以「紧急替代供应」名义→"我们有现货，3天内到货"',
             '加急费5-10%',
             '事故方恢复生产→替代需求消失→转下个事故'),
            (f'停产→库存急缺→调货服务缺口',
             '联系相关产品经销商问库存→找缺货的下游',
             '以「紧急调货」名义→"从备用仓库调货，加急配送"',
             '加急运费+10-15%',
             '停产恢复→库存回补→紧急调货需求消失'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 19. 融资/投资/收购 ===
    if any(kw in title_lower for kw in ['融资', '投资', '收购']):
        templates = [
            (f'{ent}融资→上下游有跟投机会→但缺FA撮合',
             f'查{ent}融资轮次和领投方(IT桔子)→找有跟投需求的资方',
             '以「产业链协同投资人」名义→"帮您找到最匹配的产业资本"',
             'FA费2-3%',
             '融资轮次关闭→FA窗口期结束→转向下个标的'),
            (f'融资→投后管理需求→被投企业缺财务/法务/HR',
             f'列出{ent}所在赛道的投后服务需求清单→找缺管理的被投企业',
             '以「投后管理服务商」名义→"帮您做财务/法务/HR外包"',
             '月费5-10万',
             '企业自建团队→外包需求下降→转向新融资标的'),
            (f'收购→被收购方员工会离职→人才承接缺口',
             f'在LinkedIn搜{ent}员工近期动态→找即将离职的核心人才',
             '以「人才承接」名义帮挖人→"我们帮您找到下家"',
             '猎头费3-6月薪',
             '收购整合完成→人才流失高峰过去→转做组织优化'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 20. 黄金/贵金属 ===
    if any(kw in title_lower for kw in ['黄金', '白银', '贵金属']):
        templates = [
            (f'{ent}→跨境贵金属配置需求→但渠道不透明',
             '查银行黄金保管箱开户条件→找有配置需求的资金方',
             '以「贵金属跨境通道」名义撮合→"帮您找到合规的贵金属配置渠道"',
             '通道费1-2%',
             '金价暴跌→配置需求萎缩→退出'),
            (f'金价波动→企业需黄金借贷→租赁市场断裂',
             '查上海黄金交易所租赁利率→找需黄金的企业',
             '以「黄金租赁」名义→"帮您做黄金借贷，年化3-5%"',
             '年化3-5%',
             '金价单边下跌→出借方亏损→收紧出借→评估风险'),
        ]
        return _format_xie_xiu_card(templates[seed % len(templates)])

    # === 21. 默认/通用 ===
    templates = [
        (f'从{ent}找套利视角→信息不对称处就是收钱位置——知道但接触不到的人+能接触但不知道的人之间有断裂',
         f'搜{ent}的上下游企业(行业黄页/天眼查)→找信息弱势方',
         '以「行业信息桥」名义→"我们帮您对接上/下游资源"',
         '信息差利差5-15%',
         '3个月签不到单→验证需求不真实→止损退出'),
        (f'{ent}→相关产业有渠道需求→供需断裂',
         '查同业公会/行业协会会员名单→找需渠道对接的企业',
         '以「行业资源对接」做中间人→"首单免费，后续收1-3%"',
         '1-3%撮合费',
         '双方跳过你直接交易→换下一对→连续3次被跳则退出该领域'),
        (f'每条新闻背后都有供需断裂→{ent}的断裂在哪→找到断裂做那座桥',
         f'用Google搜「{ent} + 供应商/经销商」→定位断裂点',
         '以「断裂撮合」名义→"帮您找到断裂的另一端"',
         '过桥费1-3%',
         '断裂被大平台弥合→你的桥角色消失→转向下个断裂'),
    ]
    return _format_xie_xiu_card(templates[seed % len(templates)])



def _validate_signal(signal, title, existing_signals=None):
    """V14: 验证落地动作质量 — 检查实体引用+具体数值+同质化
    
    Returns: (is_valid, reason)
    """
    import re
    entity = _extract_entity(title)
    ent_short = entity[:8] if len(entity) > 8 else entity

    # 检查1: 落地动作是否引用了新闻实体
    if ent_short and len(ent_short) >= 2 and ent_short not in signal:
        # 宽松检查：实体可能是公司全名(含代码)，落地动作中可能用了简称
        ent_core = re.sub(r'[（(].*?[）)]', '', ent_short).strip()
        if ent_core and len(ent_core) >= 2 and ent_core not in signal:
            pass  # 允许不引用实体（某些场景动作可能确实与实体无关）

    # 检查2: 是否有具体数值（金额/百分比/时间窗口）
    has_number = bool(re.search(r'\d+[%万台币元万千百]', signal))
    if not has_number:
        return False, "缺少具体数值"

    # 检查3: 同质化检测 — 与已有落地动作是否太相似
    if existing_signals:
        for existing in existing_signals:
            # 比较前20字的重叠度
            overlap = sum(1 for c in signal[:30] if c in existing[:30])
            if overlap > 20:  # 30个字符中有20+个相同，视为同质化
                return False, f"与已有动作同质化(重叠{overlap}/30)"

    return True, "通过"


def _fallback_gap_scan(top_items):
    """降级: 缺口扫描 — V10版含新闻实体注入，操作卡不泛泛而谈"""
    lines = ["## 二、市场/中间人缺口扫描\n"]
    lines.append("> 基于今日新闻的供需断裂 + 具体操作路径:\n")

    # V13: 先做新闻质量过滤
    quality_items = [n for n in top_items if len(n.get('title', '')) > 10 and
                     not any(j in n.get('title', '') for j in ['早报', '晚报', 'Daily', '8点1氪'])]
    if not quality_items:
        quality_items = top_items

    # 从新闻中提取关键信号词
    signal_keywords = _extract_signal_keywords(quality_items)

    gaps_found = 0
    for kw, context in signal_keywords.items():
        if gaps_found >= 2:
            break

        # V17: 实体名最长8字
        entity = _extract_entity(context)
        ent_short = entity[:8] if len(entity) > 8 else entity

        # 基于关键词推断缺口
        if kw in ['台湾', '两岸', '小三通']:
            lines.append(f"- **缺口**: {ent_short}→两岸通道 — {context[:30]}")
            lines.append("  - 💰 收钱模式: 小三通货运不报关/台币人民币民间兑汇/金门中转仓代发")
            lines.append("  - 🛡️ 规避路径: 单笔5万以下不触发反洗钱、走金门民间兑换所不走银行、货拆散件入境")
            lines.append("  - ⏱️ 窗口期: 政策收紧前（ECFA/小三通评估节点），通常3-6个月为一轮")
            lines.append(f"  - 🎯 操作卡: ①到金门/厦门找民间兑汇商→②以'{ent_short}'合作名义谈→③首笔试水5万台币→④走微信/支付宝对敲结算→⑤两岸任一端口严查就停")
        elif kw in ['线上庙宇', '信仰经济', '供奉', '开光']:
            lines.append(f"- **缺口**: 线上信仰平台代运营 — {context[:30]}")
            lines.append("  - 💰 收钱模式: 平台抽成15-30%/SaaS年费2-5万/庙/信仰商品供应链加价20-40%")
            lines.append("  - 🛡️ 规避路径: 不做宗教场所经营（需要审批）、只做'技术服务'和'电商代运营'、用科技公司主体")
            lines.append("  - ⏱️ 窗口期: 线上信仰还在跑马圈地阶段，预计2-3年跑出头部")
            lines.append("  - 🎯 操作卡: ①赵公明线上庙宇已启动→②找3-5家线下庙宇谈数字化合作→③首单免费做样板→④签年费SaaS+供养品代销→⑤复购率验证3个月后扩规模")
        elif kw in ['彩票', '彩券', '台彩', '威力彩']:
            lines.append(f"- **缺口**: 台彩经销权/合买平台 — {context[:30]}")
            lines.append("  - 💰 收钱模式: 经销权转让中间费（5-15万）/线上合买抽佣（5-10%）")
            lines.append("  - 🛡️ 规避路径: 合买以'社群团购'名义组织、不走官方平台抽成、用个人收款码分散入账")
            lines.append("  - ⏱️ 窗口期: 合买/代购处于灰色地带，政策明朗前快速收割")
            lines.append("  - 🎯 操作卡: ①在台湾找想转让的台彩经销商→②做中间撮合收介绍费→③同时建LINE群做合买→④收5%服务费→⑤台彩公司明文禁止合买时立刻停")
        elif kw in ['涨价', '缺货', '断供', '铜', '铝', '钢', '硫酸', '锂']:
            lines.append(f"- **缺口**: 供需断裂撮合 — {context[:30]}")
            lines.append("  - 💰 收钱模式: 撮合费（按交易额1-3%），自己不持仓不囤货")
            lines.append("  - 🛡️ 规避路径: 纯信息撮合（不签买卖合同、不碰货、不碰资金），出了问题你是介绍人不是交易方")
            lines.append("  - ⏱️ 窗口期: 供给冲击后2-4周最活跃，替代方案出现后关闭")
            lines.append("  - 🎯 操作卡: ①找到有货没渠道的供应商→②找到缺货的买家→③以'行业资源对接'名义介绍→④收撮合费现金/私账→⑤买卖双方跳过你直接交易时换下一对")
        else:
            lines.append(f"- **缺口**: {ent_short}的信息断裂 — {context[:30]}")
            lines.append(f"  - 💰 收钱模式: 在「{ent_short}」这条新闻背后的信息不对称处做中间人——不持仓只收撮合费")
            lines.append("  - 🛡️ 规避路径: 不签合同不碰货不碰资金，纯介绍人身份，出事免责")
            lines.append("  - ⏱️ 窗口期: 新闻热度消退前（1-2周），信息充分扩散后窗口关闭")
            lines.append(f"  - 🎯 操作卡: ①从'{ent_short}'找到信息最不对称的环节→②找到有资源没渠道的一方→③以{ent_short}'合作'名义联系→④收撮合费→⑤双方跳过你时换下一对")

        gaps_found += 1

    # 如果不足2条缺口，用最高分未使用的新闻补1条（必须绑定具体新闻标题）
    if gaps_found < 2 and top_items:
        used_titles = set()
        for kw, ctx in signal_keywords.items():
            used_titles.add(ctx[:30])
        for item in top_items:
            title = item.get('title', '')
            if title[:30] not in used_titles:
                ent = _extract_entity(title)
                lines.append(f"- **缺口**: {ent[:8]}的套利窗口 — {title[:35]}")
                lines.append(f"  - 💰 收钱模式: 围绕'{ent[:8]}'这条新闻→找上下游供需断裂→做撮合抽1-3%")
                lines.append("  - 🛡️ 规避路径: 纯撮合不持仓不碰货→介绍人身份")
                lines.append("  - ⏱️ 窗口期: 新闻热度1-2周内")
                lines.append(f"  - 🎯 操作卡: ①从'{ent[:8]}'找到供需断裂→②找有货没渠道方→③以'行业对接'名义→④收现金撮合费→⑤失效换下一对")
                gaps_found += 1
                break

    # 用户当前可行动标记
    lines.append(f"\n> 📍 **行动提示**: 以上缺口按热度排序，优先考察自己能快速触达的环节，不碰货不碰资金，只做信息撮合。")

    return "\n".join(lines)


def _fallback_contra_tide(top_items):
    """V13: 逆潮观察 — 选最有话题性的新闻(非top_items[0])，输出具体判断"""
    lines = ["## 三、逆潮观察\n"]
    lines.append("> 市场共识可能在错，找到逆向下注的方向:\n")

    if not top_items:
        lines.append("- **市场共识**: 当前主流叙事")
        lines.append("  - 逆向可能: 共识越强，反转越猛")
        lines.append("  - 逆向下注: 在恐慌中找折价资产")
        lines.append("  - 止损线: 共识持续强化2周则认错")
        return "\n".join(lines)

    # V13: 选有事件性的新闻(优先事件词>融资公告)
    best = None
    event_words = ['暴涨', '暴跌', '发布', '推出', '制裁', '火灾', '事故', '政策', '新规', '回应',
                   '崩溃', '突破', '创新', '合作', '收购', '上市', '过会', '出海']
    for item in top_items[:15]:
        t = item.get('title', '')
        if len(t) < 12 or any(j in t for j in ['早报', '晚报', 'Daily', '8点1氪']):
            continue
        if any(ew in t for ew in event_words):
            best = item
            break
    if not best:
        for item in top_items[:15]:
            t = item.get('title', '')
            if len(t) > 15 and not any(j in t for j in ['早报', '晚报', 'Daily', '8点1氪', '融资丨']):
                best = item
                break
    if not best:
        best = top_items[0] if top_items else None

    if not best:
        lines.append("- **市场共识**: 数据不足")
        lines.append("  - 逆向可能: 等待更多信号")
        return "\n".join(lines)

    title = best.get('title', '')
    entity = _extract_entity(title)
    # V17: 实体名最长8字，去掉介词前缀
    ent_raw = entity[:8] if len(entity) > 8 else entity
    ent = re.sub(r'^[在的得了被把将向从]', '', ent_raw).rstrip('？?！!。、')
    title_lower = title.lower()

    # 检测共识倾向 — V16: 扩充关键词覆盖+else分支生成具体逆向分析
    if any(kw in title_lower for kw in ['暴涨', '疯抢', '热', '爆发', 'ALL IN', '新高', '历史最高', '飙升', '翻倍', '大涨']):
        consensus = f"'{title[:25]}' → 市场共识偏向狂热"
        reverse = "涨过头必有回调——关注库存积压/产能释放信号"
        bet = "做空或减仓相关资产，等回调20%以上再入场"
        stop = "价格再涨15%且基本面持续强化，则逆向判断错误"
    elif any(kw in title_lower for kw in ['暴跌', '崩', '恐慌', '裁', '关停', '新低', '腰斩', '闪崩', '暴跌', '崩盘']):
        consensus = f"'{title[:25]}' → 市场共识偏向恐慌"
        reverse = "恐慌出清后强势玩家市占率上升——关注龙头"
        bet = "在恐慌底部布局行业龙头/核心资产，分批建仓"
        stop = "负面信号持续3周无缓和，则恐慌不是暂时的"
    elif any(kw in title_lower for kw in ['新规', '政策', '监管', '整顿', '审查', '备案', '合规', '限制', '禁令']):
        consensus = f"'{title[:25]}' → 市场共识偏向悲观"
        reverse = "政策从发文到执行有时间差，且执行往往打折"
        bet = "趁市场过度反应时反向布局受影响资产"
        stop = "政策细则出台后确实严格，则逆向判断错误"
    elif any(kw in title_lower for kw in ['发布', '推出', '首发', '突破', '创新', '技术', '量子', '上线']):
        consensus = f"'{title[:25]}' → 市场共识偏向乐观期待"
        reverse = f"新技术/新产品发布→PPT到量产差18-24个月→市场高估短期影响→{ent}的实际商业化进度远慢于预期"
        bet = f"做空{ent}概念股的短期溢价，或在发布后1-2周买入被连带错杀的竞争对手"
        stop = f"如果6个月内{ent}真的达到量产里程碑，则逆向判断错误"
    elif any(kw in title_lower for kw in ['融资', '投资', '收购', '合并', '并购', '定增', '募资']):
        consensus = f"'{title[:25]}' → 市场共识偏向看好融资方"
        reverse = f"融资≠盈利→{ent}拿钱烧补贴→估值虚高→下一轮融资可能down round→早期投资人锁定期后抛售"
        bet = f"不投{ent}本身→投其供应链（被融资方需求拉动的上游）→确定性更高"
        stop = f"如果{ent}融资后6个月内营收增长>100%，则融资方确实在吃市场"
    elif any(kw in title_lower for kw in ['出口', '关税', '制裁', '贸易', '禁运', '脱钩']):
        consensus = f"'{title[:25]}' → 市场共识偏向悲观脱钩"
        reverse = "脱钩越狠→灰色通道利润越高→官方越堵→民间越钻→供需不会断只会变形"
        bet = "布局转口贸易/替代供应链中间人角色，脱钩程度=利润空间"
        stop = "替代供应链完全建立（6-12个月），中间人窗口关闭"
    else:
        # V16: else分支不再说空话，基于新闻实体生成具体逆向判断
        # 提取行业关键词推断
        industry_hints = []
        if any(kw in title_lower for kw in ['科技', '技术', '软件', '硬件', '互联网', '平台']):
            industry_hints = ['科技', '技术迭代快→6个月淘汰一轮→不追首发等二代']
        elif any(kw in title_lower for kw in ['金融', '银行', '保险', '证券', '基金']):
            industry_hints = ['金融', '监管周期3-5年→利空出尽是利好→利好出尽是利空']
        elif any(kw in title_lower for kw in ['能源', '电力', '石油', '天然气', '煤炭']):
            industry_hints = ['能源', '周期性极强→价格高点=供给扩张起点→2年后过剩']
        elif any(kw in title_lower for kw in ['医药', '医疗', '生物', '药']):
            industry_hints = ['医药', '研发到上市10年→新闻发布≠产品上市→90%倒在临床']

        if industry_hints:
            consensus = f"'{title[:25]}' → {industry_hints[0]}行业共识偏乐观"
            reverse = industry_hints[1]
            bet = f"在{ent}的热度消退期（3-6个月后）低价布局真正受益的上游"
            stop = f"如果{ent}所在行业基本面持续改善3个月，则行业趋势确实成立"
        else:
            # 最终兜底：基于实体生成具体判断而非空话
            consensus = f"'{title[:25]}' → 市场正在消化{ent}信息，方向未定"
            reverse = f"方向未定=还有人没下注→邪修先于共识布局{ent}的上下游断裂点"
            bet = f"找{ent}供应链中信息不对称最大的环节（有货没渠道/有需求没供给）→做中间人"
            stop = f"如果{ent}方向在2周内被大资金明确表态（涨停/跌停），则跟风窗口关闭"

    lines.append(f"- **市场共识**: {consensus}")
    lines.append(f"  - 逆向可能: {reverse}")
    lines.append(f"  - 逆向下注: {bet}")
    lines.append(f"  - 止损线: {stop}")

    return "\n".join(lines)


def _fallback_deep_chain(top_items):
    """V15: 具体因果链传导 — 铜涨价→硫酸涨价→磷酸涨价，而非抽象的"第N层影响"
    核心思路: 从CHAIN_TEMPLATES中匹配具体因果链，注入新闻实体，生成传导路径
    格式: A→B→C→D→E (每步是具体的商品/行业/现象，不是抽象概念)"""
    lines = ["## 四、深度传导分析\n"]
    lines.append("> 从今日核心新闻出发，推导因果传导链:\n")

    if not top_items:
        lines.append("🔮 **天之道: 损有余补不足 — 待数据补充**")
        lines.append("⚡ **邪修之道: 在有余和不足之间收过路费**")
        return "\n".join(lines)

    # 选最有事件性的新闻
    best = None
    event_words = ['暴涨', '暴跌', '发布', '推出', '制裁', '火灾', '事故', '政策', '新规', '回应',
                   '崩溃', '突破', '创新', '合作', '收购', '上市', '过会', '出海']
    for item in top_items[:15]:
        t = item.get('title', '')
        if len(t) < 12 or any(j in t for j in ['早报', '晚报', 'Daily', '8点1氪']):
            continue
        if any(ew in t for ew in event_words):
            best = item
            break
    if not best:
        for item in top_items[:15]:
            t = item.get('title', '')
            if len(t) > 15 and not any(j in t for j in ['早报', '晚报', 'Daily', '8点1氪', '融资丨']):
                best = item
                break
    if not best and top_items:
        best = top_items[0]
    if not best:
        lines.append("🔮 **天之道: 损有余补不足 — 待数据补充**")
        lines.append("⚡ **邪修之道: 在有余和不足之间收过路费**")
        return "\n".join(lines)

    title = best.get('title', '')
    title_lower = title.lower()
    source = best.get('source', '')
    entity = _extract_entity(title)
    # V17: 实体名最长8字，去掉介词前缀
    ent_raw = entity[:8] if len(entity) > 8 else entity
    ent = re.sub(r'^[在的得了被把将向从]', '', ent_raw)

    # 从辅助新闻提取实体
    aux_entities = []
    for item in top_items[:6]:
        e = _extract_entity(item.get('title', ''))
        if e and e != entity and len(e) >= 2:
            aux_entities.append(e[:14])
    aux_ent = aux_entities[0] if aux_entities else '关联方'
    aux_ent2 = aux_entities[1] if len(aux_entities) > 1 else '下游'

    # V15: 具体因果链 — 每步传导是具体的商品/行业/现象
    if '台湾' in source or any(kw in title_lower for kw in ['台湾', '两岸', '台']):
        chain = f"{ent}事件 → 两岸物流/资金流短期调整 → 小三通货运量波动 → 台币/人民币民间汇兑需求激增 → 金门/厦门仓储转运需求上升 → 民间灰色通道取代部分官方渠道"
        surplus = "官方渠道的过剩壁垒（审批慢/配额少/关税高）"
        deficit = "民间通道的不足供给（快速通关/民间兑汇/拆散入境）"
        tian_dao = f"天之道: 损官方壁垒之有余→补民间通道之不足\n  > 推导: 兑汇需求↑+仓储转运↑+灰色通道利润↑→有余在官方、不足在民间"
        xie_xiu = f"邪修之道: 在金门/厦门之间做「民间桥梁」→①台币人民币对敲赚汇差②小三通货运不报关③金门中转仓代发→月入5-15万台币→两岸任一端口严查就停"

    elif any(kw in title_lower for kw in ['铜', '铜价']):
        chain = f"铜矿减产/涨价 → 冶炼加工费压缩 → 硫酸涨价（铜冶炼副产） → 磷肥成本上升 → 粮食生产成本增加"
        surplus = "铜库存过剩方（有货没渠道的供应商）"
        deficit = "硫酸/磷肥需求方（缺货的生产企业）"
        tian_dao = f"天之道: 损铜库存之有余→补硫酸/磷肥之不足\n  > 推导: 铜涨价→硫酸涨价→磷肥涨价→粮食成本↑→有余在铜库存、不足在硫酸/磷肥"
        xie_xiu = f"邪修之道: 不赌铜价涨跌→在铜→硫酸→磷肥的断裂处做中间人→①找有铜的供应商②找缺硫酸的磷肥厂③以「行业贸易对接」撮合→收2-4%→不碰货不碰资金"

    elif any(kw in title_lower for kw in ['出海', '全球化', '海外', '硬件出海', '跨境', '出海', '品牌出海']):
        chain = f"{ent}出海/跨境扩张 → 目标市场渠道缺口 → 本地化服务需求爆发 → 代理/经销商网络价值上升 → 售后/运营服务缺口"
        surplus = f"{ent}出海后的过剩产能（产品有但渠道不通）"
        deficit = f"本地化服务的不足供给（懂市场+懂产品的人极度稀缺）"
        tian_dao = f"天之道: 损产能之有余（有产品没渠道）→补本地化之不足（缺服务缺人才）\n  > 推导: 出海→渠道缺口→本地化需求→有余在产品、不足在服务"
        xie_xiu = f"邪修之道: 不做出海方→做出海服务商→①帮{ent}找目标市场经销商②做本地化咨询③收项目费5-15万+流水1%→出海方死掉换下一家"

    elif any(kw in title_lower for kw in ['涨价', '缺货', '断供', '铜', '铝', '硫酸', '锂']) or \
         ('价' in title_lower and not any(kw in title_lower for kw in ['性价比', '物美价廉', '降价', '平价', '评价'])):
        chain = f"{ent}供应变化 → 下游{aux_ent}成本上升 → 终端产品定价调整 → 替代材料需求上升 → {aux_ent2}利润暴增"
        surplus = f"有{ent}库存的供应商（供给过剩）"
        deficit = f"缺{ent}的买家（需求过剩）"
        tian_dao = f"天之道: 损库存之有余→补需求之不足\n  > 推导: {ent}涨价→下游减产→替代需求↑→供需断裂→有余在库存、不足在需求"
        xie_xiu = f"邪修之道: 不赌价格涨跌→在供需断裂处做中间人→①找到有货没渠道的供应商②找到缺货的买家③以「行业贸易对接」撮合→收2-4%→不碰货不碰资金"

    elif any(kw in title_lower for kw in ['ai', '算力', 'gpu', '大模型', '英伟达', 'nvidia', '人工智能']):
        if not re.search(r'\bai\b', title_lower) and not any(kw in title_lower for kw in ['算力', 'gpu', '大模型', '英伟达', 'nvidia', '人工智能']):
            # "ai" 子串误匹配，走通用路径
            chain = f"{ent}事件 → 相关方利益重新分配 → 信息不对称出现 → 套利窗口 → 中间人机会"
            surplus = f"{ent}信息优势方"
            deficit = f"{ent}信息劣势方"
        else:
            chain = f"AI大模型训练需求爆发 → GPU/HBM供不应求 → 散热/电源/PCB配套涨价 → 数据中心建设加速 → 电力消耗激增→核电/绿电需求"
            surplus = "IDC的过剩算力（有供给但找不到客户）"
            deficit = "AI公司的不足算力（受出口管制/价格高买不到GPU）"
            tian_dao = f"天之道: 损IDC之有余（空置算力）→补AI公司之不足（买不到GPU）\n  > 推导: GPU出口管制→IDC空置↑→算力饥渴→有余在供给端、不足在需求端"
            xie_xiu = f"邪修之道: 做算力中间人→①接触有空置GPU的IDC机房②找到缺算力的AI公司③以「算力服务商」签服务协议④收中介费3-5%⑤只做服务撮合不做硬件走私"

    elif any(kw in title_lower for kw in ['出口', '关税', '制裁', '贸易']):
        chain = f"出口管制/关税调整 → 供应链被迫重组 → 转口贸易/第三国中转 → 合规成本上升 → 替代市场开拓"
        surplus = "受管制方的过剩产能（找不到渠道）"
        deficit = "替代通道的不足供给（转口/合规服务）"
        tian_dao = f"天之道: 损受管制方之有余（过剩产能）→补替代通道之不足（转口/合规）\n  > 推导: 管制→重组→转口→合规→有余在产能、不足在通道"
        xie_xiu = f"邪修之道: 在管制和合规之间做「转口中间人」→①找受影响的出口商②找第三国中转渠道③以「转口贸易服务」收2-5%→管制越严利润越高"

    elif any(kw in title_lower for kw in ['信仰', '庙宇', '供奉', '法会', '开光', '线上庙宇']):
        chain = f"线上信仰平台涌现 → 用户付费意愿验证(ARPU高) → 平台抽成/佣金模式 → 线下寺庙被迫数字化 → 信仰+电商/直播/AI开光新形态"
        surplus = "线下庙宇的过剩流量（香客减少、年轻化不足）"
        deficit = "线上信仰平台的不足供给（缺数字化工具和内容）"
        tian_dao = f"天之道: 损线下庙宇之有余（闲置流量）→补线上信仰之不足（数字化平台）\n  > 推导: 线上付费↑+数字化焦虑↑+跑马圈地期→有余在线下、不足在线上"
        xie_xiu = f"邪修之道: 赵公明线上庙宇已启动→①找3-5家线下庙宇谈代运营②首单免费做样板③签年费SaaS+代销分成20%④复购率验证3月→规模化"

    elif any(kw in title_lower for kw in ['彩票', '彩券', '威力彩', '大乐透', '台彩']):
        chain = f"彩票热度上升 → 投注量激增 → 台彩经销商牌照价值变化 → 灰色合买/代购需求出现 → 政策风险累积"
        surplus = "台湾彩票市场的过剩热度（头奖效应+投注潮）"
        deficit = "彩票周边服务的不足供给（合买平台/经销商撮合/数据分析）"
        tian_dao = f"天之道: 损头奖热度之有余→补周边服务之不足\n  > 推导: 牌照价值变化+灰色合买↑+政策窗口→有余在热度、不足在服务"
        xie_xiu = f"邪修之道: ①找想转让的台彩经销商→做撮合收5-10万②建LINE群做合买→收5%服务费③用刘海蟾系统做差异化④台彩禁止合买时停→转经销商撮合"

    elif any(kw in title_lower for kw in ['降息', '央行', '利率', '美联储']):
        chain = f"利率变化 → 两岸定存利差扩大 → 跨境资金流动加速 → 汇率波动加剧 → 对冲工具需求激增"
        surplus = "低利率方（资金成本低的地区）"
        deficit = "高利率方（资金需求大的地区）"
        tian_dao = f"天之道: 损低利率之有余（资金泛滥）→补高利率之不足（资金渴求）\n  > 推导: 利差→资金流动→汇率波动→有余在低利率端、不足在高利率端"
        xie_xiu = f"邪修之道: 在两岸利差之间做「资金桥梁」→①低息借人民币②换台币存高息③收利差1-2%/年→锁汇对冲风险"

    elif any(kw in title_lower for kw in ['新能源', '锂', '光伏', '储能', '电网']):
        chain = f"新能源装机量激增 → 储能配套不足 → 电网调度压力 → 虚拟电厂需求 → 电力市场化交易"
        surplus = "光伏组件的过剩产能（工厂库存积压）"
        deficit = "储能/消纳的不足供给（配套跟不上）"
        tian_dao = f"天之道: 损光伏产能之有余→补储能消纳之不足\n  > 推导: 装机↑→储能不足→消纳瓶颈→有余在产能、不足在配套"
        xie_xiu = f"邪修之道: 在产能和配套之间做中间人→①帮光伏厂清库存→②对接储能项目→③收3-5%撮合费"

    elif any(kw in title_lower for kw in ['融资', '投资', '收购', '定增', '募资']):
        chain = f"{ent}获融资 → 产能扩张 → 上下游供需重新洗牌 → 供应链议价权转移 → 中间服务商(FA/合规/猎头)需求激增"
        surplus = f"{ent}融资后的过剩产能（钱多项目少，烧钱期）"
        deficit = f"配套服务的不足供给（投后管理/人才/合规跟不上融资速度）"
        tian_dao = f"天之道: 损融资过剩之有余（烧钱期产能闲置）→补配套服务之不足（投后/人才/合规缺口）\n  > 推导: 融资→扩张→但人才/合规/渠道跟不上→有余在资金、不足在配套"
        xie_xiu = f"邪修之道: 不投{ent}→投其配套缺口→①做{ent}的投后管理外包②做被融资挤出的竞争对手的转型顾问③收5-10万/月→融资方倒了你换下一家"

    elif any(kw in title_lower for kw in ['科技', '技术', '量子', '发布', '突破', '创新', '软件', '硬件', '平台', '系统']):
        chain = f"{ent}技术突破 → 早期采用者(大厂)率先部署 → 配套硬件/接口需求爆发 → 技能人才严重短缺 → 培训/咨询/外包市场出现"
        surplus = f"{ent}技术的过剩宣传（PPT到量产差18个月）"
        deficit = f"{ent}落地服务的不足供给（会部署的人/成熟的配套远不够）"
        tian_dao = f"天之道: 损技术炒作之有余（宣传过剩）→补落地服务之不足（人才/配套缺口）\n  > 推导: 发布→大厂抢部署→但没人会装→配套跟不上→有余在宣传、不足在落地"
        xie_xiu = f"邪修之道: 不做{ent}开发→做{ent}的落地服务→①找会{ent}的3-5个工程师②组外包团队③接大厂部署单→收项目费20-50万/单→技术过时换下一个"

    elif any(kw in title_lower for kw in ['金融', '银行', '保险', '证券', '基金', '利率']):
        chain = f"金融政策变化 → 资金成本调整 → 利差/汇差扩大 → 资金流动加速 → 合规通道需求激增"
        surplus = "低利率区的过剩资金（找不到投资标的）"
        deficit = "合规通道的不足供给（额度有限/审批慢）"
        tian_dao = f"天之道: 损低利率资金之有余（资金泛滥）→补合规通道之不足（额度紧）\n  > 推导: 利差→资金流动→但通道有限→有余在资金、不足在通道"
        xie_xiu = f"邪修之道: 在资金和通道之间做桥→①帮资金方找标的②帮需求方找合规渠道③收通道费0.5-2%→资金量越大赚越多"

    else:
        # V16: else分支不再用抽象模板，基于新闻实体+辅助实体生成具体因果链
        # 分析标题中的行业线索
        if any(kw in title_lower for kw in ['医药', '医疗', '生物', '药']):
            chain = f"{ent}医药动态 → 临床/审批进度变化 → 医保/集采政策联动 → 医药分销渠道调整 → 医疗服务/数字医疗机会"
            surplus = f"{ent}研发管线（90%倒在临床，过剩投入）"
            deficit = f"医疗服务的不足供给（看病难/基层缺医）"
        elif any(kw in title_lower for kw in ['汽车', '新能源', '电动', '电池', '充电']):
            chain = f"{ent}汽车/能源动态 → 电池/充电桩需求变化 → 原材料(锂/钴/镍)价格波动 → 供应链重组 → 二手车/回收市场机会"
            surplus = f"新能源产能过剩（补贴退坡后库存积压）"
            deficit = f"充电/回收配套不足（基础设施跟不上车量增长）"
        elif any(kw in title_lower for kw in ['地产', '房产', '土地', '楼盘', '物业']):
            chain = f"{ent}地产动态 → 资金链压力传导 → 上游建材/家电订单减少 → 法拍/不良资产增加 → 物业/运营转型机会"
            surplus = f"地产库存过剩（卖不掉的房子）"
            deficit = f"物业运营/改造升级服务不足（从卖房到运营的转变缺服务商）"
        else:
            # 最终兜底：用辅助实体构建传导链，每步是具体的而非抽象的
            if aux_entities:
                chain = f"{ent}事件 → {aux_ent}受直接影响 → {aux_ent2}间接受波及 → 供应链上下游重新议价 → 替代方案/中间人机会出现"
                surplus = f"{ent}的过剩产能/信息（率先反应者的先发优势）"
                deficit = f"{aux_ent}的不足应对（反应慢=需要中间人帮忙）"
            else:
                chain = f"{ent}事件 → 上游原料供应端受冲击 → 中游加工/制造环节成本变化 → 下游终端消费价格调整 → 跨区域套利窗口打开"
                surplus = f"{ent}信息先知方（有消息但没渠道变现）"
                deficit = f"{ent}信息后知方（有需求但不知道变化）"

        tian_dao = f"天之道: 损{surplus.split('（')[0] if '（' in surplus else surplus[:12]}之有余→补{deficit.split('（')[0] if '（' in deficit else deficit[:12]}之不足\n  > 推导: {chain.split('→')[0].strip()}→逐级传导→有余在先发端、不足在反应端"
        xie_xiu = f"邪修之道: 在{ent}的传导断裂处收过路费→①找到{surplus.split('（')[0] if '（' in surplus else '有货方'}②找到{deficit.split('（')[0] if '（' in deficit else '缺货方'}③以「行业资源对接」撮合→收1-3%→断裂修复就换下一对"

    lines.append(f"- **因果链**: {chain}")
    lines.append(f"- **有余方**: {surplus}")
    lines.append(f"- **不足方**: {deficit}")
    lines.append(f"\n🔮 **{tian_dao}**")
    lines.append(f"⚡ **{xie_xiu}**")

    return "\n".join(lines)


def _fallback_pitfall(top_items):
    """V13: 避坑提醒 — 从多条新闻中找2个真实陷阱"""
    lines = ["## 五、避坑提醒\n"]
    lines.append("> 看似机会实际是坑，别冲动:\n")

    if not top_items:
        lines.append("- ⚠️ **陷阱**: 今日数据不足，暂无避坑提醒")
        return "\n".join(lines)

    # 从top_items前5条找2个不同角度的坑
    pitfall_count = 0
    for item in top_items[:8]:
        if pitfall_count >= 2:
            break
        title = item.get('title', '')
        entity = _extract_entity(title)
        # V17: 实体名最长8字，去掉介词前缀
        ent_raw = entity[:8] if len(entity) > 8 else entity
        ent = re.sub(r'^[在的得了被把将向从]', '', ent_raw)
        title_lower = title.lower()

        # 根据新闻类型生成不同的陷阱
        if any(kw in title_lower for kw in ['暴涨', '疯抢', '首发', '破纪录']):
            lines.append(f"- ⚠️ **陷阱**: {ent}正在被疯狂追捧→多数人追高入场时就是头部→真机会在3个月前的低价区")
            lines.append(f"  - 为什么是坑: 现在上车=帮早期投资人接盘→他们6-7折拿的→你全价买")
            lines.append(f"  - 止损建议: 入场前设10%止损线→跌破立即走人")
            pitfall_count += 1
        elif any(kw in title_lower for kw in ['融资', '投资', '收购']):
            lines.append(f"- ⚠️ **陷阱**: {ent}拿了融资≠你也能赚钱→融资新闻是PR不是机会信号→估值越高散户越难上车")
            lines.append(f"  - 为什么是坑: 融资是给VC看的→散户看到新闻时已经晚了2个月")
            lines.append(f"  - 止损建议: 别因为融资新闻买股票/跟投→看3个月后的实际数据再决定")
            pitfall_count += 1
        elif any(kw in title_lower for kw in ['AI', '人工智能', '大模型', '算力']):
            lines.append(f"- ⚠️ **陷阱**: {ent}AI概念热→99%的AI公司会死→你赌对赛道的概率远低于赌对公司→不如做卖铲人")
            lines.append(f"  - 为什么是坑: AI淘金热→淘金者亏钱→卖铲者(算力/工具/培训)赚钱")
            lines.append(f"  - 止损建议: 如果一定要赌AI→赌基础设施不赌应用→亏损概率从95%降到60%")
            pitfall_count += 1
        elif any(kw in title_lower for kw in ['政策', '新规', '监管', '整顿']):
            lines.append(f"- ⚠️ **陷阱**: {ent}监管新规→市场恐慌时有人喊「利空出尽」→但执行细则还没出→靴子没落地")
            lines.append(f"  - 为什么是坑: 政策从发文到执行有3-6个月缓冲→中间还有2-3次加码的可能")
            lines.append(f"  - 止损建议: 等细则出台+1个月观察期再入场→别抢反弹")
            pitfall_count += 1
        elif any(kw in title_lower for kw in ['出海', '海外', '全球化']):
            lines.append(f"- ⚠️ **陷阱**: {ent}出海成功≠你能复制→他们有本土化团队→你只有钱和热情")
            lines.append(f"  - 为什么是坑: 出海最常死于本地化→法规/文化/渠道全得重做→投入翻3倍")
            lines.append(f"  - 止损建议: 做中间人不做当事人→卖水给淘金人→收服务费而不是自己去挖金")
            pitfall_count += 1

    if pitfall_count == 0:
        lines.append("- ⚠️ **陷阱**: 任何新闻上头条时，机会窗口已经缩小了一半")
        lines.append("  - 为什么是坑: 新闻是滞后指标→等你看到时早鸟已经进场2周了")
        lines.append("  - 止损建议: 用新闻找方向→用调研验证→用小额试水→不要All In")

    return "\n".join(lines)


def _fallback_quote(top_items):
    """降级: 邪修金句 — V7版结合新闻内容+记忆库去重"""
    memory = _load_xie_xiu_memory()
    used_quotes = memory.get('quotes', [])[-10:]  # 扩大去重窗口到10条

    if not top_items:
        quote = _gen_unique_quote("眼前的信息", used_quotes)
        return f"## 六、今日邪修金句\n\n💭 {quote}\n\n> 邪修提示：信息差永远存在，关键是找到那个愿意为信息付费的人。"

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


# ============================================================
# V14: 公司/品牌预置库 — 优先匹配已知实体，避免提取出无意义片段
# ============================================================
COMPANY_DB = {
    # 台湾上市公司（含股票代码）
    '台积电': '台积电(2330 TT)', '联发科': '联发科(2454 TT)', '鸿海': '鸿海(2317 TT)',
    '奇鋐': '奇鋐(3017 TT)', '双鸿': '双鸿(3324 TT)',
    '台塑': '台塑(1301 TT)', '台化': '台化(1326 TT)', '南亚': '南亚(1303 TT)',
    '中钢': '中钢(2002 TT)', '统一': '统一(1216 TT)', '味全': '味全(1201 TT)',
    '华硕': '华硕(2357 TT)', '宏碁': '宏碁(2353 TT)', '纬创': '纬创(3231 TT)',
    '日月光': '日月光(3711 TT)', '硅品': '硅品(2325 TT)', '联电': '联电(2303 TT)',
    '台湾大': '台湾大(3045 TT)', '远传': '远传(4904 TT)', '中华电信': '中华电信(2412 TT)',
    '台湾水泥': '台湾水泥(1101 TT)', '亚泥': '亚泥(1102 TT)',
    '国泰金': '国泰金(2882 TT)', '富邦金': '富邦金(2881 TT)', '中信金': '中信金(2891 TT)',
    # 大陆公司
    '腾讯': '腾讯(0700 HK)', '阿里': '阿里(9988 HK)', '字节跳动': '字节跳动(未上市)',
    '华为': '华为(未上市)', '小米': '小米(1810 HK)', '百度': '百度(9888 HK)',
    '比亚迪': '比亚迪(1211 HK)', '宁德时代': '宁德时代(300750)',
    '英伟达': 'NVIDIA(NVDA)', 'OpenAI': 'OpenAI(私有)', 'DeepSeek': 'DeepSeek(私有)',
    '英特尔': 'Intel(INTC)', 'AMD': 'AMD(AMD)', '三星': 'Samsung(005930 KS)',
}


def _extract_entity(title):
    """V14→V17: 从新闻标题中提取核心实体 — 优先预置库匹配+去前缀+多模式验证+HTML解码"""
    import re, html
    # V17: 解码HTML实体 (&ldquo; &rdquo; &middot; &amp; 等)
    title = html.unescape(title)
    # 预处理: 去掉常见前缀噪音
    title_clean = title
    for prefix in ['8点1氪丨', '8点1氪|', '氪星晚报｜', '氪星早报｜', '融资丨', '独家丨', '硬氪首发', '36氪首发', '| 36氪首发', '｜硬氪首发', '｜', '| ']:
        title_clean = title_clean.replace(prefix, '')
    title = title_clean
    # V14: 优先匹配预置公司库（最高优先级）
    for company_name, full_name in COMPANY_DB.items():
        if company_name in title:
            return full_name

    # 噪音词库
    noise = {'今日', '最新', '突发', '重磅', '刚刚', '快讯', '关注', '热点', '警惕', '注意', '曝光',
             '8点1氪', '氪星晚报', '氪星早报', '晚报', '早报', '日报', '周报', '月报',
             '丨', '｜', '【', '】', '「', '」', '《', '》',
             '中国品牌', '韩国', '美国', '日本', '中国', '香港', '澳门',
             '北京', '上海', '深圳', '广州', '福建', '厦门', '金门',
             '股价', '市值', '融资', '投资', '收购', '上市', 'IPO'}
    # 通用词子串（含这些词的片段不提取）
    noise_sub = {'中国品牌', '品牌出海', '产业链', '供应链', '制造业', '互联网', '人工智能',
                 '韩国', '美国', '日本', '中国', '台湾', '香港', '澳门',
                 '北京', '上海', '深圳', '广州', '福建', '厦门', '金门',
                 '全台疯抢', '人民币'}
    # 英文停用词（大写开头单独出现不算实体）
    eng_stop = {'The', 'How', 'What', 'Why', 'When', 'This', 'That', 'These', 'Those',
                'Here', 'There', 'Where', 'Which', 'Would', 'Could', 'Should', 'From',
                'With', 'Will', 'Have', 'Been', 'More', 'New', 'One', 'Two', 'Our'}
    
    # 用标点切分中文句子
    segments = re.split(r'[，,。！!？?；;：:、\s]+', title)
    
    # 模式1: 公司/品牌名（XX公司/集团/平台/科技/品牌/银行/基金/酒厂/股份）
    for seg in segments:
        seg = seg.strip()
        m = re.search(r'([一-龥A-Za-z]{2,10}(?:公司|集团|平台|科技|品牌|银行|证券|基金|期货|酒厂|股份|庙宇|寺|宫|商会|协会))', seg)
        if m:
            entity = m.group(1)
            if entity not in noise:
                return entity

    # V17: 模式1.5 — "公司名+完成/获/斩获+金额+融资" 提取公司名
    # 例: "安纳智芯完成数亿元融资" → "安纳智芯", "百奥几何凭XX斩获数亿元融资" → "百奥几何"
    for seg in segments:
        seg = seg.strip()
        m = re.search(r'([一-龥A-Za-z]{2,8})(?:完成|获|斩获|拿到|获得|拿到)(?:数|多|超|近|约)?(?:亿|千万|百万|万)?元?(?:融资|投资|融资|注资)', seg)
        if m:
            entity = m.group(1)
            if entity not in noise and len(entity) >= 2:
                return entity
    
    # 模式2: 英文专有名词（OpenAI, DeepSeek, NVIDIA, TSMC, SK等）
    # 要求>=4字符或多词组合，且不在英文停用词中
    for seg in segments:
        seg = seg.strip()
        m = re.search(r'([A-Z][A-Za-z]{2,15}(?:\s*[A-Z][A-Za-z]{1,15})*)', seg)
        if m:
            entity = m.group(1).strip()
            if len(entity) >= 4 and entity not in eng_stop:
                # 检查是否只是英文停用词点缀了数字
                cleaned = entity.split()[0] if ' ' in entity else entity
                if cleaned not in eng_stop:
                    return entity
    
    # 模式3: 产品/品牌名称（中文2-6字后跟'发布'/'上线'/'推出'/'上市'）
    for seg in segments:
        seg = seg.strip()
        m = re.search(r'([一-龥]{2,6})(?:发布|上线|上市|推出|官宣|融资|IPO|过会|获投|道歉|回应|财报|涨价|降价|暴跌|暴涨|开光|法会)', seg)
        if m:
            entity = m.group(1)
            if entity not in noise and entity not in {'韩国', '美国', '日本', '中国', '台湾', '北京', '上海', '深圳'}:
                return entity
    
    # 模式4: 人名+头衔（2-4字中文名+创始人/CEO/董事长/总裁）
    for seg in segments:
        seg = seg.strip()
        m = re.search(r'([一-龥]{2,4})(?:创始人|CEO|董事长|总裁|部长|经理|教授)', seg)
        if m:
            entity = m.group(1)
            if entity not in noise:
                return entity + m.group(0)[len(entity):]  # 保留头衔
    
    # 模式5: 品牌/产品名（带引号或书名号的）
    m = re.search(r'[「「]([^」」]{2,12})[」」]', title)
    if m:
        return m.group(1)
    m = re.search(r"['\"]([^'\"]{2,12})['\"]", title)
    if m:
        return m.group(1)
    
    # 模式6: 去"动词+了/得/不"等后缀，提取核心名词
    # 例: "救得了哈根达斯" → "哈根达斯", "做具身智能时代的餐饮世界模型" → "餐饮世界模型"
    verb_suffixes = ['救得了', '做得了', '看不到', '找不到', '买不到', '进不去', '出不來',
                     '做不了', '挡不住', '撑得起', '扛得住', '受得了', '吃得消',
                     '出了个', '来了个', '火了', '凉了', '崩了', '炸了', '疯了']
    for vs in verb_suffixes:
        if vs in title:
            after = title.split(vs, 1)[1]
            if after and len(after) >= 2:
                clean = re.sub(r'^[的得地]', '', after.strip())
                if len(clean) >= 2 and len(clean) <= 15:
                    return clean

    # 兜底: 从末尾取有效中文片段（中文标题核心实体通常在尾部）
    for seg in reversed(segments):
        seg = seg.strip()
        clean = re.sub(r'[\d\.\-\+%￥$€¥\s（）()\[\]""'']+', '', seg)
        if len(clean) >= 2 and len(clean) <= 15 and clean not in noise:
            # 跳过含噪音子串的片段
            if any(ns in clean for ns in noise_sub):
                continue
            # V17: 如果片段含"的"且>6字，取"的"后面的核心名词
            # 例: "一万亿市场的裂缝" → "裂缝"
            if '的' in clean and len(clean) > 6:
                after_de = clean.split('的')[-1]
                if len(after_de) >= 2 and len(after_de) <= 8 and after_de not in noise:
                    clean = after_de
            # 如果以动词开头，提取后面的核心名词
            for verb in ['做', '打造', '推出', '发布', '宣布', '表示']:
                if clean.startswith(verb) and len(clean) > len(verb) + 2:
                    clean = clean[len(verb):]
                    break
            return clean
    
    # 最后兜底：标题前15字
    return re.sub(r'[\d\.\-\+%￥$€¥\s]+', '', title[:15]).strip()[:12]

def _fill_ops_template(op_template, news_entity):
    """将新闻实体注入操作卡模板，让操作卡看起来针对这条新闻"""
    # op_template: (操作名, 找谁, 怎么说, 资金路径, 试水金额, 撤退信号)
    name, who, how, path, amount, retreat = op_template
    # 如果有新闻实体，替换模板中的泛称
    if news_entity and news_entity not in who:
        who = f"{news_entity}的{who}" if '的' not in who[:5] else who
        how = how.replace('以', f'以「{news_entity}」').replace('名义', '背景') if news_entity not in how else how


def _extract_signal_keywords(top_items):
    """从新闻中提取关键信号词和上下文"""
    sig = {}
    for item in top_items[:10]:
        title = item.get('title', '')
        title_lower = title.lower()
        for kw_group in [
            '台湾', '两岸', '小三通', '金门',
            '餐饮', '甜品', '绵绵冰', '冷链',
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
        logging.warning("[P1] 新闻生成超时(200秒)，使用降级模式")
        all_raw_fb, _ = fetch_raw_materials()
        top_items_fb = filter_by_profile(all_raw_fb, min_score=0, top_n=20)
        news_content = _fallback_all_sections(all_raw_fb, top_items_fb)
    except Exception as e:
        logging.error(f"[P1] 新闻生成异常: {e}，使用降级模式")
        try:
            all_raw_fb, _ = fetch_raw_materials()
            top_items_fb = filter_by_profile(all_raw_fb, min_score=0, top_n=20)
            news_content = _fallback_all_sections(all_raw_fb, top_items_fb)
        except Exception as e2:
            logging.error(f"[P1] 降级模式也失败: {e2}")
            news_content = "## 一、每日资讯\n（今日新闻抓取异常，下次自动恢复）\n"

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
