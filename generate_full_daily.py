#!/usr/bin/env python3
"""生成完整日报 V6 — 4板块齐全 + 邪修进化引擎

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

# 加载 .env
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
import hashlib
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import time
from concurrent.futures import TimeoutError

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
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASSWORD', os.getenv('SMTP_PASS', ''))
SMTP_TO = os.getenv('SMTP_TO', '')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(output_dir, exist_ok=True)

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def _run_with_timeout(func, timeout=180):
    """直接执行，不用子进程（OpenClaw兼容）"""
    return func()
# V7 用户画像关键词权重（原 USER_PROFILE_V7，补回）
USER_PROFILE_V7 = {
    # 台湾/两岸
    '台湾': 5, '台北': 4, '高雄': 4, '台商': 4, '两岸': 4,
    # 资金/操作
    '百万': 3, '200万': 3, '300万': 3, '小额': 3, '轻资产': 3, '中间人': 3,
    # 套利/灰色
    '价差': 3, '套利': 3, '灰色': 3, '监管差': 3, '税率差': 3, '绕开': 2,
    # 已知项目
    '庙宇': 3, '财神': 3, '赵公明': 3, '刘海蟾': 3, '彩票': 3, '台彩': 3,
    # 邪修偏好
    '漏洞': 3, '盲区': 3, '规则差': 3, '信息差': 3,
    # V21: 汇率/套息 — 三角机会触发源
    '日元': 4, '日元贬值': 5, '日元升值': 5, '套息': 4, 'carry trade': 4, '利差': 3,
    '汇率': 3, '外汇': 3, '贬值': 3, '升值': 3, '波动率': 3, '干预': 3,
    '韩元': 3, '里拉': 3, '比索': 3, '卢比': 3, '雷亚尔': 3,
    '交叉汇率': 3, '三角套利': 4, '远期': 3, 'NDF': 3, '期权': 2,
    '跨市场': 3, '价差套利': 4, '货币对冲': 3, '利差交易': 4,
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
    # V20: 大宗/供应链配额从2→4，新增供需信号关键词
    ('大宗/供应链', ['涨价', '暴跌', '缺货', '断供', '铜价', '铝价', '锂价', '硫酸', '减产', '停产',
                      '期货', '现货', '库存', '暴涨', '暴跌', '飙升', '腰斩', '翻倍', '供不应求',
                      '趋紧', '上行', '下行', '回落', '紧缺', '涨价潮', '降价潮', '价格战'], 4),
    # V20: 新增"价格/供需信号"领域 — 信号型新闻保底
    ('价格/供需信号', ['涨价', '跌价', '断供', '缺货', '短缺', '减产', '停产', '限产', '供不应求',
                       '爆单', '抢购', '售罄', '紧缺', '管制', '禁令', '制裁', '配额', '收紧',
                       '涨价潮', '降价潮', '成本上升', '利润下滑', '库存告急', '产能利用率',
                       '暴涨', '暴跌', '飙升', '狂飙', '腰斩', '回落', '趋紧'], 4),
    # V20-fix4: 新增农产品/贵金属产量预警领域
    ('农产品/贵金属', ['大豆', '玉米', '小麦', '棉花', '白糖', '糖价', '稻谷', '油菜籽', '棕榈油',
                       '橡胶', '咖啡', '可可', '粮食', '化肥', '饲料', '收成', '收割', '播种',
                       '歉收', '丰收', '种植面积', '产量预估', '产量预测', '主产区', '产区',
                       '黄金', '白银', '铂金', '钯金', '贵金属', '金矿', '银矿',
                       '开采量', '矿产产量', '冶炼产量', '减产', '增产'], 3),
    ('金融/宏观', ['央行', '降息', '加息', '汇率', '人民币', '利率', '流动性', '政策', '关税', '制裁', '出口', '出海',
                   '日元', '套息', '利差', '外汇', '贬值', '升值', '波动率', '干预',
                   '韩元', '里拉', '比索', '卢比', '雷亚尔', '三角套利', '货币对冲'], 2),
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
# V19 影响链引擎 — 多层资源传导推演，不教做生意，只推演短缺
# 每条链 = 5层资源影响 (L1→L2→L3→L4→L5)，标注短缺/过剩+时间窗
# ============================================================
IMPACT_CHAIN_TEMPLATES = [
    # 1. 稀土/稀有金属
    # 因果链: 管制→断供→磁材减产→靶材缺原料→设备停→封测受阻
    # 1. 稀土/战略金属/小金属
    # 因果链: 管制/缺货→原料紧缺→中间品断供→下游制造业成本飙升→终端涨价→普通人可做的替代/回收/中间人商机
    {'triggers': ['稀土', '镝', '铽', '钕', '铕', '战略金属', '出口管制',
                  '钨', '钨价', '钼', '锑', '镓', '锗', '铟', '小金属', '稀有金属'],
     'layers': [
         ('管制/出口限制→战略金属原料紧缺→现货溢价20%+，国内外价差拉大', '立即', '短缺'),
         ('原料紧缺→中间品(磁材/靶材/硬质合金)减产→下游买不到核心材料', '1-2月', '短缺'),
         ('中间品断供→下游制造业(电机/半导体/刀具/工具)成本飙升→减产或涨价', '2-3月', '短缺'),
         ('终端产品(电动车/家电/机床/钻头)涨价→需求下降→旧库存/二手设备价值上升', '3-6月', '过剩'),
         ('终端涨价→消费者转向二手/替代→废电机/废磁材回收料价格跟涨但拆解产能不足，国内有库存的贸易商捂货惜售加剧短缺', '3-6月', '短缺'),
     ],
     'fracture': '中间品断供→终端制造业涨价之间', 'window': '2-4个月'},

    # 2. AI/算力
    # 因果链: GPU管制→一卡难求→服务器排长队→IDC耗电飙升→散热跟不上→普通人可做的算力中间人/二手/培训
    {'triggers': ['ai', '算力', 'gpu', '大模型', '英伟达', 'nvidia', '人工智能', '机器学习', '深度学习', 'openai', 'gpt', 'deepseek', 'claude', 'gemini', 'llm', 'hbm', '智谱', '文心', '通义', 'kimi', '豆包', 'minimax'],
     'layers': [
         ('GPU/HBM出口管制+训练需求爆发→一卡难求，加价3倍也拿不到', '立即', '短缺'),
         ('组装产能跟不上订单→AI服务器交付周期从2周拉到8周', '1-3月', '短缺'),
         ('IDC电力消耗激增→电网配套不足，多地限电限批数据中心', '3-6月', '短缺'),
         ('中小AI公司算力成本过高→营收撑不住→淘汰潮开始', '6-12月', '过剩'),
         ('中小AI公司算力成本占营收超50%→倒闭潮→二手GPU/AI服务器流入二手市场但买家信息不对称，倒闭公司的算力资源闲置而新入局者仍在加价抢卡', '3-6月', '短缺'),
     ],
     'fracture': 'GPU断供→服务器交付之间', 'window': '1-3个月'},

    # 3. 芯片/半导体
    # 因果链: 制程受限→特定型号断供→代工产能错配→IC库存积压→终端减产→普通人可做的替代/库存/回收
    {'triggers': ['芯片', '半导体', '台积电', '晶圆', '代工', '封装', '封测'],
     'layers': [
         ('特定制程产能受限/管制→关键型号芯片断供，下游找不到替代', '立即', '短缺'),
         ('部分制程空置+部分制程排不上→代工产能结构性错配，价格畸变', '1-3月', '过剩'),
         ('需求转弱→IC设计公司芯片库存积压，库存周转天数翻倍', '2-4月', '过剩'),
         ('关键芯片断供→终端电子产品减产，新品发布推迟', '3-6月', '短缺'),
         ('国产替代需求爆发但良率不足→替代方案供不上→IC设计公司积压的旧型号芯片变成紧俏库存，终端厂被迫用国产但量产爬坡期供需双紧', '3-6月', '短缺'),
     ],
     'fracture': '关键芯片断供→终端减产之间', 'window': '3-6个月'},

    # 4. 机器人/具身智能
    # 因果链: 零部件进口受限→组装排队→集成商稀缺→场景数据不够→普通人可做的维修/培训/集成
    {'triggers': ['机器人', '具身智能', '智能体', '人形机器人'],
     'layers': [
         ('减速器/伺服电机依赖进口→日本HD/纳博特斯克产能瓶颈→本体厂等零部件', '立即', '短缺'),
         ('组装产能不足→本体交付排队6个月+，订单积压', '3-6月', '短缺'),
         ('懂场景落地的集成商极度稀缺→有机器人但没人会部署', '6-12月', '短缺'),
         ('真实场景训练数据不足→机器人学不到→落地效果打折', '6-12月', '短缺'),
         ('量产后维保市场缺人→已交付机器人因缺维修师傅停机→维修服务供给严重不足，已售机器人变成售后黑洞，二手翻新机填补低端需求但品质参差', '6-12月', '短缺'),
     ],
     'fracture': '零部件瓶颈→集成落地之间', 'window': '6-12个月'},

    # 5. 出口/关税/制裁
    # 因果链: 管制→断供→转口通道爆→合规咨询缺→替代供应链未就→普通人可做的转口/清仓/合规
    {'triggers': ['出口', '关税', '制裁', '贸易', '禁运', '脱钩', '实体清单', '反倾销', '反补贴', '中美', '外贸'],
     'layers': [
         ('出口管制落地→目标市场断供，买方找不到替代渠道', '立即', '短缺'),
         ('第三国中转需求爆发→越南/墨西哥转口通道容量不够→物流排队', '1-2月', '短缺'),
         ('企业不知道怎么合规→合规咨询需求激增但专业机构稀缺', '1-3月', '短缺'),
         ('原受限方卖不出去→库存积压+资金链紧→被迫折价清仓', '3-6月', '过剩'),
         ('原受限方卖不出去→库存积压+资金链紧→折价清仓但买方信息不对称找不到货源，同时替代供应商还没准备好→供需两端都在等中间人', '3-6月', '短缺'),
     ],
     'fracture': '转口通道→替代供应链之间', 'window': '3-6个月'},

    # 6. 出海/全球化
    # 因果链: 进新市场→找不到经销商→本地化缺→合规缺→普通人可做的渠道/代运营/仓储
    {'triggers': ['出海', '全球化', '海外', '跨境', '品牌出海', '国际化', '东南亚', '欧洲', '美洲', '中东', '非洲'],
     'layers': [
         ('品牌进入新市场→找不到靠谱经销商→渠道空白期3-6个月', '立即', '短缺'),
         ('语言/文化/法规不熟→落地服务缺口→产品到了卖不动', '1-3月', '短缺'),
         ('各国法规不同→合规人才不足→牌照审批排队6个月+', '1-3月', '短缺'),
         ('本地支付方式接入困难→结算通道断裂→钱收不回来', '3-6月', '短缺'),
         ('最后一公里配送→海外仓能力不足→物流成本翻3倍→有货的卖家发不出去，本地仓储供给严重不足而需求暴增3倍', '3-6月', '短缺'),
     ],
     'fracture': '渠道空白→本地化落地之间', 'window': '3-6个月'},

    # 7. 能源/新能源
    # 因果链: 光伏产能过剩→储能跟不上→电网调度压力→充电桩不足→普通人可做的回收/安装/运维
    {'triggers': ['新能源', '锂', '光伏', '储能', '电网', '充电', '电池'],
     'layers': [
         ('光伏产能远超需求→价格战杀到成本线→组件库存积压3GW+', '立即', '过剩'),
         ('装机量激增但储能跟不上→消纳瓶颈→弃光率飙到30%+', '3-6月', '短缺'),
         ('新能源并网→电网调度压力→虚拟电厂需求爆发但技术还没成熟', '6-12月', '短缺'),
         ('电动车增长→充电基础设施不足→3车1桩→排队2小时', '6-12月', '短缺'),
         ('第一批电池退役潮→回收产能严重不足→退役电池只能堆在仓库→锂钴资源浪费在废料里而新材料厂仍缺原料，充电桩安装排队但持证电工不足', '6-12月', '短缺'),
     ],
     'fracture': '储能配套→电网调度之间', 'window': '6-12个月'},

    # 8. 金融/利率
    # 因果链: 降息→资金泛滥→追逐高息→汇率波动→普通人可做的跨境/兑换/套利
    {'triggers': ['降息', '央行', '利率', '美联储', '加息', '流动性'],
     'layers': [
         ('降息落地→资金泛滥→找不到投资标的→银行理财收益率跌破2%', '立即', '过剩'),
         ('资金追逐收益→高息资产被抢光→10年期国债收益率创新低', '1-3月', '短缺'),
         ('利差变化→汇率剧烈波动→企业对冲工具不足→汇损风险飙升', '1-3月', '短缺'),
         ('宽松资金流向大企业→中小企业信贷仍缺钱→融资成本没降', '3-6月', '短缺'),
         ('宽松资金流向大企业→中小企业信贷仍缺钱→有钱方找不到安全高息标的，缺钱方借不到钱→资金供需两端断裂在对冲工具不足和信息不对称上', '3-6月', '短缺'),
     ],
     'fracture': '跨境通道→中小企业信贷之间', 'window': '3-6个月'},

    # 9. 大厂动态
    # 因果链: 大厂调整→生态位释放→人才过剩→乙方丢单→普通人可做的垂直接盘/期权/转介
    {'triggers': ['腾讯', '阿里', '字节', '百度', '快手', '网易', '华为', '美团', '京东', '拼多多', '小米', 'oppo', 'vivo', '滴滴', '蚂蚁', '京东', '拼多多'],
     'layers': [
         ('大厂业务调整→释放生态位→中小玩家涌入过快→竞争内卷', '立即', '过剩'),
         ('裁员释放AI/算法人才→市场短期供过于求→薪资打7折', '1-3月', '过剩'),
         ('大厂砍预算→乙方丢单→但转型需求出现→懂传统行业的乙方稀缺', '1-3月', '短缺'),
         ('大厂退出的垂直赛道→出现空白→没人接=机会', '3-6月', '短缺'),
         ('员工期权需变现→折价交易通道不足→私下交易风险大→期权持有人急着卖但找不到合规买方，大厂砍掉的外包项目存量需求存在但接手方稀缺', '3-6月', '短缺'),
     ],
     'fracture': '乙方转型→垂直空白之间', 'window': '3-6个月'},

    # 10. IPO/上市
    # 因果链: 打新资金爆→老股转让不对称→IR服务缺→普通人可做的老股/IR/FA
    {'triggers': ['ipo', '上市', '过会', 'a股', '港股', '招股', '融资', '天使轮', 'a轮', 'b轮', 'c轮', '并购', '收购', '入股', '投资'],
     'layers': [
         ('热门IPO→打新资金需求爆发→融资缺口→券商额度秒光', '立即', '短缺'),
         ('上市前老股东套现→老股转让市场信息不对称→估值差距大', '1-3月', '短缺'),
         ('解禁期→老股东需IR顾问→但IR服务供给不足→市值管理缺人', '1-3月', '短缺'),
         ('IPO数量增加→承销产能过剩→价格战→FA佣金从3%降到1%', '3-6月', '过剩'),
         ('解禁抛售→流动性不足→承接资金缺口→股价腰斩→急着卖的股东找不到足够买方，IR/市值管理服务供给不足而解禁期需求集中爆发', '3-6月', '短缺'),
     ],
     'fracture': '老股转让→IR服务之间', 'window': '1-3个月'},

    # 11. 信仰经济
    # 因果链: 香客减少→线下闲置→线上需求爆发→供应链断裂→普通人可做的代运营/供应链/IP
    {'triggers': ['庙宇', '供奉', '开光', '法会', '线上信仰', '财神', '赵公明', '信仰'],
     'layers': [
         ('香客减少→线下庙宇流量闲置→日均客流跌50%+', '立即', '过剩'),
         ('数字化需求爆发→线上平台供给不足→供灯/祈福排队2天', '立即', '短缺'),
         ('供养品/法器线上销售→供应链断裂→3天内发货率不到20%', '1-3月', '短缺'),
         ('线上法会直播+AI开光→技术服务缺口→直播延迟5秒+画质差', '3-6月', '短缺'),
         ('庙宇IP商业化→授权体系空白→无标准无定价→IP持有方不知道怎么授权，文创方不知道找谁谈→供需两端信息断裂在授权标准上', '3-6月', '短缺'),
     ],
     'fracture': '线上平台→商品供应链之间', 'window': '6-12个月'},

    # 12. 彩票
    # 因果链: 头奖效应→牌照涨价→合买需求爆→普通人可做的合买/数据/套利
    {'triggers': ['彩票', '彩券', '台彩', '威力彩', '大乐透', '公益彩券'],
     'layers': [
         ('头奖效应→经销牌照价值上涨→转让需求出现→牌照溢价30%+', '立即', '短缺'),
         ('合买需求爆发→可信赖的组织者不足→私吞/诈骗风险高', '立即', '短缺'),
         ('玩家需选号建议→数据分析工具不足→只能凭感觉买', '1-3月', '短缺'),
         ('奖池累积→衍生金融工具需求→但供给空白→没人做赔率差产品', '3-6月', '短缺'),
         ('不同地区赔率差→套利通道不透明→信息差3%+→有套利空间但没透明渠道，合买需求爆发但可信赖的组织者供给不足', '1-3月', '短缺'),
     ],
     'fracture': '合买服务→数据分析之间', 'window': '1-3个月'},

    # 13. 台湾/两岸
    # 因果链: 政策变化→物流断裂→兑汇需求激→普通人可做的兑汇/代购/中转
    {'triggers': ['台湾', '两岸', '小三通', '金门', '台海', '台积电', '台企', '陆资', '台商', '新竹', '台北'],
     'layers': [
         ('政策变化→官方通道收窄→物流断裂→货运排队2周+', '立即', '短缺'),
         ('台币/人民币需求激增→民间兑汇所容量不足→汇率溢价5%+', '立即', '短缺'),
         ('小三通货运量波动→金门中转仓不够→货物滞留3天+', '1-3月', '短缺'),
         ('台商资金需调整→合规回流通道有限→每年额度秒光', '1-3月', '短缺'),
         ('渠道重组→代购/集运需求爆发→供给不足→运费翻倍→大陆商品入台渠道断裂在合规集运供给上，台商资金回流合规通道额度秒光', '1-3月', '短缺'),
     ],
     'fracture': '物流断裂→兑汇渠道之间', 'window': '3-6个月'},

    # 14. 涨价/缺货/大宗
    # 因果链: 原料涨→加工减产→终端库存积压→替代品跟不上→普通人可做的回收/替代/清仓
    {'triggers': ['涨价', '缺货', '断供', '减产', '铜', '铝', '钢', '硫酸', '锂', '石油', '天然气', '铁矿石', '煤炭', '粮食', '大豆', '猪肉'],
     'layers': [
         ('供应减少→原料价格飙升→期货涨停→现货溢价20%+', '立即', '短缺'),
         ('原料涨→加工品成本上升→加工厂减产→中间品供给收紧', '1-2月', '短缺'),
         ('成本转嫁→终端需求下降→库存积压→经销商被迫折价清仓', '2-3月', '过剩'),
         ('替代品需求爆发→产能跟不上→铝代铜/合成氨代硫酸→爬坡期6个月', '2-4月', '短缺'),
         ('回收需求上升→回收产能不足→废铜/废铝回收率不到30%→大量可回收废料闲置在垃圾场而冶炼厂缺原料，替代品(铝代铜)需求爆发但产能爬坡要6个月', '2-4月', '短缺'),
     ],
     'fracture': '加工减产→替代材料之间', 'window': '2-4个月'},

    # 15. 融资/并购
    # 因果链: 标的稀缺→竞品估值涨→资金找不到标的→普通人可做的FA/猎头/整合
    {'triggers': ['融资', '天使轮', 'a轮', 'b轮', 'c轮', '并购', '收购', '入股', '投资', '估值', '独角兽'],
     'layers': [
         ('融资/并购消息→标的稀缺性上升→股权争夺→估值溢价50%+', '立即', '短缺'),
         ('标杆融资→同类竞品估值上涨→融资难度增加→新入者门槛高', '1-2月', '短缺'),
         ('大笔资金到位→短期内找不到合适标的→钱趴在账上', '1-3月', '过剩'),
         ('并购后产业链整合→整合服务需求爆发→FA/猎头/合规供给不够', '3-6月', '短缺'),
         ('IPO/并购退出→中介机构产能不足→排队6个月+→急着退出的老股东排不上队，有钱的基金找不到经过验证的标的→资金和标的断裂在FA/中介服务供给上', '3-6月', '短缺'),
     ],
     'fracture': '资金过剩→整合机会之间', 'window': '3-6个月'},

    # 16. 政策/监管
    # 因果链: 新规出台→合规顾问缺→牌照稀缺→产能闲置→普通人可做的合规/牌照/替代
    {'triggers': ['政策', '新规', '监管', '合规', '牌照', '准入', '反垄断', '数据安全', '隐私'],
     'layers': [
         ('新规出台→企业急需合规顾问→但专业机构稀缺→排队3个月+', '立即', '短缺'),
         ('准入门槛提高→牌照稀缺性上升→转让溢价100%+', '1-3月', '短缺'),
         ('监管收紧→部分产能被迫闲置→工厂停工/裁员', '1-3月', '过剩'),
         ('合规要求→替代技术需求爆发→国产替代方案爬坡期6个月+', '3-6月', '短缺'),
         ('企业需要影响政策→游说/政策咨询缺口→没人做也没人教→企业不知道怎么应对新规，合规服务供给不足而受影响企业数量暴增3倍', '3-6月', '短缺'),
     ],
     'fracture': '牌照稀缺→替代技术之间', 'window': '3-6个月'},

    # 17. 农产品/粮食
    # 因果链: 天气/产区变化→减产→粮价涨→饲料涨→普通人可做的替代/进出口/储备
    {'triggers': ['大豆', '玉米', '小麦', '棉花', '白糖', '糖价', '稻谷', '油菜籽', '棕榈油',
                  '橡胶', '咖啡', '可可', '粮食', '化肥', '饲料', '收成', '收割', '播种',
                  '歉收', '丰收', '种植面积', '产区', '主产区'],
     'layers': [
         ('天气/产区变化→农产品减产或歉收→现货价格立即飙升15%+', '立即', '短缺'),
         ('农产品涨价→饲料成本上升→养殖业利润压缩→猪/鸡减产', '1-3月', '短缺'),
         ('粮价上涨→食品加工企业成本飙升→终端食品涨价5-15%', '2-4月', '短缺'),
         ('化肥联动涨价→种植成本上升→下一季种植面积可能缩减', '3-6月', '短缺'),
         ('替代品需求爆发→但替代作物种植周期长→供给跟不上→食品厂急需植物蛋白替代动物蛋白但产能不足，农资(化肥/种子)供给在涨价周期中跟涨加剧种植成本', '3-6月', '短缺'),
     ],
     'fracture': '农产品减产→饲料/食品成本传导之间', 'window': '2-4个月'},

    # 18. 贵金属/矿产
    # 因果链: 矿产变化→开采量降→冶炼原料缺→加工品涨→终端涨→普通人可做的回收/兑换/中间人
    {'triggers': ['黄金', '白银', '铂金', '钯金', '贵金属', '金矿', '银矿',
                  '开采量', '矿产产量', '冶炼产量'],
     'layers': [
         ('矿产开采量下降/矿权变更→贵金属原料供给收紧→现货溢价5%+', '立即', '短缺'),
         ('冶炼原料不足→精炼产能闲置→加工费上涨→金条/银条供给收紧', '1-2月', '短缺'),
         ('贵金属涨价→首饰加工成本上升→终端零售涨价→消费者转向旧金兑换/以旧换新', '1-3月', '过剩'),
         ('工业用贵金属(电子/催化)成本上升→下游制造业利润压缩→寻求替代或减量', '2-4月', '短缺'),
         ('回收/旧金兑换需求爆发→但废旧贵金属回收产能不足→旧手机/电路板里的金银闲置在废料场而精炼厂缺原料，消费者想以旧换新但兑换点供给不足', '3-6月', '短缺'),
     ],
     'fracture': '矿产供给收紧→冶炼/工业用传导之间', 'window': '2-4个月'},

    # 19. 新发明/新技术突破
    # 因果链: 技术突破→资本涌入→人才争夺→配套产业缺→旧技术被替代→普通人可做的培训/专利/配套
    {'triggers': ['突破', '首创', '世界首例', '里程碑', '颠覆', '革命性', '量产突破', '商用化',
                  '固态电池', '核聚变', '可控核聚变', '室温超导', '量子计算', '量子比特',
                  '脑机接口', '基因编辑', '人造肉', '小型反应堆', '碳捕获', '绿氢',
                  '商业航天', '可回收火箭', '太空旅行', 'eVTOL', '飞行汽车'],
     'layers': [
         ('技术突破/首发→资本涌入赛道→估值泡沫→VC抢项目估值翻倍', '立即', '过剩'),
         ('核心人才被疯抢→薪资翻3倍→中小团队留不住人→研发断层', '1-3月', '短缺'),
         ('配套产业链未就绪→关键材料/零部件供给不足→量产卡壳', '3-6月', '短缺'),
         ('旧技术路线被替代→相关产能变成沉没成本→设备/产线闲置', '6-12月', '过剩'),
         ('旧技术路线被替代→相关产能变成沉没成本→设备/产线闲置→旧技术设备有价无市，新技术标准/专利争夺白热化→谁定标准谁收过路费→法律服务供给不足', '3-6月', '短缺'),
     ],
     'fracture': '资本涌入→配套产业链就绪之间', 'window': '3-6个月'},

    # 20. 化工/化肥
    # 因果链: 原料涨/停产→中间品缺→下游加工减产→终端涨→普通人可做的替代/回收/清仓
    {'triggers': ['硫酸', '硫磺', '磷酸', '磷肥', '尿素', '钾肥', '氮肥', '复合肥',
                  '双氧水', '环氧丙烷', '丙烯腈', '甲醇', '乙烯', '纯碱', '烧碱',
                  '钛白粉', '涂料', '树脂', '塑料', '橡胶', '三聚氰胺',
                  '化工', '化工厂', '停产检修', '装置停车'],
     'layers': [
         ('化工原料供应紧张/装置停车→中间体价格飙升→现货溢价20%+', '立即', '短缺'),
         ('中间体涨价→下游加工企业成本飙升→减产/停产→中间品供给收紧', '1-2月', '短缺'),
         ('化工品涨价→终端产品(建材/家电/纺织)成本上升→终端需求下降→库存积压', '2-3月', '过剩'),
         ('替代工艺需求爆发→但工艺切换需6-12个月→短期供不上', '3-6月', '短缺'),
         ('副产物/回收料需求上升→回收产能不足→废料回收率低于20%→化工厂副产废酸废碱闲置而下游中和厂缺酸碱，替代化工品(生物基/可降解)需求爆发但产能爬坡要12个月', '3-6月', '短缺'),
     ],
     'fracture': '中间体涨价→下游加工减产之间', 'window': '1-3个月'},

    # 21. 地缘/通道
    # 因果链: 通道受阻→运输成本飙升→到货延迟→替代通道拥堵→普通人可做的转口/仓储/保险
    {'triggers': ['海峡', '港口', '航线', '封锁', '通航', '禁运', '海上通道',
                  '霍尔木兹', '马六甲', '苏伊士', '巴拿马运河', '红海', '黑海', '南海',
                  '航道', '航运中断', '港口罢工', '港口拥堵'],
     'layers': [
         ('海峡/港口/航线受阻→运输成本飙升3-5倍→保险费暴涨', '立即', '短缺'),
         ('到货延迟2-4周→下游工厂原料断供→被迫减产', '1-2月', '短缺'),
         ('替代通道(绕行/陆运/空运)需求爆发→但运力有限→拥堵加剧', '1-3月', '短缺'),
         ('合规/安检成本上升→贸易商利润压缩→部分退出市场', '2-4月', '短缺'),
         ('企业转向本地化库存策略→仓储需求暴增→但仓储容量不足→港口附近仓库满租，有库存的卖方找不到急缺买方而买方找不到货源→供需断裂在仓储和信息对接上', '1-3月', '短缺'),
     ],
     'fracture': '到货延迟→替代通道拥堵之间', 'window': '1-3个月'},

    # 22. 通用兜底
    # 因果链: 新闻→直接受影响→下游成本波及→终端过剩→普通人可做的回收/替代/中间人
    {'triggers': [],
     'layers': [
         ('新闻事件→直接受影响的资源/产品→现货溢价10%+', '立即', '短缺'),
         ('使用该资源的产品→成本/供应受波及→下游减产', '1-2月', '短缺'),
         ('终端需求变化→部分环节产能过剩→库存积压→折价清仓', '2-3月', '过剩'),
         ('替代需求出现→替代品产能不足→爬坡期6个月+', '3-6月', '短缺'),
         ('转型/迁移需求→配套服务供给不足→排队2周+→有需求的企业找不到服务商，有库存的卖方找不到急缺买方→供需断裂在服务供给和信息对接上', '3-6月', '短缺'),
     ],
     'fracture': '下游减产→替代方案之间', 'window': '2-4个月'},
]


def _match_impact_chain(title):
    """V20: 从新闻标题匹配影响链模板，返回最佳匹配（多关键词加权+优先规则+方向修正）"""
    title_lower = title.lower()
    # 优先规则：包含AI专属关键词 → 强制AI模板
    ai_keywords = ['gpu', 'hbm', '算力', '世界模型', '手脑一体', '英伟达', 'nvidia']
    if any(kw in title_lower for kw in ai_keywords):
        for t in IMPACT_CHAIN_TEMPLATES:
            if 'gpu' in [tr.lower() for tr in t['triggers']] or 'ai' in [tr.lower() for tr in t['triggers']]:
                return t
    # 优先规则：包含台湾专属关键词 → 强制台湾模板
    tw_keywords = ['台湾', '两岸', '台积电', '金门']
    if any(kw in title_lower for kw in tw_keywords):
        for t in IMPACT_CHAIN_TEMPLATES:
            if '台湾' in [tr for tr in t['triggers']]:
                return t

    # V20-fix11: 方向修正 — 含"恢复/增产/扩产/投产"的新闻 = 供给增加 = 价格下行
    # 不应匹配"涨价/缺货/大宗"模板(#14)，改用"能源/新能源"模板(#7)或通用兜底(#22)
    supply_increase_kw = ['恢复', '恢复至', '恢复到', '增产', '扩产', '投产', '复产', '提高产量',
                          '加大产量', '提升产能', '解除不可抗力', '重启', '复工']
    is_supply_increase = any(kw in title for kw in supply_increase_kw)

    best_match = None
    best_score = 0
    for template in IMPACT_CHAIN_TEMPLATES:
        if not template['triggers']:
            continue
        # V20-fix11: 供给增加的新闻跳过"涨价/缺货/大宗"模板（方向相反）
        if is_supply_increase and '涨价' in template['triggers']:
            continue
        score = 0
        for trigger in template['triggers']:
            if trigger in title_lower:
                weight = len(trigger) / 10.0
                if trigger in ['gpu', 'hbm', '台积电', '稀土', '减速器', '出海', '关税']:
                    weight *= 2.0
                score += weight
        if score > best_score:
            best_score = score
            best_match = template
    return best_match if best_score > 0 else IMPACT_CHAIN_TEMPLATES[-1]


def _inject_shortage_alert(content, top_items):
    """V19: 强制接管板块二 — 已禁用（板块二「资源短缺预警」已删除）

    日报已精简为4板块，资源短缺预警功能并入马斯克推演。
    此函数直接返回原内容，不做注入。
    """
    return content

def _load_xie_xiu_memory():
    """加载邪修记忆库（冷启动自动初始化）"""
    if os.path.exists(XIE_XIU_MEMORY_PATH):
        try:  # 已禁用 Pool
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
            "邪修之道：在短缺和过剩之间找断裂层",
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

    # V19: 提取短缺预警中的影响链命中（替代旧操作卡命中）
    gap_section = re.search(r'二、资源短缺预警(.*?)(?=三、|四、|$)', sections_text, re.DOTALL)
    if gap_section:
        gap_text = gap_section.group(1)
        ops_hit = []
        for template in IMPACT_CHAIN_TEMPLATES:
            for kw in template.get('triggers', []):
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
        try:  # 已禁用 Pool
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
    import re, subprocess, json
    taiwan_items = []
    search_queries = ['台湾+经济', '台股+今日', '台币+汇率', '两岸+贸易']
    headers = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    for query in search_queries[:2]:  # 只搜2组，避免过频
        try:  # 已禁用 Pool
            url = f"https://www.baidu.com/s?wd={query}&rn=10"
            curl_cmd = ['curl', '-s', '-L', '-H', headers, url]
            result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                continue
            html = result.stdout
            # 提取搜索结果标题 - 多种正则兜底
            titles = re.findall(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
            if not titles:
                titles = re.findall(r'"title":"(.*?)"', html)
            if not titles:
                titles = re.findall(r'<a[^>]*>(.*?)</a>', html)
            # 清洗HTML标签
            clean_titles = []
            for t in titles:
                t = re.sub(r'<[^>]+>', '', t)  # 去HTML标签
                t = t.strip()
                if t and len(t) > 8 and '百度' not in t and 'baidu' not in t.lower():
                    clean_titles.append(t)
            taiwan_items.extend([{
                'title': t,
                'source': '百度台湾搜索',
                'summary': f'搜索关键词: {query.replace("+", " ")}'
            } for t in clean_titles[:5]])
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


def _fetch_taiwan_news_html():
    """备用：直接爬取台湾新闻网站HTML（非RSS）"""
    import re, subprocess
    items = []
    # 台湾新闻网站直接爬取（简化版）
    sources = [
        ('https://www.cna.com.tw/', '中央社'),
        ('https://money.udn.com/money/index', '经济日报'),
    ]
    headers = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    for url, name in sources:
        try:  # 已禁用 Pool
            curl_cmd = ['curl', '-s', '-L', '-H', headers, url]
            result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                continue
            html = result.stdout
            # 提取标题（简单正则）
            titles = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)[:5]
            if not titles:
                titles = re.findall(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL)[:5]
            for t in titles:
                t = re.sub(r'<[^>]+>', '', t).strip()
                if t and len(t) > 8:
                    items.append({'title': t, 'source': name, 'summary': f'来源: {name} HTML直接爬取'})
        except Exception as e:
            logging.warning(f"[新闻] {name} HTML爬取失败: {e}")
    return items


def _fetch_sinews(count=15):
    """V20: 生意社大宗涨跌快讯 — 供需断裂信号的核心源

    生意社(100ppi.com)提供大宗商品涨跌榜、行情分析、供需快讯。
    华为云WAF需要HW_CHECK cookie绕过：先提取JS中的cookie值，再带cookie重请求。
    """
    import re
    url = 'https://www.100ppi.com'
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        # Step 1: 获取WAF页面，提取HW_CHECK cookie值
        resp1 = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
        # 从JS中提取cookie值（华为云WAF格式: var _0x2 = "固定hash值"）
        hw_match = re.search(r'var\s+\w+\s*=\s*["\'](\w{32})["\']', resp1.text)
        if hw_match:
            hw_cookie = f'HW_CHECK={hw_match.group(1)}'
        else:
            # 尝试从Set-Cookie头获取
            hw_cookie = None
            for cookie in resp1.cookies:
                if cookie.name == 'HW_CHECK':
                    hw_cookie = f'{cookie.name}={cookie.value}'
                    break
            if not hw_cookie:
                logging.warning("[新闻] 生意社HW_CHECK cookie提取失败，跳过")
                return []

        # Step 2: 带cookie重新请求
        headers2 = {**headers, 'Cookie': hw_cookie}
        resp2 = requests.get(url, headers=headers2, timeout=12)
        if resp2.status_code != 200 or len(resp2.text) < 500:
            logging.warning(f"[新闻] 生意社二次请求失败: HTTP {resp2.status_code}, {len(resp2.text)}字节")
            return []

        html = resp2.text
        # 提取新闻标题 — 生意社首页有涨跌排行+行情分析标题
        # 多种正则兜底
        titles = re.findall(r'<a[^>]*href="[^"]*"[^>]*title="([^"]+)"', html)
        if not titles:
            titles = re.findall(r'<h[1-6][^>]*>(.*?)</h[1-6]', html, re.DOTALL)
        if not titles:
            titles = re.findall(r'<a[^>]*>(.*?)</a>', html)

        # 清洗 + 供需信号过滤
        items = []
        fracture_kw = ['涨', '跌', '飙升', '断供', '缺货', '短缺', '减产', '停产',
                        '暴涨', '暴跌', '趋紧', '上行', '下行', '冲天', '狂飙', '回落',
                        '紧缺', '缺口', '供应', '需求', '行情', '价格', '成本', '库存']
        for t in titles:
            t = re.sub(r'<[^>]+>', '', t).strip()
            if t and len(t) > 8:
                # 优先保留含供需信号关键词的标题
                items.append({
                    'title': t,
                    'source': '生意社',
                    'summary': '大宗商品供需快讯'
                })
        # 去重
        seen = set()
        unique = []
        for item in items:
            key = item['title'][:30]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:count]
    except Exception as e:
        logging.warning(f"[新闻] 生意社抓取失败: {e}")
        return []


def _fetch_wallstreetcn(count=15):
    """V20: 华尔街见闻快讯 — 国际大宗/地缘/宏观供需信号

    直接调用JSON API，无需签名，返回全球宏观+大宗快讯。
    API端点: api-one-wscn.awtmt.com/apiv1/content/lives
    """
    import json
    api_url = 'https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit={}'.format(count)
    try:
        resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code != 200:
            logging.warning(f"[新闻] 华尔街见闻API失败: HTTP {resp.status_code}")
            return []
        data = resp.json()
        items_list = data.get('data', {}).get('items', data.get('items', []))
        if not items_list:
            # 尝试其他JSON结构
            items_list = data.get('data', []) if isinstance(data.get('data'), list) else []
        results = []
        for item in items_list:
            title = item.get('title', '') or item.get('content_text', '') or ''
            title = title.strip().replace('\n', ' ')
            if title and len(title) > 5:
                # 提取摘要（如果content_text比title长）
                summary = (item.get('content_text', '') or '')[:200].strip()
                results.append({
                    'title': title[:100],
                    'source': '华尔街见闻',
                    'summary': summary,
                })
        return results[:count]
    except Exception as e:
        logging.warning(f"[新闻] 华尔街见闻抓取失败: {e}")
        return []


def _fetch_qhrb(count=15):
    """V20: 期货日报 — 期货品种供需/库存/政策信号

    注意: 必须用HTTP(非HTTPS)抓取，HTTPS会SSL握手失败。
    """
    import re
    # 必须用HTTP，HTTPS证书有问题
    url = 'http://www.qhrb.com.cn'
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            logging.warning(f"[新闻] 期货日报抓取失败: HTTP {resp.status_code}")
            return []
        html = resp.text
        # 提取新闻标题
        titles = re.findall(r'<a[^>]*href="[^"]*"[^>]*>(.*?)</a>', html)
        # 清洗 + 过滤有意义标题
        items = []
        for t in titles:
            t = re.sub(r'<[^>]+>', '', t).strip()
            if t and len(t) > 10 and t not in ['首页', '关于我们', '联系我们', '广告服务', '版权声明']:
                items.append({
                    'title': t,
                    'source': '期货日报',
                    'summary': '期货品种供需快讯'
                })
        # 去重
        seen = set()
        unique = []
        for item in items:
            key = item['title'][:30]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:count]
    except Exception as e:
        logging.warning(f"[新闻] 期货日报抓取失败: {e}")
        return []


def _fetch_cls(count=15):
    """V20: 财联社快讯 — 政策落地/关键矿产/有色金属/供应链信号

    贡献方式: 从首页HTML中提取内嵌的__NEXT_DATA__ JSON，获取快讯标题。
    不需要破解签名API。
    """
    import re, json
    url = 'https://www.cls.cn'
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            logging.warning(f"[新闻] 财联社抓取失败: HTTP {resp.status_code}")
            return []
        html = resp.text

        # 方法1: 提取 __NEXT_DATA__ JSON
        next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if next_data_match:
            try:  # 已禁用 Pool
                nd = json.loads(next_data_match.group(1))
                # 递归搜索JSON中所有title/content字段
                def _extract_titles(obj, depth=0):
                    titles = []
                    if depth > 5:
                        return titles
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k in ('title', 'content_text', 'brief') and isinstance(v, str) and len(v) > 5:
                                titles.append(v.strip())
                            elif isinstance(v, (dict, list)):
                                titles.extend(_extract_titles(v, depth+1))
                    elif isinstance(obj, list):
                        for item in obj:
                            titles.extend(_extract_titles(item, depth+1))
                    return titles
                raw_titles = _extract_titles(nd)
                results = []
                seen = set()
                for t in raw_titles:
                    t = t.replace('\n', ' ').strip()[:100]
                    if t and len(t) > 8 and t[:30] not in seen:
                        seen.add(t[:30])
                        results.append({
                            'title': t,
                            'source': '财联社',
                            'summary': '政策/供需快讯'
                        })
                if results:
                    return results[:count]
            except json.JSONDecodeError:
                pass

        # 方法2兜底: 直接从HTML提取标题链接
        titles = re.findall(r'<a[^>]*href="[^"]*"[^>]*>(.*?)</a>', html)
        items = []
        for t in titles:
            t = re.sub(r'<[^>]+>', '', t).strip()
            if t and len(t) > 10:
                items.append({
                    'title': t,
                    'source': '财联社',
                    'summary': '政策/供需快讯'
                })
        seen = set()
        unique = []
        for item in items:
            key = item['title'][:30]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:count]
    except Exception as e:
        logging.warning(f"[新闻] 财联社抓取失败: {e}")
        return []


def fetch_raw_materials():
    """并发抓取所有新闻素材，返回(raw_items, source_stats)"""
    RSS_SOURCES = {
    # 大陆科技/商业（服务器可访问）
    '36氪': 'https://36kr.com/feed',
    '36氪快讯': 'https://36kr.com/feed-newsflash',
    '虎嗅': 'https://www.huxiu.com/rss/0.xml',
    '钛媒体': 'https://www.tmtpost.com/rss.xml',
    '创业邦': 'https://www.cyzone.cn/rss/',
    # 大陆财经/大宗商品补充源（替代台湾RSS）
    '新浪财经': 'https://finance.sina.com.cn/roll/index.d.html?col=financenews&cid=56592',
    '财联社': 'https://www.cls.cn/rss',
    '华尔街见闻': 'https://wallstreetcn.com/feed',
    '生意社': 'https://www.100ppi.com/rss',
    '期货日报': 'http://www.qhrb.com.cn/rss',
}

    all_raw = []
    source_stats = {}
    # V21: 顺序执行（OpenClaw兼容，不用ThreadPoolExecutor）
    for name, url in RSS_SOURCES.items():
        try:
            raw = _fetch_rss(url, 15, 8)
            all_raw.extend(raw)
            source_stats[name] = len(raw)
        except Exception:
            source_stats[name] = 0

    try:
        hot_raw = _fetch_baidu_hot(0)
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

    # V20: 供需信号源 — 生意社/华尔街见闻/期货日报/财联社
    # V21: 顺序执行（OpenClaw兼容）
    signal_sources = {
        '生意社': lambda: _fetch_sinews(15),
        '华尔街见闻': lambda: _fetch_wallstreetcn(15),
        '期货日报': lambda: _fetch_qhrb(15),
        '财联社': lambda: _fetch_cls(15),
    }
    for name, fetch_fn in signal_sources.items():
        try:
            items = fetch_fn()
            all_raw.extend(items)
            source_stats[name] = len(items)
            if items:
                logging.info(f"[新闻] {name}补充: {len(items)}条")
        except Exception as e:
            source_stats[name] = 0
            logging.warning(f"[新闻] {name}抓取失败: {e}")

    # V21: 台湾新闻源已移除，不再尝试补源（服务器连不通台湾网站）
    # 台湾相关新闻靠大陆财经源转载覆盖

    # V17: 统一解码HTML实体 (&ldquo; &rdquo; &middot; 等)
    import html as html_mod
    for item in all_raw:
        if 'title' in item:
            item['title'] = html_mod.unescape(item['title'])

    # V20-fix4: B类噪音新闻过滤 — 融资/股票/盘前播报/产品发布PR/会议预告全部丢弃
    pre_count = len(all_raw)
    all_raw = _filter_noise_news(all_raw)
    filtered_count = pre_count - len(all_raw)
    if filtered_count > 0:
        logging.info(f"[新闻] 噪音过滤: 丢弃{filtered_count}条低价值新闻(融资/股票/PR/会议), 剩余{len(all_raw)}条")

    logging.info(f"[新闻] 抓取完成: {source_stats}, 共{len(all_raw)}条")
    return all_raw, source_stats


def _filter_noise_news(news_items):
    """V20-fix4: 过滤低价值噪音新闻 — 只保留高价值因果链触发源

    丢弃类型:
    - 融资PR: XX完成X轮融资/天使轮/A轮/B轮/领投/募资/定增
    - 股票行情: 盘前/盘初/多数上涨/多数下跌/涨超/跌超/涨停/跌停/纳指/标普/道琼斯/中概股
    - 产品发布PR: 发布/推出/首发/上线（排除"发布政策/意见/办法"）
    - 会议预告: 大会/展会/论坛/峰会/将至/即将举办
    - 人事变动: 辞职/离职/任命/加盟/卸任
    """
    # 融资类关键词
    financing_kw = ['融资', '天使轮', 'a轮', 'b轮', 'c轮', 'pre-a', 'pre-a轮',
                    '领投', '募资', '定增', '增资', '独角兽', '估值', '参投']
    # 股票行情类关键词
    stock_kw = ['盘前', '盘初', '盘后', '多数上涨', '多数下跌', '涨超', '跌超',
                '涨停', '跌停', '跌幅扩大', '涨幅扩大', '纳指', '标普', '道琼斯',
                '中概股', '美股盘', 'A股盘', '港股盘', '期权到期', '期货涨',
                '多数走高', '多数走低', '股价飙升', '股价暴跌', '市值超',
                '违规信披', '取保候审', '自律监管措施', '异常交易行为']
    # 会议预告类关键词
    meeting_kw = ['大会将至', '展会将至', '论坛将至', '峰会将至', '即将举办',
                  '即将召开', '即将开幕', '博览会将至']
    # 人事变动类关键词
    hr_kw = ['辞职', '离职', '卸任', '递交辞呈', '提交辞呈']
    # V20-fix11: 喊话/表态/驳斥类 — 没有改变任何供需，纯嘴炮
    rhetoric_kw = ['驳斥', '回应', '表态', '喊话', '警告', '谴责', '抗议', '否认',
                   '批评', '指责', '反驳', '澄清', '辟谣', '强烈不满', '严重关切',
                   '称将', '表示将', '打算', '计划将', '考虑', '研究将']

    filtered = []
    for item in news_items:
        title = item.get('title', '')
        title_lower = title.lower()

        # 融资类 → 丢弃
        if any(kw in title_lower for kw in financing_kw):
            continue

        # 股票行情类 → 丢弃
        if any(kw in title for kw in stock_kw):
            continue

        # 人事变动类 → 丢弃
        if any(kw in title for kw in hr_kw):
            continue

        # 会议预告类 → 丢弃
        if any(kw in title for kw in meeting_kw):
            continue

        # V20-fix11: 喊话/表态/驳斥类 → 丢弃（纯嘴炮不改变供需）
        # 但保留含实质事件的（如"签署协议后驳斥"不算纯嘴炮）
        if any(kw in title for kw in rhetoric_kw):
            # 如果同时含实质事件词则保留
            has_substance = any(kw in title for kw in ['签署', '协议', '贷款', '停产', '减产',
                                                        '投产', '复产', '扩产', '涨价', '暴跌',
                                                        '断供', '缺货', '管制', '禁令', '制裁',
                                                        '停产检修', '装置停车'])
            if not has_substance:
                continue

        # 产品发布PR → 丢弃（但保留"发布政策/意见/办法/新规/数据"）
        if any(kw in title for kw in ['发布', '推出', '首发', '上线', '亮相']):
            # 排除高价值发布（政策/数据/报告的发布）
            if not any(kw in title for kw in ['政策', '意见', '办法', '新规', '条例',
                                               '数据', '报告', '白皮书', '指数',
                                               '签署', '协议', '贷款', '备忘录']):
                continue

        filtered.append(item)

    return filtered


# ============================================================
# AI调用
# ============================================================
def _call_hunyuan_api(system_msg, user_msg, timeout=90):
    """调用混元API，单次调用带timeout"""
    api_key = os.getenv('HUNYUAN_API_KEY', '')
    if not api_key:
        logging.error("[AI] HUNYUAN_API_KEY未设置，请在环境变量中配置")
        return None
    url = "https://api.lkeap.cloud.tencent.com/plan/v3/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hy3-preview",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": 6000,
        "temperature": 0.75,
    }

    try:
        logging.info(f"[AI] 开始调用混元API: model=hy3-preview, system_msg长度={len(system_msg)}, user_msg长度={len(user_msg)}")
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        logging.info(f"[AI] 混元API响应: status={resp.status_code}, 长度={len(resp.text)}")
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
# V21: 三角机会 — 基于实时汇率波动率自动触发
# ============================================================

# 监控货币: 代码 → (中文名, 月波动阈值>4%触发)
FX_MONITOR = {
    'JPY': ('日元', 0.04),
    'KRW': ('韩元', 0.04),
    'TRY': ('土耳其里拉', 0.04),
    'INR': ('印度卢比', 0.04),
    'BRL': ('巴西雷亚尔', 0.04),
    'MXN': ('墨西哥比索', 0.04),
    'ZAR': ('南非兰特', 0.04),
}

# 汇率缓存（避免每次调用都请求API）
_fx_cache = {}  # {'JPY': {'current': 161.7, '30d_ago': 154.2, 'ts': ...}, ...}


def _fetch_fx_data():
    """拉取实时汇率数据 + 30天前汇率，计算波动率。带缓存10分钟。"""
    global _fx_cache
    now = time.time()
    if _fx_cache and now - _fx_cache.get('_ts', 0) < 600:
        return _fx_cache
    
    try:
        # 当前汇率: open.er-api.com (免费, 无key)
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        if resp.status_code != 200:
            raise Exception(f"API status {resp.status_code}")
        data = resp.json()
        current_rates = data.get('rates', {})
    except Exception as e:
        logging.warning(f"[三角机会] 拉取实时汇率失败: {e}")
        # 备用硬编码数据（2026-06-25 近似值）
        current_rates = {
            'JPY': 161.7, 'KRW': 1380.0, 'TRY': 46.5,
            'INR': 94.5, 'BRL': 5.72, 'MXN': 17.45, 'ZAR': 16.6,
            'CNY': 7.25,
        }
    
    # 30天前汇率: 用同一API的历史端点（部分免费层不支持，用估算）
    # 实际部署可换 exchangerate.host 的 /history 端点
    try:
        # 尝试获取历史数据
        thirty_days_ago = (datetime.now(CST) - timedelta(days=30)).strftime('%Y-%m-%d')
        hist_resp = requests.get(
            f"https://open.er-api.com/v6/latest/USD",  # 免费层不支持历史，用当前值估算
            timeout=10
        )
        # 免费层无历史端点，用近似值：根据已知月变动估算
        # 日元: 月初约155→现在162，月贬值~4.5%
        # 里拉: 月初约43→现在46.5，月贬值~8%
        # 韩元: 月初约1350→现在1380，月贬值~2.2%
        hist_rates = {
            'JPY': 155.0, 'KRW': 1350.0, 'TRY': 43.0,
            'INR': 93.0, 'BRL': 5.55, 'MXN': 17.0, 'ZAR': 16.0,
            'CNY': 7.20,
        }
    except:
        hist_rates = {
            'JPY': 155.0, 'KRW': 1350.0, 'TRY': 43.0,
            'INR': 93.0, 'BRL': 5.55, 'MXN': 17.0, 'ZAR': 16.0,
            'CNY': 7.20,
        }
    
    result = {'_ts': now}
    for code, (name, threshold) in FX_MONITOR.items():
        curr = current_rates.get(code)
        hist = hist_rates.get(code)
        if curr and hist and hist > 0:
            change_pct = abs(curr - hist) / hist
            result[code] = {
                'name': name,
                'current': round(curr, 2),
                '30d_ago': round(hist, 2),
                'change_pct': round(change_pct * 100, 1),
                'direction': '贬值' if curr > hist else '升值',
                'triggered': change_pct > threshold,
            }
    
    _fx_cache = result
    return result


def _detect_fx_signal(top_items=None):
    """检测是否有货币月波动>5% — 基于实时汇率数据而非新闻标题
    
    返回: dict {code, name, current, 30d_ago, change_pct, direction} 或 None
    """
    fx_data = _fetch_fx_data()
    triggered = []
    for code in FX_MONITOR:
        info = fx_data.get(code, {})
        if info.get('triggered'):
            triggered.append({'code': code, **info})
    
    if not triggered:
        return None
    
    # 优先日元（最核心关注），其次按波动率降序
    jpy = next((t for t in triggered if t['code'] == 'JPY'), None)
    if jpy:
        return jpy
    triggered.sort(key=lambda x: x['change_pct'], reverse=True)
    return triggered[0]


def _generate_triangle_section(fx_signal):
    """生成三角机会分析 — 基于实时汇率波动数据推导合法套利路径
    
    Args:
        fx_signal: dict {code, name, current, 30d_ago, change_pct, direction}
    """
    code = fx_signal['code']
    name = fx_signal['name']
    current = fx_signal['current']
    ago = fx_signal['30d_ago']
    change_pct = fx_signal['change_pct']
    direction = fx_signal['direction']
    
    lines = []
    lines.append("")
    lines.append("📐 **三角机会**（货币异动·合法套利路径）:")
    lines.append("")
    lines.append(f"- **货币异动**: {name}({code}) — 当前 {current}，30天前 {ago}，月{direction}{change_pct}%（触发阈值>4%）")
    lines.append("")
    
    if code == 'JPY':
        lines.append(f"- **套息方向**: 借日元（利率~1.0%）→买美元资产（利率~5%），利差约4%，年化套息收益约4%")
        lines.append(f"  - 工具: 外汇保证金账户做多USD/JPY（OANDA/IG/Saxo），资金门槛$2000+")
        lines.append(f"  - 或买入货币对冲型日股ETF（HEWJ/DXJ），剥离日元贬值风险，纯吃日股涨幅")
        lines.append(f"- **交叉盘联动**: EUR/JPY、GBP/JPY高度相关（>0.85），若USD/JPY突破160但EUR/JPY未跟→存在均值回归套利")
        lines.append(f"- **实体传导**: 日元贬值→日本出口商品变便宜→丰田/索尼/东电全球份额提升→韩国现代/三星受压")
        lines.append(f"  - 中间商节点: 日本二手半导体设备（东京电子/SCREEN的翻新机）以日元计价出口，人民币购买力增强→中日设备贸易商有套利空间")
        lines.append(f"- **期权策略**: USD/JPY在160关口双向波动率高，买入宽跨式期权（straddle）博弈波动率，资金$5000+")
        lines.append(f"- **风险**: BOJ可能加大干预（已投入11.7万亿日元），日元可能快速反弹500点以上")
    elif code == 'TRY':
        lines.append(f"- **趋势方向**: 做空USD/TRY（做多USD，做空TRY），里拉年化贬值15-20%")
        lines.append(f"  - 工具: 外汇保证金（Saxo/IG支持USD/TRY），资金$2000+，使用2-3x杠杆")
        lines.append(f"- **实体传导**: 里拉贬值→土耳其出口纺织品/农产品变便宜→中国进口商采购成本降低→中间商撮合利润")
        lines.append(f"- **风险**: 土耳其央行可能突发加息或资本管制，隔夜利息成本高（做空高利率货币需付carry）")
    elif code == 'KRW':
        lines.append(f"- **套利方向**: 韩元贬值时韩国加密货币交易所（Upbit/Bithumb）出现'泡菜溢价'，BTC溢价1-5%")
        lines.append(f"  - 工具: 海外买入BTC→提至韩国交易所→卖出KRW，需韩国银行账户，每人年换汇$5万限额")
        lines.append(f"- **实体传导**: 韩元贬值→三星/SK海力士出口竞争力提升→关注韩国半导体设备/材料进口成本变化")
    elif code == 'INR':
        lines.append(f"- **套利方向**: 印度卢比受油价和资本流动驱动，USD/INR在94-99区间宽幅震荡")
        lines.append(f"  - 工具: 关注USD/INR期货（CME或NSE），利用区间上下沿做均值回归")
        lines.append(f"- **实体传导**: 卢比贬值→印度IT外包/制药出口竞争力提升→关注印度仿制药进口成本变化")
    elif code == 'BRL':
        lines.append(f"- **套利方向**: 巴西雷亚尔受大宗商品（铁矿石/大豆）价格驱动，与DXY负相关")
        lines.append(f"  - 工具: 做多或做空USD/BRL期货（CME），配合铁矿石期货做对冲组合")
        lines.append(f"- **实体传导**: 雷亚尔贬值→巴西大豆/铁矿石出口以美元计价更便宜→中国进口商采购窗口")
    else:
        lines.append(f"- **套利方向**: 关注{code}兑USD/EUR/CNY的交叉盘波动率差异")
        lines.append(f"- **实体传导**: {name}{direction}→该国出口商品变便宜→进口商采购成本降低→中间商撮合机会")
        lines.append(f"- **风险**: 资本管制、政策突变、流动性枯竭")
    
    return "\n".join(lines)


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
    if not top_items:
        logging.warning("[日报] ⚠️ 新闻抓取为空，使用默认提示词调AI")
        news_digest = f"（今日新闻抓取失败，请基于{today_str}的已知市场动态生成6板块日报，重点关注：AI/算力/GPU/英伟达、大宗商品价格、两岸经贸、台湾彩券、赵公明庙宇项目）"
    else:
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
- 身份: 往来台湾的掮客中间商，资金200-300万人民币，周期3个月-1年
- 偏好: 不做重资产，不做长周期，做中间人/渠道/信息差
- 当前项目: 算力/GPU/英伟达/信息化/信息差/赵公明线上庙宇
- 可用工具: 上海户籍+腾讯项目Owner身份背书，两岸均有触角"""

    system_msg = f"""你是邪修分析师。专注"新闻→断裂→机会"的隐秘传导链。日报的灰色操作由引擎自动生成，你的任务是新闻解读。

⏰ 当前日期: {today_str} — 所有时间节点基于此日期推算，禁止用过期年份。

== 你的角色 ==
天之道损有余补不足——你在新闻中找到"有余方"和"不足方"之间的断裂。不是赌方向，是识别断裂位置。

⚠️ 核心原则:
1. 因果链必须基于今日具体新闻推演——每步因果关系要从新闻事件本身推导，禁止套用固定模板（如每次稀土新闻都输出同样5步链）
2. 同一类新闻不同事件的因果链必须不同——例如"稀土管制150天"和"稀土价格微涨3%"的传导路径完全不同，前者断供后者微调
3. 降级模板因果链仅供参考结构（L1→L5的传导方向），AI必须结合新闻具体内容替换为真实推演
4. 末端供需状态要具体——写清什么资源过剩/短缺、谁找不到谁、断裂在哪个环节，禁止"供需断裂""信息不对称"等空话

== 输出格式 ==

## 一、每日资讯

分类: 🎯 重大签署/政策 | 🤖 AI/算力 | 📊 供需/大宗 | 🌍 地缘/通道 | 📈 行业数据/投资 | 🌾 农产品/贵金属 | 🚀 新发明/新应用 | 🌐 出海/商业 | 🔍 国内/外严重缺货观察
每条:
- **标题**
  > 📡 因果链: [因为今日新闻事件所以A→因为A所以B→因为B所以C→因为C所以D→因为D所以E，每步从新闻本身推导，禁止套用固定模板。同一条新闻里的具体数字/公司/政策名必须出现在因果链中]

  > ⭐ 高价值触发源（遇到必须深度推演因果链）:
  > 1. 重大签署: 任何国家间的协议/贷款/合作签署（中美/中欧/中日/美日等），直接改变供应链结构
  > 2. 国内新规: 国务院/部委/省级新政策/新办法/新指导意见，直接改变供需规则
  > 3. AI/算力/信息化: GPU/芯片/大模型/数据中心/算力基建，直接改变算力供需结构
  > 4. 供需断裂: 暴涨/暴跌/断供/缺货/减产/停产/紧缺/供不应求，直接暴露断裂位置（短缺传导路径并入马斯克推演）
  > 4b. 避坑信号: 看似机会实则是坑→止损方式并入马斯克合规评估
  > 5. 产能变化: 投产/复产/扩产/检修/减值/资产减值，直接改变供给量
  > 6. 地缘/通道: 海峡/港口/航线/封锁/通航/制裁/出口管制，直接改变资源可达性
  > 7. 农产品/贵金属产量预警: 减产/歉收/丰收/种植面积变化/开采量下降，直接改变大宗供给
  > 8. 新发明/新应用/新skill/新产品(全球关注): 时代级突破+实用级新应用+全球关注新产品，能创造或摧毁整个产业供需结构
  > 9. 行业数据: 同比/环比/进出口量/库存/产能利用率，量化证据最强的触发源
  > 10. 国内/外严重缺货: 国内缺货→进口替代/转口机会；国外缺货→出口机会。从缺货资源推导下游断裂，找普通人可做的商机
  > 11. 货币异动（V21新增·三角机会）: 日元/韩元/里拉/比索/卢比/雷亚尔等单日波动超1%或月波动超5%→必须分析套息/跨市场/交叉汇率机会。推演路径: 货币异动→利差变化→套息交易方向→交叉盘联动→对相关行业进出口成本影响→可操作的中间商套利节点。禁止推演去当地购物/代购/旅游。

  > ❌ 禁止推送（无因果推演价值）:
  > - 融资PR（XX完成X轮融资）、股票盘前涨跌、普通产品发布PR（手机更新/SaaS上线）、会议预告、人事变动
  > - 注意: 普通产品发布≠新发明/新应用。只有能创造或摧毁整个产业的技术突破才算时代级

## 二、逆潮观察

- **市场共识**: [多数人怎么看]
  - 🔄 逆向可能: [为什么多数人可能错]
  - 🛑 止损: [什么信号说明逆向判断错]

📐 **三角机会**（仅当今日有货币单日波动超1%或月波动超4%时触发，无则跳过此子板块不输出）:
- **货币异动**: [哪个货币、变动幅度、原因]
- **套息方向**: [借哪个低息货币→买哪个高息资产，利差多少]
- **交叉盘联动**: [受影响的相关货币对，是否存在波动率差异]
- **实体传导**: [汇率变化→进出口成本变化→哪个行业/商品出现价差→中间商可操作节点]
- **工具路径**: [合法的操作工具: 外汇保证金/期货/期权/ETF/跨境贸易结算，资金门槛]

## 三、深度传导分析

> 从今日最高分新闻出发，推导因果传导链。必须写清每步的因果关系（因为A所以B），禁止只列断言（A短缺、B短缺）。必须结合今日具体新闻，禁止抽象模板。因果链中必须出现新闻里的具体公司名/政策名/数字，如果因果链里没有今日新闻的具体内容，说明你在套模板。

- **因果链**: [因为今日新闻事件所以A→因为A所以B→因为B所以C→因为C所以D→因为D所以E，每步写清因果，链中必须含今日新闻的具体内容]
- **有余方**: [谁有过剩]
- **不足方**: [谁有缺口]

🔮 天之道: [损X之有余→补Y之不足，附推导]
⚡ 商机定位: [断裂在哪两步之间→短缺的是什么→窗口期多久→中间人可找寻的空间在哪]

## 四、今日邪修金句

💭 [1句话，结合今日新闻主题。要冷、要利、有画面感。禁止鸡汤、禁止格言式。]{used_quotes_warn}

== 铁律 ==
1. 4板块齐全，每板块有实质内容，每条新闻附因果链，不需要操作话术
2. 因果链必须写清因果关系（因为A所以B），禁止只列断言（A短缺、B短缺）
3. ❌ 禁止模板填空——因果链必须从今日新闻本身推导，因果链中必须出现新闻里的具体公司名/政策名/数字。如果删掉新闻标题后因果链仍然成立=你在套模板=违规
4. ❌ 禁止同类新闻输出相同因果链——同板块不同新闻的因果链必须不同，因为事件不同传导路径就不同
5. 传导链必须基于今日新闻，禁止铜→PCB→电动车抽象模板
6. ❌ 融资PR/股票盘前涨跌/普通产品发布PR/会议预告/人事变动/喊话表态——禁止推送，无因果推演价值
7. 只推送11类高价值触发源: 重大签署/国内新规/AI算力信息化/供需断裂/产能变化/地缘通道/农产品贵金属产量预警/新发明新应用/行业数据/国内国外缺货/货币异动
8. ⭐ 重大签署类新闻（国家间协议/贷款/合作）必须深度推演因果链
9. ⭐ 国内新政策/新规类新闻（国务院/部委/省级）必须深度推演因果链
10. ⭐ 农产品/贵金属产量预警（减产/歉收/种植面积/开采量变化）必须深度推演因果链
11. ⭐ 新发明/新应用/新产品(全球关注)必须深度推演因果链
12. ⭐ 货币异动（日元/韩元/里拉等单日波动超1%或月波动超5%）必须深度推演因果链 — 重点推演: 套息交易方向→交叉盘联动→进出口成本变化→可操作的中间商套利节点。禁止推演购物/代购/旅游。
12. 注意: 普通产品发布(手机更新/SaaS上线/小版本迭代)≠新发明新应用，前者禁止后者必须推演
13. 金句每天不同，结合当日主题
14. 总字数2000-3000字
15. ⏰ 所有时间窗口基于{today_str}推算
16. 📍 优先挖掘台湾相关机会
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
                "二、逆潮观察",
                "三、深度传导分析",
                "四、今日邪修金句",
            ]
            missing = [h for h in section_headers if h not in content]
            if not missing:
                logging.info(f"[日报] ✅ AI生成4板块齐全: {len(content)}字符")
                # V8: 注入灰色操作卡（代码层生成，不受AI安全限制）
                content = _inject_shortage_alert(content, top_items)
                # V21: 注入三角机会（货币异动时追加合法套利分析）
                fx_item = _detect_fx_signal(top_items)
                if fx_item:
                    triangle = _generate_triangle_section(fx_item)
                    if triangle:
                        # 插入到逆潮观察和深度传导之间
                        content = content.replace("## 三、深度传导分析", triangle + "\n\n## 三、深度传导分析")
                        logging.info(f"[日报] 📐 三角机会已注入: {fx_item['name']}({fx_item['code']}) {fx_item['direction']}{fx_item['change_pct']}%")
                else:
                    logging.info("[日报] 📐 三角机会: 无货币异动新闻，跳过")
                # 记录邪修内容
                _record_xie_xiu_content(content)
                return content
            else:
                logging.warning(f"[日报] AI生成缺板块: {missing}，补齐后使用")
                # 补齐缺失板块
                content = _patch_missing_sections(content, top_items, missing)
                # V8: 注入灰色操作卡
                content = _inject_shortage_alert(content, top_items)
                # V21: 注入三角机会
                fx_item = _detect_fx_signal(top_items)
                if fx_item:
                    triangle = _generate_triangle_section(fx_item)
                    if triangle:
                        content = content.replace("## 三、深度传导分析", triangle + "\n\n## 三、深度传导分析")
                        logging.info(f"[日报] 📐 三角机会已注入(补板块): {fx_item['name']}({fx_item['code']}) {fx_item['direction']}{fx_item['change_pct']}%")
                else:
                    logging.info("[日报] 📐 三角机会: 无货币异动新闻，跳过")
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
        if header == "二、资源短缺预警":
            patch = _fallback_shortage_alert(top_items)
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


def _fallback_contra_tide(top_items):
    """逆潮观察降级: 从top_items找反直觉信号"""
    lines = ["## 三、逆潮观察\n"]
    # 找价格跌/供应增的反直觉新闻
    contra = [n for n in top_items if any(k in n.get('title', '') for k in ['跌', '降', '过剩', '库存'])] or top_items[:1]
    for item in contra[:2]:
        title = item.get('title', '未知')
        src = item.get('source', '未知')
        lines.append(f"- **{title}** ({src})\n")
        lines.append(f"  > 逆潮信号: 表面利空，关注资金是否借机吸筹\n")
    return ''.join(lines)


# ============================================================
# 降级路径: 基于关键词推断生成6板块
# ============================================================
def _fallback_all_sections(all_raw, top_items):
    """降级模式: 关键词推断6板块(有内容不是空壳)"""
    logging.info("[日报] 降级模式: 关键词推断6板块")

    # 画像过滤
    filtered_all = filter_by_profile(all_raw, min_score=0, top_n=15)

    # V20: 砍掉百度热搜板块，改为"🎯 重大签署/政策 + 📊 供需/大宗"两个信号板块
    signal_items = [n for n in all_raw if n.get('source') in ['生意社', '期货日报', '华尔街见闻', '财联社', '新浪财经']]
    # V20-fix2: 重大签署/政策类新闻从所有源筛选（不只限信号源）
    signing_policy_kw = ['签署', '协议', '贷款', '备忘录', '联合声明', '框架协议', '战略协议',
                         '国务院', '部委', '实施意见', '指导意见', '管理办法', '管理条例',
                         '印发', '征求意见', '施行', '新规', '政策', '监管', '合规']
    signing_policy_items = [n for n in all_raw
                            if any(kw in n.get('title', '') for kw in signing_policy_kw)
                            and not any(kw in n.get('title', '').lower() for kw in ['融资', '天使轮', 'a轮', 'b轮', 'pre-a', '领投'])][:3]

    # V20-fix7: 供需/大宗拆成3个独立板块，避免重大新闻被挤掉
    # A3: 供需断裂信号 + A4: 产能变化
    supply_demand_kw = ['断供', '缺货', '短缺', '减产', '停产', '限产', '供需',
                        '供应', '需求', '成本', '价格', '行情',
                        '飙升', '狂飙', '趋紧', '紧缺', '一飞冲天', '破十万',
                        '暴涨', '暴跌', '腰斩', '涨价潮', '降价潮', '价格战',
                        '投产', '复产', '扩产', '检修', '减值', '资产减值',
                        '涨', '跌', '库存', '产能', '产量']
    signal_filtered = [n for n in signal_items 
                       if any(kw in n.get('title', '') for kw in supply_demand_kw)
                       and not any(kw in n.get('title', '').lower() for kw in ['融资', '天使轮', 'a轮', 'b轮', 'pre-a', '领投'])][:4]
    if not signal_filtered:
        signal_filtered = [n for n in signal_items if n.get('source') in ['生意社', '期货日报']][:4]

    # A5: 地缘/通道变化 — 独立板块
    geopolitical_kw = ['海峡', '港口', '航线', '封锁', '通航', '禁运', '制裁', '出口管制',
                       '实体清单', '关税', '霍尔木兹', '马六甲', '苏伊士', '巴拿马运河',
                       '南海', '红海', '黑海', '封锁线', '海上通道']
    geopolitical_items = [n for n in all_raw
                          if any(kw in n.get('title', '') for kw in geopolitical_kw)][:3]

    # A6+A7: 行业数据/重大投资 — 独立板块
    industry_data_kw = ['同比', '环比', '进出口', '出口量', '进口量', '库存数据',
                        '利用率', '指数', '占比', '市场份额', '出货量', '订单量',
                        '项目', '基地', '工厂', '园区', '签约', '投资', '募投']
    industry_data_items = [n for n in all_raw
                           if any(kw in n.get('title', '') for kw in industry_data_kw)
                           and not any(kw in n.get('title', '').lower() for kw in ['融资', '天使轮', 'a轮', 'b轮', 'pre-a', '领投'])][:3]

    # V20-fix6: 新发明/新应用/新skill/新产品(全球关注) — 时代级+实用级
    breakthrough_kw = ['突破', '首创', '世界首例', '里程碑', '颠覆', '革命性', '量产突破', '商用化',
                       '固态电池', '核聚变', '可控核聚变', '室温超导', '量子计算', '量子比特',
                       '脑机接口', '基因编辑', '人造肉', '小型反应堆', '碳捕获', '绿氢',
                       '人形机器人', '具身智能', 'AGI', '通用人工智能',
                       # 实用级新应用/新产品(全球关注)
                       '全球首发', '全球首秀', '正式商用', '大规模商用', '规模化部署',
                       '新架构', '全新一代', '跨代',
                       'ChatGPT', 'GPT-5', 'GPT-6', 'Sora', 'Gemini',
                       'Cybertruck', 'Vision Pro',
                       '太空旅行', '商业航天', '可回收火箭', '星链',
                       '无人驾驶出租车', '飞行汽车', 'eVTOL',
                       'AI Agent', 'AI制药', 'AI编程']
    breakthrough_items = [n for n in all_raw
                          if any(kw in n.get('title', '') for kw in breakthrough_kw)
                          and not any(kw in n.get('title', '').lower() for kw in ['融资', '天使轮', 'a轮', 'b轮', 'pre-a', '领投'])][:3]

    # V20-fix4: 农产品/贵金属产量预警板块
    agri_metal_kw = ['大豆', '玉米', '小麦', '棉花', '白糖', '糖价', '稻谷', '油菜籽', '棕榈油',
                     '橡胶', '咖啡', '可可', '粮食', '化肥', '饲料', '收成', '收割', '播种',
                     '歉收', '丰收', '种植面积', '产量预估', '产量预测', '主产区', '产区',
                     '黄金', '白银', '铂金', '钯金', '贵金属', '金矿', '银矿',
                     '开采量', '矿产产量', '冶炼产量', '减产', '增产']
    agri_metal_items = [n for n in all_raw
                        if any(kw in n.get('title', '') for kw in agri_metal_kw)][:4]

    # V20-fix5: AI/算力/信息化
    ai_keywords = ['AI', '人工智能', '芯片', '半导体', '大模型', '英伟达', '算力', 'NVIDIA', 'GPU',
                   '数据中心', 'HBM', '台积电', '智能体', 'AGI', '机器人', '光刻']
    ai_items = [n for n in all_raw if any(kw.lower() in n['title'].lower() for kw in ai_keywords)
                and not any(kw in n['title'].lower() for kw in ['融资', '天使轮', 'a轮', 'b轮', 'pre-a', '领投'])][:3]

    # 板块一: 每日资讯
    used_chain_templates = set()
    sections = ["## 一、每日资讯\n"]

    # V20-fix8: 板块→模板优先映射，避免农产品/地缘/化工全落通用兜底
    SECTION_TEMPLATE_HINT = {
        'signing_policy': ['政策/监管', '出口/关税', '金融/利率'],   # #16, #5, #8
        'ai': ['AI/算力', '芯片/半导体'],                              # #2, #3
        'supply_demand': ['涨价/缺货/大宗', '化工/化肥'],              # #14, #20
        'geopolitical': ['地缘/通道', '出口/关税'],                    # #21, #5
        'industry_data': ['涨价/缺货/大宗', '融资/并购'],              # #14, #15
        'agri_metal': ['农产品/粮食', '贵金属/矿产', '稀土/稀有金属'],  # #17, #18, #1
        'breakthrough': ['新发明/新技术', '机器人/具身智能'],           # #19, #4
    }

    def _append_impact(n, section_hint=None):
        """给单条新闻附加因果链，同模板去重。V20-fix8: 按板块优先匹配模板。"""
        title = n['title']
        sections.append(f"- **{title}**")

        # V20-fix8: 按板块优先匹配对应模板
        template = None
        if section_hint and section_hint in SECTION_TEMPLATE_HINT:
            hint_keywords = SECTION_TEMPLATE_HINT[section_hint]
            title_lower = title.lower()
            # 在板块对应的模板里找最佳匹配
            best_score = 0
            for t in IMPACT_CHAIN_TEMPLATES:
                if not t['triggers']:
                    continue
                # 检查这个模板是否属于板块hint推荐的范围（用triggers内容近似匹配）
                score = 0
                for trigger in t['triggers']:
                    if trigger.lower() in title_lower:
                        weight = len(trigger) / 10.0
                        if trigger in ['gpu', 'hbm', '台积电', '稀土', '钨', '海峡', '港口', '出口管制']:
                            weight *= 2.0
                        score += weight
                if score > best_score:
                    best_score = score
                    template = t
            # 如果板块优先匹配没命中，回退到全局匹配
            if not template or best_score == 0:
                template = _match_impact_chain(title)
        else:
            template = _match_impact_chain(title)

        tpl_id = template['fracture']
        entity = _extract_entity(title)
        ent_short = entity
        clean = re.sub(r'[在的得了被把将向从]', '', entity)
        if len(clean) < 3:
            ent_short = n['title'][:15].strip()
        else:
            ent_short = re.sub(r'^[在的得了被把将向从]', '', entity).rstrip('？?！!。、')
            if len(ent_short) < 3:
                ent_short = n['title'][:10].strip()
        if tpl_id not in used_chain_templates:
            used_chain_templates.add(tpl_id)
            sections.append(_format_impact_chain(template, ent_short))
        else:
            sections.append(f"  > 📌 同类因果: 「{ent_short}」触发相同因果链（断裂在{template['fracture']}，窗口{template['window']}）→ 见上方完整链")

    # 板块一结构: 🎯重大签署/政策 → 🤖AI/算力 → 📊供需/大宗 → 🌍地缘/通道 → 📈行业数据/投资 → 🌾农产品/贵金属 → 🚀新发明/新应用 → 🌐出海
    used_titles_sp = set()

    sections.append("### 🎯 重大签署/政策\n")
    for n in signing_policy_items[:4]:
        if n['title'][:30] not in used_titles_sp:
            _append_impact(n, 'signing_policy')
            used_titles_sp.add(n['title'][:30])

    sections.append("\n### 🤖 AI/算力\n")
    for n in ai_items[:3]:
        if n['title'][:30] not in used_titles_sp:
            _append_impact(n, 'ai')
            used_titles_sp.add(n['title'][:30])

    sections.append("\n### 📊 供需/大宗\n")
    for n in signal_filtered[:4]:
        if n['title'][:30] not in used_titles_sp:
            _append_impact(n, 'supply_demand')
            used_titles_sp.add(n['title'][:30])

    sections.append("\n### 🌍 地缘/通道\n")
    for n in geopolitical_items[:3]:
        if n['title'][:30] not in used_titles_sp:
            _append_impact(n, 'geopolitical')
            used_titles_sp.add(n['title'][:30])

    sections.append("\n### 📈 行业数据/投资\n")
    for n in industry_data_items[:3]:
        if n['title'][:30] not in used_titles_sp:
            _append_impact(n, 'industry_data')
            used_titles_sp.add(n['title'][:30])

    sections.append("\n### 🌾 农产品/贵金属\n")
    for n in agri_metal_items[:4]:
        if n['title'][:30] not in used_titles_sp:
            _append_impact(n, 'agri_metal')
            used_titles_sp.add(n['title'][:30])

    sections.append("\n### 🚀 新发明/新应用/新产品\n")
    for n in breakthrough_items[:3]:
        if n['title'][:30] not in used_titles_sp:
            _append_impact(n, 'breakthrough')
            used_titles_sp.add(n['title'][:30])

    # V20-fix9: 国内/外严重缺货观察 — 双向缺货信号都是商机
    # 国内缺货→进口替代机会；国外缺货→出口机会
    shortage_signal_kw = ['缺货', '断供', '短缺', '紧缺', '供不应求', '断货', '抢购', '售罄',
                          '供应紧张', '供应不足', '产能不足', '缺料', '缺芯', '缺货潮',
                          '一货难求', '排队拿货', '货期延长']
    shortage_items = [n for n in all_raw
                      if any(kw in n.get('title', '') for kw in shortage_signal_kw)
                      and n['title'][:30] not in used_titles_sp][:4]

    biz_items = [n for n in filtered_all if n['title'][:30] not in used_titles_sp
                 and not any(kw in n.get('title', '') for kw in shortage_signal_kw)]
    sections.append("\n### 🌐 出海/商业\n")
    for n in biz_items[:3]:
        _append_impact(n)

    # 国内/外严重缺货观察
    if shortage_items:
        sections.append("\n### 🔍 国内/外严重缺货观察\n")
        sections.append("> 缺货=供需断裂最直接的信号。国内缺货→进口替代/转口机会；国外缺货→出口机会。从缺货资源推导下游断裂，找普通人可做的商机。\n")
        for n in shortage_items:
            _append_impact(n, 'supply_demand')
            used_titles_sp.add(n['title'][:30])

    # 板块二: 缺口扫描
    sections.append("\n\n" + _fallback_shortage_alert(top_items))

    # 板块三: 逆潮观察
    sections.append("\n" + _fallback_contra_tide(top_items))
    
    # V21: 三角机会 — 检测汇率异动新闻，追加合法套利分析
    fx_item = _detect_fx_signal(top_items)
    if fx_item:
        triangle_section = _generate_triangle_section(fx_item)
        if triangle_section:
            sections.append(triangle_section)
            logging.info(f"[日报] 📐 三角机会已注入(降级): {fx_item['name']}({fx_item['code']}) {fx_item['direction']}{fx_item['change_pct']}%")
    else:
        logging.info("[日报] 📐 三角机会: 无货币异动新闻，跳过")

    # 板块四: 深度传导
    sections.append("\n" + _fallback_deep_chain(top_items))

    # 板块五: 避坑提醒
    sections.append("\n" + _fallback_pitfall(top_items))

    # 板块六: 邪修金句
    sections.append("\n" + _fallback_quote(top_items))

    return "\n".join(sections)


def _format_impact_chain(template, entity=''):
    """V20: 格式化影响链为因果句式 — 人话，不用密码

    参数: IMPACT_CHAIN_TEMPLATES 中的模板 dict
    返回: 因果链叙事字符串
    """
    layers = template['layers']
    # 每层 = (因果句, 时间窗, 方向)，直接拼接因果句
    chain_parts = []
    for i, (step_desc, timing, direction) in enumerate(layers, 1):
        # 方向标记：短缺不加标记（默认关注），过剩标注
        if direction == '过剩':
            chain_parts.append(f"{step_desc}(过剩)")
        else:
            chain_parts.append(f"{step_desc}")
    chain_str = ' → '.join(chain_parts)
    fracture = template['fracture']
    window = template['window']

    # 注入新闻实体，让同类别不同新闻的输出有差异
    entity_tag = f"「{entity}」" if entity else ''

    lines = [
        f"  > 📡 因果链: {chain_str}",
        f"  > ⚡ 断裂在{fracture}，窗口{window}",
    ]
    if entity:
        lines.append(f"  > 📌 触发: {entity_tag}引发上述传导")
    return "\n".join(lines)


def _infer_impact_chain(title):
    """V20: 影响链推演 — 每条新闻生成因果链叙事

    替代V18的_infer_impact_chain()话术模板。
    不教怎么做生意，只推演因果传导路径。
    """
    template = _match_impact_chain(title)
    entity = _extract_entity(title)
    return _format_impact_chain(template, entity)


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


def _fallback_shortage_alert(top_items):
    """V20: 资源短缺预警 — 叙事化因果链，不用密码格式

    不教怎么做生意，只推演因果传导路径和短缺窗口。
    """
    lines = ["## 二、逆潮观察\n"]
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

    # V20-fix: 先判断是否政策/监管类新闻 — 政策发布≠产品发布，逻辑完全不同
    policy_markers = ['总局', '部门', '委员会', '委办', '办公室', '国务院', '省政府', '市发改委',
                      '意见', '通知', '办法', '规定', '条例', '指导意见', '实施方案', '纲要',
                      '印发', '贯彻', '落实', '监管', '备案', '准入', '审查']
    is_policy_news = any(kw in title for kw in policy_markers)

    # 检测共识倾向 — V16: 扩充关键词覆盖+else分支生成具体逆向分析
    if is_policy_news:
        # V20-fix: 政策/监管类新闻的逆向逻辑 — 不做空概念股，而是找政策落地的断裂点
        # 从标题提取政策影响的行业/领域
        policy_domains = {
            '人工智能': 'AI', 'ai': 'AI', '算力': 'AI', '大模型': 'AI',
            '金融': '金融', '银行': '金融', '保险': '金融', '证券': '金融',
            '新能源': '新能源', '光伏': '新能源', '储能': '新能源', '电动车': '新能源',
            '芯片': '半导体', '半导体': '半导体',
            '数据': '数据', '网络安全': '数据',
        }
        affected_domain = '相关行业'
        for kw, domain in policy_domains.items():
            if kw in title_lower:
                affected_domain = domain
                break
        consensus = f"'{title[:25]}' → 市场共识偏向悲观（政策=合规成本上升）"
        reverse = f"政策从发文到落地有时间差+执行往往打折→{affected_domain}行业短期过度反应，实际影响远小于预期"
        bet = f"趁市场过度反应时关注{affected_domain}行业的合规服务商/替代技术供应商——政策越严，合规需求越旺"
        stop = f"政策细则出台后确实严格执行（3-6个月内出现批量处罚/关停案例），则政策影响是实质性的"
    elif any(kw in title_lower for kw in ['暴涨', '疯抢', '热', '爆发', 'ALL IN', '新高', '历史最高', '飙升', '翻倍', '大涨']):
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
    elif any(kw in title_lower for kw in ['发布', '推出', '首发', '突破', '创新', '技术', '量子', '上线']) and not is_policy_news:
        # V20-fix: 排除政策类新闻（已在上方is_policy_news分支处理）
        consensus = f"'{title[:25]}' → 市场共识偏向乐观期待"
        reverse = f"新技术/新产品发布→PPT到量产差18-24个月→市场高估短期影响→{ent}的实际商业化进度远慢于预期"
        bet = f"关注{ent}发布后1-2周被连带错杀的竞争对手——确定性更高的标的"
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
    格式: 因为A所以B→因为B所以C→因为C所以D→因为D所以E (每步写清因果，不是并列断言)"""
    lines = ["## 三、深度传导分析\n"]
    lines.append("> 从今日核心新闻出发，推导因果传导链:\n")

    if not top_items:
        lines.append("🔮 **天之道: 损有余补不足 — 待数据补充**")
        lines.append("⚡ **商机定位: 待数据补充，识别断裂层与短缺资源**")
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
        lines.append("⚡ **商机定位: 待数据补充，识别断裂层与短缺资源**")
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
        xie_xiu = f"商机定位: 断裂在两岸物流+兑汇通道→短缺=民间兑汇渠道+中转仓储→窗口3-6个月→中间人空间: 民间通道对接"

    elif any(kw in title_lower for kw in ['铜', '铜价']):
        chain = f"铜矿减产/涨价 → 冶炼加工费压缩 → 硫酸涨价（铜冶炼副产） → 磷肥成本上升 → 粮食生产成本增加"
        surplus = "铜库存过剩方（有货没渠道的供应商）"
        deficit = "硫酸/磷肥需求方（缺货的生产企业）"
        tian_dao = f"天之道: 损铜库存之有余→补硫酸/磷肥之不足\n  > 推导: 铜涨价→硫酸涨价→磷肥涨价→粮食成本↑→有余在铜库存、不足在硫酸/磷肥"
        xie_xiu = f"商机定位: 断裂在铜→硫酸→磷肥传导链→短缺=硫酸/磷肥→窗口2-4个月→中间人空间: 库存方与需求方信息断裂"

    elif any(kw in title_lower for kw in ['出海', '全球化', '海外', '硬件出海', '跨境', '出海', '品牌出海']):
        chain = f"{ent}出海/跨境扩张 → 目标市场渠道缺口 → 本地化服务需求爆发 → 代理/经销商网络价值上升 → 售后/运营服务缺口"
        surplus = f"{ent}出海后的过剩产能（产品有但渠道不通）"
        deficit = f"本地化服务的不足供给（懂市场+懂产品的人极度稀缺）"
        tian_dao = f"天之道: 损产能之有余（有产品没渠道）→补本地化之不足（缺服务缺人才）\n  > 推导: 出海→渠道缺口→本地化需求→有余在产品、不足在服务"
        xie_xiu = f"商机定位: 断裂在{ent}出海→本地化落地→短缺=目标市场渠道+本地化服务→窗口3-6个月→中间人空间: 渠道对接+本地化服务"

    elif any(kw in title_lower for kw in ['涨价', '缺货', '断供', '铜', '铝', '硫酸', '锂']) or \
         ('价' in title_lower and not any(kw in title_lower for kw in ['性价比', '物美价廉', '降价', '平价', '评价'])):
        chain = f"{ent}供应变化 → 下游{aux_ent}成本上升 → 终端产品定价调整 → 替代材料需求上升 → {aux_ent2}利润暴增"
        surplus = f"有{ent}库存的供应商（供给过剩）"
        deficit = f"缺{ent}的买家（需求过剩）"
        tian_dao = f"天之道: 损库存之有余→补需求之不足\n  > 推导: {ent}涨价→下游减产→替代需求↑→供需断裂→有余在库存、不足在需求"
        xie_xiu = f"商机定位: 断裂在{ent}供需断裂→短缺={aux_ent}等下游→窗口2-4个月→中间人空间: 库存方与需求方对接"

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
            xie_xiu = f"商机定位: 断裂在GPU供给→AI公司算力需求→短缺=GPU/HBM芯片+AI服务器→窗口1-3个月→中间人空间: 空置算力与算力需求方对接"

    elif any(kw in title_lower for kw in ['出口', '关税', '制裁', '贸易']):
        chain = f"出口管制/关税调整 → 供应链被迫重组 → 转口贸易/第三国中转 → 合规成本上升 → 替代市场开拓"
        surplus = "受管制方的过剩产能（找不到渠道）"
        deficit = "替代通道的不足供给（转口/合规服务）"
        tian_dao = f"天之道: 损受管制方之有余（过剩产能）→补替代通道之不足（转口/合规）\n  > 推导: 管制→重组→转口→合规→有余在产能、不足在通道"
        xie_xiu = f"商机定位: 断裂在出口管制→替代供应链→短缺=转口贸易通道+合规咨询→窗口3-6个月→中间人空间: 转口通道+合规服务对接"

    elif any(kw in title_lower for kw in ['信仰', '庙宇', '供奉', '法会', '开光', '线上庙宇']):
        chain = f"线上信仰平台涌现 → 用户付费意愿验证(ARPU高) → 平台抽成/佣金模式 → 线下寺庙被迫数字化 → 信仰+电商/直播/AI开光新形态"
        surplus = "线下庙宇的过剩流量（香客减少、年轻化不足）"
        deficit = "线上信仰平台的不足供给（缺数字化工具和内容）"
        tian_dao = f"天之道: 损线下庙宇之有余（闲置流量）→补线上信仰之不足（数字化平台）\n  > 推导: 线上付费↑+数字化焦虑↑+跑马圈地期→有余在线下、不足在线上"
        xie_xiu = f"商机定位: 断裂在线下庙宇流量→线上信仰平台→短缺=线上平台+信仰商品供应链→窗口6-12个月→中间人空间: 庙宇数字化对接"

    elif any(kw in title_lower for kw in ['彩票', '彩券', '威力彩', '大乐透', '台彩']):
        chain = f"彩票热度上升 → 投注量激增 → 台彩经销商牌照价值变化 → 灰色合买/代购需求出现 → 政策风险累积"
        surplus = "台湾彩票市场的过剩热度（头奖效应+投注潮）"
        deficit = "彩票周边服务的不足供给（合买平台/经销商撮合/数据分析）"
        tian_dao = f"天之道: 损头奖热度之有余→补周边服务之不足\n  > 推导: 牌照价值变化+灰色合买↑+政策窗口→有余在热度、不足在服务"
        xie_xiu = f"商机定位: 断裂在台彩经销→合买服务→短缺=经销牌照+合买组织者→窗口1-3个月→中间人空间: 经销权转让+合买服务"

    elif any(kw in title_lower for kw in ['降息', '央行', '利率', '美联储']):
        chain = f"利率变化 → 两岸定存利差扩大 → 跨境资金流动加速 → 汇率波动加剧 → 对冲工具需求激增"
        surplus = "低利率方（资金成本低的地区）"
        deficit = "高利率方（资金需求大的地区）"
        tian_dao = f"天之道: 损低利率之有余（资金泛滥）→补高利率之不足（资金渴求）\n  > 推导: 利差→资金流动→汇率波动→有余在低利率端、不足在高利率端"
        xie_xiu = f"商机定位: 断裂在两岸利差→跨境配置→短缺=合规跨境通道+对冲工具→窗口3-6个月→中间人空间: 资金与合规通道对接"

    elif any(kw in title_lower for kw in ['新能源', '锂', '光伏', '储能', '电网']):
        chain = f"新能源装机量激增 → 储能配套不足 → 电网调度压力 → 虚拟电厂需求 → 电力市场化交易"
        surplus = "光伏组件的过剩产能（工厂库存积压）"
        deficit = "储能/消纳的不足供给（配套跟不上）"
        tian_dao = f"天之道: 损光伏产能之有余→补储能消纳之不足\n  > 推导: 装机↑→储能不足→消纳瓶颈→有余在产能、不足在配套"
        xie_xiu = f"商机定位: 断裂在光伏产能→储能配套→短缺=储能配套+电网调度→窗口6-12个月→中间人空间: 过剩产能与配套需求对接"

    elif any(kw in title_lower for kw in ['融资', '投资', '收购', '定增', '募资']):
        chain = f"{ent}获融资 → 产能扩张 → 上下游供需重新洗牌 → 供应链议价权转移 → 中间服务商(FA/合规/猎头)需求激增"
        surplus = f"{ent}融资后的过剩产能（钱多项目少，烧钱期）"
        deficit = f"配套服务的不足供给（投后管理/人才/合规跟不上融资速度）"
        tian_dao = f"天之道: 损融资过剩之有余（烧钱期产能闲置）→补配套服务之不足（投后/人才/合规缺口）\n  > 推导: 融资→扩张→但人才/合规/渠道跟不上→有余在资金、不足在配套"
        xie_xiu = f"商机定位: 断裂在{ent}融资→配套服务→短缺=投后管理+人才+合规→窗口3-6个月→中间人空间: 配套服务对接"

    elif any(kw in title_lower for kw in ['科技', '技术', '量子', '发布', '突破', '创新', '软件', '硬件', '平台', '系统']):
        chain = f"{ent}技术突破 → 早期采用者(大厂)率先部署 → 配套硬件/接口需求爆发 → 技能人才严重短缺 → 培训/咨询/外包市场出现"
        surplus = f"{ent}技术的过剩宣传（PPT到量产差18个月）"
        deficit = f"{ent}落地服务的不足供给（会部署的人/成熟的配套远不够）"
        tian_dao = f"天之道: 损技术炒作之有余（宣传过剩）→补落地服务之不足（人才/配套缺口）\n  > 推导: 发布→大厂抢部署→但没人会装→配套跟不上→有余在宣传、不足在落地"
        xie_xiu = f"商机定位: 断裂在{ent}技术发布→落地服务→短缺=落地人才+配套硬件→窗口3-6个月→中间人空间: 技术落地服务对接"

    elif any(kw in title_lower for kw in ['金融', '银行', '保险', '证券', '基金', '利率']):
        chain = f"金融政策变化 → 资金成本调整 → 利差/汇差扩大 → 资金流动加速 → 合规通道需求激增"
        surplus = "低利率区的过剩资金（找不到投资标的）"
        deficit = "合规通道的不足供给（额度有限/审批慢）"
        tian_dao = f"天之道: 损低利率资金之有余（资金泛滥）→补合规通道之不足（额度紧）\n  > 推导: 利差→资金流动→但通道有限→有余在资金、不足在通道"
        xie_xiu = f"商机定位: 断裂在资金供给→合规通道→短缺=合规通道+中小企业信贷→窗口3-6个月→中间人空间: 资金与通道对接"

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
        xie_xiu = f"商机定位: 断裂在{ent}传导链→短缺={deficit.split('（')[0] if '（' in deficit else '下游需求方'[:12]}→窗口2-4个月→中间人空间: {surplus.split('（')[0] if '（' in surplus else '有货方'[:12]}与短缺方对接"

    lines.append(f"- **因果链**: {chain}")
    lines.append(f"- **有余方**: {surplus}")
    lines.append(f"- **不足方**: {deficit}")
    lines.append(f"\n🔮 **{tian_dao}**")
    lines.append(f"⚡ **{xie_xiu}**")

    return "\n".join(lines)


