#!/usr/bin/env python3
"""创建虚拟用户并模拟下注（固定策略，支持从virtual_users.json读取）"""
import sys, json, os
from datetime import datetime, timedelta

sys.path.insert(0, '/root/asuan-scheduler')

# 固定的10个虚拟用户配置（策略稳定，便于ROI对比）
FIXED_USERS = [
    {'user_id': 'virtual_001', 'strategy_pref': 'P0核心注', 'kelly_factor': 0.3, 'budget_per_day': 20, 'risk_tolerance': 0.7},
    {'user_id': 'virtual_002', 'strategy_pref': 'P0核心注', 'kelly_factor': 0.5, 'budget_per_day': 30, 'risk_tolerance': 0.9},
    {'user_id': 'virtual_003', 'strategy_pref': 'P1扩展1', 'kelly_factor': 0.2, 'budget_per_day': 15, 'risk_tolerance': 0.5},
    {'user_id': 'virtual_004', 'strategy_pref': 'P1扩展1', 'kelly_factor': 0.4, 'budget_per_day': 25, 'risk_tolerance': 0.8},
    {'user_id': 'virtual_005', 'strategy_pref': 'P1扩展2', 'kelly_factor': 0.3, 'budget_per_day': 20, 'risk_tolerance': 0.6},
    {'user_id': 'virtual_006', 'strategy_pref': 'P1扩展2', 'kelly_factor': 0.5, 'budget_per_day': 30, 'risk_tolerance': 0.85},
    {'user_id': 'virtual_007', 'strategy_pref': '冷号注', 'kelly_factor': 0.2, 'budget_per_day': 10, 'risk_tolerance': 0.4},
    {'user_id': 'virtual_008', 'strategy_pref': '冷号注', 'kelly_factor': 0.3, 'budget_per_day': 15, 'risk_tolerance': 0.55},
    {'user_id': 'virtual_009', 'strategy_pref': 'P0核心注', 'kelly_factor': 0.4, 'budget_per_day': 25, 'risk_tolerance': 0.75},
    {'user_id': 'virtual_010', 'strategy_pref': 'P1扩展1', 'kelly_factor': 0.3, 'budget_per_day': 20, 'risk_tolerance': 0.65},
]

def load_virtual_users():
    """加载虚拟用户配置（优先从JSON读取，不存在则用固定配置并保存）"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'virtual_users.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                users = json.load(f)
            if users and isinstance(users, list) and len(users) == 10:
                print(f"✅ 从 {path} 加载 {len(users)} 个虚拟用户")
                return users
        except Exception as e:
            print(f"⚠️ 读取 {path} 失败: {e}，使用固定配置")
    
    # 首次运行：保存固定配置到JSON
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(FIXED_USERS, f, ensure_ascii=False, indent=2)
    print(f"✅ 已创建 {len(FIXED_USERS)} 个固定虚拟用户 → {path}")
    return FIXED_USERS


def simulate_bets_for_date(date_str, users):
    """为指定日期模拟下注"""
    from algo_module import AlgoEngine
    engine = AlgoEngine()
    tracker = engine.roi_tracker
    
    # 获取今日推荐（从 lottery-predictions.json）
    preds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
    try:
        with open(preds_path, 'r', encoding='utf-8') as f:
            preds = json.load(f)
        today_pred = None
        for p in preds:
            if p.get('date') == date_str:
                today_pred = p
                break
        if not today_pred:
            print(f"⚠️ 未找到 {date_str} 的推荐数据，跳过虚拟下注")
            return
    except Exception as e:
        print(f"❌ 读取 lottery-predictions.json 失败: {e}")
        return
    
    kelly_map = {'ssq': 2, 'dlt': 2, 'qxc': 2}
    
    total_bets = 0
    for user in users:
        user_id = user['user_id']
        strategy_pref = user['strategy_pref']
        kelly_factor = user['kelly_factor']
        
        # 为每个彩种下注
        for game in ['ssq', 'dlt', 'qxc']:
            recs_key = f'{game}_recs'
            recs = today_pred.get(recs_key, [])
            if not recs:
                continue
            
            # 选择符合用户偏好的推荐
            preferred = [r for r in recs if strategy_pref in r.get('strategy', '')]
            if not preferred:
                preferred = recs  # 没有偏好匹配则全选
            
            # 根据Kelly因子选择注数
            num_bets = max(1, int(len(preferred) * kelly_factor))
            selected = preferred[:num_bets]
            
            # 记录下注（用虚拟用户ID）
            tracker.record_bets(date_str, game, selected, kelly_map, user_id=user_id)
            total_bets += len(selected)
    
    print(f"✅ {date_str} 虚拟下注完成：{len(users)}用户 × 3彩种 = {total_bets}注")

if __name__ == '__main__':
    print("=== 虚拟用户系统 ===")
    
    # 1. 加载虚拟用户（固定策略）
    users = load_virtual_users()
    
    # 2. 为今天模拟下注
    today = (datetime.now() + timedelta(hours=8)).strftime('%Y-%m-%d')
    simulate_bets_for_date(today, users)
    
    print("\n=== 完成 ===")
