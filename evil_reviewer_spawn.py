#!/usr/bin/env python3
"""
东方朔心跳检查脚本
由阿策在心跳时调用，检查今天日报是否已生成 + 东方朔评价是否已追加
"""

import os
import json
import subprocess
from datetime import datetime, timezone, timedelta

WORKSPACE = '/root/.openclaw/workspace'
REPORT_DIR = '/root/asuan-scheduler/output'
DATA_DIR = '/root/asuan-scheduler/data'
STATE_FILE = os.path.join(WORKSPACE, 'memory/heartbeat-state.json')

CST = timezone(timedelta(hours=8))

def get_today_str():
    return datetime.now(CST).strftime('%Y-%m-%d')

def check_daily_report():
    """检查今天日报是否存在"""
    today = get_today_str()
    report_path = os.path.join(REPORT_DIR, f"{today}.md")
    return os.path.exists(report_path), report_path

def check_evil_review(report_path):
    """检查日报末尾是否已有东方朔评价"""
    with open(report_path, 'r') as f:
        content = f.read()
    return '【东方朔邪修评价】' in content or '【东方朔邪修评价】' in content

def update_state():
    """更新心跳状态文件"""
    today = get_today_str()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    else:
        state = {}
    
    state['last_evil_review_date'] = today
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def main():
    now = datetime.now(CST)
    
    # 只在 07:30 之后检查
    if now.hour < 7 or (now.hour == 7 and now.minute < 30):
        print(f"[{now.strftime('%H:%M')}] 还没到 07:30，跳过检查")
        return
    
    # 检查今天日报
    report_exists, report_path = check_daily_report()
    if not report_exists:
        print(f"[{now.strftime('%H:%M')}] 今天日报不存在，跳过")
        return
    
    # 检查东方朔评价是否已追加
    if check_evil_review(report_path):
        print(f"[{now.strftime('%H:%M')}] 今天东方朔评价已追加，跳过")
        return
    
    # 需要 spawn 东方朔
    print(f"[{now.strftime('%H:%M')}] 触发东方朔评价")
    print(f"  日报文件: {report_path}")
    print(f"  状态文件: {STATE_FILE}")
    
    # 这里不直接 spawn，由阿策在心跳时调用 sessions_spawn
    # 脚本只做检查，输出需要 spawn 的信号
    print("NEED_SPAWN")
    print(f"REPORT_PATH={report_path}")
    
    # 更新状态（避免重复检查）
    update_state()

if __name__ == '__main__':
    main()
