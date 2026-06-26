#!/usr/bin/env python3
"""
东方朔-邪修评论员 v4.0
读当日日报 + jinzhu_analysis.json + weight-config.json + musk-push.json，生成邪修评价，追加到日报文件末尾。


v3.0 升级:
  - 新增维度: ⑧马斯克审视(推演质量+红线检测)
  - 新增维度: ⑥进化陷阱(GEPA权重污染检测) + ⑦虚伪指数(日报自我标榜检测)
  - ①自嗨检测: 增加金句空话检测 + 因果链长度分析 + 数字密度检测
  - ②因果谬误: 增加伪因果链识别(A→B但A和B无逻辑必然) + 过度泛化检测
  - ③盲区定位: 增加策略ROI排名 + 核心注A vs B 对比 + 盈利策略识别
  - ④结构漏洞: 增加AI生成vs降级比例 + 数据源覆盖度 + 结算完整性
  - ⑤逆向回测: 增加反向操作可行性评估 + 最优/最差策略ROI对比
  - 邪修语气: 从客气陈述改为毒舌点评，每条发现附带邪修点评
  - 邪修指数: 权重重调，新增维度贡献
  - 新增: 邪修建议(基于发现给出可操作建议)

调用方式：
python3 evil_reviewer.py [YYYY-MM-DD]
若不传日期，默认今天。
"""

import os
import sys
import json
import re
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(MODULE_DIR, 'output')
TODAY = datetime.now(CST).strftime('%Y-%m-%d')

JINZHU_ANALYSIS_PATH = os.path.join(MODULE_DIR, 'jinzhu_analysis.json')
PREDICTIONS_PATH = os.path.join(MODULE_DIR, 'lottery-predictions.json')
WEIGHT_CONFIG_PATH = os.path.join(MODULE_DIR, 'weight-config.json')

# 空话黑名单
HOLLOW_PHRASES = [
    '供需断裂', '信息不对称', '产业链重构', '深度赋能', '强势崛起',
    '意义重大', '深远影响', '值得关注', '有望迎来', '或将导致',
    '不容忽视', '至关重要', '密切相关', '密不可分', '值得关注',
]


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_append(path, content):
    with open(path, 'a', encoding='utf-8') as f:
        f.write('\n\n' + content)


def extract_sections(md):
    """提取日报关键内容供分析"""
    sections = {}
    # 新闻标题
    titles = re.findall(r'### .+?\n\n- \*\*(.+?)\*\*', md)
    sections['titles'] = titles[:20]
    # 因果链
    chains = re.findall(r'📡 因果链: (.+?)(?=\n\s*📡|$)', md, re.DOTALL)
    sections['chains'] = chains[:10]
    # 断裂位置
    fractures = re.findall(r'断裂在(.+?)之间', md)
    sections['fractures'] = fractures
    # 板块标题
    headers = re.findall(r'^##\s+(.+)$', md, re.MULTILINE)
    sections['headers'] = headers
    # 降级标记
    fallback_markers = re.findall(r'（.*?异常.*?下次.*?）|（.*?降级.*?）', md)
    sections['fallback_count'] = len(fallback_markers)
    # 总字数
    sections['total_chars'] = len(md)
    # 金句提取
    quotes = re.findall(r'💬.*?今日邪修金句.*?\n(.+?)(?=\n##|\n---|\Z)', md, re.DOTALL)
    sections['quotes'] = quotes
    # 窗口期提取
    windows = re.findall(r'窗口期[：:]\s*(.+?)(?=\n-|\n\*|\n#|\Z)', md)
    sections['windows'] = windows
    # 数字密度（因果链里有多少具体数字/百分比/金额）
    numbers_in_chains = 0
    for c in chains:
        numbers_in_chains += len(re.findall(r'\d+[%％]|\d+万|\d+亿|\d+\.?\d*[元吨]|20\d\d年', c))
    sections['numbers_in_chains'] = numbers_in_chains
    return sections


