#!/usr/bin/env python3
"""
jinzhu_analysis_generator.py
从 lottery-predictions.json + algo_state.db 生成 jinzhu_analysis.json
供东方朔邪修评论员的⑤逆向回测维度使用

数据流:
  lottery-predictions.json  →  历史推荐号码 + 策略标签
  algo_state.db             →  结算数据(命中数/奖级/奖金)
  ↓
  jinzhu_analysis.json      →  策略命中率分析 + 逆向回测

注意:
  - JinZhu 无"置信度"概念，推荐只有策略标签(核心注A/B、扩展1/2、冷号注)
  - 逆向回测维度基于"策略命中率"而非概率分数
  - lottery-predictions.json 只存 ssq/dlt/qxc，不存 pln/ltn
  - 脚本只读，不修改任何源文件

用法:
  python3 jinzhu_analysis_generator.py
  # 输出: jinzhu_analysis.json (同目录)
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PREDICTIONS_PATH = os.path.join(MODULE_DIR, 'lottery-predictions.json')
DB_PATH = os.path.join(MODULE_DIR, 'algo_state.db')
OUTPUT_PATH = os.path.join(MODULE_DIR, 'jinzhu_analysis.json')

CST_OFFSET = timedelta(hours=8)

def _now_cst():
    return datetime.utcnow() + CST_OFFSET


def load_predictions():
    """读取 lottery-predictions.json 历史推荐"""
    if not os.path.exists(PREDICTIONS_PATH):
        return []
    try:
        with open(PREDICTIONS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[分析] 读取 predictions 失败: {e}")
        return []


def load_settlements():
    """从 algo_state.db 读取结算数据( algo_bets JOIN algo_settlements )"""
    if not os.path.exists(DB_PATH):
        print(f"[分析] algo_state.db 不存在")
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute('''
            SELECT b.date, b.game, b.strategy, b.numbers AS bet_numbers,
                   b.cost, s.actual_numbers, s.hit_count, s.prize_tier,
                   s.prize_name, s.prize_amount, s.settled_at
            FROM algo_bets b
            LEFT JOIN algo_settlements s ON b.id = s.bet_id
            WHERE b.status = 'settled'
            ORDER BY b.date DESC
        ''').fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[分析] 读取结算数据失败: {e}")
        return []
    finally:
        conn.close()


def parse_numbers(raw):
    """安全解析 JSON 号码字段"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except:
            return {}
    return {}


def build_records(predictions, settlements):
    """合并推荐和结算数据，构建逐期记录"""
    # 按 (date, game) 索引结算数据
    settle_map = defaultdict(list)
    for s in settlements:
        key = (s.get('date', ''), s.get('game', ''))
        settle_map[key].append(s)

    records = []
    for pred in predictions:
        date = pred.get('date', '')
        if not date:
            continue
        for game in ['ssq', 'dlt', 'qxc']:
            recs = pred.get(f'{game}_recs', [])
            if not recs:
                continue

            # 找对应结算数据
            game_settlements = settle_map.get((date, game), [])

            # 合并推荐和结算
            rec_settlements = []
            for s in game_settlements:
                bet_nums = parse_numbers(s.get('bet_numbers'))
                actual = parse_numbers(s.get('actual_numbers'))
                rec_settlements.append({
                    'strategy': s.get('strategy', ''),
                    'numbers': bet_nums,
                    'actual': actual,
                    'hit_count': s.get('hit_count', 0),
                    'prize_tier': s.get('prize_tier', 0),
                    'prize_name': s.get('prize_name', '未中奖'),
                    'prize_amount': s.get('prize_amount', 0),
                    'cost': s.get('cost', 2),
                })

            records.append({
                'date': date,
                'game': game,
                'recommendations': recs,
                'settlements': rec_settlements,
            })

    return records


def analyze_strategies(records):
    """按彩种 × 策略类型统计命中率"""
    # stats[game][strategy] = {total, hits, total_hit_count, total_prize, total_cost}
    stats = defaultdict(lambda: defaultdict(lambda: {
        'total_bets': 0, 'hit_bets': 0, 'total_hit_count': 0,
        'total_prize': 0, 'total_cost': 0,
    }))

    for rec in records:
        game = rec['game']
        for s in rec.get('settlements', []):
            strategy = s.get('strategy', '未知')
            st = stats[game][strategy]
            st['total_bets'] += 1
            st['total_cost'] += s.get('cost', 2)
            st['total_hit_count'] += s.get('hit_count', 0)
            st['total_prize'] += s.get('prize_amount', 0)
            if s.get('prize_tier', 0) > 0:
                st['hit_bets'] += 1

    # 计算衍生指标
    result = {}
    for game, strategies in stats.items():
        result[game] = {}
        for strategy, s in strategies.items():
            total = max(s['total_bets'], 1)
            cost = max(s['total_cost'], 1)
            result[game][strategy] = {
                'total_bets': s['total_bets'],
                'hit_bets': s['hit_bets'],
                'hit_rate': round(s['hit_bets'] / total, 4),
                'avg_hit_count': round(s['total_hit_count'] / total, 2),
                'total_prize': s['total_prize'],
                'total_cost': s['total_cost'],
                'roi': round(s['total_prize'] / cost, 4),
            }

    return result


