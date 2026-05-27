#!/usr/bin/env python3
"""虚拟用户系统 v3.0 — 50人系统虚拟用户 + JinZhu参数化生成

数据流:
1. 50个内置虚拟用户，每人3彩种各一套独立策略参数（6类策略×随机微扰）
2. 缓存3彩种历史数据（仅3次网络请求）
3. 每用户每彩种用 JinZhu + model_override 生成5注推荐
4. 写入 algo_state.db（供JinZhu结算/进化，user_id = vu01~vu50）
5. 策略命中数据反哺JinZhu evolve（通过_collect_system_vuser_signals）

策略类型分布(50人):
  - lhs(10人): 拉丁超立方采样，均匀探索参数空间
  - extreme_freq(6人): 高频偏好(freq=0.6~0.7)
  - extreme_miss(6人): 高遗漏偏好(miss=0.5~0.6)
  - extreme_trend(6人): 高趋势偏好(trend=0.5~0.6)
  - extreme_zone(6人): 高区间偏好(zone=0.5~0.6)
  - balanced(16人): 均衡+随机微扰
"""
import sys
import json
import os
import random
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [VUser] [%(levelname)s] %(message)s')

# ===== 策略参数生成器 =====

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

# JinZhu PARAM_BOUNDS (与jin_zhu.py保持同步)
BOUNDS = {
    'freq': (0.15, 0.50), 'miss': (0.10, 0.40), 'trend': (0.10, 0.50), 'zone': (0.05, 0.35),
    'cold_miss_front': (0.20, 0.60), 'cold_cycle_front': (0.15, 0.50), 'cold_freq_front': (0.10, 0.45),
    'cold_miss_back': (0.15, 0.50), 'cold_cycle_back': (0.20, 0.60), 'cold_freq_back': (0.10, 0.45),
    'neighbor_bonus': (0.00, 0.10), 'gamma': (0.50, 0.95),
}

BASE = {
    'freq': 0.30, 'miss': 0.25, 'trend': 0.25, 'zone': 0.20,
    'cold_miss_front': 0.40, 'cold_cycle_front': 0.30, 'cold_freq_front': 0.30,
    'cold_miss_back': 0.30, 'cold_cycle_back': 0.40, 'cold_freq_back': 0.30,
    'neighbor_bonus': 0.03, 'gamma': 0.85,
}


def _normalize_main(p):
    """归一化 freq+miss+trend+zone=1.0"""
    s = p['freq'] + p['miss'] + p['trend'] + p['zone']
    if s > 0:
        for k in ['freq', 'miss', 'trend', 'zone']:
            p[k] = round(p[k] / s, 4)
    return p


def _make_lhs_params(index, total):
    """拉丁超立方采样 — 均匀覆盖参数空间"""
    rng = random.Random(index * 137 + 42)
    p = {}
    for k in ['freq', 'miss', 'trend', 'zone']:
        lo, hi = BOUNDS[k]
        p[k] = lo + (hi - lo) * rng.random()
    _normalize_main(p)
    for k in ['cold_miss_front', 'cold_cycle_front', 'cold_freq_front',
              'cold_miss_back', 'cold_cycle_back', 'cold_freq_back', 'neighbor_bonus', 'gamma']:
        lo, hi = BOUNDS[k]
        p[k] = round(lo + (hi - lo) * rng.random(), 4)
    return p


def _make_extreme_params(dominant_key, rng):
    """极端偏好策略 — 某一维拉满"""
    p = dict(BASE)
    # 主维度拉高
    lo, hi = BOUNDS[dominant_key]
    p[dominant_key] = round(lo + (hi - lo) * (0.7 + 0.3 * rng.random()), 4)
    # 其他维度压缩
    others = [k for k in ['freq', 'miss', 'trend', 'zone'] if k != dominant_key]
    for k in others:
        lo_k, hi_k = BOUNDS[k]
        p[k] = round(lo_k + (hi_k - lo_k) * rng.random() * 0.3, 4)
    _normalize_main(p)
    # cold参数微扰
    for k in ['cold_miss_front', 'cold_cycle_front', 'cold_freq_front',
              'cold_miss_back', 'cold_cycle_back', 'cold_freq_back']:
        lo, hi = BOUNDS[k]
        p[k] = round(lo + (hi - lo) * rng.random(), 4)
    p['neighbor_bonus'] = round(rng.uniform(0.01, 0.08), 4)
    p['gamma'] = round(rng.uniform(0.6, 0.9), 4)
    return p