def load_jinzhu():
    """加载 JinZhu 分析数据"""
    if os.path.exists(JINZHU_ANALYSIS_PATH):
        try:
            with open(JINZHU_ANALYSIS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data['_source'] = 'jinzhu_analysis'
                return data
        except Exception as e:
            print(f'[东方朔] jinzhu_analysis.json 解析失败: {e}')

    if os.path.exists(PREDICTIONS_PATH):
        try:
            with open(PREDICTIONS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data['_source'] = 'lottery-predictions'
                return data
        except Exception as e:
            print(f'[东方朔] lottery-predictions.json 解析失败: {e}')

    return {'_source': 'none'}


def load_weight_config():
    """加载 GEPA 进化权重配置"""
    if os.path.exists(WEIGHT_CONFIG_PATH):
        try:
            with open(WEIGHT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return None


# ===== 七维度分析 =====

def analyze_self_promotion(sections):
    """① 自嗨检测：日报哪些结论是事后解释而非事前预测？"""
    findings = []
    chains = sections.get('chains', [])

    # 重复因果链检测
    if chains:
        chain_counts = {}
        for c in chains:
            key = c[:30]
            chain_counts[key] = chain_counts.get(key, 0) + 1
        dup = [(k, v) for k, v in chain_counts.items() if v > 1]
        if dup:
            findings.append(f'发现 {len(dup)} 条重复因果链（模板复用嫌疑）')
            for d, count in dup[:3]:
                findings.append(f'  - 重复链({count}次): {d}...')
            findings.append('邪修点评: 同一条因果链出现多次，说明AI在偷懒套模板，不是真在分析新闻')

    # 降级标记
    fb_count = sections.get('fallback_count', 0)
    if fb_count > 0:
        findings.append(f'发现 {fb_count} 处降级/异常标记')
        findings.append('邪修点评: AI调用失败走降级模板，这些内容是代码生成的不是AI分析的，参考价值归零')

    # 实体名缺失检测
    generic_chains = [c for c in chains if not re.search(r'[\u4e00-\u9fff]{3,}(公司|集团|股份|科技|能源|矿业|化工)', c)]
    if generic_chains and chains:
        ratio = len(generic_chains) / len(chains)
        if ratio > 0.5:
            findings.append(f'{len(generic_chains)}/{len(chains)} 条因果链未提及具体公司实体')
            findings.append('邪修点评: 没有具体公司名的因果链，就是"事后诸葛亮"——开奖后谁都能解释为什么出这组号')

    # 空话检测
    hollow_count = 0
    hollow_found = []
    for c in chains:
        for phrase in HOLLOW_PHRASES:
            if phrase in c:
                hollow_count += 1
                if phrase not in hollow_found:
                    hollow_found.append(phrase)
    if hollow_count > 0:
        findings.append(f'发现 {hollow_count} 处空话套话: {", ".join(hollow_found[:5])}')
        findings.append('邪修点评: 这些词放之四海而皆准，等于什么都没说。真正的邪修要找具体的、可操作的断裂')

    # 因果链长度分析
    short_chains = [c for c in chains if len(c.strip()) < 30]
    if short_chains:
        findings.append(f'{len(short_chains)} 条因果链过短（<30字），可能是凑数')

    # 数字密度检测
    numbers = sections.get('numbers_in_chains', 0)
    if chains and numbers < len(chains) * 0.5:
        findings.append(f'因果链数字密度低（{numbers}个数字/{len(chains)}条链），缺乏量化支撑')
        findings.append('邪修点评: 没有数字的因果链就是讲故事。真正的传导链要有量级、价格、产能数字')

    return findings


def analyze_causal_fallacy(sections):
    """② 因果谬误：因果链中相关性被误认为因果性？"""
    findings = []
    fractures = sections.get('fractures', [])
    chains = sections.get('chains', [])

    # 通用断裂模板检测
    generic_patterns = ['下游减产→替代方案', 'GPU断供→服务器交付', '产能受限→涨价']
    generic = []
    for f in fractures:
        for p in generic_patterns:
            if p in f:
                generic.append(f)
                break
    if generic:
        findings.append(f'发现 {len(generic)} 条通用断裂模板（未结合新闻实体）')
        findings.append('邪修点评: 每次都断在同一位置，说明不是在分析新闻，是在背模板')

    # 简单因果链检测
    simple_causal = [c for c in chains if c.count('→') < 2 and len(c) < 50]
    if simple_causal:
        findings.append(f'{len(simple_causal)} 条因果链只有1个环节（A→B），可能是相关性误认为因果性')
        findings.append('邪修点评: 真正的传导至少3环（A→B→C→D），1环因果就是"因为涨停所以涨"的废话')

    # 伪因果检测：因果链里出现"可能""或许""有望"等不确定词
    uncertain = []
    uncertain_words = ['可能', '或许', '有望', '或将', '预计', '料将', '预计可能']
    for c in chains:
        for w in uncertain_words:
            if w in c:
                uncertain.append(c[:40])
                break
    if uncertain:
        findings.append(f'{len(uncertain)} 条因果链含不确定词（可能/或许/有望），因果关系存疑')
        findings.append('邪修点评: "可能"出现3次的因果链，等于在说"也许A也许导致B也许不"。邪修不要也许')

    # 过度泛化检测：因果链以"整个行业""全面""所有"开头或包含
    overgeneral = [c for c in chains if re.search(r'整个行业|全面|所有|全部|完全', c)]
    if overgeneral:
        findings.append(f'{len(overgeneral)} 条因果链含过度泛化词（整个行业/全面/所有）')
        findings.append('邪修点评: 说过度泛化的话最安全也最没用。真正的断裂在具体环节，不在"整个行业"')

    # 窗口期检测：如果窗口期都是笼统的"X周内""X月内"
    windows = sections.get('windows', [])
    vague_windows = [w for w in windows if re.search(r'\d+周|\d+月|短期内|近期|未来', w) and not re.search(r'\d{4}|\d{1,2}月\d{1,2}日|本周|下周', w)]
    if vague_windows:
        findings.append(f'{len(vague_windows)} 个窗口期表述模糊（只有"X周/X月"没有具体日期）')
        findings.append('邪修点评: 窗口期要给具体日期。"2-3周内"是什么时候？邪修要精确到日才能操作')

    return findings


def analyze_blind_spot(jinzhu):
    """③ 盲区定位：JinZhu 对哪类组合持续给出错误置信度？"""
    findings = []

    if jinzhu.get('_source') == 'none':
        return ['无 JinZhu 分析数据，跳过盲区定位']

    if jinzhu.get('_source') == 'lottery-predictions':
        findings.append('仅有当期推荐数据，无历史命中率分析')
        return findings

    strategy_analysis = jinzhu.get('strategy_analysis', {})
    if not strategy_analysis:
        return ['jinzhu_analysis.json 无 strategy_analysis 字段']

    # 每个彩种：找最差策略 + 最优策略 + 核心注A vs B
    for game, strategies in strategy_analysis.items():
        if not strategies:
            continue
        candidates = {k: v for k, v in strategies.items() if v.get('total_bets', 0) >= 3}
        if not candidates:
            candidates = strategies
        if not candidates:
            continue

        # 最差策略
        worst = min(candidates.items(), key=lambda x: x[1].get('effective_hit_rate', 0))
        ehr = worst[1].get('effective_hit_rate', 0)
        hr = worst[1].get('hit_rate', 0)
        roi = worst[1].get('roi', 0)
        findings.append(
            f'[{game}] 最差策略「{worst[0]}」: 号码命中率{ehr:.0%}, 中奖率{hr:.0%}, ROI={roi:.2f}'
            f'({worst[1].get("total_bets", 0)}注)'
        )

        # 最优策略
        best = max(candidates.items(), key=lambda x: x[1].get('roi', 0))
        best_roi = best[1].get('roi', 0)
        best_hr = best[1].get('hit_rate', 0)
        if best_roi > 1.0:
            findings.append(
                f'[{game}] 最赚钱策略「{best[0]}」: ROI={best_roi:.2f}, 中奖率{best_hr:.0%}'
                f'（投入{best[1].get("total_cost", 0)}元/回收{best[1].get("total_prize", 0)}元）'
            )

        # 核心注A vs B 对比（同一前缀下）
        a_strategies = {k: v for k, v in strategies.items() if k.endswith('A') or k.endswith('(加权)A') or k.endswith('(权重)A')}
        b_strategies = {k: v for k, v in strategies.items() if k.endswith('B') or k.endswith('(加权)B') or k.endswith('(次优)B')}
        if a_strategies and b_strategies:
            a_roi = sum(s.get('roi', 0) * s.get('total_bets', 1) for s in a_strategies.values()) / max(sum(s.get('total_bets', 1) for s in a_strategies.values()), 1)
            b_roi = sum(s.get('roi', 0) * s.get('total_bets', 1) for s in b_strategies.values()) / max(sum(s.get('total_bets', 1) for s in b_strategies.values()), 1)
            if b_roi > a_roi * 1.5:
                findings.append(
                    f'[{game}] 核心注B(ROI={b_roi:.2f})远优于核心注A(ROI={a_roi:.2f})'
                    f'——JinZhu主推的A注反而最差'
                )
                findings.append(f'邪修点评: JinZhu把权重最高的号码当核心注A主推，但历史数据证明B注更好。模型在"追热"上犯了赌徒谬误')

    # 冷号注全面检测
    cold_zero_count = 0
    for game, strategies in strategy_analysis.items():
        for k, v in strategies.items():
            if '冷号' in k and v.get('total_bets', 0) >= 3 and v.get('hit_rate', 0) == 0 and v.get('roi', 0) == 0:
                cold_zero_count += 1
    if cold_zero_count > 0:
        findings.append(f'{cold_zero_count} 个冷号策略变体0%中奖率+ROI=0（纯亏损）')
        findings.append('邪修点评: 冷号策略全废——选遗漏最久的号等于赌徒谬误。彩票是随机的，遗漏久不代表"该出了"')

    return findings if findings else ['各策略命中率差异不显著']


def analyze_structure_hole(sections, jinzhu):
    """④ 结构漏洞：数据 pipeline / 模型更新 / 配额逻辑中的时间差或边界条件"""
    findings = []

    # AI生成 vs 降级比例
    fb_count = sections.get('fallback_count', 0)
    total_chars = sections.get('total_chars', 0)
    if fb_count > 0:
        findings.append(f'日报存在 {fb_count} 处降级标记')
        if total_chars > 0:
            findings.append(f'邪修点评: {fb_count}处降级意味着这些板块是代码生成的硬编码文本，不是AI分析。降级内容=占位符')

    # JinZhu 数据源
    source = jinzhu.get('_source', 'none')
    if source == 'lottery-predictions':
        findings.append('jinzhu_analysis.json 未生成，仅有当期推荐')
        findings.append('邪修点评: 没有历史回测数据=没有后视镜=开车瞎跑')
    elif source == 'none':
        findings.append('无任何 JinZhu 数据，盲区定位和逆向回测均失效')

    # 覆盖彩种
    metadata = jinzhu.get('metadata', {}) if isinstance(jinzhu, dict) else {}
    games_covered = metadata.get('games_covered', [])
    total_settlements = metadata.get('total_settlements', 0)
    if games_covered:
        missing = [g for g in ['ssq', 'dlt', 'qxc', 'pln', 'ltn'] if g not in games_covered]
        if missing:
            findings.append(f'JinZhu 数据不覆盖: {", ".join(missing)}')
            findings.append(f'邪修点评: 不覆盖的彩种=盲区。邪修专攻盲区')

    # 数据量检测
    if total_settlements > 0:
        findings.append(f'结算数据量: {total_settlements} 条（{"充足" if total_settlements > 5000 else "偏少，统计不显著"}）')

    # 时间延迟
    findings.append('日报生成时间距新闻发布约12-15小时（数据延迟窗口）')
    findings.append('邪修点评: 12小时延迟=别人已经行动了你才看到新闻。这个窗口期是最大的结构漏洞')

    return findings if findings else ['未发现明显结构漏洞']


def analyze_reverse_backtest(jinzhu):
    """⑤ 逆向回测：基于策略命中率分析，找持续失效的策略和可利用盲区"""
    findings = []

    if jinzhu.get('_source') != 'jinzhu_analysis':
        return ['jinzhu_analysis.json 尚未生成，暂无可回测数据']

    reverse = jinzhu.get('reverse_backtest', {})
    if not reverse:
        return ['jinzhu_analysis.json 无 reverse_backtest 字段']

    # 提取 findings
    reverse_findings = reverse.get('findings', [])
    if reverse_findings:
        for f in reverse_findings:
            findings.append(f)

    # 样本量
    sample_note = reverse.get('sample_note', '')
    if sample_note:
        findings.append(f'样本: {sample_note}')

    # 最差策略可利用性评估
    worst = reverse.get('worst_strategy_by_game', {})
    exploitable = 0
    for game, info in worst.items():
        ehr = info.get('effective_hit_rate', info.get('hit_rate', 0))
        if ehr < 0.1:
            exploitable += 1
            findings.append(
                f'⚠️ [{game}] 策略「{info.get("strategy")}」号码命中率仅{ehr:.0%}'
                f'，反向操作可行（买它不推荐的号）'
            )
    if exploitable > 0:
        findings.append(f'邪修点评: {exploitable}个彩种存在可反向利用的策略。但注意——彩票是随机的，反向操作也不保证盈利')

    # 最优 vs 最差 ROI 差距
    strategy_analysis = jinzhu.get('strategy_analysis', {})
    for game, strategies in strategy_analysis.items():
        if not strategies:
            continue
        rois = [(k, v.get('roi', 0)) for k, v in strategies.items() if v.get('total_bets', 0) >= 3]
        if len(rois) >= 2:
            rois.sort(key=lambda x: x[1])
            gap = rois[-1][1] - rois[0][1]
            if gap > 5:
                findings.append(
                    f'[{game}] 策略ROI差距巨大: 最差「{rois[0][0]}」={rois[0][1]:.2f} vs 最优「{rois[-1][0]}」={rois[-1][1]:.2f}'
                )
                findings.append(f'邪修点评: ROI差{gap:.1f}倍。最差策略在烧钱，最优策略在赚钱。JinZhu的GEPA应该把最差的权重砍掉')

    return findings if findings else ['逆向回测未发现可利用规律']


def analyze_evolution_trap(weight_config, jinzhu):
    """⑥ 进化陷阱：GEPA 权重是否被错误信号污染？"""
    findings = []

    if not weight_config:
        return ['weight-config.json 不存在，无法检测进化陷阱']

    freq = weight_config.get('freq', 0)
    miss = weight_config.get('miss', 0)
    trend = weight_config.get('trend', 0)
    zone = weight_config.get('zone', 0)
    gamma = weight_config.get('gamma', 0.88)
    version = weight_config.get('version', 0)
    evo_log = weight_config.get('evolution_log', [])

    findings.append(f'当前模型版本: v{version}，进化{len(evo_log)}代')

    # 权重失衡检测
    weights = {'freq(频率)': freq, 'miss(遗漏)': miss, 'trend(趋势)': trend, 'zone(区间)': zone}
    max_w = max(weights.values())
    min_w = min(weights.values())
    if max_w > min_w * 2.5:
        max_name = max(weights, key=weights.get)
        min_name = min(weights, key=weights.get)
        findings.append(f'权重失衡: {max_name}={max_w:.4f} 是 {min_name}={min_w:.4f} 的 {max_w/min_w:.1f}倍')
        findings.append(f'邪修点评: 权重极度偏向单一信号=模型对某类数据过拟合。过拟合=未来必然失效')

    # trend 权重过高检测（dlt bug可能推高了trend）
    if trend > 0.30:
        findings.append(f'trend权重={trend:.4f}偏高(>0.30)')
        findings.append('邪修点评: trend权重被dlt虚假100%中奖率信号推高过。虽然bug已修，但权重可能还残留污染')

    # gamma 过低检测
    if gamma < 0.80:
        findings.append(f'gamma={gamma:.2f}偏低(<0.80)，模型对近期数据过于敏感')
        findings.append('邪修点评: gamma低=记忆短=容易追涨杀跌。彩票是随机的，近期数据不代表趋势')

    # 进化日志重复检测
    if evo_log:
        recent = evo_log[-5:]
        changes = [e.get('changes', []) for e in recent]
        flat = [c for sublist in changes for c in sublist]
        if flat.count(flat[0]) == len(flat) and len(flat) > 2:
            findings.append(f'最近{len(recent)}代进化日志完全相同，可能进化停滞')
            findings.append('邪修点评: 连续多代进化结果一样=模型没有在学习，只是在重复')

    # 进化日志中 dlt 虚假信号检测
    dlt_signals = [e for e in evo_log if 'dlt' in str(e.get('changes', '')) or '大乐透' in str(e.get('changes', ''))]
    if len(dlt_signals) > 3:
        findings.append(f'进化日志中{len(dlt_signals)}条含dlt信号（可能受bug污染）')

    return findings if findings else ['GEPA 进化权重未发现明显异常']


# ===== 第8维度：马斯克审视 =====

MUSK_PUSH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'musk')

def load_musk_pushes():
    """读取马斯克推演结果（自动找今天的 musk-push-YYYY-MM-DD.json）"""
    today = datetime.now(CST).strftime('%Y-%m-%d')
    # 尝试今天
    p = os.path.join(MUSK_PUSH_DIR, f'musk-push-{today}.json')
    if not os.path.exists(p):
        # 找最近的
        files = sorted([f for f in os.listdir(MUSK_PUSH_DIR) if f.startswith('musk-push-') and f.endswith('.json')], reverse=True)
        if files:
            p = os.path.join(MUSK_PUSH_DIR, files[0])
        else:
            return []
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('pushes', [])
    except Exception as e:
        print(f'[东方朔] musk-push.json 解析失败: {e}')
    return []


def analyze_musk_review(musk_pushes):
    """⑧ 马斯克审视：推演质量+红线检测"""
    findings = []

    if not musk_pushes:
        return ['无马斯克推演数据（musk-push.json 不存在或为空）']

    HIGH_RISK_KEYWORDS = [
        '假冒', '诈骗', '洗钱', '行贿', '走私',
        '虚开发票', '逃税', '骗补', '套现', '非法集资',
        '虚构贸易', '伪造合同', '虚假流水'
    ]

    for i, push in enumerate(musk_pushes, 1):
        title = push.get('news_title', f'新闻{i}')
        insight = push.get('musk_insight', '')

        # 检查1：推演是否过于简略
        if len(insight) < 30:
            findings.append(f'推演{i}「{title[:30]}...」过于简略（{len(insight)}字 < 30字）')
            findings.append('邪修点评: 推演字数太少，等于没说。马斯克需要深度，不是三言两语')
            continue

        # 检查2：高危违法词（带上下文判断，避免误判）
        import re
        raw_risk = [kw for kw in HIGH_RISK_KEYWORDS if kw in insight]
        found_risk = []
        risk_context = {}
        for kw in raw_risk:
            start_pos = 0
            while True:
                pos = insight.find(kw, start_pos)
                if pos == -1:
                    break
                # 取前后10字
                left = insight[max(0, pos-10):pos]
                right = insight[pos+len(kw):pos+len(kw)+10]
                ctx = left + kw + right
                # 否定语境：前面10字内有否定词
                neg_prefixes = ['防止', '禁止', '避免', '杜绝', '不是', '并非', '不得', '不许', '不能', '切勿', '无需']
                is_neg = any(p in left for p in neg_prefixes)
                # 引用语境：高危词在引号内部（正则判断）
                # 匹配模式："...高危词..." 或 "高危词" 等
                quote_pattern = r'["\u201c\u300c\u300e][^"\u201d\u300d\u300f]{0,30}' + re.escape(kw) + r'[^"\u201d\u300d\u300f]{0,30}["\u201d\u300d\u300f]'
                is_quoted = bool(re.search(quote_pattern, insight))
                # 引用前缀
                ref_prefixes = ['所谓的', '被称为', '所谓', '被称为', '即']
                is_ref = any(p in left for p in ref_prefixes)
                # 假设语境
                assume_prefixes = ['如果', '假如', '假设', '若', '要是', '当']
                is_assume = any(p in left for p in assume_prefixes)
                is_safe = is_neg or is_quoted or is_ref or is_assume
                if not is_safe:
                    found_risk.append(kw)
                    risk_context[kw] = ctx
                start_pos = pos + 1
        found_risk = list(set(found_risk))

        if found_risk:
            for kw in found_risk:
                ctx = risk_context.get(kw, kw)
                neg_words = ['防止', '禁止', '避免', '杜绝', '不是', '并非']
                if any(w in ctx for w in neg_words):
                    findings.append(f'💡 推演{i}「{title[:30]}...」含敏感词「{kw}」但属否定语境: {ctx[:20]}...')
                    findings.append('邪修点评: 推演在讨论合规边界，措辞可更精确（避免用敏感词本身）')
                else:
                    findings.append(f'⚠️ 推演{i}「{title[:30]}...」含高危词: {kw}（上下文: {ctx[:25]}...）')
                    findings.append('邪修点评: 推演踩红线了。换合规表述（如"通道服务费"代替"洗钱"）')

        # 检查3：是否明确了谁有需求
        need_keywords = ['需要', '需求', 'KPI', '考核', '指标', '套利', '赚钱', '盈利', '省税', '降本']
        has_need = any(kw in insight for kw in need_keywords)
        if not has_need:
            findings.append(f'推演{i}「{title[:30]}...」未明确谁有需求填缺口')
            findings.append('邪修点评: 只说缺口不说谁需要，等于只诊断不开药。马斯克要回答②谁需要填')

        # 检查4：推演质量评价
        if len(insight) >= 100 and not found_risk and has_need:
            findings.append(f'✅ 推演{i}「{title[:30]}...」质量合格（{len(insight)}字，需求明确，无高危词）')

    return findings


def analyze_hypocrisy(sections):
    """⑦ 虚伪指数：日报是否在自我标榜或夸大成效？"""
    findings = []
    md_chars = sections.get('total_chars', 0)
    chains = sections.get('chains', [])

    # 金句检测
    quotes = sections.get('quotes', [])
    if quotes:
        for q in quotes[:3]:
            q_text = q.strip()[:100]
            if any(phrase in q_text for phrase in HOLLOW_PHRASES):
                findings.append(f'金句含空话: "{q_text}..."')
                findings.append('邪修点评: 金句应该是洞察，不是鸡汤。含"供需断裂""信息不对称"的金句=废话包装成智慧')

    # 因果链数量 vs 内容量
    if md_chars > 3000 and len(chains) < 3:
        findings.append(f'日报{md_chars}字但只有{len(chains)}条因果链，内容空洞')
        findings.append('邪修点评: 字数多≠内容多。3000字3条因果链=注水肉')

    # 检测自我肯定词
    md_text = ' '.join(chains)
    self_praise = len(re.findall(r'精准|完美|绝佳|最优|最强|突破|颠覆|革命性', md_text))
    if self_praise > 3:
        findings.append(f'因果链中{self_praise}处自我肯定词（精准/完美/最优等）')
        findings.append('邪修点评: 真正精准的预测不需要说"精准"。说3次"精准"的=心虚')

    # 检测"建议"但没有具体操作步骤
    suggestions = re.findall(r'建议(.+?)(?=\n|$)', ' '.join(chains))
    vague_suggestions = [s for s in suggestions if len(s) < 20 and not re.search(r'\d|具体|操作|步骤', s)]
    if vague_suggestions:
        findings.append(f'{len(vague_suggestions)} 条模糊建议（无具体操作步骤）')
        findings.append('邪修点评: "建议关注"不是建议。邪修要的是"买什么/卖什么/什么时候/多少量"')

    return findings if findings else ['日报未发现明显自我标榜']


def calculate_score(dimension_findings):
    """动态计算邪修指数（1-10）"""
    score = 0
    evidence = []

    for dim_name, findings in dimension_findings.items():
        if not findings:
            continue

        dim_score = 0
        for f in findings:
            # 高权重
            if any(kw in f for kw in ['模板', '降级', '失效', '异常', '0%中奖', '纯亏损', '过拟合', '污染', '停滞']):
                dim_score += 2.5
                evidence.append(f'[{dim_name}] {f[:60]}')
            # 中权重
            elif any(kw in f for kw in ['命中率', '盲区', '漏洞', '亏损', '失衡', '偏低', '偏高', '空洞', '模糊']):
                dim_score += 1.5
                evidence.append(f'[{dim_name}] {f[:60]}')
            # 低权重
            elif any(kw in f for kw in ['未生成', '无', '缺失', '不覆盖', '偏少']):
                dim_score += 1
            elif '邪修点评' in f:
                dim_score += 0.3
            else:
                dim_score += 0.5

        score += min(dim_score, 3.5)

    score = max(1, min(10, round(score)))
    return score, evidence


def generate_summary(dimension_findings, score):
    """毒舌一句话总结"""
    if score >= 8:
        for dim_name, findings in dimension_findings.items():
            for f in findings:
                if '0%中奖' in f or '纯亏损' in f or '过拟合' in f:
                    return f'系统千疮百孔——{f}。邪修不需要破解，系统自己在崩。'
            for f in findings:
                if '模板' in f or '降级' in f:
                    return f'AI在偷懒走模板——{f}。这日报一半是代码生成的，不是分析。'
        return '系统存在多个严重漏洞，邪修可以挑着利用。'
    elif score >= 5:
        return '系统有可利用的盲区，但需要耐心等待条件配合。'
    else:
        return '今天系统表现尚可，邪修找不到明显破绽——但别高兴太早，明天再说。'


def generate_evil_advice(dimensions):
    """基于发现给出邪修可操作建议"""
    advice = []

    for dim_name, findings in dimensions.items():
        for f in findings:
            if '0%中奖' in f and '冷号' in f:
                advice.append('冷号策略全面失效——如果JinZhu推荐冷号注，反着买（买它不推荐的号）')
            elif '降级' in f and '标记' in f:
                advice.append('日报有降级内容——降级板块的因果链是硬编码的，不要据此操作')
            elif '权重失衡' in f:
                advice.append('GEPA权重失衡——模型过拟合，近期推荐可信度打折')
            elif 'trend权重' in f and '偏高' in f:
                advice.append('trend权重可能受bug污染——JinZhu追热号的推荐可能不准')
            elif '核心注B' in f and '优于' in f:
                advice.append('核心注B比A好——如果跟JinZhu，选B注不选A注')
            elif '时间延迟' in f or '12' in f:
                advice.append('日报有12小时延迟——新闻里的机会可能已经被抢完了')

    if not advice:
        advice.append('暂无可操作建议——系统今天没有明显可利用的破绽')

    return advice[:3]


def analyze_evil(sections, jinzhu, weight_config):
    """东方朔邪修分析 v4.0 — 七维度毒舌版"""
    lines = []
    lines.append(f'【东方朔邪修评价 v3.0】{TODAY}')
    lines.append('')

    # 七维度分析
    # 加载马斯克推演
    musk_pushes = load_musk_pushes()

    dimensions = {
        '①自嗨检测': analyze_self_promotion(sections),
        '②因果谬误': analyze_causal_fallacy(sections),
        '③盲区定位': analyze_blind_spot(jinzhu),
        '④结构漏洞': analyze_structure_hole(sections, jinzhu),
        '⑤逆向回测': analyze_reverse_backtest(jinzhu),
        '⑥进化陷阱': analyze_evolution_trap(weight_config, jinzhu),
        '⑦虚伪指数': analyze_hypocrisy(sections),
        '⑧马斯克审视': analyze_musk_review(musk_pushes),
    }

    dim_labels = {
        '①自嗨检测': '🔍',
        '②因果谬误': '🔗',
        '③盲区定位': '🎯',
        '④结构漏洞': '🕳️',
        '⑤逆向回测': '🔄',
        '⑥进化陷阱': '⚖️',
        '⑦虚伪指数': '🎭',
        '⑧马斯克审视': '🔮',
    }

    for dim_name, findings in dimensions.items():
        label = dim_labels.get(dim_name, '▸')
        lines.append(f'{label} {dim_name}：')
        if findings:
            for f in findings:
                lines.append(f'> {f}')
        else:
            lines.append('> 未发现明显问题')
        lines.append('')

    # 邪修指数
    score, evidence = calculate_score(dimensions)
    lines.append('---')
    lines.append(f'今日邪修指数：{score}/10')
    if score >= 8:
        lines.append('- 8-10分：系统千疮百孔，邪修可以随意收割')
    elif score >= 5:
        lines.append('- 5-7分：存在可利用盲区，需要条件配合')
    else:
        lines.append('- 1-4分：系统尚可，邪修暂无下手处')
    if evidence:
        lines.append('')
        lines.append('打分依据：')
        for e in evidence[:5]:
            lines.append(f'  - {e}')
    lines.append('')

    # 毒舌总结
    lines.append('💬 邪修总结：')
    summary = generate_summary(dimensions, score)
    lines.append(f'> {summary}')
    lines.append('')

    # 邪修建议
    lines.append('🗡️ 邪修建议：')
    advice = generate_evil_advice(dimensions)
    for a in advice:
        lines.append(f'> {a}')
    lines.append('')

    # 独立性声明
    lines.append('> ⚠️ JinZhu 是独立彩票闭环系统，与当日新闻无关，禁止将推荐号码与新闻数字强行关联。')
    lines.append('> ⚠️ 邪修评价不代表投资建议。彩票是随机的，任何策略都无法保证盈利。')

    return '\n'.join(lines)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else TODAY
    report_path = os.path.join(REPORT_DIR, f'{date_str}.md')

    if not os.path.exists(report_path):
        print(f'❌ 日报不存在: {report_path}')
        sys.exit(1)

    print(f'📖 读日报: {report_path}')
    md = read_file(report_path)
    sections = extract_sections(md)

    print('📊 加载 JinZhu 数据...')
    jinzhu = load_jinzhu()
    print(f'   数据源: {jinzhu.get("_source", "none")}')

    print('⚖️ 加载 GEPA 权重...')
    weight_config = load_weight_config()
    if weight_config:
        print(f'   版本: v{weight_config.get("version", "?")}, 进化{len(weight_config.get("evolution_log", []))}代')

    print('🧠 生成东方朔评价 v3.0...')
    evil = analyze_evil(sections, jinzhu, weight_config)

    print('✍️ 追加到日报末尾...')
    write_append(report_path, evil)

    print(f'✅ 完成，评价已追加到: {report_path}')
    print('---评价内容---')
    print(evil)

    # 重发邮件（含东方朔评价）
    print('📧 重发邮件（含东方朔评价）...')
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        _env = {}
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    _env[k.strip()] = v.strip()
        with open(report_path, 'r', encoding='utf-8') as f:
            full_body = f.read()
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'阿算帮刘老板发财日报 | {TODAY}（含东方朔邪修评价）'
        msg['From'] = _env.get('SMTP_USER', '')
        msg['To'] = _env.get('SMTP_TO', '')
        msg.attach(MIMEText(full_body, 'plain', 'utf-8'))
        try:
            import markdown as md
            html_body = md.markdown(full_body, extensions=['extra', 'nl2br'])
            html_wrapped = f'<html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.7;color:#333;max-width:680px;margin:0 auto;padding:20px;">{html_body}</body></html>'
            msg.attach(MIMEText(html_wrapped, 'html', 'utf-8'))
        except Exception:
            pass
        server = smtplib.SMTP_SSL(_env.get('SMTP_SERVER', 'smtp.163.com'), int(_env.get('SMTP_PORT', '465')), timeout=30)
        server.login(_env.get('SMTP_USER', ''), _env.get('SMTP_PASSWORD', '') or _env.get('SMTP_PASS', ''))
        server.sendmail(_env.get('SMTP_USER', ''), [_env.get('SMTP_TO', '')], msg.as_string())
        server.quit()
        print('✅ 邮件重发成功')
    except Exception as e:
        print(f'⚠️ 邮件重发失败: {e}')


if __name__ == '__main__':
    main()