def reverse_backtest(strategy_analysis):
    """逆向回测分析 - 找出持续失效的策略和可利用盲区

    JinZhu 无置信度，改为基于策略命中率分析:
    1. 哪种策略命中率最低(持续失效)?
    2. 哪种策略 ROI 最低(最不值得跟)?
    3. 冷号注 vs 核心注 谁表现更好?
    4. JinZhu 的主推策略(核心注)是否真的是最优策略?
    """
    findings = []
    worst_strategies = {}  # game -> worst strategy
    best_strategies = {}   # game -> best strategy
    core_vs_cold = {}      # game -> {core_hit_rate, cold_hit_rate, winner}

    for game, strategies in strategy_analysis.items():
        if not strategies:
            continue

        # 找命中率最低的策略(至少3注才有意义)
        candidates = {k: v for k, v in strategies.items() if v['total_bets'] >= 3}
        if not candidates:
            candidates = strategies

        # 最差策略(命中率最低)
        worst = min(candidates.items(), key=lambda x: x[1]['hit_rate'])
        worst_strategies[game] = {
            'strategy': worst[0],
            'hit_rate': worst[1]['hit_rate'],
            'total_bets': worst[1]['total_bets'],
        }
        if worst[1]['hit_rate'] < 0.1 and worst[1]['total_bets'] >= 3:
            findings.append(
                f"[{game}] 策略「{worst[0]}」命中率仅{worst[1]['hit_rate']:.0%}"
                f"({worst[1]['hit_bets']}/{worst[1]['total_bets']}注)，持续失效"
            )

        # 最优策略
        best = max(candidates.items(), key=lambda x: x[1]['hit_rate'])
        best_strategies[game] = {
            'strategy': best[0],
            'hit_rate': best[1]['hit_rate'],
            'total_bets': best[1]['total_bets'],
        }

        # 核心注 vs 冷号注 对比
        core_strategies = {k: v for k, v in strategies.items() if '核心' in k}
        cold_strategies = {k: v for k, v in strategies.items() if '冷号' in k}

        core_hr = sum(s['hit_bets'] for s in core_strategies.values()) / max(
            sum(s['total_bets'] for s in core_strategies.values()), 1)
        cold_hr = sum(s['hit_bets'] for s in cold_strategies.values()) / max(
            sum(s['total_bets'] for s in cold_strategies.values()), 1)

        winner = '平局'
        if core_hr > cold_hr + 0.05:
            winner = '核心注'
        elif cold_hr > core_hr + 0.05:
            winner = '冷号注'

        core_vs_cold[game] = {
            'core_hit_rate': round(core_hr, 4),
            'cold_hit_rate': round(cold_hr, 4),
            'winner': winner,
        }

        # 如果冷号注明显优于核心注，这是可利用盲区
        if winner == '冷号注' and cold_hr > core_hr + 0.1:
            findings.append(
                f"[{game}] 冷号注命中率{cold_hr:.0%} > 核心注{core_hr:.0%}，"
                f"JinZhu主推核心注但冷号注表现更好，策略权重可能需要调整"
            )

        # ROI 分析
        roi_sorted = sorted(strategies.items(), key=lambda x: x[1]['roi'])
        if roi_sorted:
            worst_roi = roi_sorted[0]
            if worst_roi[1]['roi'] < 0.5 and worst_roi[1]['total_bets'] >= 3:
                findings.append(
                    f"[{game}] 策略「{worst_roi[0]}」ROI={worst_roi[1]['roi']:.2f}"
                    f"(投入{worst_roi[1]['total_cost']}元/回收{worst_roi[1]['total_prize']}元)，"
                    f"长期亏损"
                )

    # 生成总结
    summary_parts = []
    if findings:
        summary_parts.append("发现以下策略盲区:")
        summary_parts.extend(f"  - {f}" for f in findings)
    else:
        summary_parts.append("各策略命中率差异不显著，未发现明显可利用盲区(可能样本不足)")

    return {
        'findings': findings,
        'summary': '\n'.join(summary_parts),
        'worst_strategy_by_game': worst_strategies,
        'best_strategy_by_game': best_strategies,
        'core_vs_cold': core_vs_cold,
        'sample_note': f"样本基于 {sum(s['total_bets'] for g in strategy_analysis.values() for s in g.values())} 注结算数据",
    }


def generate():
    """主生成函数"""
    print(f"[分析] 开始生成 jinzhu_analysis.json @ {_now_cst().isoformat()}")

    # 1. 加载数据
    predictions = load_predictions()
    settlements = load_settlements()

    print(f"[分析] predictions: {len(predictions)} 期")
    print(f"[分析] settlements: {len(settlements)} 条结算记录")

    # 2. 构建记录
    records = build_records(predictions, settlements)
    print(f"[分析] 合并后 records: {len(records)} 条")

    # 3. 策略分析
    strategy_analysis = analyze_strategies(records)

    # 4. 逆向回测
    reverse = reverse_backtest(strategy_analysis)

    # 5. 输出
    output = {
        'metadata': {
            'generated_at': _now_cst().isoformat(),
            'generator': 'jinzhu_analysis_generator.py v1.0',
            'data_source': 'lottery-predictions.json + algo_state.db',
            'note': 'JinZhu无置信度概念，逆向回测基于策略命中率分析。只覆盖ssq/dlt/qxc，不含pln/ltn',
            'games_covered': list(strategy_analysis.keys()),
            'total_records': len(records),
            'total_settlements': len(settlements),
        },
        'records': records,
        'strategy_analysis': strategy_analysis,
        'reverse_backtest': reverse,
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[分析] 已输出: {OUTPUT_PATH}")
    print(f"[分析] 逆向回测总结:")
    print(f"  {reverse['summary']}")

    return output


if __name__ == '__main__':
    generate()