def _make_balanced_params(rng):
    """均衡策略 — 轻微随机微扰"""
    p = dict(BASE)
    for k in p:
        lo, hi = BOUNDS.get(k, (p[k] * 0.8, p[k] * 1.2))
        delta = (hi - lo) * 0.15 * (rng.random() - 0.5)  # ±7.5%波动
        p[k] = round(_clamp(p[k] + delta, lo, hi), 4)
    _normalize_main(p)
    return p


def generate_50_users():
    """生成50个虚拟用户（固定种子，结果可复现）"""
    master_rng = random.Random(20260527)  # 固定种子

    users = []
    uid = 1

    # 1. LHS探索型(10人)
    for i in range(10):
        params = _make_lhs_params(i, 10)
        users.append({
            'user_id': f'vu{uid:02d}',
            'username': f'LHS探索{i+1:02d}',
            'strategy_type': 'lhs',
            'params': params,
        })
        uid += 1

    # 2. 极端频率型(6人)
    for i in range(6):
        params = _make_extreme_params('freq', master_rng)
        users.append({
            'user_id': f'vu{uid:02d}',
            'username': f'高频{i+1:02d}',
            'strategy_type': 'extreme_freq',
            'params': params,
        })
        uid += 1

    # 3. 极端遗漏型(6人)
    for i in range(6):
        params = _make_extreme_params('miss', master_rng)
        users.append({
            'user_id': f'vu{uid:02d}',
            'username': f'高遗漏{i+1:02d}',
            'strategy_type': 'extreme_miss',
            'params': params,
        })
        uid += 1

    # 4. 极端趋势型(6人)
    for i in range(6):
        params = _make_extreme_params('trend', master_rng)
        users.append({
            'user_id': f'vu{uid:02d}',
            'username': f'高趋势{i+1:02d}',
            'strategy_type': 'extreme_trend',
            'params': params,
        })
        uid += 1

    # 5. 极端区间型(6人)
    for i in range(6):
        params = _make_extreme_params('zone', master_rng)
        users.append({
            'user_id': f'vu{uid:02d}',
            'username': f'高区间{i+1:02d}',
            'strategy_type': 'extreme_zone',
            'params': params,
        })
        uid += 1

    # 6. 均衡型(16人)
    for i in range(16):
        params = _make_balanced_params(master_rng)
        users.append({
            'user_id': f'vu{uid:02d}',
            'username': f'均衡{i+1:02d}',
            'strategy_type': 'balanced',
            'params': params,
        })
        uid += 1

    return users


def simulate_bets_for_date(date_str, users):
    """为指定日期生成虚拟用户下注"""
    from jin_zhu import get_jinzhu
    jz = get_jinzhu()
    from algo_module import AlgoDB, ROITracker

    db = AlgoDB()
    tracker = ROITracker(db)

    # 缓存3彩种历史数据（仅3次网络请求）
    history_cache = {}
    for game in ['ssq', 'dlt', 'qxc']:
        history = jz._fetch_history(game)
        history_cache[game] = history

    kelly_map = {'ssq': 1, 'dlt': 1, 'qxc': 1}  # 1倍=2元/注
    total_bets = 0

    for user in users:
        algo_user_id = user['user_id']
        params = user['params']
        strategy_type = user['strategy_type']

        for game in ['ssq', 'dlt', 'qxc']:
            history = history_cache.get(game, [])
            if not history:
                continue

            # 用该用户的策略参数生成推荐
            recs = jz.generate_recs(
                game,
                history_data=history,
                model_override=params,
            )
            if not recs:
                continue

            # 标注策略类型（便于evolve按类型统计）
            for rec in recs:
                rec['strategy'] = f"[{strategy_type}]{rec.get('strategy', '')}"

            tracker.record_bets(date_str, game, recs, kelly_map, user_id=algo_user_id)
            total_bets += len(recs)

    logging.info(f"✅ {date_str} 虚拟下注完成：{len(users)}用户 × 3彩种 = {total_bets}注")
    return total_bets


if __name__ == '__main__':
    logging.info("=== 虚拟用户系统 v3.0（50人 + JinZhu参数化生成）===")
    users = generate_50_users()

    # 打印用户分布
    from collections import Counter
    type_counts = Counter(u['strategy_type'] for u in users)
    for t, c in sorted(type_counts.items()):
        logging.info(f"  {t}: {c}人")

    today = (datetime.now() + timedelta(hours=8)).strftime('%Y-%m-%d')
    total = simulate_bets_for_date(today, users)
    logging.info(f"=== 完成: {total}注 ===")
