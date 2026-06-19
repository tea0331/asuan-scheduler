#!/usr/bin/env python3
"""
东方朔-邪修评论员 v2.0
读当日日报 + jinzhu_analysis.json，生成邪修评价，追加到日报文件末尾。

v2.0 修复 (WorkBuddy):
  - P0: jinzhu_analysis.json 路径修正 (data/ → 模块同目录)
  - P0: ⑤逆向回测改为真正读 jinzhu_analysis.json 的 reverse_backtest 字段
  - P0: 邪修指数改为动态计算 (基于 5 维度评价结果)
  - P1: ③盲区定位改为真正分析 strategy_analysis 数据
  - P1: ④结构漏洞改为基于数据的动态分析
  - P1: 一句话总结改为基于评价结果动态生成
  - P2: eviL → evil 变量名修正

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

# jinzhu_analysis.json 由 jinzhu_analysis_generator.py 生成，输出到模块同目录
JINZHU_ANALYSIS_PATH = os.path.join(MODULE_DIR, 'jinzhu_analysis.json')
PREDICTIONS_PATH = os.path.join(MODULE_DIR, 'lottery-predictions.json')


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_append(path, content):
    with open(path, 'a', encoding='utf-8') as f:
        f.write('\n\n' + content)


def extract_sections(md):
    """提取日报关键内容供分析"""
    sections = {}
    # 提取新闻标题
    titles = re.findall(r'### .+?\n\n- \*\*(.+?)\*\*', md)
    sections['titles'] = titles[:20]
    # 提取因果链
    chains = re.findall(r'📡 因果链: (.+?)(?=\n\s*📡|$)', md, re.DOTALL)
    sections['chains'] = chains[:10]
    # 提取断裂位置
    fractures = re.findall(r'断裂在(.+?)之间', md)
    sections['fractures'] = fractures
    # 提取所有板块标题
    headers = re.findall(r'^##\s+(.+)$', md, re.MULTILINE)
    sections['headers'] = headers
    # 统计降级标记
    fallback_markers = re.findall(r'（.*?异常.*?下次.*?）|（.*?降级.*?）', md)
    sections['fallback_count'] = len(fallback_markers)
    return sections


def load_jinzhu():
    """加载 JinZhu 分析数据

    优先读 jinzhu_analysis.json（含 strategy_analysis + reverse_backtest）
    降级读 lottery-predictions.json（只有当期推荐）
    """
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


# ===== 五维度分析 =====

def analyze_self_promotion(sections):
    """① 自嗨检测：日报哪些结论是事后解释而非事前预测？"""
    findings = []
    chains = sections.get('chains', [])

    # 检测重复因果链（模板复用嫌疑）
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

    # 检测降级标记
    fb_count = sections.get('fallback_count', 0)
    if fb_count > 0:
        findings.append(f'发现 {fb_count} 处降级/异常标记（可能是 AI 调用失败后的模板填空）')

    # 检测因果链是否包含具体实体名（>2字专名）
    generic_chains = [c for c in chains if not re.search(r'[\u4e00-\u9fff]{3,}(公司|集团|股份|科技|能源)', c)]
    if generic_chains and chains:
        ratio = len(generic_chains) / len(chains)
        if ratio > 0.5:
            findings.append(f'{len(generic_chains)}/{len(chains)} 条因果链未提及具体公司实体（事后解释嫌疑）')

    return findings


def analyze_causal_fallacy(sections):
    """② 因果谬误：因果链中相关性被误认为因果性？"""
    findings = []
    fractures = sections.get('fractures', [])

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
        findings.append('降级模式典型特征：因果链未因新闻而异')

    # 检测因果链中的"因为...所以..."模式是否过于简单
    chains = sections.get('chains', [])
    simple_causal = [c for c in chains if c.count('→') < 2 and len(c) < 50]
    if simple_causal:
        findings.append(f'{len(simple_causal)} 条因果链过于简单（<2个环节），可能是相关性误认为因果性')

    return findings


def analyze_blind_spot(jinzhu):
    """③ 盲区定位：JinZhu 对哪类组合持续给出错误置信度？"""
    findings = []

    if jinzhu.get('_source') == 'none':
        return ['无 JinZhu 分析数据，跳过盲区定位']

    if jinzhu.get('_source') == 'lottery-predictions':
        findings.append('仅有当期推荐数据（lottery-predictions.json），无历史命中率分析')
        findings.append('JinZhu 是独立闭环系统（结算→进化→推荐），与当日新闻无关联')
        return findings

    # 有 jinzhu_analysis.json，做深度分析
    strategy_analysis = jinzhu.get('strategy_analysis', {})
    if not strategy_analysis:
        findings.append('jinzhu_analysis.json 无 strategy_analysis 字段')
        return findings

    # 找命中率最低的策略
    for game, strategies in strategy_analysis.items():
        if not strategies:
            continue
        candidates = {k: v for k, v in strategies.items() if v.get('total_bets', 0) >= 3}
        if not candidates:
            candidates = strategies
        if candidates:
            worst = min(candidates.items(), key=lambda x: x[1].get('hit_rate', 0))
            findings.append(
                f'[{game}] 策略「{worst[0]}」命中率最低: {worst[1].get("hit_rate", 0):.0%}'
                f'({worst[1].get("hit_bets", 0)}/{worst[1].get("total_bets", 0)}注)'
            )

    # 核心注 vs 冷号注对比
    reverse = jinzhu.get('reverse_backtest', {})
    core_vs_cold = reverse.get('core_vs_cold', {})
    for game, comp in core_vs_cold.items():
        winner = comp.get('winner', '平局')
        if winner != '平局':
            findings.append(
                f'[{game}] {winner}命中率更高'
                f'(核心{comp.get("core_hit_rate", 0):.0%} vs 冷号{comp.get("cold_hit_rate", 0):.0%})'
            )

    return findings if findings else ['各策略命中率差异不显著，未发现明显盲区']


def analyze_structure_hole(sections, jinzhu):
    """④ 结构漏洞：数据 pipeline / 模型更新 / 配额逻辑中的时间差或边界条件"""
    findings = []

    # 降级模式检测
    fb_count = sections.get('fallback_count', 0)
    if fb_count > 0:
        findings.append(f'日报存在 {fb_count} 处降级标记，降级模式走关键词模板而非真实因果推演')

    # JinZhu 数据源检测
    source = jinzhu.get('_source', 'none')
    if source == 'lottery-predictions':
        findings.append('jinzhu_analysis.json 未生成，仅有当期推荐，无法做历史回测（逆向回测维度失效）')
    elif source == 'none':
        findings.append('无任何 JinZhu 数据，盲区定位和逆向回测均失效')

    # 元数据检测
    metadata = jinzhu.get('metadata', {}) if isinstance(jinzhu, dict) else {}
    games_covered = metadata.get('games_covered', [])
    if games_covered and 'pln' not in games_covered and 'ltn' not in games_covered:
        findings.append('JinZhu 分析数据不覆盖 PLN/LTN（台湾彩种），台湾彩票评价缺失')

    # 日报生成时间窗口
    findings.append('日报生成时间距新闻发布约 12-15 小时（数据延迟窗口，理论上可被利用）')

    return findings if findings else ['未发现明显结构漏洞']


def analyze_reverse_backtest(jinzhu):
    """⑤ 逆向回测：基于策略命中率分析，找持续失效的策略和可利用盲区"""
    findings = []

    if jinzhu.get('_source') != 'jinzhu_analysis':
        return ['jinzhu_analysis.json 尚未生成，暂无可回测数据（需先运行 jinzhu_analysis_generator.py）']

    reverse = jinzhu.get('reverse_backtest', {})
    if not reverse:
        return ['jinzhu_analysis.json 无 reverse_backtest 字段']

    # 提取 findings
    reverse_findings = reverse.get('findings', [])
    if reverse_findings:
        for f in reverse_findings:
            findings.append(f)
    else:
        findings.append('各策略命中率差异不显著，未发现可利用盲区')

    # 样本量说明
    sample_note = reverse.get('sample_note', '')
    if sample_note:
        findings.append(f'样本说明: {sample_note}')

    # 最差策略汇总
    worst = reverse.get('worst_strategy_by_game', {})
    for game, info in worst.items():
        if info.get('hit_rate', 1) < 0.1:
            findings.append(
                f'⚠️ [{game}] 策略「{info.get("strategy")}」命中率仅{info.get("hit_rate", 0):.0%}'
                f'，邪修可反向利用'
            )

    return findings if findings else ['逆向回测未发现可利用规律']


def calculate_score(dimension_findings):
    """动态计算邪修指数（1-10）

    规则:
    - 每个维度发现的问题按严重度加权
    - 硬编码/模板复用/降级模式 = 高权重
    - 无数据/轻微问题 = 低权重
    """
    score = 0
    evidence = []

    for dim_name, findings in dimension_findings.items():
        if not findings:
            continue

        dim_score = 0
        for f in findings:
            fl = f.lower()
            # 高权重问题（硬编码/模板/降级/失效）
            if '模板' in f or '降级' in f or '失效' in f or '异常' in f:
                dim_score += 2
                evidence.append(f'[{dim_name}] {f[:50]}')
            # 中权重问题（命中率低/盲区/漏洞）
            elif '命中率' in f or '盲区' in f or '漏洞' in f or '亏损' in f:
                dim_score += 1.5
                evidence.append(f'[{dim_name}] {f[:50]}')
            # 低权重（信息性）
            elif '未生成' in f or '无' in f or '缺失' in f:
                dim_score += 1
            else:
                dim_score += 0.5

        score += min(dim_score, 3)  # 每个维度最多贡献 3 分

    # 归一化到 1-10
    score = max(1, min(10, round(score)))

    return score, evidence


def generate_summary(dimension_findings, score):
    """基于评价结果动态生成一句话总结"""
    if score >= 7:
        # 找最严重的问题
        for dim_name, findings in dimension_findings.items():
            for f in findings:
                if '模板' in f or '降级' in f or '失效' in f:
                    return f'系统存在明显漏洞——{f}；邪修可稳定利用此盲区。'
        return '系统存在多个可利用漏洞，邪修指数偏高。'
    elif score >= 4:
        return '系统存在部分盲区，但需要特定条件配合才能利用。'
    else:
        return '系统较为严密，邪修无从下手。'


def analyze_evil(sections, jinzhu):
    """东方朔邪修分析（基于规则的数据驱动分析）"""
    lines = []
    lines.append(f'【东方朔邪修评价】{TODAY}')
    lines.append('')

    # 五维度分析
    dimensions = {
        '①自嗨检测': analyze_self_promotion(sections),
        '②因果谬误': analyze_causal_fallacy(sections),
        '③盲区定位': analyze_blind_spot(jinzhu),
        '④结构漏洞': analyze_structure_hole(sections, jinzhu),
        '⑤逆向回测': analyze_reverse_backtest(jinzhu),
    }

    # 输出各维度
    dim_labels = {
        '①自嗨检测': '🔍',
        '②因果谬误': '🔗',
        '③盲区定位': '🎯',
        '④结构漏洞': '🕳️',
        '⑤逆向回测': '🔄',
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

    # 动态计算邪修指数
    score, evidence = calculate_score(dimensions)
    lines.append('---')
    lines.append(f'今日邪修指数：{score}/10')
    if score >= 7:
        lines.append('- 7-10分：系统存在明显逻辑漏洞，邪修可稳定利用')
    elif score >= 4:
        lines.append('- 4-6分：存在可利用盲区，但需要特定条件配合')
    else:
        lines.append('- 1-3分：系统较为严密，邪修无从下手')
    if evidence:
        lines.append('')
        lines.append('打分依据：')
        for e in evidence[:3]:
            lines.append(f'  - {e}')
    lines.append('')

    # 动态一句话总结
    lines.append('💬 一句话总结：')
    summary = generate_summary(dimensions, score)
    lines.append(f'> {summary}')

    # JinZhu 独立性声明（固定）
    lines.append('')
    lines.append('> ⚠️ JinZhu 是独立彩票闭环系统，与当日新闻无关，禁止将推荐号码与新闻数字强行关联。')

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

    print('🧠 生成东方朔评价...')
    evil = analyze_evil(sections, jinzhu)

    print('✍️ 追加到日报末尾...')
    write_append(report_path, evil)

    print(f'✅ 完成，评价已追加到: {report_path}')
    print('---评价内容---')
    print(evil)


if __name__ == '__main__':
    main()
