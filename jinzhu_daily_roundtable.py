#!/usr/bin/env python3
"""
JinZhu 多角色推荐 - 每日调度
只跑当天开奖的彩种
"""
import os
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
today = datetime.now(CST)
weekday = today.weekday()

# 开奖日判断
g = {}
# 双色球: 周二(1), 周四(3), 周日(6)
g['ssq'] = weekday in [1, 3, 6]
# 大乐透: 周一(0), 周三(2), 周六(5)
g['dlt'] = weekday in [0, 2, 5]
# 七星彩: 周二(1), 周五(4), 周日(6)
g['qxc'] = weekday in [1, 4, 6]
# 排列三/五: 每天
g['pln'] = True
g['ltn'] = True

today_games = [name for name, is_today in g.items() if is_today]
print(f"=== JinZhu 多角色推荐 [{today.strftime('%Y-%m-%d')}] ===")
print(f"今日开奖: {today_games}")

scheduler_dir = '/root/asuan-scheduler'
os.chdir(scheduler_dir)
sys.path.insert(0, scheduler_dir)

from jinzhu_multi_role import main as run_jinzhu_roundtable

for game in today_games:
    print(f"\n--- {game} ---")
    # 改 game 参数
    sys.argv = ['jinzhu_multi_role.py', game]
    try:
        run_jinzhu_roundtable()
    except SystemExit:
        pass  # 正常退出

print(f"\n✅ 全部完成")