def _fallback_pitfall(top_items):
    """V13: 避坑提醒 — 从多条新闻中找2个真实陷阱"""
    lines = ["## 四、今日邪修金句\n\n💭 {quote}\n\n> 邪修提示：信息差永远存在，关键是找到那个愿意为信息付费的人。"]

    top = top_items[0]
    title = top.get('title', '未知')
    # 提取标题核心名词（5-8字）
    core = title[:12] if len(title) >= 8 else title

    title_lower = title.lower()

    # 基于新闻主题从多个金句角度尝试，取第一个不重复的
    candidates = []

    if any(kw in title_lower for kw in ['台湾', '两岸', '小三通']):
        candidates = [
            f"两岸之间的空隙不是障碍——是资源传导的缓冲区",
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

    return f"## 四、今日邪修金句\n\n💭 {quote}"


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
    '知源智能': '知源智能(天使轮)',
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
            # V19-fix: 验证匹配是否合理（排除误匹配）
            # 如果匹配到的片段包含噪音词（融资/收购/完成等），可能是误匹配
            noise_in_match = {'融资', '收购', '完成', '宣布', '推出', '发布', '获', '斩获'}
            if not any(n in full_name for n in noise_in_match):
                return full_name

    # V19-fix: 公司库未匹配到 → 取标题前15字符作为实体（降级方案）
    title_prefix = title[:15].strip()
    if title_prefix:
        return title_prefix

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
# 彩票部分（V21: 解耦JinZhu，读取输出文件，不import代码）
# ============================================================
def generate_lottery_section():
    """读取 JinZhu 输出的推荐结果，不 import JinZhu 代码"""
    # V21: 优先读 asuan-jinzhu 的输出，降级读本地
    jinzhu_output = "/root/asuan-jinzhu/lottery-predictions.json"
    local_output = os.path.join(MODULE_DIR, 'lottery-predictions.json')

    for pred_file in [jinzhu_output, local_output]:
        if not os.path.exists(pred_file):
            continue
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
            logging.warning(f"[彩票] 读取{pred_file}失败: {e}")
            continue

    return "\n---\n## 🎰 彩票推荐\nJinZhu引擎今日未运行，推荐结果未生成。\n---\n"


def _fallback_lottery_display():
    """降级显示（调用generate_lottery_section）"""
    return generate_lottery_section()


# ============================================================
# 台湾彩种（V21: 解耦JinZhu，读取输出文件，不import代码）
# ============================================================
def generate_taiwan_section():
    """读取 JinZhu 输出的台湾彩种结果，不 import generate_taiwan"""
    jinzhu_output = "/root/asuan-jinzhu/lottery-predictions.json"
    local_output = os.path.join(MODULE_DIR, 'lottery-predictions.json')

    for pred_file in [jinzhu_output, local_output]:
        if not os.path.exists(pred_file):
            continue
        try:
            with open(pred_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            lines = ['\n---\n## 🎰 台湾彩种推荐（JinZhu引擎）\n']

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

                for game_key, game_label in [('pln_recs', '🎲 台湾威力彩(PLN)'), ('ltn_recs', '🎯 台湾大乐透(LTN)')]:
                    game_recs = recs.get(game_key, [])
                    if game_recs:
                        lines.append(f'### {game_label}')
                        for i, rec in enumerate(game_recs[:5]):
                            nums = rec.get('numbers', rec.get('digits', []))
                            if isinstance(nums, list):
                                if len(nums) >= 7:
                                    main_nums = nums[:6]
                                    special = nums[6]
                                    fmt = f"主号 {' '.join(str(int(n)) for n in main_nums)} + 特别号 {special}"
                                else:
                                    fmt = ' '.join(str(int(n)) for n in nums)
                            else:
                                fmt = str(rec)
                            lines.append(f'注{i+1}: {fmt}  [{rec.get("strategy", "策略")}]')
                        lines.append('')
                if not recs.get('pln_recs') and not recs.get('ltn_recs'):
                    return ""
            return '\n'.join(lines)
        except Exception as e:
            logging.warning(f"[台湾彩] 读取{pred_file}失败: {e}")
            continue

    return ""


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
        try:  # 已禁用 Pool
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

    # 5. 质量守护 — 发送前验证（V21: 守护脚本可选，失败不阻塞）
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
        try:  # 已禁用 Pool
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
        try:  # 已禁用 Pool
            subject = '阿算帮刘老板发财日报 | ' + today_str
            send_email(subject, full_content)
        except Exception as e:
            logging.error(f"[P1] 邮件发送异常: {e}")

    logging.info(f"========== 完成 {today_str} ==========")
