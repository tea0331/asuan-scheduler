#!/usr/bin/env python3
"""
彩票号码分析模块 v7.4 — 刘海蟾点金（加权统计+GEPA自动进化+Kelly驱动选号+冷号注+休市+预算策略+多奖级EV+相关性分析+统计显著性+scrapling降级引擎+和值约束引导+重大事件告警）

v7.4核心改动（重大事件告警）：
1. 🔴 新增detect_lottery_alerts()：检测7类重大事件并生成告警
2. 🔴 告警写入lottery-alerts.json，供scheduler发送单独告警邮件
3. 🔴 GEPA重大更新、回测命中、规律发现、Kelly偏高、策略调整等均可触发告警

v7.3核心改动（和值约束引导）：
1. 🔴 修复GEPA从未生效bug：回测记录只有1条时GEPA需要2条，改为至少1条+6样本
2. 🔴 GEPA加统计显著性检验：Welch t-test，差异不显著时保守微调
3. 🔴 GEPA重大变更加样本门槛：20样本以下只允许微调±0.03，不允许大改
4. 🔴 清理旧版adjustments/last_reset_date遗留字段
5. 🔴 号码相关性分析：条件概率P(n|上期m)显著高于先验P(n)时加分
6. 🔴 GEPA进化日志加入sample_size和t_test记录

v7.0核心改动（GEPA自动进化闭环）：
1. 🔴 回测重构：不再读旧版推荐记录，用当前代码+开奖前数据实时生成推荐再对比开奖号
2. 🔴 GEPA自动进化：回测→诊断→调参→版本更新，每日闭环
3. 🔴 冷号注权重分前后区：前区miss主导(0.40/0.30)，后区cycle主导(0.30/0.40)
4. 🔴 所有可调参数统一收归weight-config.json（冷号权重/邻号bonus/gamma）
5. 🔴 执行顺序修正：回测→进化→推荐（避免正反馈环路）
6. 🔴 归一化下限保护：zone≥0.05, cold_freq≥0.05
7. 🔴 七星彩miss_score评分尺度统一
8. 🔴 回测记录权重快照（weight_snapshot）
9. 🔴 删除DLT gamma=0.85 clamp，由GEPA统一管理

v6.8核心改动（回测重构）：
1. 🟢 邻号加分：上期开出的号±1获得0.03权重bonus（球机机械偏差）
2. 🟢 分区平衡约束：选号贪心搜索中加入分区覆盖评分，后验检查确保每注至少覆盖2个区

v6.6核心改动（回测优化）：
1. 🟢 冷号注前区权重：遗漏0.30→0.40, 周期0.40→0.30（回测26020-26045期验证，总奖金+150%）
2. 🟢 冷号注红球权重：同步调整遗漏0.30→0.40, 周期0.40→0.30

v6.2核心改动（P0-P2全面优化）：
1. 🟢 Kelly→bias连续映射（tanh消除硬断层）
2. 🟢 排序键归一化（freq/miss/weight统一到[0,1]再组合）
3. 🟢 统一STRATEGY_MAP + Strategy枚举常量（消除字符串散落）
4. 🟢 冷号注w_score修正（w*4.0替代w/5.0）
5. 🟢 DLT FALLBACK补充 + SSQ/DLT fallback merge逻辑
6. 🟢 蓝球分散（exclude参数避免4注同蓝球）
7. 🟢 回测噪声过滤（领先需≥3次+命中均值更优才调整权重）
8. 🟢 趋势权重对称化（上升1.0x/下降0.8x，无先验偏好）
9. 🟢 OFFICE_ENABLED改环境变量 + HOLIDAYS动态生成2025-2028
10. 🟢 权重重置改日期间隔（30天而非version计数）
11. 🟢 QXC加Kelly驱动+冷号注（与SSQ/DLT对齐）
12. 🟢 多奖级Kelly EV计算（替代单一赔率50/100）
13. 🟢 遗漏值平均间隔维度（"到期号"额外加分）

v6吸收chinese-lottery-predict优势：
1. 🟢 新增冷号注策略：遗漏值最高号码组合，与核心注(追热)互补覆盖
2. 🟢 新增节假日休市判断：春节/国庆休市自动跳过，标注休市提醒
3. 🟢 新增购彩预算策略：按预算算注数，推荐单式/复式方案
4. 🟢 新增下期开奖日期计算（含休市跳过）

注意：彩票本质是随机事件，分析仅供娱乐参考。
"""

import os
import requests
import re
import random
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

# 🟢 v7.2: scrapling降级引擎（requests被封时自动启用）
try:
    from scrapling import Fetcher as _ScraplingFetcher, DynamicFetcher as _ScraplingDynamic
    _SCRAPLING_AVAILABLE = True
except ImportError:
    _SCRAPLING_AVAILABLE = False

CST = timezone(timedelta(hours=8))

# 百炼API配置 — 🔴 优先环境变量，回退硬编码
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', 'sk-a6149c2fa4534ee08fc5e46f797d32ef')
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

# 🔴 办公室Qwen3.6-abliterated（免费不限量！彩票零隐私，优先走这里）
OFFICE_API_BASE = os.environ.get('OFFICE_API_BASE', '')
OFFICE_API_KEY = os.environ.get('OFFICE_API_KEY', '')
OFFICE_MODEL = 'huihui-qwen3.6-27b-abliterated'
# 🟢 v6.5: OFFICE_ENABLED改用环境变量开关，默认开启（新模型更稳定）
OFFICE_ENABLED = os.environ.get('OFFICE_ENABLED', 'true').lower() in ('true', '1', 'yes')

# 🔴 开奖日历（周几开奖，周一=0，周日=6）
LOTTERY_SCHEDULE = {
    'ssq': [1, 3, 6],    # 双色球：周二四日
    'dlt': [0, 2, 5],    # 大乐透：周一三六
    'qxc': [1, 4, 6],    # 七星彩：周二五日
}

LOTTERY_NAMES = {
    'ssq': '双色球',
    'dlt': '大乐透',
    'qxc': '七星彩',
}

# 🟢 v6吸收：节假日休市配置（源自chinese-lottery-predict）
# 🟢 v6.2: 改用函数动态判断，不再只硬编码特定年份
def _build_holidays():
    """动态生成节假日表，覆盖2025-2028年"""
    holidays = {}
    # 春节休市：农历正月初一前后各3天 ≈ 每年1月下旬~2月中旬
    spring_festivals = {
        2025: (1, 26),   # 2025春节1/29
        2026: (2, 14),   # 2026春节2/17
        2027: (2, 5),    # 2027春节2/8
        2028: (1, 23),   # 2028春节1/26
    }
    for year, (m, d) in spring_festivals.items():
        from datetime import date, timedelta as _td
        start = date(year, m, d)
        for i in range(10):  # 10天休市
            day = start + _td(days=i)
            holidays[day.strftime('%Y-%m-%d')] = '春节休市'
    # 国庆休市：每年10月1日-7日
    for year in range(2025, 2029):
        for day in range(1, 8):
            holidays[f'{year}-10-{day:02d}'] = '国庆休市'
    return holidays

HOLIDAYS = _build_holidays()

# 🟢 v6吸收：购彩预算配置（源自chinese-lottery-predict）
BUDGET_CONFIG = {
    'default': 10,       # 默认预算(元)
    'price_per_bet': 2,  # 单注价格(元)
}

# 开奖日历的中文显示
WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 🟢 v6.2: 统一策略名映射（全局常量，避免散落各处不一致）
# 🔴 v6.2: 策略名常量 — 替代字符串字面量，减少拼写错误风险
class Strategy:
    CORE = '核心注'
    EXT1 = '扩展1'
    EXT2 = '扩展2'
    COLD = '冷号注'
    # 带后缀的变体
    CORE_WEIGHTED = '核心注(加权)'
    CORE_HOT = '核心注(追热)'
    CORE_COLD = '核心注(搏冷)'
    CORE_FALLBACK = '核心注(兜底)'
    EXT1_WEIGHTED = '扩展1(加权)'
    EXT1_FALLBACK = '扩展1(兜底)'
    EXT2_WEIGHTED = '扩展2(加权)'
    EXT2_FALLBACK = '扩展2(兜底)'
    COLD_MISS = '冷号注(遗漏)'
    COLD_FALLBACK = '冷号注(兜底)'
    # 旧格式兼容
    HOT_STRATEGY = '追热策略'
    REBOUND_STRATEGY = '回补策略'
    BALANCED_STRATEGY = '综合策略'

STRATEGY_MAP = {
    Strategy.HOT_STRATEGY: Strategy.CORE, Strategy.REBOUND_STRATEGY: Strategy.EXT2, Strategy.BALANCED_STRATEGY: Strategy.EXT1,
    Strategy.CORE_WEIGHTED: Strategy.CORE, Strategy.CORE_HOT: Strategy.CORE, Strategy.CORE_COLD: Strategy.CORE,
    Strategy.CORE_FALLBACK: Strategy.CORE, Strategy.CORE: Strategy.CORE,
    Strategy.EXT1_WEIGHTED: Strategy.EXT1, Strategy.EXT1_FALLBACK: Strategy.EXT1, Strategy.EXT1: Strategy.EXT1,
    Strategy.EXT2_WEIGHTED: Strategy.EXT2, Strategy.EXT2_FALLBACK: Strategy.EXT2, Strategy.EXT2: Strategy.EXT2,
    Strategy.COLD_MISS: Strategy.COLD, Strategy.COLD_FALLBACK: Strategy.COLD, Strategy.COLD: Strategy.COLD,
}

def is_holiday(date_str):
    """🟢 v6吸收：检查是否在节假日休市期间"""
    return HOLIDAYS.get(date_str)


def get_next_draw_date(game, from_date=None):
    """🟢 v6吸收：计算下期开奖日期（含节假日跳过）
    返回: (日期字符串, 星期几, 是否在休市期) 或 None
    """
    if game not in LOTTERY_SCHEDULE:
        return None
    draw_days = LOTTERY_SCHEDULE[game]
    current = from_date or datetime.now(CST)
    for offset in range(1, 15):  # 最多往后看2周
        check = current + timedelta(days=offset)
        date_str = check.strftime('%Y-%m-%d')
        holiday = is_holiday(date_str)
        if holiday:
            continue  # 跳过休市日
        if check.weekday() in draw_days:
            return (check.strftime('%m月%d日'), WEEKDAY_NAMES[check.weekday()], False)
    # 2周内都是休市？返回第一个开奖日（带休市标记）
    for offset in range(1, 30):
        check = current + timedelta(days=offset)
        if check.weekday() in draw_days:
            date_str = check.strftime('%Y-%m-%d')
            return (check.strftime('%m月%d日'), WEEKDAY_NAMES[check.weekday()], bool(is_holiday(date_str)))
    return None


def get_draw_games(date=None):
    """返回指定日期开奖的彩种列表，默认今天"""
    if date is None:
        wd = datetime.now(CST).weekday()
    else:
        wd = date.weekday()
    return [game for game, days in LOTTERY_SCHEDULE.items() if wd in days]


def get_draw_games_yesterday():
    """返回昨天开奖的彩种列表"""
    yesterday = datetime.now(CST) - timedelta(days=1)
    return get_draw_games(yesterday)


def get_draw_games_tomorrow():
    """返回明天开奖的彩种列表"""
    tomorrow = datetime.now(CST) + timedelta(days=1)
    return get_draw_games(tomorrow)


def _get_hit_numbers(predicted, actual):
    """返回命中的号码列表（排序）"""
    return sorted(set(predicted) & set(actual))


def _get_miss_numbers(predicted, actual):
    """返回预测中未命中的号码"""
    return sorted(set(predicted) - set(actual))

_BASE_DIR = os.environ.get('BASE_DIR', os.path.dirname(os.path.abspath(__file__)))
# 回测记录文件
BACKTEST_LOG = os.path.join(_BASE_DIR, 'lottery-backtest.json')
# 昨日推荐记录
PREDICTION_LOG = os.path.join(_BASE_DIR, 'lottery-predictions.json')


# ===== 硬编码Fallback数据（2026-04-18更新） =====

FALLBACK_SSQ = [
    {'period': '26045', 'reds': [4, 11, 15, 17, 24, 30], 'blue': 15},
    {'period': '26044', 'reds': [2, 14, 17, 18, 22, 30], 'blue': 1},
    {'period': '26043', 'reds': [6, 9, 14, 16, 25, 32], 'blue': 16},
    {'period': '26042', 'reds': [2, 7, 12, 19, 24, 31], 'blue': 10},
    {'period': '26041', 'reds': [2, 8, 10, 17, 19, 24], 'blue': 13},
    {'period': '26040', 'reds': [3, 4, 14, 22, 23, 33], 'blue': 4},
    {'period': '26039', 'reds': [8, 17, 18, 21, 25, 30], 'blue': 5},
    {'period': '26038', 'reds': [1, 2, 13, 23, 25, 27], 'blue': 5},
    {'period': '26037', 'reds': [11, 22, 27, 29, 31, 33], 'blue': 12},
    {'period': '26036', 'reds': [6, 10, 12, 15, 22, 28], 'blue': 8},
    {'period': '26035', 'reds': [2, 6, 12, 24, 25, 32], 'blue': 2},
    {'period': '26034', 'reds': [1, 3, 7, 13, 22, 23], 'blue': 7},
    {'period': '26033', 'reds': [3, 6, 13, 21, 28, 29], 'blue': 6},
    {'period': '26032', 'reds': [1, 3, 11, 18, 31, 33], 'blue': 2},
    {'period': '26031', 'reds': [3, 10, 12, 13, 18, 33], 'blue': 8},
    {'period': '26030', 'reds': [10, 11, 14, 19, 22, 24], 'blue': 4},
    {'period': '26029', 'reds': [6, 19, 22, 23, 28, 31], 'blue': 5},
    {'period': '26028', 'reds': [2, 6, 9, 17, 25, 28], 'blue': 15},
]

FALLBACK_DLT = [
    {'period': '26044', 'front': [3, 8, 22, 26, 29], 'back': [7, 10]},
    {'period': '26043', 'front': [8, 12, 14, 19, 22], 'back': [11, 12]},
    {'period': '26042', 'front': [2, 7, 13, 19, 24], 'back': [3, 8]},
    {'period': '26041', 'front': [6, 12, 13, 21, 34], 'back': [8, 9]},
    {'period': '26040', 'front': [9, 11, 20, 26, 27], 'back': [6, 9]},
    {'period': '26039', 'front': [9, 11, 20, 26, 27], 'back': [6, 9]},  # 🔴 v6.2补缺失
    {'period': '26038', 'front': [8, 17, 21, 33, 35], 'back': [6, 7]},
    {'period': '26037', 'front': [7, 12, 13, 28, 32], 'back': [6, 8]},
    {'period': '26036', 'front': [4, 7, 16, 26, 32], 'back': [5, 8]},
    {'period': '26035', 'front': [2, 22, 30, 33, 34], 'back': [8, 12]},
    {'period': '26034', 'front': [11, 12, 25, 26, 27], 'back': [8, 11]},
    {'period': '26033', 'front': [3, 5, 7, 9, 18], 'back': [2, 10]},
    {'period': '26032', 'front': [3, 4, 19, 26, 32], 'back': [1, 12]},
    {'period': '26031', 'front': [6, 8, 22, 29, 34], 'back': [5, 7]},
    {'period': '26030', 'front': [2, 13, 22, 28, 34], 'back': [5, 12]},
    {'period': '26029', 'front': [3, 5, 17, 33, 35], 'back': [5, 7]},
    {'period': '26028', 'front': [15, 27, 29, 30, 34], 'back': [1, 10]},
    {'period': '26027', 'front': [9, 10, 11, 12, 16], 'back': [1, 11]},
    {'period': '26026', 'front': [10, 11, 22, 26, 32], 'back': [1, 8]},
]

FALLBACK_QXC = [
    {'period': '26042', 'digits': [6, 5, 1, 8, 1, 3, 6]},
    {'period': '26041', 'digits': [7, 9, 1, 1, 4, 9, 1]},
    {'period': '26040', 'digits': [0, 7, 7, 1, 8, 7, 4]},
    {'period': '26039', 'digits': [0, 6, 6, 2, 5, 2, 1]},
    {'period': '26038', 'digits': [0, 7, 1, 3, 0, 2, 1]},
    {'period': '26037', 'digits': [9, 9, 6, 9, 4, 0, 1]},
    {'period': '26036', 'digits': [2, 8, 8, 9, 7, 9, 8]},
    {'period': '26035', 'digits': [7, 4, 2, 7, 2, 7, 2]},
    {'period': '26034', 'digits': [3, 9, 9, 1, 5, 3, 5]},
    {'period': '26033', 'digits': [1, 8, 9, 1, 9, 3, 1]},
    {'period': '26032', 'digits': [3, 1, 6, 4, 4, 5, 1]},
    {'period': '26031', 'digits': [6, 8, 9, 5, 2, 2, 1]},
    {'period': '26030', 'digits': [1, 9, 8, 1, 5, 9, 1]},
    {'period': '26029', 'digits': [1, 4, 0, 4, 3, 2, 1]},
    {'period': '26028', 'digits': [7, 9, 8, 0, 1, 1, 6]},
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
}


# ===== 期望期号计算（用于验证数据新鲜度）=====

def _get_expected_ssq_period():
    """根据当前日期估算双色球最新期号（用于数据新鲜度验证）
    双色球每周二、四、日开奖，一年约153期
    🔴 注意：此为估算值，实际期号由彩票中心分配，可能有调整
    """
    now = datetime.now(CST)
    year_start = datetime(2026, 1, 1, tzinfo=CST)
    if now < year_start:
        return 26001
    # 简单估算：自1月1日起每天约0.43期（3期/7天）
    days_passed = (now - year_start).days
    estimated = 26001 + int(days_passed * 3 / 7)
    return estimated

def _get_expected_dlt_period():
    """根据当前日期估算大乐透最新期号
    大乐透每周一、三、六开奖
    """
    now = datetime.now(CST)
    year_start = datetime(2026, 1, 1, tzinfo=CST)
    if now < year_start:
        return 26001
    days_passed = (now - year_start).days
    estimated = 26001 + int(days_passed * 3 / 7)
    return estimated


# ===== 数据抓取 =====

def fetch_ssq_history(periods=15):
    print(f"\n[双色球] 开始抓取，目标 {periods} 期...")
    min_required = min(periods, 3)  # 🔴 修复：回测只请求1期时，不能要求>=3
    # 源1: datachart.500.com
    result = _fetch_ssq_500com(periods)
    if result and len(result) >= min_required:
        print(f"[双色球] ✅ datachart.500.com 成功: {len(result)} 期")
        return result
    # 源2: cjcp.cn
    print("[双色球] 尝试备用源 cjcp.cn...")
    result = _fetch_ssq_cjcp(periods)
    if result and len(result) >= min_required:
        print(f"[双色球] ✅ cjcp.cn 成功: {len(result)} 期")
        return result
    # 源3: kaijiang.500.com 单页
    print("[双色球] 尝试备用源 kaijiang.500.com...")
    result = _fetch_ssq_kaijiang500(periods)
    if result and len(result) >= min_required:
        print(f"[双色球] ✅ kaijiang.500.com 成功: {len(result)} 期")
        return result
    # 🟢 v6.2: 网络抓到少量数据也比纯硬编码好（与QXC逻辑一致）
    if result and len(result) >= 1:
        print(f"[双色球] 网络抓取到{len(result)}期，补充硬编码数据")
        fallback = [f for f in FALLBACK_SSQ if not any(f['period'] == r['period'] for r in result)]
        merged = result + fallback[:periods - len(result)]
        return merged
    print("[双色球] ⚠️ 所有网络源失败，使用硬编码数据")
    return FALLBACK_SSQ[:periods]

def fetch_dlt_history(periods=15):
    print(f"\n[大乐透] 开始抓取，目标 {periods} 期...")
    min_required = min(periods, 3)  # 🔴 修复：回测只请求1期时，不能要求>=3
    # 源1: datachart.500.com
    result = _fetch_dlt_500com(periods)
    if result and len(result) >= min_required:
        print(f"[大乐透] ✅ datachart.500.com 成功: {len(result)} 期")
        return result
    # 源2: cjcp.cn
    print("[大乐透] 尝试备用源 cjcp.cn...")
    result = _fetch_dlt_cjcp(periods)
    if result and len(result) >= min_required:
        print(f"[大乐透] ✅ cjcp.cn 成功: {len(result)} 期")
        return result
    # 源3: kaijiang.500.com 单页
    print("[大乐透] 尝试备用源 kaijiang.500.com...")
    result = _fetch_dlt_kaijiang500(periods)
    if result and len(result) >= min_required:
        print(f"[大乐透] ✅ kaijiang.500.com 成功: {len(result)} 期")
        return result
    # 🟢 v6.2: 网络抓到少量数据也比纯硬编码好（与SSQ/QXC逻辑一致）
    if result and len(result) >= 1:
        print(f"[大乐透] 网络抓取到{len(result)}期，补充硬编码数据")
        fallback = [f for f in FALLBACK_DLT if not any(f['period'] == r['period'] for r in result)]
        merged = result + fallback[:periods - len(result)]
        return merged
    print("[大乐透] ⚠️ 所有网络源失败，使用硬编码数据")
    return FALLBACK_DLT[:periods]

def fetch_qxc_history(periods=15):
    min_required = min(periods, 3)  # 🔴 修复：回测只请求1期时，不能要求>=3
    result = _fetch_qxc_500com(periods)
    if result and len(result) >= min_required:
        return result
    result = _fetch_qxc_cjcp(periods)
    if result and len(result) >= min_required:
        return result
    # 🔴 网络抓到少量数据也比硬编码好（硬编码会过时）
    if result and len(result) >= 1:
        print(f"[七星彩] 网络抓取到{len(result)}期，补充硬编码数据")
        fallback = [f for f in FALLBACK_QXC if not any(f['period'] == r['period'] for r in result)]
        return result + fallback[:periods - len(result)]
    print("[七星彩] 网络抓取失败，使用硬编码数据")
    return FALLBACK_QXC[:periods]


def _scrapling_fallback_get(url, referer='', timeout=15):
    """🟢 v7.2: scrapling降级请求 — 当requests被封/超时时自动启用
    优先用Fetcher（curl_cffi+反指纹），失败则用DynamicFetcher（Playwright）
    """
    if not _SCRAPLING_AVAILABLE:
        return None
    try:
        # 方案1: Fetcher（快，反指纹）
        fetcher = _ScraplingFetcher(auto_match=False)
        page = fetcher.get(url, headers={'Referer': referer} if referer else {})
        if page and page.status == 200:
            return page.body.decode('gb2312', errors='replace') if isinstance(page.body, bytes) else page.body
    except Exception as e:
        print(f"[scrapling-Fetcher] 失败: {type(e).__name__}: {str(e)[:80]}")
    try:
        # 方案2: DynamicFetcher（Playwright驱动，能跑JS）
        fetcher2 = _ScraplingDynamic()
        page2 = fetcher2.fetch(url, referer=referer if referer else None)
        if page2 and page2.status == 200:
            return page2.body.decode('gb2312', errors='replace') if isinstance(page2.body, bytes) else page2.body
    except Exception as e:
        print(f"[scrapling-DynamicFetcher] 失败: {type(e).__name__}: {str(e)[:80]}")
    return None

def _fetch_ssq_500com(periods, retries=3):
    """双色球历史数据 - datachart 页面（带重试）"""
    for attempt in range(retries):
        try:
            ts = int(time.time())
            url = f'https://datachart.500.com/ssq/history/newinc/history.php?t={ts}'
            print(f"[双色球-500] 请求 (尝试{attempt+1}/{retries}): {url}")
            resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://datachart.500.com/ssq/history/'}, timeout=15)
            print(f"[双色球-500] 状态码: {resp.status_code}, 长度: {len(resp.text)}")
            if resp.status_code != 200:
                print(f"[双色球-500] HTTP错误: {resp.status_code}")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None
            resp.encoding = 'gb2312'
            result = _parse_ssq_html(resp.text, periods)
            if result and len(result) > 0:
                latest_period = result[0]['period']
                print(f"[双色球-500] 获取到期号: {latest_period}")
                expected_min = _get_expected_ssq_period() - 8  # 🔴 放宽容差，避免误判
                if int(latest_period) < expected_min:
                    print(f"[双色球-500] 警告: 数据过期，期望至少 {expected_min}")
                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    return None
                return result
            else:
                print(f"[双色球-500] 解析结果为空")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None
        except Exception as e:
            import traceback
            print(f"[双色球-500] 抓取失败 (尝试{attempt+1}/{retries}): {type(e).__name__}: {e}")
            if attempt < retries - 1:
                time.sleep(2)
                continue
            print(f"[双色球-500] 堆栈: {traceback.format_exc()[:200]}")
            return None
    # 🟢 v7.2: scrapling降级 — requests全部失败后自动启用
    print("[双色球-500] requests失败，尝试scrapling降级...")
    html = _scrapling_fallback_get(url, referer='https://datachart.500.com/ssq/history/')
    if html:
        result = _parse_ssq_html(html, periods)
        if result and len(result) > 0:
            print(f"[双色球-500] ✅ scrapling降级成功: {len(result)} 期")
            return result
    print("[双色球-500] scrapling降级也失败")
    return None

def _fetch_dlt_500com(periods, retries=3):
    """大乐透历史数据 - datachart 页面（带重试）"""
    for attempt in range(retries):
        try:
            ts = int(time.time())
            url = f'https://datachart.500.com/dlt/history/newinc/history.php?t={ts}'
            print(f"[大乐透-500] 请求 (尝试{attempt+1}/{retries}): {url}")
            resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://datachart.500.com/dlt/history/'}, timeout=15)
            print(f"[大乐透-500] 状态码: {resp.status_code}, 长度: {len(resp.text)}")
            if resp.status_code != 200:
                print(f"[大乐透-500] HTTP错误: {resp.status_code}")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None
            resp.encoding = 'gb2312'
            result = _parse_dlt_html(resp.text, periods)
            if result and len(result) > 0:
                latest_period = result[0]['period']
                print(f"[大乐透-500] 获取到期号: {latest_period}")
                expected_min = _get_expected_dlt_period() - 8  # 🔴 放宽容差，避免误判
                if int(latest_period) < expected_min:
                    print(f"[大乐透-500] 警告: 数据过期，期望至少 {expected_min}")
                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    return None
                return result
            else:
                print(f"[大乐透-500] 解析结果为空")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None
        except Exception as e:
            import traceback
            print(f"[大乐透-500] 抓取失败 (尝试{attempt+1}/{retries}): {type(e).__name__}: {e}")
            if attempt < retries - 1:
                time.sleep(2)
                continue
            print(f"[大乐透-500] 堆栈: {traceback.format_exc()[:200]}")
            return None
    # 🟢 v7.2: scrapling降级
    print("[大乐透-500] requests失败，尝试scrapling降级...")
    html = _scrapling_fallback_get(url, referer='https://datachart.500.com/dlt/history/')
    if html:
        result = _parse_dlt_html(html, periods)
        if result and len(result) > 0:
            print(f"[大乐透-500] ✅ scrapling降级成功: {len(result)} 期")
            return result
    print("[大乐透-500] scrapling降级也失败")
    return None

def _fetch_qxc_500com(periods):
    """七星彩：datachart历史页已404，改用kaijiang单期页面逐期抓取"""
    try:
        results = []
        # 先从开奖主页获取最新期号列表
        index_url = 'https://kaijiang.500.com/qxc.shtml'
        resp = requests.get(index_url, headers=HEADERS, timeout=15)
        resp.encoding = 'gb2312'
        # 提取期号
        period_list = re.findall(r'qxc/(\d{5})\.shtml', resp.text)
        if not period_list:
            print("[七星彩-500] 主页未找到期号列表")
            return None

        # 去重保序
        seen = set()
        unique_periods = []
        for p in period_list:
            if p not in seen:
                seen.add(p)
                unique_periods.append(p)

        for period in unique_periods[:periods]:
            try:
                page_url = f'https://kaijiang.500.com/shtml/qxc/{period}.shtml'
                page_resp = requests.get(page_url, headers=HEADERS, timeout=10)
                page_resp.encoding = 'gb2312'
                # 提取号码：class含ball的标签里的单个数字
                digits = re.findall(r'class="[^"]*ball[^"]*"[^>]*>(\d)<', page_resp.text)
                if len(digits) >= 7:
                    results.append({'period': period, 'digits': [int(d) for d in digits[:7]]})
            except Exception:
                continue

        return results if results else None
    except Exception as e:
        print(f"[七星彩-500] 抓取失败: {e}")
        return None

def _fetch_ssq_cjcp(periods):
    try:
        url = f'https://www.cjcp.cn/kaijiang/ssq/{periods}qi.html'
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        return _parse_ssq_html(resp.text, periods)
    except Exception as e:
        print(f"[双色球-cjcp] 抓取失败: {e}")
        return None

def _fetch_dlt_cjcp(periods):
    try:
        url = f'https://www.cjcp.cn/kaijiang/dlt/{periods}qi.html'
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        return _parse_dlt_html(resp.text, periods)
    except Exception as e:
        print(f"[大乐透-cjcp] 抓取失败: {e}")
        return None

def _fetch_qxc_cjcp(periods):
    try:
        url = f'https://www.cjcp.cn/kaijiang/qxc/{periods}qi.html'
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        return _parse_qxc_html(resp.text, periods)
    except Exception as e:
        print(f"[七星彩-cjcp] 抓取失败: {e}")
        return None


def _fetch_ssq_kaijiang500(periods):
    """备用：kaijiang.500.com 双色球单页抓取"""
    try:
        # 先获取最新期号列表（跟随重定向）
        index_url = 'https://kaijiang.500.com/ssq.shtml'
        print(f"[双色球-kaijiang] 请求主页: {index_url}")
        resp = requests.get(index_url, headers=HEADERS, timeout=15, allow_redirects=True)
        print(f"[双色球-kaijiang] 状态码: {resp.status_code}, 最终URL: {resp.url}")
        resp.encoding = 'gb2312'
        # 尝试多种期号格式
        period_list = re.findall(r'ssq/(\d{5})\.shtml', resp.text)
        if not period_list:
            # 尝试从链接中提取
            period_list = re.findall(r'(\d{5})(?:\.shtml|/)</a>', resp.text)
        if not period_list:
            print(f"[双色球-kaijiang] 未找到期号列表，响应长度: {len(resp.text)}")
            return None
        # 去重保序
        seen = set()
        unique_periods = []
        for p in period_list:
            if p not in seen:
                seen.add(p)
                unique_periods.append(p)
        results = []
        for period in unique_periods[:periods]:
            try:
                page_url = f'https://kaijiang.500.com/shtml/ssq/{period}.shtml'
                page_resp = requests.get(page_url, headers=HEADERS, timeout=10)
                page_resp.encoding = 'gb2312'
                # 提取红球和蓝球
                balls = re.findall(r'class="ball_red">(\d+)</span>', page_resp.text)
                blue_match = re.search(r'class="ball_blue">(\d+)</span>', page_resp.text)
                if len(balls) >= 6 and blue_match:
                    results.append({
                        'period': period,
                        'reds': [int(balls[i]) for i in range(6)],
                        'blue': int(blue_match.group(1))
                    })
            except Exception as e:
                continue
        print(f"[双色球-kaijiang] 获取到 {len(results)} 期")
        return results if results else None
    except Exception as e:
        print(f"[双色球-kaijiang] 抓取失败: {e}")
        return None


def _fetch_dlt_kaijiang500(periods):
    """备用：kaijiang.500.com 大乐透单页抓取"""
    try:
        index_url = 'https://kaijiang.500.com/dlt.shtml'
        print(f"[大乐透-kaijiang] 请求主页: {index_url}")
        resp = requests.get(index_url, headers=HEADERS, timeout=15)
        resp.encoding = 'gb2312'
        period_list = re.findall(r'dlt/(\d{5})\.shtml', resp.text)
        if not period_list:
            print("[大乐透-kaijiang] 未找到期号列表")
            return None
        seen = set()
        unique_periods = []
        for p in period_list:
            if p not in seen:
                seen.add(p)
                unique_periods.append(p)
        results = []
        for period in unique_periods[:periods]:
            try:
                page_url = f'https://kaijiang.500.com/shtml/dlt/{period}.shtml'
                page_resp = requests.get(page_url, headers=HEADERS, timeout=10)
                page_resp.encoding = 'gb2312'
                # 提取前区号码（class包含ball_red或ball_1）
                front_balls = re.findall(r'class="ball_red">(\d+)</span>', page_resp.text)
                # 提取后区号码（class包含ball_blue）
                back_balls = re.findall(r'class="ball_blue">(\d+)</span>', page_resp.text)
                if len(front_balls) >= 5 and len(back_balls) >= 2:
                    results.append({
                        'period': period,
                        'front': [int(front_balls[i]) for i in range(5)],
                        'back': [int(back_balls[i]) for i in range(2)]
                    })
            except Exception as e:
                continue
        print(f"[大乐透-kaijiang] 获取到 {len(results)} 期")
        return results if results else None
    except Exception as e:
        print(f"[大乐透-kaijiang] 抓取失败: {e}")
        return None


# ===== HTML解析 =====

def _parse_ssq_html(html, max_periods):
    results = []
    # 🔴 修复：500.com的HTML在期号前多了一个<td>（星期几），
    # 所以pattern1从期号直接开始已经匹配不到了
    # 改用更健壮的tr/td逐行解析
    tr_pattern = r'<tr[^>]*>(.*?)</tr>'
    for tr_match in re.findall(tr_pattern, html, re.DOTALL)[:100]:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_match, re.DOTALL)
        clean_tds = [re.sub(r'<[^>]+>', '', td).strip() for td in tds]
        # 找到期号位置：5位数字且以26开头
        period_idx = None
        for i, td in enumerate(clean_tds):
            if re.match(r'^2\d{4}$', td):
                period_idx = i
                break
        if period_idx is None:
            continue
        # 期号后6个td=红球，再1个td=蓝球
        if len(clean_tds) >= period_idx + 8:
            try:
                period = clean_tds[period_idx]
                reds = [int(clean_tds[period_idx + j]) for j in range(1, 7)]
                blue = int(clean_tds[period_idx + 7])
                # 验证红球范围1-33，蓝球1-16
                if all(1 <= r <= 33 for r in reds) and 1 <= blue <= 16:
                    results.append({'period': period, 'reds': reds, 'blue': blue})
            except (ValueError, IndexError):
                continue
    return results[:max_periods] if results else None

def _parse_dlt_html(html, max_periods):
    results = []
    tr_pattern = r'<tr[^>]*>(.*?)</tr>'
    for tr_match in re.findall(tr_pattern, html, re.DOTALL)[:100]:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_match, re.DOTALL)
        clean_tds = [re.sub(r'<[^>]+>', '', td).strip() for td in tds]
        period_idx = None
        for i, td in enumerate(clean_tds):
            if re.match(r'^2\d{4}$', td):
                period_idx = i
                break
        if period_idx is None:
            continue
        # 期号后5个td=前区，再2个td=后区
        if len(clean_tds) >= period_idx + 8:
            try:
                period = clean_tds[period_idx]
                front = [int(clean_tds[period_idx + j]) for j in range(1, 6)]
                back = [int(clean_tds[period_idx + j]) for j in range(6, 8)]
                if all(1 <= f <= 35 for f in front) and all(1 <= b <= 12 for b in back):
                    results.append({'period': period, 'front': front, 'back': back})
            except (ValueError, IndexError):
                continue
    return results[:max_periods] if results else None

def _parse_qxc_html(html, max_periods):
    results = []
    tr_pattern = r'<tr[^>]*>(.*?)</tr>'
    for tr_match in re.findall(tr_pattern, html, re.DOTALL)[:100]:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_match, re.DOTALL)
        clean_tds = [re.sub(r'<[^>]+>', '', td).strip() for td in tds]
        period_idx = None
        for i, td in enumerate(clean_tds):
            if re.match(r'^2\d{4}$', td):
                period_idx = i
                break
        if period_idx is None:
            continue
        # 期号后7个td=7位数字
        if len(clean_tds) >= period_idx + 8:
            try:
                period = clean_tds[period_idx]
                digits = [int(clean_tds[period_idx + j]) for j in range(1, 8)]
                if all(0 <= d <= 9 for d in digits):
                    results.append({'period': period, 'digits': digits})
            except (ValueError, IndexError):
                continue
    return results[:max_periods] if results else None


# ===== 🟢 加权统计算法（v5新增 — 方案A） =====

class WeightedAnalyzer:
    """
    基于多维度加权的号码分析器。
    不依赖AI，纯数学计算，结果喂给AI作为参考。

    维度：
    1. 频率加权：近N期出现次数越多权重越高
    2. 遗漏加权：连续未出现期数越多，回补权重越高
    3. 近期趋势加权：最近5期比前10期出现多的号加分（趋势上升）
    4. 连号分析：统计连号对出现频率
    5. 和值分析：统计和值范围
    6. 🟢 v6.7: 邻号加分 — 上期开出的号±1获得额外权重（球机机械偏差）
    """

    def __init__(self, history, weight_freq=None, weight_miss=None, weight_trend=None, weight_zone=None, gamma=None):
        self.history = history
        # 🟢 v6.3: gamma可配置，默认0.88，可从配置文件读取
        config = _load_weight_config()
        self.w_freq = weight_freq if weight_freq is not None else config.get('freq', 0.30)
        self.w_miss = weight_miss if weight_miss is not None else config.get('miss', 0.25)
        self.w_trend = weight_trend if weight_trend is not None else config.get('trend', 0.25)
        self.w_zone = weight_zone if weight_zone is not None else config.get('zone', 0.20)
        self.gamma = gamma if gamma is not None else config.get('gamma', 0.88)  # 🟢 v6.3
        # 🔴 v6.8: 邻号bonus和冷号注权重也从配置读取
        # 🔴 分前后区：前区/红球miss主导，后区/蓝球/七星彩cycle主导
        self.neighbor_bonus = config.get('neighbor_bonus', 0.03)
        self.cold_miss_front = config.get('cold_miss_front', 0.40)
        self.cold_cycle_front = config.get('cold_cycle_front', 0.30)
        self.cold_freq_front = config.get('cold_freq_front', 0.30)
        self.cold_miss_back = config.get('cold_miss_back', 0.30)
        self.cold_cycle_back = config.get('cold_cycle_back', 0.40)
        self.cold_freq_back = config.get('cold_freq_back', 0.30)

    def _calc_weights(self, number_range, extract_fn, total_periods):
        """通用加权计算
        extract_fn(history_item) -> list of numbers
        🟢 v6.3: 频率改为指数衰减，近期数据权重提升2-3倍，解冻号码粘滞
        """
        # 🟢 v6.3: 指数衰减频率统计 — γ=0.88，近1期权重≈远期5倍
        # 等权旧方式: freq = Counter(); freq.update(extract_fn(d)) — 15期前和1期前等权
        # 新方式: freq[n] = Σ(γ^idx × 出现标记) / Σ(γ^idx)，idx=0为最近期
        gamma = self.gamma  # 🟢 v6.3: 可配置衰减因子
        decay_freq = Counter()
        decay_total = 0.0
        for idx, d in enumerate(self.history):
            w = gamma ** idx  # idx=0最近期权重最大
            decay_total += w
            for n in extract_fn(d):
                decay_freq[n] += w

        # 等权频率也保留（供冷号注等需要原始频率的场景）
        raw_freq = Counter()
        for d in self.history:
            raw_freq.update(extract_fn(d))

        # 遗漏值：连续未出现期数
        miss = {}
        # 🟢 v6.2: 平均遗漏间隔（历史平均隔几期出现一次）
        avg_miss_interval = {}
        for n in number_range:
            count = 0
            # 当前遗漏
            for d in self.history:
                if n in extract_fn(d):
                    break
                count += 1
            miss[n] = count
            # 平均遗漏间隔：找所有出现位置，计算间隔均值
            positions = [i for i, d in enumerate(self.history) if n in extract_fn(d)]
            if len(positions) >= 2:
                intervals = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
                avg_miss_interval[n] = sum(intervals) / len(intervals)
            elif len(positions) == 1:
                avg_miss_interval[n] = positions[0] if positions[0] > 0 else len(self.history)
            else:
                avg_miss_interval[n] = len(self.history)  # 从未出现

        # 近期趋势：最近5期 vs 前10期
        recent = Counter()
        older = Counter()
        mid = min(5, len(self.history))
        for d in self.history[:mid]:
            recent.update(extract_fn(d))
        for d in self.history[mid:mid*2]:
            older.update(extract_fn(d))

        # 🟢 P1修复：分区平衡真正融入权重
        # 🔴 Bug3修复：zone_size统一，与analyze_ssq(n//11)/analyze_dlt(n//12)一致
        # _calc_weights是通用函数，需要根据number_range动态计算正确的zone边界
        if max(number_range) == 33:  # 双色球红球1-33，分区1-11/12-22/23-33
            zone_size = 11
        elif max(number_range) == 35:  # 大乐透前区1-35，分区1-12/13-24/25-35
            zone_size = 12
        else:  # 七星彩每位0-9，分区0-3/4-6/7-9
            zone_size = (max(number_range) + 1) // 3
        zone_counts = [0, 0, 0]
        for d in self.history[:5]:
            for n in extract_fn(d):
                z = min(n // zone_size, 2)
                zone_counts[z] += 1
        total_z = sum(zone_counts) or 1
        zone_expected = total_z / 3  # 均衡期望

        # 计算综合权重
        weights = {}
        for n in number_range:
            f = decay_freq.get(n, 0) / max(decay_total, 1)  # 🟢 v6.3: 指数衰减频率
            m = math.log1p(miss.get(n, 0)) / math.log1p(total_periods)
            t = (recent.get(n, 0) - older.get(n, 0)) / max(mid, 1)
            # 🔴 Bug4修复：趋势权重逻辑修正
            # t > 0 表示近5期比前10期出现多（上升趋势），应给正权重
            # t < 0 表示近5期比前10期出现少（下降趋势），应给负权重或零权重
            # 之前abs(t)给下降趋势正权重是错误的
            if t > 0:
                t_weight = t * 1.0  # 🟢 v6.2: 上升趋势（对称，无先验偏好）
            elif t < 0:
                t_weight = t * 0.8  # 🟢 v6.2: 下降趋势轻微衰减（0.8而非0.5，不过度惩罚）
            else:
                t_weight = 0

            # 🟢 分区平衡：偏低区的号加分，偏高区的号减分
            z = min(n // zone_size, 2)
            z_factor = max(0, (zone_expected - zone_counts[z]) / max(zone_expected, 1))

            # 🟢 v6.2: 遗漏周期加分 — 当前遗漏 > 平均遗漏间隔时，说明"到期"
            avg_interval = avg_miss_interval.get(n, total_periods)
            overdue_bonus = 0
            if avg_interval > 0 and miss.get(n, 0) > avg_interval:
                overdue_bonus = min((miss.get(n, 0) - avg_interval) / max(avg_interval, 1) * 0.15, 0.3)

            # 🟢 v6.7: 邻号加分 — 上期开出的号±1获得微弱加分
            # 球机有机械偏差，相邻号码统计相关性略高
            # 只看最近1期开出的号，邻号获得0.03的bonus（约权重1-2%的提升）
            neighbor_bonus = 0
            if self.history:
                last_drawn = set(extract_fn(self.history[0]))
                if (n - 1) in last_drawn or (n + 1) in last_drawn:
                    neighbor_bonus = self.neighbor_bonus

            # 🟢 v7.1: 号码相关性bonus — 某号出现时，历史中与其同区/连号的号也出现概率更高
            # 计算条件概率：P(n出现 | 上期某号出现) vs P(n出现)
            correlation_bonus = 0
            if self.history:
                last_drawn_set = set(extract_fn(self.history[0]))
                # 统计历史中条件概率
                n_appear = raw_freq.get(n, 0)  # n出现次数
                n_total = len(self.history)
                if n_total >= 5 and n_appear > 0:
                    p_n = n_appear / n_total  # P(n)
                    # 计算 P(n | 上期出现m) 对上期每个m
                    for m in last_drawn_set:
                        if m == n:
                            continue
                        # 🔴 v7.2 修复：条件概率 P(n | 上期m) 正确计算
                        # 逻辑：若第i期出现m，统计第i+1期是否出现n
                        co_occur = 0
                        m_occur = 0
                        for i in range(len(self.history) - 1):
                            if m in extract_fn(self.history[i]):
                                m_occur += 1
                                if n in extract_fn(self.history[i + 1]):
                                    co_occur += 1
                        # 🔴 v7.2 修复：在for i循环外、for m循环内计算lift
                        if m_occur >= 3:  # 至少3次共现才有统计意义
                            p_n_given_m = co_occur / m_occur
                            lift = p_n_given_m / max(p_n, 0.01)
                            if lift > 1.2:  # 提升20%以上才算有信号
                                correlation_bonus += min((lift - 1.0) * 0.02, 0.06)

            weights[n] = (
                self.w_freq * f +
                self.w_miss * m +
                self.w_trend * t_weight +
                self.w_zone * z_factor +  # 🟢 zone终于生效
                overdue_bonus +  # 🟢 v6.2: 遗漏周期加分
                neighbor_bonus +  # 🟢 v6.7: 邻号加分
                correlation_bonus  # 🟢 v7.1: 号码相关性加分
            )


        return weights, raw_freq, miss, avg_miss_interval  # 🟢 v6.3: raw_freq替代decay_freq返回

    def analyze_ssq(self):
        """双色球加权分析"""
        total = len(self.history)

        # 红球权重
        red_weights, red_freq, red_miss, red_avg_interval = self._calc_weights(
            range(1, 34), lambda d: d['reds'], total
        )

        # 蓝球权重
        blue_weights, blue_freq, blue_miss, blue_avg_interval = self._calc_weights(
            range(1, 17), lambda d: [d['blue']], total
        )

        # 🔴 Bug3修复：zone_size统一为11（与_calc_weights中max=33时的zone_size一致）
        # 红球分区权重（1-11/12-22/23-33三区）
        zone_balance = [0, 0, 0]
        for d in self.history[:5]:
            for n in d['reds']:
                zone = min(n // 11, 2)
                zone_balance[zone] += 1

        # 和值范围
        sums = [sum(d['reds']) for d in self.history]
        avg_sum = sum(sums) / len(sums)

        # 连号统计
        consec_count = 0
        for d in self.history[:10]:
            reds = sorted(d['reds'])
            for i in range(len(reds)-1):
                if reds[i+1] - reds[i] == 1:
                    consec_count += 1
        consec_rate = consec_count / min(10, len(self.history))

        # 按权重排序
        hot_reds = sorted(red_weights.items(), key=lambda x: x[1], reverse=True)
        miss_reds = sorted(red_weights.items(), key=lambda x: red_miss.get(x[0], 0), reverse=True)
        hot_blues = sorted(blue_weights.items(), key=lambda x: x[1], reverse=True)

        # 🔴 v7.3: 和值约束检查 — 选中的6个红球的和值是否接近历史均值
        # 注意：实际选号在调用处完成，此处仅提供avg_sum供参考
        # 调用处应使用：abs(sum(selected_6_reds) - avg_sum) < avg_sum * 0.15 来判断是否接近

        return {
            'red_weights': hot_reds,
            'red_freq': red_freq,
            'red_miss': red_miss,
            'red_avg_interval': red_avg_interval,  # 🟢 v6.2: 平均遗漏间隔
            'blue_weights': hot_blues,
            'blue_freq': blue_freq,
            'blue_miss': blue_miss,
            'blue_avg_interval': blue_avg_interval,  # 🟢 v6.2
            'zone_balance': zone_balance,
            'avg_sum': avg_sum,  # 历史平均和值
            'sum_value_guidance': f"选中6个红球的和值应接近{avg_sum:.1f}（偏差<15%）",
            'consec_rate': consec_rate,
            'total_periods': total,
        }

    def analyze_dlt(self):
        """大乐透加权分析"""
        total = len(self.history)

        front_weights, front_freq, front_miss, front_avg_interval = self._calc_weights(
            range(1, 36), lambda d: d['front'], total
        )
        back_weights, back_freq, back_miss, back_avg_interval = self._calc_weights(
            range(1, 13), lambda d: d['back'], total
        )

        # 🔴 Bug3修复：zone_size统一为12（与_calc_weights中max=35时的zone_size一致）
        zone_balance = [0, 0, 0]
        for d in self.history[:5]:
            for n in d['front']:
                zone = min(n // 12, 2)
                zone_balance[zone] += 1

        sums = [sum(d['front']) for d in self.history]
        avg_sum = sum(sums) / len(sums)

        consec_count = 0
        for d in self.history[:10]:
            fronts = sorted(d['front'])
            for i in range(len(fronts)-1):
                if fronts[i+1] - fronts[i] == 1:
                    consec_count += 1
        consec_rate = consec_count / min(10, len(self.history))

        hot_fronts = sorted(front_weights.items(), key=lambda x: x[1], reverse=True)
        hot_backs = sorted(back_weights.items(), key=lambda x: x[1], reverse=True)

        return {
            'front_weights': hot_fronts,
            'front_freq': front_freq,
            'front_miss': front_miss,
            'front_avg_interval': front_avg_interval,  # 🟢 v6.2: 平均遗漏间隔
            'back_weights': hot_backs,
            'back_freq': back_freq,
            'back_miss': back_miss,
            'back_avg_interval': back_avg_interval,  # 🟢 v6.2
            'zone_balance': zone_balance,
            'avg_sum': avg_sum,  # 历史平均和值
            # 🔴 v7.3: 和值约束引导 — 前区5个号+后区2个号的和值应接近历史均值
            'sum_value_guidance': f"前区5个号的和值应接近{avg_sum:.1f}（偏差<15%），后区2个号的和值应接近{avg_sum*2/36:.1f}",
            'consec_rate': consec_rate,
            'total_periods': total,
        }

    def analyze_qxc(self):
        """七星彩加权分析（逐位统计）"""
        total = len(self.history)
        pos_data = []
        for pos in range(7):
            weights, freq, miss, avg_interval = self._calc_weights(
                range(10), lambda d: [d['digits'][pos]], total
            )
            hot = sorted(weights.items(), key=lambda x: x[1], reverse=True)
            pos_data.append({
                'weights': hot,
                'freq': freq,
                'miss': miss,
                'avg_interval': avg_interval,  # 🟢 v6.2: 平均遗漏间隔
            })
        return {'positions': pos_data, 'total_periods': total}

    def _smart_blue_select(self, analysis, mode='hot', exclude=None):
        """🔴 双色球蓝球智能选号（1-16）
        mode: 'hot'权重优先 / 'mix'均衡 / 'miss'遗漏回补
        exclude: set of blue numbers to skip (for dispersion across bets)
        """
        blue_weight_dict = dict(analysis['blue_weights'])
        blue_miss = analysis['blue_miss']
        blue_freq = analysis['blue_freq']
        exclude = exclude or set()

        scores = {}
        for n in range(1, 17):
            if n in exclude:
                continue  # 🟢 v6.2: 跳过已选蓝球
            weight_score = blue_weight_dict.get(n, 0)
            miss_val = blue_miss.get(n, 0)
            if miss_val >= 10:
                miss_score = 3.0
            elif miss_val >= 6:
                miss_score = 2.5
            elif miss_val >= 3:
                miss_score = 1.5
            elif miss_val == 0:
                miss_score = 1.0
            else:
                miss_score = 0.8
            freq_score = min(blue_freq.get(n, 0), 4) / 2.0

            if mode == 'hot':
                # 🟢 v6.5: hot模式加周期信号作负向 — 到期号反而不热
                blue_avg_interval = analysis.get('blue_avg_interval', {}).get(n, 10)
                cycle_signal = min(miss_val / max(blue_avg_interval, 1), 2.0)
                # cycle_signal>1=到期(冷号特征), 热模式应减分
                hot_penalty = max(0, (cycle_signal - 1.0)) * 1.5  # 到期号扣分
                scores[n] = weight_score * 0.4 + freq_score * 0.4 + miss_score * 0.2 - hot_penalty
            elif mode == 'mix':
                scores[n] = weight_score * 0.3 + freq_score * 0.3 + miss_score * 0.4
            elif mode == 'miss':
                # 🟢 v6.8: 冷号评分 — 权重从配置读取
                blue_avg_interval = analysis.get('blue_avg_interval', {}).get(n, 10)
                cycle_signal = min(miss_val / max(blue_avg_interval, 1), 2.0)  # >1=到期, <1=未到
                scores[n] = miss_score * self.cold_miss_back + cycle_signal * self.cold_cycle_back + freq_score * self.cold_freq_back

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[0][0] if ranked else 1

    def _select_blues_with_shape(self, analysis, n_blues=4):
        """🟢 v6.3: 蓝球整体选号 — 强制奇偶2:2、大小2:2形态约束
        先算每个蓝球综合得分，再在满足形态约束的组合中选总分最高的
        """
        blue_weight_dict = dict(analysis['blue_weights'])
        blue_miss = analysis['blue_miss']
        blue_freq = analysis['blue_freq']
        blue_avg_interval = analysis.get('blue_avg_interval', {})

        # 每个蓝球的综合得分
        scores = {}
        for n in range(1, 17):
            w = blue_weight_dict.get(n, 0)
            miss_val = blue_miss.get(n, 0)
            if miss_val >= 10:
                miss_score = 3.0
            elif miss_val >= 6:
                miss_score = 2.5
            elif miss_val >= 3:
                miss_score = 1.5
            elif miss_val == 0:
                miss_score = 1.0
            else:
                miss_score = 0.8
            freq_score = min(blue_freq.get(n, 0), 4) / 2.0
            scores[n] = w * 0.3 + freq_score * 0.3 + miss_score * 0.4  # 均衡评分

        # 按得分排序
        sorted_blues = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 🟢 v6.3: 形态约束 — 奇偶2:2 + 大小2:2
        # 如果4个蓝球不能满足约束，放宽为3:1或2:2
        best_combo = None
        best_total = -1
        # 从TOP8中选4个，搜索满足约束的最佳组合
        candidates = sorted_blues[:8]
        from itertools import combinations
        for combo in combinations([n for n, s in candidates], n_blues):
            odds = sum(1 for n in combo if n % 2 == 1)  # 奇数个数
            bigs = sum(1 for n in combo if n >= 9)  # 大号个数(9-16)
            # 理想: 奇偶2:2, 大小2:2; 可接受: 3:1
            odd_ok = odds == 2 or odds == 3 or odds == 1
            big_ok = bigs == 2 or bigs == 3 or bigs == 1
            if odd_ok and big_ok:
                total = sum(scores[n] for n in combo)
                # 给接近2:2的组合加分
                shape_bonus = 0
                if odds == 2 and bigs == 2:
                    shape_bonus = 1.0  # 完美形态
                elif odds == 2 or bigs == 2:
                    shape_bonus = 0.5  # 一项完美
                total += shape_bonus
                if total > best_total:
                    best_total = total
                    best_combo = combo

        if best_combo:
            return list(best_combo)
        # 回退：取TOP4
        return [n for n, s in sorted_blues[:n_blues]]

    def _select_backs_distributed(self, analysis, n_pairs=4):
        """🟢 v6.3: 大乐透后区分散选号 — 4组后区8个号尽量不重复
        每组2个后区号(1-12)，4组共8个号最大覆盖
        """
        back_weight_dict = dict(analysis['back_weights'])
        back_miss = analysis['back_miss']
        back_freq = analysis['back_freq']

        # 每个后区号综合评分
        scores = {}
        for n in range(1, 13):
            w = back_weight_dict.get(n, 0)
            miss_val = back_miss.get(n, 0)
            if miss_val >= 10:
                miss_score = 3.0
            elif miss_val >= 6:
                miss_score = 2.5
            elif miss_val >= 3:
                miss_score = 1.5
            elif miss_val == 0:
                miss_score = 1.0
            else:
                miss_score = 0.8
            freq_score = min(back_freq.get(n, 0), 4) / 2.0
            scores[n] = w * 0.3 + freq_score * 0.3 + miss_score * 0.4

        sorted_nums = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 贪心分配：每组选2个最高分但未用过的号
        used = set()
        result = []
        for i in range(n_pairs):
            pair = []
            for n, s in sorted_nums:
                if n not in used:
                    pair.append(n)
                    used.add(n)
                if len(pair) == 2:
                    break
            # 奇偶约束：尽量一奇一偶
            if len(pair) == 2:
                odds = sum(1 for n in pair if n % 2 == 1)
                if odds == 2 or odds == 0:
                    # 全奇或全偶，尝试替换一个
                    for n, s in sorted_nums:
                        if n not in used and n not in pair and n % 2 != pair[0] % 2:
                            # 找到异偶的替换pair中同偶的那个
                            for j, p in enumerate(pair):
                                if p % 2 == pair[0] % 2:
                                    used.discard(pair[j])
                                    pair[j] = n
                                    used.add(n)
                                    break
                            break
            result.append(sorted(pair))

        # 补全不够的
        while len(result) < n_pairs:
            result.append([1, 2])

        return result

    def _shape_optimized_select(self, candidates, n_select, target_sum, target_odd, target_big, must_include=None, big_threshold=17):
        """🟢 v6.4: 形态优化选号 — 贪心搜索，支持大候选池
        candidates: 候选号码列表（支持20+个）
        n_select: 选几个号
        target_sum: 目标和值
        target_odd: 目标奇数个数
        target_big: 目标大号个数
        must_include: 必须包含的号码
        big_threshold: 大号阈值（SSQ=17, DLT=18）
        """
        must_include = must_include or []
        # 🟢 v6.4: 贪心搜索替代暴力枚举，支持20+候选
        # 策略：必须包含的号先加入，然后贪心添加最改善形态的号
        result = list(must_include)
        remaining = [n for n in candidates if n not in result]
        
        while len(result) < n_select and remaining:
            best_n = None
            best_score = -999
            for n in remaining:
                trial = sorted(result + [n])
                s = sum(trial)
                odd_count = sum(1 for x in trial if x % 2 == 1)
                big_count = sum(1 for x in trial if x >= big_threshold)
                # 评分：和值偏差 + 奇偶偏差 + 大小偏差
                sum_penalty = -abs(s - target_sum) / max(target_sum, 1) * 2.0
                odd_penalty = -abs(odd_count - target_odd) * 1.5
                big_penalty = -abs(big_count - target_big) * 1.5
                score = sum_penalty + odd_penalty + big_penalty
                if score > best_score:
                    best_score = score
                    best_n = n
            if best_n is not None:
                result.append(best_n)
                remaining.remove(best_n)
            else:
                break
        
        return sorted(result)

    def generate_recs_ssq(self, analysis, kelly_bias=0.0):
        """根据加权分析生成双色球推荐（纯数学，不依赖AI）
        🟢 v6.5: SSQ gamma降到0.85，蓝球16选1也稀疏需更快衰减
        """
        self.gamma = min(self.gamma, 0.85)
        # 追热：权重最高的6个红球 + 最高权重蓝球
        hot_reds = sorted([n for n, w in analysis['red_weights'][:10]][:6])
        hot_blue = analysis['blue_weights'][0][0]

        # 回补：遗漏值最高的6个红球 + 最高遗漏蓝球
        miss_reds = sorted([(n, analysis['red_miss'].get(n, 0)) for n in range(1, 34)],
                          key=lambda x: x[1], reverse=True)[:6]
        miss_red_nums = sorted([n for n, m in miss_reds])
        miss_blues = sorted([(n, analysis['blue_miss'].get(n, 0)) for n in range(1, 17)],
                           key=lambda x: x[1], reverse=True)
        miss_blue = miss_blues[0][0]

        # 综合：频率中等+遗漏中等 的平衡选号
        mid_reds = sorted([(n, analysis['red_freq'].get(n, 0) + analysis['red_miss'].get(n, 0))
                          for n in range(1, 34)], key=lambda x: x[1], reverse=True)
        # 取频率3-6次的号码（中等热度）
        mid_pool = [n for n, f in mid_reds if 2 <= analysis['red_freq'].get(n, 0) <= 5][:6]
        if len(mid_pool) < 6:
            mid_pool = sorted([n for n, w in analysis['red_weights'][3:12]][:6])
        mid_blue = analysis['blue_weights'][1][0] if len(analysis['blue_weights']) > 1 else 1

        # 🟢 v6.1: Kelly驱动核心注 — kelly_bias调节热号/冷号比例
        # kelly_bias > 0 → 核心注偏热号（追求命中率，Kelly高时值得投）
        # kelly_bias < 0 → 核心注偏冷号（搏大奖小注，Kelly低时小博大）
        # kelly_bias = 0 → 默认均衡（纯权重排名）
        red_weight_dict = dict(analysis['red_weights'])
        all_pool = []
        for n in range(1, 34):
            w = red_weight_dict.get(n, 0)
            all_pool.append((n, w, analysis['red_freq'].get(n, 0), analysis['red_miss'].get(n, 0)))

        if kelly_bias > 0:
            # 🔥 Kelly高：核心注偏热 — 归一化频率+权重排序
            max_freq = max(x[2] for x in all_pool) or 1
            max_weight = max(x[1] for x in all_pool) or 1
            all_pool.sort(key=lambda x: (x[2]/max_freq) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
            strategy_tag = Strategy.CORE_HOT
        elif kelly_bias < 0:
            # ❄️ Kelly低：核心注偏冷 — 归一化遗漏+权重排序
            max_miss = max(x[3] for x in all_pool) or 1
            max_weight = max(x[1] for x in all_pool) or 1
            all_pool.sort(key=lambda x: (x[3]/max_miss) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
            strategy_tag = Strategy.CORE_COLD
        else:
            # ⚖️ 默认：纯权重排序
            all_pool.sort(key=lambda x: x[1], reverse=True)
            strategy_tag = Strategy.CORE_WEIGHTED

        core_reds_by_weight = [n for n, w, f, m in all_pool[:6]]
        core_reds = sorted(core_reds_by_weight)
        # 🟢 v6.4: 蓝球按策略需求分配 — 核心注得热蓝，冷号注得周期回补蓝
        core_blue = self._smart_blue_select(analysis, mode='hot' if kelly_bias >= 0 else 'miss')
        ext1_blue = self._smart_blue_select(analysis, mode='mix', exclude={core_blue})
        ext2_blue = self._smart_blue_select(analysis, mode='mix', exclude={core_blue, ext1_blue})  # 🟢 v6.5: 扩展2红球偏热配均衡蓝
        cold_blue = self._smart_blue_select(analysis, mode='miss', exclude={core_blue, ext1_blue, ext2_blue})

        # 🔴 Bug修复：扩展注保留的是权重最高的号，不是号码最小的号
        # 扩展1：保留权重最高的4号 + 替换权重最低的2号
        ext1_keep = sorted(core_reds_by_weight[:4])  # 权重TOP4
        ext1_new = sorted([n for n, w, f, m in all_pool[6:8] if n not in ext1_keep][:2])
        ext1_reds = sorted(ext1_keep + ext1_new)
        # 🟢 v6.4: 扩展2 — 形态模拟选号（从TOP20贪心搜索和值/奇偶/大小最优组合）
        target_sum = analysis.get('avg_sum', 100)
        target_odd = 3
        target_big = 3

        top20 = [n for n, w, f, m in all_pool[:20]]
        ext2_reds = self._shape_optimized_select(top20, 6, target_sum, target_odd, target_big,
                                                  core_reds_by_weight[:2])  # 🟢 v6.5: 只锁TOP2，留4号自由调形态

        # 🟢 v6.8: 冷号注红球 — 权重从配置读取，auto_evolve可调
        # 🔴 v7.2: 冷号注排除核心注+扩展1+扩展2已选号码，避免重复
        used_reds = set(core_reds) | set(ext1_reds) | set(ext2_reds)
        cold_scores = []
        red_avg_interval = analysis.get('red_avg_interval', {})
        for n in range(1, 34):
            miss_val = analysis['red_miss'].get(n, 0)
            miss_score = min(miss_val / 10.0, 3.0)
            # 周期回补信号：当前遗漏 / 平均遗漏间隔，>1说明到期
            avg_interval = red_avg_interval.get(n, 15)
            cycle_signal = min(miss_val / max(avg_interval, 1), 2.0)
            f = analysis['red_freq'].get(n, 0)
            f_score = min(f / 3.0, 1.5)
            score = miss_score * self.cold_miss_front + cycle_signal * self.cold_cycle_front + f_score * self.cold_freq_front
            cold_scores.append((n, score))
        cold_scores.sort(key=lambda x: x[1], reverse=True)
        cold_red_nums = sorted([n for n, s in cold_scores if n not in used_reds][:6])

        return [
            {'reds': core_reds, 'blue': core_blue, 'strategy': strategy_tag},  # 🟢 v6.1: Kelly驱动
            {'reds': ext1_reds, 'blue': ext1_blue, 'strategy': Strategy.EXT1_WEIGHTED},
            {'reds': ext2_reds, 'blue': ext2_blue, 'strategy': Strategy.EXT2_WEIGHTED},
            {'reds': cold_red_nums, 'blue': cold_blue, 'strategy': Strategy.COLD_MISS},  # 🟢 v6
        ]

    def _smart_back_select(self, analysis, count=2, mode='hot', exclude=None):
        """🔴 大乐透后区智能选号（v2优化版）
        综合考虑：权重+遗漏+奇偶+大小+振幅，而非仅靠权重排名
        exclude: set of back numbers already used (for dispersion)

        mode:
          - 'hot': 热号为主（核心注）
          - 'mix': 热号+遗漏回补（扩展1）
          - 'miss': 遗漏回补为主（扩展2）
        """
        back_weight_dict = dict(analysis['back_weights'])
        back_miss = analysis['back_miss']
        back_freq = analysis['back_freq']

        # 综合评分：权重(40%) + 遗漏回补力(30%) + 近期活跃度(30%)
        scores = {}
        exclude = exclude or set()
        for n in range(1, 13):
            if n in exclude:
                continue
            weight_score = back_weight_dict.get(n, 0)
            # 遗漏回补力：遗漏越大，回补概率越高（但超过10期可能偏冷）
            miss_val = back_miss.get(n, 0)
            if miss_val >= 8:
                miss_score = 3.0  # 深度遗漏，强回补信号
            elif miss_val >= 5:
                miss_score = 2.5
            elif miss_val >= 3:
                miss_score = 1.5
            elif miss_val == 0:
                miss_score = 1.0  # 刚出，回补力弱
            else:
                miss_score = 0.8

            # 近期活跃度：近5期出现次数
            freq_score = min(back_freq.get(n, 0), 4) / 2.0

            if mode == 'hot':
                # 核心注：权重+活跃度优先
                scores[n] = weight_score * 0.4 + freq_score * 0.4 + miss_score * 0.2
            elif mode == 'mix':
                # 扩展1：均衡
                scores[n] = weight_score * 0.3 + freq_score * 0.3 + miss_score * 0.4
            elif mode == 'miss':
                # 🟢 v6.8: 冷号评分 — 权重从配置读取
                back_avg_interval = analysis.get('back_avg_interval', {}).get(n, 10)
                cycle_signal = min(miss_val / max(back_avg_interval, 1), 2.0)
                scores[n] = miss_score * self.cold_miss_back + cycle_signal * self.cold_cycle_back + freq_score * self.cold_freq_back

        # 按评分排序
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 🔴 奇偶约束：优先选"一奇一偶"组合（占比47%，最高频）
        # 🔴 大小约束：优先选"一小一大"组合（占比60%，最高频）
        best_pair = None
        best_score = -1

        # 从TOP6候选中搜索最佳奇偶+大小组合
        candidates = [n for n, s in ranked[:6]]
        for i in range(len(candidates)):
            for j in range(i+1, len(candidates)):
                pair = sorted([candidates[i], candidates[j]])
                # 奇偶检查
                odd_count = sum(1 for n in pair if n % 2 == 1)
                # 大小检查（1-6小，7-12大）
                big_count = sum(1 for n in pair if n >= 7)

                bonus = 0
                # 奇偶加分：一奇一偶最优先
                if odd_count == 1:
                    bonus += 0.5
                # 大小加分：一小一大最优先
                if big_count == 1:
                    bonus += 0.5
                # 连号微调（出现概率17%，不算高但值得覆盖）
                if abs(pair[0] - pair[1]) == 1:
                    bonus += 0.2

                pair_score = scores[candidates[i]] + scores[candidates[j]] + bonus
                if pair_score > best_score:
                    best_score = pair_score
                    best_pair = pair

        if best_pair:
            return best_pair

        # 降级：直接取评分前2
        return sorted([ranked[0][0], ranked[1][0]])

    def generate_recs_dlt(self, analysis, kelly_bias=0.0):
        """根据加权分析生成大乐透推荐
        🟢 v6.1: Kelly驱动选号 — kelly_bias越高越偏热号，越低越偏冷号
        🔴 v6.8: 删除gamma=0.85 clamp，由GEPA统一管理gamma
        """
        # 🟢 v6.1: Kelly驱动核心注
        front_weight_dict = dict(analysis['front_weights'])
        all_pool = []
        for n in range(1, 36):
            w = front_weight_dict.get(n, 0)
            all_pool.append((n, w, analysis['front_freq'].get(n, 0), analysis['front_miss'].get(n, 0)))

        if kelly_bias > 0:
            max_freq = max(x[2] for x in all_pool) or 1
            max_weight = max(x[1] for x in all_pool) or 1
            all_pool.sort(key=lambda x: (x[2]/max_freq) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
            strategy_tag = Strategy.CORE_HOT
        elif kelly_bias < 0:
            max_miss = max(x[3] for x in all_pool) or 1
            max_weight = max(x[1] for x in all_pool) or 1
            all_pool.sort(key=lambda x: (x[3]/max_miss) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
            strategy_tag = Strategy.CORE_COLD
        else:
            all_pool.sort(key=lambda x: x[1], reverse=True)
            strategy_tag = Strategy.CORE_WEIGHTED

        core_front_by_weight = [n for n, w, f, m in all_pool[:5]]
        core_front = sorted(core_front_by_weight)

        # 🟢 v6.5: 后区按策略需求分配 + exclude分散
        core_back = self._smart_back_select(analysis, mode='hot' if kelly_bias >= 0 else 'miss')
        core_back_set = set(core_back)
        ext1_back = self._smart_back_select(analysis, mode='mix', exclude=core_back_set)
        ext1_back_set = core_back_set | set(ext1_back)
        ext2_back = self._smart_back_select(analysis, mode='miss', exclude=ext1_back_set)
        ext2_back_set = ext1_back_set | set(ext2_back)
        cold_back_nums = self._smart_back_select(analysis, mode='miss', exclude=ext2_back_set)

        # 扩展1：保留权重TOP3 + 替换权重最低的2个
        ext1_keep = sorted(core_front_by_weight[:3])
        ext1_new = sorted([n for n, w, f, m in all_pool[5:7] if n not in ext1_keep][:2])
        ext1_front = sorted(ext1_keep + ext1_new)

        # 🟢 v6.4: DLT扩展2 — 形态模拟选号（从TOP20贪心搜索）
        target_sum_dlt = analysis.get('avg_sum', 80)
        target_odd_dlt = 3
        target_big_dlt = 3
        top20_dlt = [n for n, w, f, m in all_pool[:20]]
        ext2_front = self._shape_optimized_select(top20_dlt, 5, target_sum_dlt, target_odd_dlt, target_big_dlt,
                                                   core_front_by_weight[:1], big_threshold=18)  # 🟢 v6.5: 只锁TOP1

        # 🟢 v6.8: 冷号注前区 — 权重从配置读取，auto_evolve可调
        # 🔴 v7.2: 冷号注排除核心注+扩展1+扩展2已选号码，避免重复
        used_front = set(core_front) | set(ext1_front) | set(ext2_front)
        cold_front_scores = []
        front_avg_interval = analysis.get('front_avg_interval', {})
        for n in range(1, 36):
            miss_val = analysis['front_miss'].get(n, 0)
            miss_score = min(miss_val / 10.0, 3.0)
            avg_interval = front_avg_interval.get(n, 15)
            cycle_signal = min(miss_val / max(avg_interval, 1), 2.0)
            f = analysis['front_freq'].get(n, 0)
            f_score = min(f / 3.0, 1.5)
            score = miss_score * self.cold_miss_front + cycle_signal * self.cold_cycle_front + f_score * self.cold_freq_front
            cold_front_scores.append((n, score))
        cold_front_scores.sort(key=lambda x: x[1], reverse=True)
        cold_front_nums = sorted([n for n, s in cold_front_scores if n not in used_front][:5])

        return [
            {'front': core_front, 'back': core_back, 'strategy': strategy_tag},  # 🟢 v6.1: Kelly驱动
            {'front': ext1_front, 'back': ext1_back, 'strategy': Strategy.EXT1_WEIGHTED},
            {'front': ext2_front, 'back': ext2_back, 'strategy': Strategy.EXT2_WEIGHTED},
            {'front': cold_front_nums, 'back': cold_back_nums, 'strategy': Strategy.COLD_MISS},  # 🟢 v6
        ]

    def generate_recs_qxc(self, analysis, kelly_bias=0.0):
        """根据加权分析生成七星彩推荐
        🟢 v6.2: 添加kelly_bias驱动 + 冷号注（与SSQ/DLT对齐）
        """
        # 🟢 v6.2: Kelly驱动核心注偏向
        if kelly_bias > 0:
            strategy_tag = Strategy.CORE_HOT
            # 追热：每位优先选频率最高的数字
            core_digits = []
            for pd in analysis['positions']:
                # 频率权重排序：QXC weights是(n,w)对，用freq辅助排序
                weight_dict = dict(pd['weights'])
                freq_dict = pd.get('freq', {})
                sorted_by_freq = sorted(pd['weights'], key=lambda x: (freq_dict.get(x[0], 0), x[1]), reverse=True)
                core_digits.append(sorted_by_freq[0][0] if sorted_by_freq else pd['weights'][0][0])
        elif kelly_bias < 0:
            strategy_tag = Strategy.CORE_COLD
            # 搏冷：每位优先选遗漏最高的数字
            core_digits = []
            for pd in analysis['positions']:
                miss_sorted = sorted(pd['miss'].items(), key=lambda x: x[1], reverse=True)
                # 用遗漏+权重综合评分
                weight_dict = dict(pd['weights'])
                best = None
                best_score = -1
                for n, m in miss_sorted[:5]:
                    w = weight_dict.get(n, 0)
                    score = m * 0.6 + w * 4.0 * 0.4  # 遗漏60% + 权重40%
                    if score > best_score:
                        best_score = score
                        best = n
                core_digits.append(best if best is not None else pd['weights'][0][0])
        else:
            strategy_tag = Strategy.CORE_WEIGHTED
            core_digits = [pd['weights'][0][0] for pd in analysis['positions']]

        # 扩展1：保留核心4位 + 替换3位(权重第2)
        ext1_digits = list(core_digits)
        for i in range(3, 7):
            ext1_digits[i] = analysis['positions'][i]['weights'][1][0] if len(analysis['positions'][i]['weights']) > 1 else core_digits[i]
        # 扩展2：保留核心2位 + 替换5位(遗漏最高)
        ext2_digits = list(core_digits)
        for i in range(2, 7):
            top_miss = sorted(analysis['positions'][i]['miss'].items(), key=lambda x: x[1], reverse=True)
            ext2_digits[i] = top_miss[0][0] if top_miss else core_digits[i]

        # 🟢 v6.8: 七星彩冷号注 — 权重从配置读取，auto_evolve可调
        cold_digits = list(core_digits)
        for i in range(7):
            pd = analysis['positions'][i]
            miss_sorted = sorted(pd['miss'].items(), key=lambda x: x[1], reverse=True)
            freq_dict = pd.get('freq', {})
            avg_interval_dict = pd.get('avg_interval', {})
            best = None
            best_score = -1
            max_miss = max(m for _, m in miss_sorted) if miss_sorted else 1
            for n, m in miss_sorted[:5]:
                f = freq_dict.get(n, 0)
                # 🔴 v6.8: 统一miss_score尺度为[0,3.0]，与SSQ/DLT一致
                miss_score = min(m / 10.0, 3.0)
                # 周期回补信号
                avg_interval = avg_interval_dict.get(n, 5)
                cycle_signal = min(m / max(avg_interval, 1), 2.0)
                f_score = min(f / 3.0, 1.5)
                score = miss_score * self.cold_miss_back + cycle_signal * self.cold_cycle_back + f_score * self.cold_freq_back
                if score > best_score:
                    best_score = score
                    best = n
            cold_digits[i] = best if best is not None else (miss_sorted[0][0] if miss_sorted else core_digits[i])

        recs = [
            {'digits': core_digits, 'strategy': strategy_tag},  # 🟢 v6.2: Kelly驱动
            {'digits': ext1_digits, 'strategy': Strategy.EXT1_WEIGHTED},
            {'digits': ext2_digits, 'strategy': Strategy.EXT2_WEIGHTED},
            {'digits': cold_digits, 'strategy': Strategy.COLD_MISS},  # 🟢 v6.2: QXC也加冷号注
        ]
        return recs


# ===== 数据格式化（给刘海蟾看） =====

def _format_ssq_for_ai(history, kelly_bias=0.0):
    lines = []
    for draw in history:
        reds_str = ' '.join(f'{n:02d}' for n in draw['reds'])
        lines.append(f"第{draw['period']}期: 红球 {reds_str} | 蓝球 {draw['blue']:02d}")
    red_counter = Counter()
    blue_counter = Counter()
    for draw in history:
        red_counter.update(draw['reds'])
        blue_counter.update([draw['blue']])
    stats = [
        f"红球频率(高→低): {', '.join(f'{n}({c}次)' for n, c in red_counter.most_common())}",
        f"蓝球频率(高→低): {', '.join(f'{n}({c}次)' for n, c in blue_counter.most_common())}",
    ]
    oe = []
    for draw in history:
        odd = sum(1 for n in draw['reds'] if n % 2 == 1)
        oe.append(f"{odd}:{6-odd}")
    stats.append(f"奇偶比: {', '.join(oe)}")
    spans = [max(d['reds']) - min(d['reds']) for d in history]
    stats.append(f"跨度: {', '.join(str(s) for s in spans)} (均值{sum(spans)/len(spans):.0f})")

    # 🟢 v5新增：加权分析数据
    wa = WeightedAnalyzer(history)
    analysis = wa.analyze_ssq()

    # 遗漏值TOP10
    miss_sorted = sorted(analysis['red_miss'].items(), key=lambda x: x[1], reverse=True)
    stats.append(f"🔴红球遗漏TOP10: {', '.join(f'{n}({m}期未出)' for n, m in miss_sorted[:10])}")
    blue_miss_sorted = sorted(analysis['blue_miss'].items(), key=lambda x: x[1], reverse=True)
    stats.append(f"🔴蓝球遗漏: {', '.join(f'{n}({m}期未出)' for n, m in blue_miss_sorted[:5])}")

    # 加权号码池（追热/回补/综合各6个）
    weighted_recs = wa.generate_recs_ssq(analysis, kelly_bias=kelly_bias)  # 🟢 v6.1: Kelly驱动
    for rec in weighted_recs:
        reds_str = ' '.join(f'{n:02d}' for n in rec['reds'])
        stats.append(f"📊{rec['strategy']}: {reds_str} + 蓝{rec['blue']:02d}")

    # 分区平衡
    zb = analysis['zone_balance']
    total_z = sum(zb) or 1
    stats.append(f"📊近5期分区比: 一区{zb[0]}({zb[0]*100//total_z}%) 二区{zb[1]}({zb[1]*100//total_z}%) 三区{zb[2]}({zb[2]*100//total_z}%)")

    # 和值与连号
    stats.append(f"📊和值均值: {analysis['avg_sum']:.0f}, 连号概率: {analysis['consec_rate']:.1f}对/期")

    return '\n'.join(lines) + '\n\n' + '\n'.join(stats)

def _format_dlt_for_ai(history, kelly_bias=0.0):
    lines = []
    for draw in history:
        front_str = ' '.join(f'{n:02d}' for n in draw['front'])
        back_str = ' '.join(f'{n:02d}' for n in draw['back'])
        lines.append(f"第{draw['period']}期: 前区 {front_str} | 后区 {back_str}")
    front_counter = Counter()
    back_counter = Counter()
    for draw in history:
        front_counter.update(draw['front'])
        back_counter.update(draw['back'])
    stats = [
        f"前区频率(高→低): {', '.join(f'{n}({c}次)' for n, c in front_counter.most_common())}",
        f"后区频率(高→低): {', '.join(f'{n}({c}次)' for n, c in back_counter.most_common())}",
    ]
    oe = []
    for draw in history:
        odd = sum(1 for n in draw['front'] if n % 2 == 1)
        oe.append(f"{odd}:{5-odd}")
    stats.append(f"奇偶比: {', '.join(oe)}")
    spans = [max(d['front']) - min(d['front']) for d in history]
    stats.append(f"跨度: {', '.join(str(s) for s in spans)} (均值{sum(spans)/len(spans):.0f})")

    # 🟢 v5新增：加权分析数据
    wa = WeightedAnalyzer(history)
    analysis = wa.analyze_dlt()

    miss_sorted = sorted(analysis['front_miss'].items(), key=lambda x: x[1], reverse=True)
    stats.append(f"🔴前区遗漏TOP10: {', '.join(f'{n}({m}期未出)' for n, m in miss_sorted[:10])}")
    back_miss_sorted = sorted(analysis['back_miss'].items(), key=lambda x: x[1], reverse=True)
    stats.append(f"🔴后区遗漏: {', '.join(f'{n}({m}期未出)' for n, m in back_miss_sorted[:5])}")

    weighted_recs = wa.generate_recs_dlt(analysis, kelly_bias=kelly_bias)  # 🟢 v6.1: Kelly驱动
    for rec in weighted_recs:
        front_str = ' '.join(f'{n:02d}' for n in rec['front'])
        back_str = ' '.join(f'{n:02d}' for n in rec['back'])
        stats.append(f"📊{rec['strategy']}: {front_str} + 后{back_str}")

    zb = analysis['zone_balance']
    total_z = sum(zb) or 1
    stats.append(f"📊近5期分区比: 一区{zb[0]}({zb[0]*100//total_z}%) 二区{zb[1]}({zb[1]*100//total_z}%) 三区{zb[2]}({zb[2]*100//total_z}%)")
    stats.append(f"📊和值均值: {analysis['avg_sum']:.0f}, 连号概率: {analysis['consec_rate']:.1f}对/期")

    return '\n'.join(lines) + '\n\n' + '\n'.join(stats)

def _format_qxc_for_ai(history, kelly_bias=0.0):
    lines = []
    for draw in history:
        digits_str = ' '.join(str(n) for n in draw['digits'])
        lines.append(f"第{draw['period']}期: {digits_str}")
    stats = []
    for pos in range(7):
        counter = Counter(d['digits'][pos] for d in history)
        stats.append(f"第{pos+1}位频率(高→低): {', '.join(f'{n}({c}次)' for n, c in counter.most_common())}")

    # 🟢 v5新增：加权分析
    wa = WeightedAnalyzer(history)
    analysis = wa.analyze_qxc()

    for i, pd in enumerate(analysis['positions']):
        miss_sorted = sorted(pd['miss'].items(), key=lambda x: x[1], reverse=True)
        stats.append(f"🔴第{i+1}位遗漏TOP3: {', '.join(f'{n}({m}期未出)' for n, m in miss_sorted[:3])}")

    weighted_recs = wa.generate_recs_qxc(analysis, kelly_bias=kelly_bias)  # 🟢 v6.2: Kelly驱动
    for rec in weighted_recs:
        digits_str = ' '.join(str(n) for n in rec['digits'])
        stats.append(f"📊{rec['strategy']}: {digits_str}")

    return '\n'.join(lines) + '\n\n' + '\n'.join(stats)


# ===== 回测系统 =====

def _load_predictions():
    """加载昨日推荐记录"""
    try:
        with open(PREDICTION_LOG, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ===== 🟢 P1: 回测驱动权重自适应 =====

# 权重配置文件（持久化，回测可修改）
WEIGHT_CONFIG_FILE = os.path.join(_BASE_DIR, 'weight-config.json')

DEFAULT_WEIGHT_CONFIG = {
    # 🔴 核心注权重（4维度归一化）
    'freq': 0.30,
    'miss': 0.25,
    'trend': 0.25,
    'zone': 0.20,
    # 🔴 冷号注权重 — 前区/红球（遗漏主导，回测26020-26045验证）
    'cold_miss_front': 0.40,
    'cold_cycle_front': 0.30,
    'cold_freq_front': 0.30,
    # 🔴 冷号注权重 — 后区/蓝球/七星彩（周期主导，回测验证cycle信号更重要）
    'cold_miss_back': 0.30,
    'cold_cycle_back': 0.40,
    'cold_freq_back': 0.30,
    # 🔴 邻号加分
    'neighbor_bonus': 0.03,
    # 🔴 衰减因子
    'gamma': 0.88,
    # 🔴 版本与日志
    'version': 1,
    'algo_version': 'v7.1',
    'evolution_log': [],   # 🔴 GEPA进化日志：重大逻辑变更
}


def _load_weight_config():
    """加载权重配置"""
    try:
        with open(WEIGHT_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_WEIGHT_CONFIG)


def _save_weight_config(config):
    """保存权重配置"""
    with open(WEIGHT_CONFIG_FILE, 'w') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def adjust_weights_from_backtest():
    """
    🔴 v6.8 GEPA自动进化：回测→诊断→调参→版本更新
    不再只看"哪个策略赢"，而是：
    1. 诊断冷号注 vs 核心注的命中差距
    2. 诊断邻号bonus是否有效
    3. 诊断gamma衰减是否合理
    4. 自动微调 + 记录进化日志
    5. 重大变更自动升版本号
    """
    backtest_log = _load_backtest()
    config = _load_weight_config()
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # 只用最近7天回测数据（当前版本回测才有意义）
    # 🔴 v7.1: 扩大到最近15天回测数据（之前7天+至少2条，样本太小无统计意义）
    recent = [bt for bt in backtest_log[-15:]
              if bt.get('backtest_method') == 'current_version']
    if len(recent) < 1:
        return None  # 无回测数据

    # 🔴 v7.1: 统计显著性检验 — 样本不足时不调参
    total_strategy_games = 0
    for bt in recent:
        for game in ['ssq', 'dlt', 'qxc']:
            if game not in bt:
                continue
            total_strategy_games += len(bt[game].get('hits', []))
    MIN_GAMES_FOR_ADJUST = 6   # 至少6个策略-彩种样本才微调
    MIN_GAMES_FOR_MAJOR = 20   # 至少20个样本才允许重大调参
    if total_strategy_games < MIN_GAMES_FOR_ADJUST:
        print(f"[GEPA] 样本不足({total_strategy_games}<{MIN_GAMES_FOR_ADJUST})，暂不进化")
        return None

    # ===== 诊断：统计各策略命中情况 =====
    strategy_stats = defaultdict(lambda: {'hits': [], 'games': 0})
    neighbor_hits = []  # 邻号是否命中
    for bt in recent:
        for game in ['ssq', 'dlt', 'qxc']:
            if game not in bt:
                continue
            bt_data = bt[game]
            for h in bt_data.get('hits', []):
                s = h.get('strategy', '')
                total = h.get('total', 0)
                strategy_stats[s]['hits'].append(total)
                strategy_stats[s]['games'] += 1
                # 诊断邻号：核心注的推荐号里有几个是上期邻号？
                # （暂时用命中数据推断，后续可加专门追踪）

    # 映射策略名
    mapped_stats = defaultdict(lambda: {'hits': [], 'games': 0})
    for name, data in strategy_stats.items():
        mapped_name = STRATEGY_MAP.get(name, name)
        mapped_stats[mapped_name]['hits'].extend(data['hits'])
        mapped_stats[mapped_name]['games'] += data['games']

    # ===== 决策：计算各维度调整 =====
    changes = []
    old_config = {k: config.get(k, DEFAULT_WEIGHT_CONFIG.get(k)) for k in
                  ['freq', 'miss', 'trend', 'zone',
                   'cold_miss_front', 'cold_cycle_front', 'cold_freq_front',
                   'cold_miss_back', 'cold_cycle_back', 'cold_freq_back',
                   'neighbor_bonus', 'gamma']}

    # 🔴 v7.1: 统计显著性检验 — Welch t-test
    core_hits_list = mapped_stats.get(Strategy.CORE, {}).get('hits', [0])
    cold_hits_list = mapped_stats.get(Strategy.COLD_MISS, {}).get('hits', [0])
    core_avg = sum(core_hits_list) / max(len(core_hits_list), 1)
    cold_avg = sum(cold_hits_list) / max(len(cold_hits_list), 1)

    def _welch_ttest(a, b):
        """Welch t-test，返回t值和是否显著(p<0.10)"""
        import math
        n1, n2 = len(a), len(b)
        if n1 < 2 or n2 < 2:
            return 0, False
        m1, m2 = sum(a)/n1, sum(b)/n2
        v1 = sum((x-m1)**2 for x in a)/(n1-1) if n1 > 1 else 0
        v2 = sum((x-m2)**2 for x in b)/(n2-1) if n2 > 1 else 0
        se = math.sqrt(v1/n1 + v2/n2) if (v1/n1 + v2/n2) > 0 else 1e-9
        t = (m1 - m2) / se
        # 简化：|t|>1.65 ≈ p<0.10（单侧），对样本量小的情况足够保守
        return t, abs(t) > 1.65

    t_val, is_significant = _welch_ttest(core_hits_list, cold_hits_list)
    if not is_significant and len(core_hits_list) + len(cold_hits_list) < 15:
        # 样本小且差异不显著：降低调参力度（步长减半）
        step = 0.01  # 微调步长（保守）
        print(f"[GEPA] 差异不显著(t={t_val:.2f})，保守微调")
    else:
        step = 0.02  # 微调步长（正常）
        if is_significant:
            print(f"[GEPA] 差异显著(t={t_val:.2f})，正常调参")

    if cold_avg > core_avg + 0.3:
        # 冷号注明显优于核心注 → 加大冷号遗漏权重
        config['cold_miss_front'] = min(0.60, config.get('cold_miss_front', 0.40) + step)
        config['cold_miss_back'] = min(0.50, config.get('cold_miss_back', 0.30) + step * 0.5)
        changes.append(f"冷号注命中{cold_avg:.1f}>核心注{core_avg:.1f} → cold_miss_front +{step}, cold_miss_back +{step*0.5}")
    elif core_avg > cold_avg + 0.5:
        # 核心注明显优于冷号注 → 加大周期权重（周期回补信号更有效）
        config['cold_cycle_front'] = min(0.50, config.get('cold_cycle_front', 0.30) + step * 0.5)
        config['cold_cycle_back'] = min(0.60, config.get('cold_cycle_back', 0.40) + step * 0.5)
        changes.append(f"核心注命中{core_avg:.1f}>冷号注{cold_avg:.1f} → cold_cycle +{step*0.5}")

    # 2️⃣ 归一化冷号注权重（🔴 下限保护0.05，防止趋零）
    for suffix in ['front', 'back']:
        cm = config.get(f'cold_miss_{suffix}', 0.40 if suffix == 'front' else 0.30)
        cc = config.get(f'cold_cycle_{suffix}', 0.30 if suffix == 'front' else 0.40)
        cf = config.get(f'cold_freq_{suffix}', 0.30)
        cold_total = cm + cc + cf
        if cold_total > 0:
            config[f'cold_miss_{suffix}'] = round(cm / cold_total, 4)
            config[f'cold_cycle_{suffix}'] = round(cc / cold_total, 4)
            # 🔴 下限保护：cold_freq至少0.05
            config[f'cold_freq_{suffix}'] = max(0.05, round(1.0 - config[f'cold_miss_{suffix}'] - config[f'cold_cycle_{suffix}'], 4))
            # 归一化后重新校验
            total2 = config[f'cold_miss_{suffix}'] + config[f'cold_cycle_{suffix}'] + config[f'cold_freq_{suffix}']
            if total2 > 0:
                config[f'cold_miss_{suffix}'] = round(config[f'cold_miss_{suffix}'] / total2, 4)
                config[f'cold_cycle_{suffix}'] = round(config[f'cold_cycle_{suffix}'] / total2, 4)
                config[f'cold_freq_{suffix}'] = max(0, round(1.0 - config[f'cold_miss_{suffix}'] - config[f'cold_cycle_{suffix}'], 4))

    # 3️⃣ 核心注权重微调
    hot_wins = mapped_stats.get(Strategy.CORE, {}).get('games', 0)
    cold_wins = mapped_stats.get(Strategy.COLD_MISS, {}).get('games', 0)
    if hot_wins > cold_wins + 1 and core_avg >= cold_avg:
        config['freq'] = min(0.45, config.get('freq', 0.30) + step)
        config['miss'] = max(0.10, config.get('miss', 0.25) - step)
        changes.append(f"热号领先 → freq +{step}, miss -{step}")
    elif cold_wins > hot_wins + 1 and cold_avg >= core_avg:
        config['miss'] = min(0.45, config.get('miss', 0.25) + step)
        config['freq'] = max(0.10, config.get('freq', 0.30) - step)
        changes.append(f"冷号领先 → miss +{step}, freq -{step}")

    # 归一化核心注权重（🔴 下限保护zone≥0.05）
    f, m, t, z = config.get('freq', 0.30), config.get('miss', 0.25), config.get('trend', 0.25), config.get('zone', 0.20)
    total = f + m + t + z
    if total > 0:
        config['freq'] = round(f / total, 4)
        config['miss'] = round(m / total, 4)
        config['trend'] = round(t / total, 4)
        config['zone'] = max(0.05, round(1.0 - config['freq'] - config['miss'] - config['trend'], 4))
        # 归一化后重新校验
        total2 = config['freq'] + config['miss'] + config['trend'] + config['zone']
        if total2 > 0:
            config['freq'] = round(config['freq'] / total2, 4)
            config['miss'] = round(config['miss'] / total2, 4)
            config['trend'] = round(config['trend'] / total2, 4)
            config['zone'] = max(0, round(1.0 - config['freq'] - config['miss'] - config['trend'], 4))

    # 4️⃣ 邻号bonus调整 — 如果核心注命中率持续偏低，微增邻号bonus
    if core_avg < 0.8 and config.get('neighbor_bonus', 0.03) < 0.06:
        config['neighbor_bonus'] = min(0.06, config.get('neighbor_bonus', 0.03) + 0.005)
        changes.append(f"核心注命中偏低({core_avg:.1f}) → neighbor_bonus +0.005 → {config['neighbor_bonus']:.3f}")
    elif core_avg > 1.5 and config.get('neighbor_bonus', 0.03) > 0.01:
        config['neighbor_bonus'] = max(0.01, config.get('neighbor_bonus', 0.03) - 0.005)
        changes.append(f"核心注命中良好({core_avg:.1f}) → neighbor_bonus -0.005 → {config['neighbor_bonus']:.3f}")

    # 5️⃣ gamma调整 — 如果近期数据预测力下降，减小gamma（更重视远期稳定模式）
    if core_avg < 0.5 and config.get('gamma', 0.88) > 0.80:
        config['gamma'] = max(0.80, config.get('gamma', 0.88) - 0.01)
        changes.append(f"命中率极低 → gamma -0.01 → {config['gamma']:.2f}（更重视远期模式）")
    elif core_avg > 2.0 and config.get('gamma', 0.88) < 0.95:
        config['gamma'] = min(0.95, config.get('gamma', 0.88) + 0.01)
        changes.append(f"命中率很高 → gamma +0.01 → {config['gamma']:.2f}（更重视近期趋势）")

    if not changes:
        return None

    # ===== 版本更新 =====
    config['version'] = config.get('version', 1) + 1

    # 判断是否重大变更（任何参数变化≥0.04视为重大）
    # 🔴 v7.1: 样本不足时不允许重大变更，只允许微调
    is_major = False
    all_param_keys = ['freq', 'miss', 'trend', 'zone',
                      'cold_miss_front', 'cold_cycle_front', 'cold_freq_front',
                      'cold_miss_back', 'cold_cycle_back', 'cold_freq_back',
                      'neighbor_bonus', 'gamma']
    for key in all_param_keys:
        old_val = old_config.get(key, 0)
        new_val = config.get(key, 0)
        if abs(new_val - old_val) >= 0.04:
            if total_strategy_games >= MIN_GAMES_FOR_MAJOR:
                is_major = True
            else:
                # 🔴 v7.1: 样本不足时回退该参数变更到不超过0.03
                config[key] = old_val + (0.03 if new_val > old_val else -0.03)
                changes = [c for c in changes if key not in c]  # 移除相关变更说明
                changes.append(f"样本不足({total_strategy_games}<{MIN_GAMES_FOR_MAJOR})，{key}变更被限制为微调±0.03")
            break

    if is_major:
        # 🔴 修复版本号解析：用正则匹配，防止3段式或非数字格式
        import re
        algo_version = config.get('algo_version', 'v7.1')
        m = re.match(r'(v\d+)\.(\d+)', algo_version)
        if m:
            config['algo_version'] = f"{m.group(1)}.{int(m.group(2)) + 1}"
        else:
            config['algo_version'] = 'v6.9'

    # 进化日志
    # 🔴 v7.1: 清理旧版adjustments遗留字段
    config.pop('adjustments', None)
    config.pop('last_reset_date', None)
    evo_entry = {
        'date': today_str,
        'trigger': '回测驱动',
        'sample_size': total_strategy_games,
        't_test': {'t_value': round(t_val, 3), 'significant': is_significant},
        'changes': changes,
        'old_weights': {k: round(old_config.get(k, 0), 4) for k in all_param_keys},
        'new_weights': {k: round(config.get(k, 0), 4) for k in all_param_keys},
        'is_major': is_major,
        'algo_version': config.get('algo_version', 'v7.1'),
    }
    evo_log = config.get('evolution_log', [])
    evo_log.append(evo_entry)
    if len(evo_log) > 30:
        evo_log = evo_log[-30:]
    config['evolution_log'] = evo_log

    _save_weight_config(config)

    # 打印进化结果
    version_tag = config.get('algo_version', 'v7.1')
    major_tag = '🔴 重大更新' if is_major else '🟢 微调'
    print(f"[GEPA进化] {major_tag} → {version_tag}")
    for c in changes:
        print(f"  {c}")
    print(f"  核心注权重: freq={config['freq']:.2f} miss={config['miss']:.2f} trend={config['trend']:.2f} zone={config['zone']:.2f}")
    print(f"  冷号注(前区): miss={config['cold_miss_front']:.2f} cycle={config['cold_cycle_front']:.2f} freq={config['cold_freq_front']:.2f}")
    print(f"  冷号注(后区): miss={config['cold_miss_back']:.2f} cycle={config['cold_cycle_back']:.2f} freq={config['cold_freq_back']:.2f}")

    return config


# ===== 🟢 P2: Kelly仓位管理 =====

def kelly_fraction(estimated_hit_prob, odds):
    """
    Kelly公式：计算最优投注比例
    f* = (b*p - q) / b，其中b=赔率，p=估计胜率，q=1-p
    返回值：正数=建议投注比例，≤0=不建议投注
    """
    p = estimated_hit_prob
    q = 1 - p
    if odds <= 0 or p <= 0:
        return 0
    f = (odds * p - q) / odds
    return max(f, 0)


# 🟢 v6.2: 多奖级Kelly期望值（替代单一赔率）
PRIZE_TIERS = {
    'ssq': [
        # (命中条件, 奖金, 大致概率)
        # 6+1 一等奖 ≈ 500万, P ≈ 1/17,721,088
        {'name': '一等奖', 'prize': 5000000, 'prob': 1/17721088},
        # 6+0 二等奖 ≈ 20万, P ≈ 1/1,181,406
        {'name': '二等奖', 'prize': 200000, 'prob': 1/1181406},
        # 5+1 三等奖 ≈ 3000, P ≈ 1/135,078
        {'name': '三等奖', 'prize': 3000, 'prob': 1/135078},
        # 5+0/4+1 四等奖 ≈ 200, P ≈ 1/17,393
        {'name': '四等奖', 'prize': 200, 'prob': 1/17393},
        # 4+0/3+1 五等奖 ≈ 10, P ≈ 1/1,351
        {'name': '五等奖', 'prize': 10, 'prob': 1/1351},
        # 2+1/1+1/0+1 六等奖 ≈ 5, P ≈ 1/50
        {'name': '六等奖', 'prize': 5, 'prob': 1/50},
    ],
    'dlt': [
        {'name': '一等奖', 'prize': 5000000, 'prob': 1/21425712},
        {'name': '二等奖', 'prize': 100000, 'prob': 1/1428381},
        {'name': '三等奖', 'prize': 5000, 'prob': 1/163329},
        {'name': '四等奖', 'prize': 300, 'prob': 1/24386},
        {'name': '五等奖', 'prize': 15, 'prob': 1/2029},
        {'name': '六等奖', 'prize': 5, 'prob': 1/195},
        {'name': '七等奖', 'prize': 5, 'prob': 1/37},
    ],
    'qxc': [
        {'name': '一等奖', 'prize': 5000000, 'prob': 1/10000000},
        {'name': '二等奖', 'prize': 50000, 'prob': 1/1111111},
        {'name': '三等奖', 'prize': 3000, 'prob': 1/178571},
        {'name': '四等奖', 'prize': 500, 'prob': 1/15306},
        {'name': '五等奖', 'prize': 30, 'prob': 1/1319},
        {'name': '六等奖', 'prize': 5, 'prob': 1/263},
    ],
}


def kelly_ev_multitier(game):
    """
    🟢 v6.2: 多奖级Kelly期望值计算
    用多奖级的期望值替代单一赔率，更准确反映真实投注价值
    EV = Σ(prize_i * prob_i * confidence_boost) - 1
    有效赔率 = EV / total_prob
    """
    tiers = PRIZE_TIERS.get(game, [])
    if not tiers:
        return 0.0, 50  # 回退

    # 从历史回测获取信心系数：命中率是否高于随机基线
    backtest_log = _load_backtest()
    confidence = 1.0  # 默认无加成
    if backtest_log:
        recent = backtest_log[-10:]
        hit_rates = []
        for bt in recent:
            if game in bt:
                hits = bt[game].get('hits', [])
                if hits:
                    avg_hit = sum(h.get('total', 0) for h in hits) / len(hits)
                    hit_rates.append(avg_hit)
        if hit_rates:
            avg_rate = sum(hit_rates) / len(hit_rates)
            # 如果命中率高于随机基线(≈2-3个号/注)，给予信心加成
            baseline = {'ssq': 2.5, 'dlt': 2.0, 'qxc': 2.0}.get(game, 2.0)
            if avg_rate > baseline:
                confidence = min(1.0 + (avg_rate - baseline) * 0.2, 2.0)

    # 计算期望值
    total_ev = 0
    total_prob = 0
    for tier in tiers:
        p = tier['prob'] * confidence
        total_ev += tier['prize'] * p
        total_prob += p

    # 有效赔率 = 期望回报 / 投注成本
    # 投注成本=2元，有效赔率 = total_ev / 2
    effective_odds = total_ev / 2 if total_prob > 0 else 50
    effective_odds = max(effective_odds, 1)  # 下限1，避免负值

    # Kelly值 = (effective_odds * total_prob - (1-total_prob)) / effective_odds
    if effective_odds > 0:
        k = (effective_odds * total_prob - (1 - total_prob)) / effective_odds
    else:
        k = 0

    return max(k, 0), effective_odds


def estimate_hit_probability(game, hit_count, total_numbers):
    """
    基于历史回测估算命中率
    🔴 Bug修复：不再用avg_hit/total_numbers（不是真正的概率）
    改用二项分布近似：P(≥k命中) ≈ 基于历史命中率的累积概率
    简化模型：用历史平均命中率作为单号命中概率，然后用组合公式估算
    """
    backtest_log = _load_backtest()
    if not backtest_log:
        return 0.02  # 🔴 BugF修复：默认概率从0.1降到0.02（更保守）

    # 收集该彩种的历史命中数
    game_hits = []
    game_total_predicted = 0
    for bt in backtest_log[-10:]:
        if game in bt:
            for h in bt[game].get('hits', []):
                game_hits.append(h.get('total', 0))
                # 计算总预测号码数（用于计算单号命中率）
                if game == 'ssq':
                    game_total_predicted += 7  # 6红+1蓝
                elif game == 'dlt':
                    game_total_predicted += 7  # 5前+2后
                elif game == 'qxc':
                    game_total_predicted += 7

    if not game_hits or not game_total_predicted:
        return 0.02

    # 🔴 正确的概率模型：
    # 单号命中率 p = avg_hit / avg_predicted_per_bet
    avg_hit = sum(game_hits) / len(game_hits)
    avg_predicted = game_total_predicted / len(game_hits)
    single_hit_prob = min(avg_hit / (avg_predicted * 3), 0.15)  # 除以3因为每期3注

    # 命中hit_count个号的概率（极简估计）
    # 实际上对于彩票这种极低概率事件，这个值应该很小
    prob = max(0.005, single_hit_prob * (hit_count / total_numbers))
    return min(prob, 0.15)  # 上限15%，彩票不存在高命中概率


def _save_predictions(predictions):
    """保存推荐记录"""
    # 只保留最近7天的记录
    if len(predictions) > 7:
        predictions = predictions[-7:]
    with open(PREDICTION_LOG, 'w') as f:
        json.dump(predictions, f, ensure_ascii=False, indent=2)


def _load_backtest():
    """加载回测记录"""
    try:
        with open(BACKTEST_LOG, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_backtest(backtest):
    """保存回测记录"""
    if len(backtest) > 30:
        backtest = backtest[-30:]
    with open(BACKTEST_LOG, 'w') as f:
        json.dump(backtest, f, ensure_ascii=False, indent=2)


def _calc_hit_rate(predictions, actual):
    """计算命中数
    predictions: 推荐号码列表
    actual: 实际开奖号码列表
    返回：命中个数
    """
    return len(set(predictions) & set(actual))


def _run_backtest():
    """回测当前版本 vs 昨天开奖结果
    🔴 v6.8核心改进：用当前版本代码重新生成推荐，而非读旧版推荐记录
    逻辑：
    1. 抓取昨天开奖号码
    2. 抓取历史数据，去掉最新一期（模拟"开奖前的信息"）
    3. 用当前WeightedAnalyzer生成推荐
    4. 对比推荐号 vs 实际开奖号
    这样每次版本迭代后，回测验证的都是当前算法的水平
    """
    backtest_log = _load_backtest()
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # 昨天开奖的彩种
    draw_games = get_draw_games_yesterday()
    if not draw_games:
        print("[回测] 昨天无彩种开奖，跳过回测")
        return None

    draw_names = [LOTTERY_NAMES.get(g, g) for g in draw_games]
    draw_names_str = ', '.join(draw_names)
    print(f"[回测] 昨天开奖彩种: {draw_names_str}")

    # 🔴 防止重复回测：检查今天是否已用当前版本回测过
    for bt in backtest_log:
        if bt.get('backtest_date') == today_str and bt.get('backtest_method') == 'current_version':
            print(f"[回测] 今天已用当前版本回测过，跳过")
            return bt

    backtest_result = {
        'date': (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d'),
        'backtest_date': today_str,
        'backtest_method': 'current_version',  # 🔴 标记回测方法，区分旧版
        'draw_games': draw_games,
    }

    # 🔴 v6.8: 记录回测时使用的权重快照（方便追溯"这个结果基于什么参数"）
    config = _load_weight_config()
    backtest_result['weight_snapshot'] = {
        'algo_version': config.get('algo_version', 'v7.1'),
        'freq': config.get('freq', 0.30), 'miss': config.get('miss', 0.25),
        'trend': config.get('trend', 0.25), 'zone': config.get('zone', 0.20),
        'cold_miss_front': config.get('cold_miss_front', 0.40),
        'cold_cycle_front': config.get('cold_cycle_front', 0.30),
        'cold_miss_back': config.get('cold_miss_back', 0.30),
        'cold_cycle_back': config.get('cold_cycle_back', 0.40),
        'neighbor_bonus': config.get('neighbor_bonus', 0.03),
        'gamma': config.get('gamma', 0.88),
    }

    # ===== 双色球回测 =====
    if 'ssq' in draw_games:
        ssq_history = fetch_ssq_history(16)  # 多抓1期，去掉最新开奖
        if ssq_history and len(ssq_history) >= 6:
            actual = ssq_history[0]  # 最新一期 = 昨天开奖
            ssq_pre_draw = ssq_history[1:]  # 去掉最新期，模拟开奖前的数据

            wa = WeightedAnalyzer(ssq_pre_draw)
            analysis = wa.analyze_ssq()
            recs = wa.generate_recs_ssq(analysis, kelly_bias=0.0)

            hits = []
            for rec in recs:
                red_hit_nums = _get_hit_numbers(rec['reds'], actual['reds'])
                blue_hit = 1 if rec['blue'] == actual['blue'] else 0
                hits.append({
                    'strategy': rec['strategy'],
                    'red_hits': len(red_hit_nums),
                    'red_hit_nums': red_hit_nums,
                    'blue_hit': blue_hit,
                    'total': len(red_hit_nums) + blue_hit,
                    'predicted_reds': rec['reds'],
                    'predicted_blue': rec['blue'],
                    'actual_reds': actual['reds'],
                    'actual_blue': actual['blue'],
                })
            backtest_result['ssq'] = {
                'period': actual['period'],
                'hits': hits,
                'best_strategy': max(hits, key=lambda x: x['total'])['strategy'] if hits else None,
                'best_total': max(hits, key=lambda x: x['total'])['total'] if hits else 0,
                'actual_reds': actual['reds'],
                'actual_blue': actual['blue'],
            }
            print(f"[回测] 双色球 第{actual['period']}期: 最佳策略={backtest_result['ssq']['best_strategy']}, 命中={backtest_result['ssq']['best_total']}个")
        else:
            print("[回测] 双色球数据不足，跳过")

    # ===== 大乐透回测 =====
    if 'dlt' in draw_games:
        dlt_history = fetch_dlt_history(16)
        if dlt_history and len(dlt_history) >= 6:
            actual = dlt_history[0]
            dlt_pre_draw = dlt_history[1:]

            wa = WeightedAnalyzer(dlt_pre_draw)
            analysis = wa.analyze_dlt()
            recs = wa.generate_recs_dlt(analysis, kelly_bias=0.0)

            hits = []
            for rec in recs:
                front_hit_nums = _get_hit_numbers(rec['front'], actual['front'])
                back_hit_nums = _get_hit_numbers(rec['back'], actual['back'])
                hits.append({
                    'strategy': rec['strategy'],
                    'front_hits': len(front_hit_nums),
                    'front_hit_nums': front_hit_nums,
                    'back_hits': len(back_hit_nums),
                    'back_hit_nums': back_hit_nums,
                    'total': len(front_hit_nums) + len(back_hit_nums),
                    'predicted_front': rec['front'],
                    'predicted_back': rec['back'],
                    'actual_front': actual['front'],
                    'actual_back': actual['back'],
                })
            backtest_result['dlt'] = {
                'period': actual['period'],
                'hits': hits,
                'best_strategy': max(hits, key=lambda x: x['total'])['strategy'] if hits else None,
                'best_total': max(hits, key=lambda x: x['total'])['total'] if hits else 0,
                'actual_front': actual['front'],
                'actual_back': actual['back'],
            }
            print(f"[回测] 大乐透 第{actual['period']}期: 最佳策略={backtest_result['dlt']['best_strategy']}, 命中={backtest_result['dlt']['best_total']}个")
        else:
            print("[回测] 大乐透数据不足，跳过")

    # ===== 七星彩回测 =====
    if 'qxc' in draw_games:
        qxc_history = fetch_qxc_history(31)  # 七星彩隔期开奖，多抓一些
        if qxc_history and len(qxc_history) >= 6:
            actual = qxc_history[0]
            qxc_pre_draw = qxc_history[1:]

            wa = WeightedAnalyzer(qxc_pre_draw)
            analysis = wa.analyze_qxc()
            recs = wa.generate_recs_qxc(analysis, kelly_bias=0.0)

            hits = []
            for rec in recs:
                digit_hits_detail = [(i, rec['digits'][i], actual['digits'][i], rec['digits'][i] == actual['digits'][i]) for i in range(7)]
                digit_hit_count = sum(1 for _, _, _, hit in digit_hits_detail if hit)
                hits.append({
                    'strategy': rec['strategy'],
                    'digit_hits': digit_hit_count,
                    'digit_hits_detail': digit_hits_detail,
                    'total': digit_hit_count,
                    'predicted': rec['digits'],
                    'actual': actual['digits'],
                })
            backtest_result['qxc'] = {
                'period': actual['period'],
                'hits': hits,
                'best_strategy': max(hits, key=lambda x: x['total'])['strategy'] if hits else None,
                'best_total': max(hits, key=lambda x: x['total'])['total'] if hits else 0,
                'actual_digits': actual['digits'],
            }
            print(f"[回测] 七星彩 第{actual['period']}期: 最佳策略={backtest_result['qxc']['best_strategy']}, 命中={backtest_result['qxc']['best_total']}个")
        else:
            print("[回测] 七星彩数据不足，跳过")

    # 保存回测结果
    if any(k in backtest_result for k in ['ssq', 'dlt', 'qxc']):
        backtest_log.append(backtest_result)
        # 🔴 只保留最近30条回测记录
        if len(backtest_log) > 30:
            backtest_log = backtest_log[-30:]
        _save_backtest(backtest_log)
        return backtest_result

    return None


def _format_backtest_for_ai(backtest_result):
    """把回测结果格式化成刘海蟾能读的反馈（🔴含逐号对比详情）"""
    if not backtest_result:
        return ''

    draw_names = [LOTTERY_NAMES.get(g, g) for g in backtest_result.get('draw_games', [])]
    method = backtest_result.get('backtest_method', 'legacy')
    method_label = '当前版本回测' if method == 'current_version' else '旧版推荐记录'
    lines = [f'\n=== 昨日开奖回测（{", ".join(draw_names)}开奖，{method_label}）===']

    if 'ssq' in backtest_result:
        ssq = backtest_result['ssq']
        actual_r = ' '.join(f'{n:02d}' for n in ssq['actual_reds'])
        actual_b = f'{ssq["actual_blue"]:02d}'
        lines.append(f'双色球第{ssq["period"]}期开奖: 红球 {actual_r} | 蓝球 {actual_b}')
        for h in ssq['hits']:
            pred_r = ' '.join(f'{n:02d}' for n in h['predicted_reds'])
            hit_r = ' '.join(f'{n:02d}' for n in h.get('red_hit_nums', []))
            miss_r = ' '.join(f'{n:02d}' for n in _get_miss_numbers(h['predicted_reds'], ssq['actual_reds']))
            lines.append(f"  {h['strategy']}: 预测{pred_r}+蓝{h['predicted_blue']:02d}")
            lines.append(f"    红球命中{h['red_hits']}/6(命中:{hit_r}, 未中:{miss_r}), 蓝球{'✅命中' if h['blue_hit'] else '❌未中'}, 总{h['total']}")
        lines.append(f"  最佳策略: {ssq['best_strategy']} (命中{ssq['best_total']}个)")

    if 'dlt' in backtest_result:
        dlt = backtest_result['dlt']
        actual_f = ' '.join(f'{n:02d}' for n in dlt['actual_front'])
        actual_b = ' '.join(f'{n:02d}' for n in dlt['actual_back'])
        lines.append(f'大乐透第{dlt["period"]}期开奖: 前区 {actual_f} | 后区 {actual_b}')
        for h in dlt['hits']:
            pred_f = ' '.join(f'{n:02d}' for n in h['predicted_front'])
            hit_f = ' '.join(f'{n:02d}' for n in h.get('front_hit_nums', []))
            hit_b = ' '.join(f'{n:02d}' for n in h.get('back_hit_nums', []))
            lines.append(f"  {h['strategy']}: 预测{pred_f}+后{h['predicted_back'][0]:02d}{h['predicted_back'][1]:02d}")
            lines.append(f"    前区命中{h['front_hits']}/5(命中:{hit_f}), 后区命中{h['back_hits']}/2(命中:{hit_b}), 总{h['total']}")
        lines.append(f"  最佳策略: {dlt['best_strategy']} (命中{dlt['best_total']}个)")

    if 'qxc' in backtest_result:
        qxc = backtest_result['qxc']
        actual_d = ''.join(str(n) for n in qxc['actual_digits'])
        lines.append(f'七星彩第{qxc["period"]}期开奖: {actual_d}')
        for h in qxc['hits']:
            pred_d = ''.join(str(n) for n in h['predicted'])
            pos_hits = [str(i+1) for i, _, _, hit in h.get('digit_hits_detail', []) if hit]
            lines.append(f"  {h['strategy']}: 预测{pred_d}")
            lines.append(f"    位置命中{h['digit_hits']}/7(命中位置:{','.join(pos_hits) if pos_hits else '无'}), 总{h['total']}")
        lines.append(f"  最佳策略: {qxc['best_strategy']} (命中{qxc['best_total']}个)")

    # 从历史回测中总结策略偏好
    all_backtest = _load_backtest()
    if len(all_backtest) >= 3:
        strategy_scores = Counter()
        strategy_total_hits = defaultdict(list)  # 每种策略的历次命中数
        for bt in all_backtest[-7:]:
            for game in ['ssq', 'dlt', 'qxc']:
                if game in bt:
                    best = bt[game].get('best_strategy', '')
                    if best:
                        strategy_scores[best] += 1
                    # 🟢 收集每种策略的命中数趋势
                    for h in bt[game].get('hits', []):
                        s = h.get('strategy', '')
                        strategy_total_hits[s].append(h.get('total', 0))
        if strategy_scores:
            lines.append(f"\n近{len(all_backtest[-7:])}天回测策略胜率: {', '.join(f'{s}({c}次最佳)' for s, c in strategy_scores.most_common())}")

        # 🟢 策略平均命中率
        avg_lines = []
        for s, hits_list in sorted(strategy_total_hits.items()):
            avg = sum(hits_list) / len(hits_list) if hits_list else 0
            trend = hits_list[-1] - hits_list[0] if len(hits_list) >= 2 else 0
            trend_arrow = '↑' if trend > 0 else '↓' if trend < 0 else '→'
            avg_lines.append(f"{s}: 均值{avg:.1f} {trend_arrow}(最近{hits_list[-1]}个)")
        if avg_lines:
            lines.append(f"📊策略命中率趋势: {'; '.join(avg_lines)}")

        # 🟢 v6.2: 使用全局STRATEGY_MAP
        mapped_scores = Counter()
        for name, count in strategy_scores.items():
            mapped_name = STRATEGY_MAP.get(name, name)
            mapped_scores[mapped_name] += count
        hot_count = mapped_scores.get(Strategy.CORE, 0)
        cold_count = mapped_scores.get(Strategy.EXT2, 0)
        mid_count = mapped_scores.get(Strategy.EXT1, 0)
        if hot_count > cold_count + 2:
            lines.append(f"⚡核心注策略大幅领先({hot_count}次 vs 扩展2的{cold_count}次)，建议追热推荐占比60%+，从加权池追热TOP8中选号")
        elif cold_count > hot_count + 2:
            lines.append(f"⚡扩展2策略领先({cold_count}次 vs 核心注{hot_count}次)，建议多选遗漏>5期的号码，回补推荐占比50%+")
        else:
            lines.append(f"⚡策略胜率接近(核心注{hot_count}/扩展2{cold_count}/扩展1{mid_count})，建议三种策略均衡，参考加权号码池")

    lines.append('\n🔴 关键调整规则（根据回测验证）：')
    lines.append('1. 如果某号码连续3期以上命中，下期降低其权重（回归均值）')
    lines.append('2. 如果遗漏号开始回补命中，下期继续关注同遗漏区间的号码')
    lines.append('3. 参考📊加权号码池：它是纯数学计算的结果，不受AI主观偏差影响')
    lines.append('4. 你可以微调加权池的号码（换1-2个），但不要大幅偏离统计规律\n')

    return '\n'.join(lines)


# ===== 刘海蟾点金（DeepSeek-V3，一次调用三个彩种） =====

def _call_jiran(ssq_text, dlt_text, qxc_text, backtest_feedback=''):
    """一次性调用刘海蟾点金三个彩种 — 优先办公室Qwen3.6（免费），失败回退百炼"""
    # 🟢 v6吸收：休市信息注入AI prompt
    today_date_str = datetime.now(CST).strftime('%Y-%m-%d')
    holiday_info = is_holiday(today_date_str)
    holiday_prompt = f"\n🔴 今日({today_date_str})处于{holiday_info}期间，休市暂停开奖，推荐仅供参考。\n" if holiday_info else ""

    next_draw_lines = []
    for game in ['ssq', 'dlt', 'qxc']:
        nd = get_next_draw_date(game)
        if nd:
            name = LOTTERY_NAMES.get(game, game)
            next_draw_lines.append(f"{name}下期开奖: {nd[0]}({nd[1]})")
    next_draw_prompt = '\n'.join(next_draw_lines) if next_draw_lines else ""

    prompt = f"""请基于以下近15期开奖数据，分别为三个彩种推算下期号码。
{holiday_prompt}
{next_draw_prompt}

=== 双色球（红球1-33选6，蓝球1-16选1）===
{ssq_text}

=== 大乐透（前区1-35选5，后区1-12选2）===
{dlt_text}

=== 七星彩（7位数字0-9）===
{qxc_text}
{backtest_feedback}
请为每个彩种给出4组推荐号码，格式严格要求如下（不要输出其他内容）：

双色球核心注：红球 NN NN NN NN NN NN | 蓝球 NN
双色球扩展1：红球 NN NN NN NN NN NN | 蓝球 NN
双色球扩展2：红球 NN NN NN NN NN NN | 蓝球 NN
双色球冷号注：红球 NN NN NN NN NN NN | 蓝球 NN
大乐透核心注：前区 NN NN NN NN NN | 后区 NN NN
大乐透扩展1：前区 NN NN NN NN NN | 后区 NN NN
大乐透扩展2：前区 NN NN NN NN NN | 后区 NN NN
大乐透冷号注：前区 NN NN NN NN NN | 后区 NN NN
七星彩核心注：N N N N N N N
七星彩扩展1：N N N N N N N
七星彩扩展2：N N N N N N N
七星彩冷号注：N N N N N N N

🔴 核心注生成规则（最重要！）：
- 核心注 = 从加权号码池的追热+回补+综合三组中，选综合权重最高的6个号
- 追热和回补覆盖了不同号码区间，合并选TOP6可以同时覆盖冷热号
- 核心注的目标是最大化单注命中数（而不是分散覆盖）
- 蓝球/后区选加权权重最高的1-2个

🔴 扩展注生成规则：
- 扩展1：保留核心注4个号 + 替换2个为权重次高的号（1号微调）
- 扩展2：保留核心注3个号 + 替换3个为权重第7-12高的号（大换血）
- 这样3注形成"核心→微调→大换"梯度，既保核心命中又扩展覆盖

🔴 冷号注生成规则（v6新增）：
- 冷号注 = 选择遗漏值最高的6个红球/5个前区 + 遗漏最高的蓝球/2个后区
- 冷号注与核心注互补：核心注追热，冷号注搏冷，两者覆盖面最广
- 如果某号同时是权重最高和遗漏最高，优先放冷号注

红球/前区从小到大排列，用两位数（如02 07 12）。"""

    system_msg = '你是刘海蟾，求是方法论驱动的彩票分析AI。v7升级：GEPA自动进化+回测驱动权重调整+冷号注分前后区权重。核心注+缩水扩展+冷号注策略。v7改进：回测用当前代码实时生成（非读旧版推荐）、冷号注前区miss主导后区cycle主导、GEPA每日自动优化权重。4注梯度：核心注(追热)→扩展1(微调)→扩展2(大换)→冷号注(搏冷)。规则：1.核心注从加权池取综合权重TOP6；2.扩展1保留核心4号换2号，扩展2保留3号换3号；3.冷号注选遗漏值TOP号；4.严格按格式输出4组，不输出分析过程。休市期间仍可推荐，但标注仅供参考。彩票本质随机，求是让过程系统可追溯，不提高中奖率。'

    # 🔴 优先办公室Qwen3.6-abliterated（彩票零隐私，免费不限量，不会拒绝预测）
    if OFFICE_ENABLED:
        result = _call_llm(OFFICE_API_BASE, OFFICE_API_KEY, OFFICE_MODEL, system_msg, prompt, max_tokens=1000, timeout=120)
        if result:
            print(f"[刘海蟾] 办公室Qwen3.6-abliterated推算完成: {len(result)}字符")
            return result
        print("[刘海蟾] 办公室API失败，回退百炼DeepSeek-V3")

    # 回退到百炼DeepSeek-V3
    print("[刘海蟾] 办公室API失败，回退百炼DeepSeek-V3")
    result = _call_llm(DASHSCOPE_BASE_URL, DASHSCOPE_API_KEY, 'deepseek-v3', system_msg, prompt, max_tokens=1000, timeout=45)
    if result:
        print(f"[刘海蟾] 百炼DeepSeek推算完成: {len(result)}字符")
        return result

    return None


def _call_llm(base_url, api_key, model, system_msg, user_msg, max_tokens=1000, timeout=120):
    """通用LLM调用"""
    try:
        resp = requests.post(
            f'{base_url}/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_msg},
                    {'role': 'user', 'content': user_msg}
                ],
                'max_tokens': max_tokens,
                'temperature': 0.8
            },
            timeout=timeout
        )
        data = resp.json()

        if 'choices' not in data:
            error_msg = json.dumps(data, ensure_ascii=False)[:200]
            print(f"[LLM] API失败({base_url}): {error_msg}")
            return None

        content = data['choices'][0]['message']['content']
        return content

    except requests.exceptions.Timeout:
        print(f"[LLM] API超时({base_url}, {timeout}秒)")
        return None
    except Exception as e:
        print(f"[LLM] 调用失败({base_url}): {e}")
        return None


# ===== 解析刘海蟾输出 =====

def _parse_ssq_recs(ai_text):
    recs = []
    strategies = [Strategy.CORE, Strategy.EXT1, Strategy.EXT2]
    # 兼容新旧格式
    pattern = r'双色球(?:核心注|推荐1)[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
    m = re.search(pattern, ai_text)
    if m:
        recs.append({
            'reds': [int(m.group(j)) for j in range(1, 7)],
            'blue': int(m.group(7)),
            'strategy': Strategy.CORE
        })
    pattern2 = r'双色球扩展1[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
    m2 = re.search(pattern2, ai_text)
    if m2:
        recs.append({
            'reds': [int(m2.group(j)) for j in range(1, 7)],
            'blue': int(m2.group(7)),
            'strategy': Strategy.EXT1
        })
    pattern3 = r'双色球扩展2[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
    m3 = re.search(pattern3, ai_text)
    if m3:
        recs.append({
            'reds': [int(m3.group(j)) for j in range(1, 7)],
            'blue': int(m3.group(7)),
            'strategy': Strategy.EXT2
        })
    # 🟢 v6.6: 冷号注解析容错（匹配"冷号"/"冷号注"/"搏冷"/"冷门"）
    pattern4 = r'双色球(?:冷号注|冷号|搏冷|冷门)[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
    m4 = re.search(pattern4, ai_text)
    if m4:
        recs.append({
            'reds': [int(m4.group(j)) for j in range(1, 7)],
            'blue': int(m4.group(7)),
            'strategy': Strategy.COLD
        })
    # 兜底：旧格式
    if not recs:
        old_pattern = r'双色球推荐\d[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
        matches = re.findall(old_pattern, ai_text)
        strategies_fallback = [Strategy.CORE, Strategy.EXT1, Strategy.EXT2, Strategy.COLD_FALLBACK]
        for i, m in enumerate(matches[:4]):
            recs.append({
                'reds': [int(m[j]) for j in range(6)],
                'blue': int(m[6]),
                'strategy': strategies_fallback[i] if i < len(strategies_fallback) else f'策略{i+1}'
            })
    if len(recs) == 3:
        print("[解析] 双色球AI输出缺少冷号注，只有3注")
    return recs

def _parse_dlt_recs(ai_text):
    recs = []
    strategies = [Strategy.CORE, Strategy.EXT1, Strategy.EXT2]
    # 新格式
    pattern = r'大乐透(?:核心注|推荐1)[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
    m = re.search(pattern, ai_text)
    if m:
        recs.append({
            'front': [int(m.group(j)) for j in range(1, 6)],
            'back': [int(m.group(j)) for j in range(6, 8)],
            'strategy': Strategy.CORE
        })
    pattern2 = r'大乐透扩展1[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
    m2 = re.search(pattern2, ai_text)
    if m2:
        recs.append({
            'front': [int(m2.group(j)) for j in range(1, 6)],
            'back': [int(m2.group(j)) for j in range(6, 8)],
            'strategy': Strategy.EXT1
        })
    pattern3 = r'大乐透扩展2[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
    m3 = re.search(pattern3, ai_text)
    if m3:
        recs.append({
            'front': [int(m3.group(j)) for j in range(1, 6)],
            'back': [int(m3.group(j)) for j in range(6, 8)],
            'strategy': Strategy.EXT2
        })
    # 🟢 v6吸收：冷号注解析（v6.6增加容错：匹配"冷号"/"冷号注"/"搏冷"/"冷门"）
    pattern4 = r'大乐透(?:冷号注|冷号|搏冷|冷门)[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
    m4 = re.search(pattern4, ai_text)
    if m4:
        recs.append({
            'front': [int(m4.group(j)) for j in range(1, 6)],
            'back': [int(m4.group(j)) for j in range(6, 8)],
            'strategy': Strategy.COLD
        })
    # 🟢 v6.6: 兜底旧格式也补冷号注（第4注）
    if not recs:
        old_pattern = r'大乐透推荐\d[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
        matches = re.findall(old_pattern, ai_text)
        strategies_fallback = [Strategy.CORE, Strategy.EXT1, Strategy.EXT2, Strategy.COLD_FALLBACK]
        for i, m in enumerate(matches[:4]):
            recs.append({
                'front': [int(m[j]) for j in range(5)],
                'back': [int(m[j]) for j in range(5, 7)],
                'strategy': strategies_fallback[i] if i < len(strategies_fallback) else f'策略{i+1}'
            })
    # 🟢 v6.6: 如果AI只输出了3注没冷号，补一个冷号注标记
    if len(recs) == 3:
        recs[2]['strategy'] = Strategy.EXT2  # 确保第3注是扩展2
        # 没有冷号注，回测时将缺少冷号注数据
        print("[解析] 大乐透AI输出缺少冷号注，只有3注")
    return recs

def _parse_qxc_recs(ai_text):
    recs = []
    strategies = [Strategy.CORE, Strategy.EXT1, Strategy.EXT2]
    # 新格式
    pattern = r'七星彩(?:核心注|推荐1)[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
    m = re.search(pattern, ai_text)
    if m:
        recs.append({
            'digits': [int(m.group(j)) for j in range(1, 8)],
            'strategy': Strategy.CORE
        })
    pattern2 = r'七星彩扩展1[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
    m2 = re.search(pattern2, ai_text)
    if m2:
        recs.append({
            'digits': [int(m2.group(j)) for j in range(1, 8)],
            'strategy': Strategy.EXT1
        })
    pattern3 = r'七星彩扩展2[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
    m3 = re.search(pattern3, ai_text)
    if m3:
        recs.append({
            'digits': [int(m3.group(j)) for j in range(1, 8)],
            'strategy': Strategy.EXT2
        })
    # 🟢 v6.6: 冷号注解析容错
    pattern4 = r'七星彩(?:冷号注|冷号|搏冷|冷门)[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
    m4 = re.search(pattern4, ai_text)
    if m4:
        recs.append({
            'digits': [int(m4.group(j)) for j in range(1, 8)],
            'strategy': Strategy.COLD
        })
    # 兜底旧格式
    if not recs:
        old_pattern = r'七星彩推荐\d[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
        matches = re.findall(old_pattern, ai_text)
        for i, m in enumerate(matches[:3]):
            recs.append({
                'digits': [int(m[j]) for j in range(7)],
                'strategy': strategies[i] if i < len(strategies) else f'策略{i+1}'
            })
    return recs


# ===== Python Fallback分析 =====

class SimpleAnalyzer:
    def analyze_ssq(self, history):
        red_counter = Counter()
        blue_counter = Counter()
        for d in history:
            red_counter.update(d['reds'])
            blue_counter.update([d['blue']])
        # 核心注：频率最高8个中取6个（按频率排序保留TOP6）
        top8 = red_counter.most_common(8)
        core_by_freq = [n for n, _ in top8][:6]  # 🔴 Bug6修复：保持频率排序
        core = sorted(core_by_freq)  # 只用于显示
        core_blue = blue_counter.most_common(1)[0][0]
        # 扩展1：保留频率TOP4 + 频率次高2号
        ext1_keep = sorted(core_by_freq[:4])  # 🔴 Bug6修复：按频率TOP4保留，不是号码最小的4个
        ext1_new = sorted([n for n, _ in top8[6:10] if n not in ext1_keep][:2])
        ext1_blue = blue_counter.most_common(2)[-1][0] if len(blue_counter.most_common(2)) > 1 else core_blue
        # 🔴 扩展2：保留核心2号 + 频率中等号(出现2-3次)，模拟"大换血但不是全冷"
        ext2_keep = sorted(core_by_freq[:2])
        mid_freq = sorted([n for n in range(1, 34) if 2 <= red_counter.get(n, 0) <= 3 and n not in core_by_freq][:4])
        if len(mid_freq) < 4:
            mid_freq = sorted([n for n in range(1, 34) if red_counter.get(n, 0) <= 1 and n not in core_by_freq][:4])
        ext2_reds = sorted(ext2_keep + mid_freq[:4])
        ext2_blue_candidates = [n for n in range(1, 17) if 1 <= blue_counter.get(n, 0) <= 2]
        ext2_blue = ext2_blue_candidates[0] if ext2_blue_candidates else (blue_counter.most_common(2)[-1][0] if len(blue_counter.most_common(2)) > 1 else core_blue)
        # 🟢 v6吸收：冷号注（遗漏最高的号码）
        miss_reds = sorted([n for n in range(1, 34) if n not in red_counter or red_counter.get(n, 0) == 0][:6])
        miss_blues = sorted([n for n in range(1, 17) if n not in blue_counter or blue_counter.get(n, 0) == 0])
        if len(miss_reds) < 6:
            miss_reds = sorted([n for n in range(1, 34) if red_counter.get(n, 0) <= 1 and n not in core_by_freq][:6])
        return [
            {'reds': core, 'blue': core_blue, 'strategy': Strategy.CORE_FALLBACK},
            {'reds': sorted(ext1_keep + ext1_new), 'blue': ext1_blue, 'strategy': Strategy.EXT1_FALLBACK},
            {'reds': ext2_reds, 'blue': ext2_blue, 'strategy': Strategy.EXT2_FALLBACK},
            {'reds': miss_reds, 'blue': miss_blues[0] if miss_blues else 1, 'strategy': Strategy.COLD_FALLBACK},
        ]

    def analyze_dlt(self, history):
        front_counter = Counter()
        back_counter = Counter()
        for d in history:
            front_counter.update(d['front'])
            back_counter.update(d['back'])
        top7 = front_counter.most_common(7)
        core_by_freq = [n for n, _ in top7][:5]  # 🔴 Bug6修复：保持频率排序
        core = sorted(core_by_freq)  # 只用于显示
        core_back = sorted([back_counter.most_common(1)[0][0], back_counter.most_common(2)[1][0]])
        ext1_keep = sorted(core_by_freq[:3])  # 🔴 Bug6修复：按频率TOP3保留
        ext1_new = sorted([n for n, _ in top7[5:10] if n not in ext1_keep][:2])
        ext1_back = sorted([back_counter.most_common(1)[0][0], back_counter.most_common(3)[1][0]]) if len(back_counter.most_common(3)) > 1 else core_back
        # 🔴 扩展2：保留核心2号 + 频率中等号(出现2-3次)，模拟"大换血但不是全冷"
        ext2_keep = sorted(core_by_freq[:2])
        mid_freq_front = sorted([n for n in range(1, 36) if 2 <= front_counter.get(n, 0) <= 3 and n not in core_by_freq][:3])
        if len(mid_freq_front) < 3:
            mid_freq_front = sorted([n for n in range(1, 36) if front_counter.get(n, 0) <= 1 and n not in core_by_freq][:3])
        ext2_front = sorted(ext2_keep + mid_freq_front[:3])
        ext2_back_candidates = sorted([n for n in range(1, 13) if 1 <= back_counter.get(n, 0) <= 2 and n not in core_back][:2])
        if len(ext2_back_candidates) < 2:
            ext2_back_candidates = sorted([n for n in range(1, 13) if back_counter.get(n, 0) >= 1 and n not in core_back][:2])
        if len(ext2_back_candidates) < 2:
            ext2_back_candidates = core_back
        # 🟢 v6吸收：冷号注（遗漏最高的号码）
        miss_front = sorted([n for n in range(1, 36) if n not in front_counter or front_counter.get(n, 0) == 0][:5])
        miss_back = sorted([n for n in range(1, 13) if n not in back_counter or back_counter.get(n, 0) == 0][:2])
        if len(miss_front) < 5:
            miss_front = sorted([n for n in range(1, 36) if front_counter.get(n, 0) <= 1 and n not in core_by_freq][:5])
        if len(miss_back) < 2:
            miss_back = sorted([n for n in range(1, 13) if back_counter.get(n, 0) <= 1 and n not in core_back][:2])
        if len(miss_back) < 2:
            miss_back = [1, 2]
        return [
            {'front': core, 'back': core_back, 'strategy': Strategy.CORE_FALLBACK},
            {'front': sorted(ext1_keep + ext1_new), 'back': ext1_back, 'strategy': Strategy.EXT1_FALLBACK},
            {'front': ext2_front, 'back': ext2_back_candidates, 'strategy': Strategy.EXT2_FALLBACK},
            {'front': miss_front, 'back': miss_back, 'strategy': Strategy.COLD_FALLBACK},
        ]

    def analyze_qxc(self, history):
        recs = []
        # 核心注：每位最高频
        core = []
        for pos in range(7):
            counter = Counter(d['digits'][pos] for d in history)
            core.append(counter.most_common(1)[0][0])
        # 扩展1：前3位核心 + 后4位次高频
        ext1 = list(core)
        for pos in range(3, 7):
            counter = Counter(d['digits'][pos] for d in history)
            ext1[pos] = counter.most_common(2)[1][0] if len(counter.most_common(2)) > 1 else core[pos]
        # 🔴 扩展2：前2位核心 + 后5位中等频率(出现2-3次)，模拟"大换血但不是全冷"
        ext2 = list(core)
        for pos in range(2, 7):
            counter = Counter(d['digits'][pos] for d in history)
            mid = [n for n in range(10) if 2 <= counter.get(n, 0) <= 3 and n != core[pos]]
            ext2[pos] = mid[0] if mid else ([n for n in range(10) if counter.get(n, 0) <= 1 and n != core[pos]][0] if [n for n in range(10) if counter.get(n, 0) <= 1] else counter.most_common()[-1][0])
        # 🟢 v6吸收：冷号注（每位遗漏最高的数字）
        cold_digits = list(core)
        for pos in range(7):
            counter = Counter(d['digits'][pos] for d in history)
            cold = [n for n in range(10) if counter.get(n, 0) == 0]
            cold_digits[pos] = cold[0] if cold else counter.most_common()[-1][0]
        recs = [
            {'digits': core, 'strategy': Strategy.CORE_FALLBACK},
            {'digits': ext1, 'strategy': Strategy.EXT1_FALLBACK},
            {'digits': ext2, 'strategy': Strategy.EXT2_FALLBACK},
            {'digits': cold_digits, 'strategy': Strategy.COLD_FALLBACK},
        ]
        return recs


# ===== 格式化输出 =====

def format_lottery_section(ssq_result=None, dlt_result=None, qxc_result=None, backtest_result=None):
    lines = []
    lines.append("\n---\n")
    lines.append("## 🎰 彩票号码推荐 — 刘海蟾点金（仅供娱乐参考）\n")
    lines.append("> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n")

    # 🔴 开奖日历提示 + 🟢 v6吸收：下期开奖日期+休市提示
    today_games = get_draw_games()
    tomorrow_games = get_draw_games_tomorrow()
    if today_games:
        today_names = '、'.join(LOTTERY_NAMES.get(g, g) for g in today_games)
        lines.append(f"📅 **今天开奖**: {today_names}\n")
    if tomorrow_games:
        tomorrow_names = '、'.join(LOTTERY_NAMES.get(g, g) for g in tomorrow_games)
        lines.append(f"📅 **明天开奖**: {tomorrow_names}\n")

    # 🟢 v6吸收：下期开奖日期（含休市跳过）+ 今日是否休市
    today_str = datetime.now(CST).strftime('%Y-%m-%d')
    today_holiday = is_holiday(today_str)
    if today_holiday:
        lines.append(f"🔴 **休市提醒**: 今日({today_str})处于{today_holiday}期间，暂停开奖\n")
    next_draw_info = []
    for game in ['ssq', 'dlt', 'qxc']:
        nd = get_next_draw_date(game)
        if nd:
            name = LOTTERY_NAMES.get(game, game)
            date_str, weekday, is_hol = nd
            hol_mark = ' ⚠️可能受休市影响' if is_hol else ''
            next_draw_info.append(f"{name}: {date_str}({weekday}){hol_mark}")
    if next_draw_info:
        lines.append("📅 **下期开奖**: " + ' | '.join(next_draw_info) + "\n")
    if not today_games and not tomorrow_games:
        lines.append("📅 今明两天无开奖\n")

    # 🔴 增强版回测结果（逐号对比）— v6.8: 用当前版本代码回测
    if backtest_result:
        draw_games = backtest_result.get('draw_games', [])
        draw_names_str = '、'.join(LOTTERY_NAMES.get(g, g) for g in draw_games)
        method = backtest_result.get('backtest_method', 'legacy')
        method_note = '（当前版本算法回测）' if method == 'current_version' else '（旧版推荐记录）'
        lines.append(f"### 📊 开奖回测{method_note}")
        lines.append(f"昨日开奖: {draw_names_str}\n")

        if 'ssq' in backtest_result:
            ssq = backtest_result['ssq']
            actual_r = ' '.join(f'{n:02d}' for n in ssq['actual_reds'])
            actual_b = f'{ssq["actual_blue"]:02d}'
            lines.append(f"🔴 **双色球** 第{ssq['period']}期 开奖: {actual_r} + 蓝{actual_b}")
            for h in ssq['hits']:
                pred_r = ' '.join(f'{n:02d}' for n in h['predicted_reds'])
                hit_nums = ' '.join(f'{n:02d}✅' for n in h.get('red_hit_nums', []))
                blue_status = '✅' if h['blue_hit'] else '❌'
                lines.append(f"  {h['strategy']}: {pred_r} + 蓝{h['predicted_blue']:02d} → 红球{h['red_hits']}/6({hit_nums}) 蓝球{blue_status} = {h['total']}")
            lines.append(f"  ▶ 最佳: {ssq['best_strategy']}({ssq['best_total']}个)")
            lines.append("")

        if 'dlt' in backtest_result:
            dlt = backtest_result['dlt']
            actual_f = ' '.join(f'{n:02d}' for n in dlt['actual_front'])
            actual_b = ' '.join(f'{n:02d}' for n in dlt['actual_back'])
            lines.append(f"🟡 **大乐透** 第{dlt['period']}期 开奖: {actual_f} + 后{actual_b}")
            for h in dlt['hits']:
                pred_f = ' '.join(f'{n:02d}' for n in h['predicted_front'])
                hit_f = ' '.join(f'{n:02d}✅' for n in h.get('front_hit_nums', []))
                hit_b = ' '.join(f'{n:02d}✅' for n in h.get('back_hit_nums', []))
                lines.append(f"  {h['strategy']}: {pred_f} + 后{' '.join(f'{n:02d}' for n in h['predicted_back'])} → 前区{h['front_hits']}/5({hit_f}) 后区{h['back_hits']}/2({hit_b}) = {h['total']}")
            lines.append(f"  ▶ 最佳: {dlt['best_strategy']}({dlt['best_total']}个)")
            lines.append("")

        if 'qxc' in backtest_result:
            qxc = backtest_result['qxc']
            actual_d = ' '.join(str(n) for n in qxc['actual_digits'])
            lines.append(f"🟢 **七星彩** 第{qxc['period']}期 开奖: {actual_d}")
            for h in qxc['hits']:
                pred_d = ' '.join(str(n) for n in h['predicted'])
                pos_marks = ''
                for i, pred_val, actual_val, hit in h.get('digit_hits_detail', []):
                    pos_marks += f'{pred_val}{"✅" if hit else "❌"} '
                lines.append(f"  {h['strategy']}: {pred_d} → {pos_marks}= {h['digit_hits']}/7")
            lines.append(f"  ▶ 最佳: {qxc['best_strategy']}({qxc['best_total']}个)")
            lines.append("")

    if ssq_result:
        history, recs = ssq_result
        lines.append("### 🔴 双色球")
        lines.append(f"（近{len(history)}期数据，刘海蟾点金）\n")
        lines.append("**近期开奖：**")
        lines.append("| 期号 | 红球 | 蓝球 |")
        lines.append("|------|------|------|")
        for draw in history[:3]:
            reds_str = ' '.join(f'{n:02d}' for n in draw['reds'])
            lines.append(f"| {draw['period']} | {reds_str} | {draw['blue']:02d} |")
        if recs:
            lines.append("\n**下期推荐：**")
            for rec in recs:
                reds_str = ' '.join(f'{n:02d}' for n in rec['reds'])
                lines.append(f"- [{rec['strategy']}] {reds_str} + 蓝球{rec['blue']:02d}")
        else:
            lines.append("\n**⚠️ 推算失败**")

    if dlt_result:
        history, recs = dlt_result
        lines.append("### 🟡 大乐透")
        lines.append(f"（近{len(history)}期数据，刘海蟾点金）\n")
        lines.append("**近期开奖：**")
        lines.append("| 期号 | 前区 | 后区 |")
        lines.append("|------|------|------|")
        for draw in history[:3]:
            front_str = ' '.join(f'{n:02d}' for n in draw['front'])
            back_str = ' '.join(f'{n:02d}' for n in draw['back'])
            lines.append(f"| {draw['period']} | {front_str} | {back_str} |")
        if recs:
            lines.append("\n**下期推荐：**")
            for rec in recs:
                front_str = ' '.join(f'{n:02d}' for n in rec['front'])
                back_str = ' '.join(f'{n:02d}' for n in rec['back'])
                lines.append(f"- [{rec['strategy']}] `{front_str}` + 🔵`{back_str}`")
        else:
            lines.append("\n**⚠️ 推算失败**")

    if qxc_result:
        history, recs = qxc_result
        lines.append("### 🟢 七星彩")
        lines.append(f"（近{len(history)}期数据，刘海蟾点金）\n")
        lines.append("**近期开奖：**")
        lines.append("| 期号 | 号码 |")
        lines.append("|------|------|")
        for draw in history[:3]:
            digits_str = ' '.join(str(n) for n in draw['digits'])
            lines.append(f"| {draw['period']} | {digits_str} |")
        if recs:
            lines.append("\n**下期推荐：**")
            for rec in recs:
                digits_str = ' '.join(str(n) for n in rec['digits'])
                lines.append(f"- [{rec['strategy']}] `{digits_str}`")
        else:
            lines.append("\n**⚠️ 推算失败**")

    # 🔴 开奖日历速查
    lines.append("\n📅 **开奖日历**: 大乐透(一三六) | 双色球(二四日) | 七星彩(二五日)")

    # 🟢 P2: Kelly仓位建议 + 🔴 Kelly>5%重点关注复式建议
    config = _load_weight_config()
    lines.append(f"\n⚖️ **风控提示**:")
    
    # 收集Kelly>5%的彩种，用于生成复式建议
    high_kelly_games = []
    
    for game_name, game_key, total_nums in [('双色球', 'ssq', 7), ('大乐透', 'dlt', 7), ('七星彩', 'qxc', 7)]:
        hit_prob = estimate_hit_probability(game_key, 4, total_nums)
        # 🔴 BugD修复：Kelly赔率匹配真实奖级
        odds_map = {'ssq': 50, 'dlt': 50, 'qxc': 100}
        k = kelly_fraction(hit_prob, odds_map.get(game_key, 200))
        if k > 0:
            lines.append(f"  {game_name}核心注: Kelly={k:.2%}（建议投入≤本金的{k:.1%}）")
            if k > 0.05:
                high_kelly_games.append((game_name, game_key, k))
        else:
            lines.append(f"  {game_name}核心注: Kelly≤0（❌不建议本期投注）")

    # 🔴 Kelly>5%重点关注：复式购买建议
    if high_kelly_games:
        lines.append(f"\n🔥 **Kelly>5%重点关注**:")
        for game_name, game_key, k in high_kelly_games:
            lines.append(f"\n**{game_name}** Kelly={k:.2%} ⬆️ 值得加码")
            
            # 根据彩种生成复式建议
            if game_key == 'ssq':
                lines.append("  📋 复式方案建议：")
                lines.append("  - 🔹 小复式：红7+1（14元）— 覆盖1个额外红球")
                lines.append("  - 🔸 中复式：红8+1（56元）— 覆盖2个额外红球")
                lines.append("  - 🔶 大复式：红6+2（12元）— 覆盖1个额外蓝球")
                lines.append("  - 💡 推荐：红7+1或红6+2，性价比最高")
            elif game_key == 'dlt':
                lines.append("  📋 复式方案建议：")
                lines.append("  - 🔹 小复式：前6+2（12元）— 覆盖1个额外前区")
                lines.append("  - 🔸 中复式：前7+2（42元）— 覆盖2个额外前区")
                lines.append("  - 🔶 大复式：前5+3（18元）— 覆盖1个额外后区")
                lines.append("  - 💡 推荐：前6+2或前5+3，性价比最高")
            elif game_key == 'qxc':
                lines.append("  📋 复式方案建议：")
                lines.append("  - 🔹 小复式：选8个号码复式（16元）— 多1位覆盖")
                lines.append("  - 🔸 中复式：选9个号码复式（36元）— 多2位覆盖")
                lines.append("  - 💡 推荐：选8个号码复式，性价比最高")
            
            lines.append(f"  ⚠️ Kelly={k:.1%}意味着建议用本金的{k:.1%}投注，不要超过此比例")
    else:
        lines.append(f"\n📌 本期无Kelly>5%彩种，建议单式小额为主")

    # 🟢 v6吸收：购彩策略建议（源自chinese-lottery-predict预算模块）
    budget = BUDGET_CONFIG['default']
    price = BUDGET_CONFIG['price_per_bet']
    max_bets = budget // price
    lines.append(f"\n💡 **购彩策略** (预算{budget}元):")
    if max_bets >= 4:
        lines.append(f"  - 可购{max_bets}注（每注{price}元），推荐：核心注×1 + 扩展1×1 + 冷号注×1 + 备选×1")
        lines.append(f"  - 💰 省钱方案：核心注×1 + 冷号注×1 = {price*2}元（覆盖追热+搏冷）")
    elif max_bets >= 2:
        lines.append(f"  - 可购{max_bets}注，推荐：核心注×1 + 冷号注×1")
    elif max_bets >= 1:
        lines.append(f"  - 可购{max_bets}注，推荐：核心注×1")
    else:
        lines.append(f"  - ⚠️ 预算不足{price}元，无法购买完整注")
    lines.append(f"  - 🎯 核心注=权重追热 | 冷号注=遗漏搏冷 | 两者互补覆盖面最广")

    algo_ver = config.get('algo_version', 'v7.1')
    evo_log = config.get('evolution_log', [])
    last_evo = evo_log[-1] if evo_log else None
    lines.append(f"\n📊 **算法参数**: {algo_ver} | 核心: 频率={config.get('freq',0.3):.0%} 遗漏={config.get('miss',0.25):.0%} 趋势={config.get('trend',0.25):.0%} 分区={config.get('zone',0.2):.0%} | 冷号前区: 遗漏={config.get('cold_miss_front',0.4):.0%} 周期={config.get('cold_cycle_front',0.3):.0%} | 冷号后区: 周期={config.get('cold_cycle_back',0.4):.0%} 遗漏={config.get('cold_miss_back',0.3):.0%} | 邻号+{config.get('neighbor_bonus',0.03):.3f} γ={config.get('gamma',0.88):.2f}")
    if last_evo:
        evo_date = last_evo.get('date', '')
        evo_changes = '; '.join(last_evo.get('changes', []))
        major_tag = '🔴重大' if last_evo.get('is_major') else '🟢微调'
        lines.append(f"🧬 **最近进化**: {evo_date} {major_tag} → {last_evo.get('algo_version', algo_ver)} | {evo_changes}")
    lines.append("---\n")
    return '\n'.join(lines)


# ===== 主入口 =====

def generate_lottery_recommendations():
    """主函数：回测昨日 → GEPA自动进化 → 抓取数据 → 刘海蟾点金 → 格式化 → 保存记录"""
    print("[彩票] 开始生成推荐（刘海蟾点金模式）...")
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # 🔴 v6.8: 执行顺序 = 回测→进化→推荐
    # 第1步：先用当前权重回测昨日（测试的是"昨天推荐时的权重"）
    print("[回测] 用当前版本代码回测昨日开奖...")
    backtest_result = _run_backtest()
    backtest_feedback = _format_backtest_for_ai(backtest_result)
    if backtest_feedback:
        print(f"[回测] 已生成回测反馈: {len(backtest_feedback)}字符")

    # 第2步：基于回测结果GEPA进化（回测→诊断→调参→版本更新）
    evolved_config = adjust_weights_from_backtest()
    if evolved_config:
        version_tag = evolved_config.get('algo_version', 'v7.1')
        is_major = evolved_config.get('evolution_log', [{}])[-1].get('is_major', False) if evolved_config.get('evolution_log') else False
        print(f"[GEPA] 算法已进化至{version_tag}{'（重大更新！）' if is_major else ''}")
    else:
        evolved_config = _load_weight_config()
        print(f"[GEPA] 算法无变化，当前{evolved_config.get('algo_version', 'v7.1')}")

    fallback = SimpleAnalyzer()
    ssq_result = None
    dlt_result = None
    qxc_result = None

    # 🟢 v6.2: Kelly驱动选号 — 用多奖级EV替代单一赔率
    kelly_map = {}  # {game_key: kelly_value}
    for game_name, game_key, total_nums in [('双色球', 'ssq', 7), ('大乐透', 'dlt', 7), ('七星彩', 'qxc', 7)]:
        k_ev, eff_odds = kelly_ev_multitier(game_key)
        # 也用旧方法算一个，取较大值（多奖级EV更保守时用旧方法兜底）
        hit_prob = estimate_hit_probability(game_key, 4, total_nums)
        k_simple = kelly_fraction(hit_prob, eff_odds)
        kelly_map[game_key] = max(k_ev, k_simple)
    # 🟢 v6.2: Kelly→选号偏向连续映射（消除硬断层）
    # 用tanh平滑过渡: Kelly=0→bias=0, Kelly>5%→bias趋近+0.5, Kelly<0→bias趋近-0.5
    def _kelly_to_bias(k):
        import math
        return math.tanh(k * 20) * 0.5  # 连续映射，无硬断层
    kelly_bias_map = {g: _kelly_to_bias(k) for g, k in kelly_map.items()}
    print(f"[Kelly] 双色球={kelly_map['ssq']:.2%}(bias={kelly_bias_map['ssq']:+.1f}) 大乐透={kelly_map['dlt']:.2%}(bias={kelly_bias_map['dlt']:+.1f}) 七星彩={kelly_map['qxc']:.2%}(bias={kelly_bias_map['qxc']:+.1f})")

    # 第3步：抓取数据并生成推荐（用进化后的权重）（🟢 v6.2: 七星彩请求30期因为隔期开奖，15期只能拿到6-8期）
    print("[彩票] 抓取双色球数据...")
    ssq_history = fetch_ssq_history(15)
    print("[彩票] 抓取大乐透数据...")
    dlt_history = fetch_dlt_history(15)
    print("[彩票] 抓取七星彩数据...")
    qxc_history = fetch_qxc_history(30)

    # 2. 刘海蟾一次性推算（带回测反馈）
    all_data_ok = (ssq_history and len(ssq_history) >= 5 and
                   dlt_history and len(dlt_history) >= 5 and
                   qxc_history and len(qxc_history) >= 5)

    if all_data_ok:
        ssq_text = _format_ssq_for_ai(ssq_history, kelly_bias=kelly_bias_map.get('ssq', 0.0))
        dlt_text = _format_dlt_for_ai(dlt_history, kelly_bias=kelly_bias_map.get('dlt', 0.0))
        qxc_text = _format_qxc_for_ai(qxc_history, kelly_bias=kelly_bias_map.get('qxc', 0.0))

        print("[彩票] 调用刘海蟾一次性推算三个彩种（含回测反馈）...")
        ai_output = _call_jiran(ssq_text, dlt_text, qxc_text, backtest_feedback)

        if ai_output:
            ssq_recs = _parse_ssq_recs(ai_output)
            dlt_recs = _parse_dlt_recs(ai_output)
            qxc_recs = _parse_qxc_recs(ai_output)

            ssq_result = (ssq_history, ssq_recs if ssq_recs else fallback.analyze_ssq(ssq_history))
            dlt_result = (dlt_history, dlt_recs if dlt_recs else fallback.analyze_dlt(dlt_history))
            qxc_result = (qxc_history, qxc_recs if qxc_recs else fallback.analyze_qxc(qxc_history))

            # 🟢 v6.6: 如果AI缺少冷号注，用WeightedAnalyzer自动补上
            for game, recs, history in [
                ('ssq', ssq_recs, ssq_history),
                ('dlt', dlt_recs, dlt_history),
                ('qxc', qxc_recs, qxc_history),
            ]:
                if recs and not any(r.get('strategy') in (Strategy.COLD, Strategy.COLD_MISS, Strategy.COLD_FALLBACK) for r in recs):
                    print(f"[彩票] {game}缺少冷号注，自动补上")
                    wa = WeightedAnalyzer(history)
                    wa_method = 'analyze_' + game
                    analysis = getattr(wa, wa_method)()
                    gen_method = 'generate_recs_' + game
                    cold_recs = getattr(wa, gen_method)(analysis, kelly_bias=0.0)
                    # 找冷号注
                    for cr in cold_recs:
                        if cr.get('strategy') in (Strategy.COLD, Strategy.COLD_MISS, Strategy.COLD_FALLBACK):
                            recs.append(cr)
                            print(f"[彩票] {game}冷号注已补上: {cr}")
                            break

            print(f"[彩票] ✅ 双色球: {len(ssq_recs) if ssq_recs else 0}组AI推荐")
            print(f"[彩票] ✅ 大乐透: {len(dlt_recs) if dlt_recs else 0}组AI推荐")
            print(f"[彩票] ✅ 七星彩: {len(qxc_recs) if qxc_recs else 0}组AI推荐")
        else:
            print("[彩票] ⚠️ 刘海蟾API失败，全部兜底")
            ssq_result = (ssq_history, fallback.analyze_ssq(ssq_history))
            dlt_result = (dlt_history, fallback.analyze_dlt(dlt_history))
            qxc_result = (qxc_history, fallback.analyze_qxc(qxc_history))
    else:
        print("[彩票] 部分数据不足，使用兜底规则")
        if ssq_history and len(ssq_history) >= 5:
            ssq_result = (ssq_history, fallback.analyze_ssq(ssq_history))
        if dlt_history and len(dlt_history) >= 5:
            dlt_result = (dlt_history, fallback.analyze_dlt(dlt_history))
        if qxc_history and len(qxc_history) >= 5:
            qxc_result = (qxc_history, fallback.analyze_qxc(qxc_history))

    # 3. 保存今日推荐（供明天回测用）
    today_prediction = {
        'date': today_str,
        'ssq_recs': None,
        'dlt_recs': None,
        'qxc_recs': None,
    }
    if ssq_result:
        today_prediction['ssq_recs'] = ssq_result[1]
    if dlt_result:
        today_prediction['dlt_recs'] = dlt_result[1]
    if qxc_result:
        today_prediction['qxc_recs'] = qxc_result[1]

    predictions = _load_predictions()
    # 如果今天已经有记录了，覆盖
    predictions = [p for p in predictions if p.get('date') != today_str]
    predictions.append(today_prediction)
    _save_predictions(predictions)
    print(f"[彩票] 今日推荐已保存（供明天回测）")

    # 🔴 v7.4: 重大事件告警检测
    alerts = detect_lottery_alerts(
        evolved_config=evolved_config,
        backtest_result=backtest_result,
        kelly_map=kelly_map,
        ssq_result=ssq_result,
        dlt_result=dlt_result,
        qxc_result=qxc_result,
        ssq_history=ssq_history,
        dlt_history=dlt_history,
        qxc_history=qxc_history,
    )
    if alerts:
        _save_alerts(alerts, today_str)
        print(f"[告警] 检测到{len(alerts)}个重大事件！已写入lottery-alerts.json")
    else:
        _save_alerts([], today_str)  # 清空旧告警
        print("[告警] 无重大事件")

    # 4. 在输出中附加回测结果
    result = format_lottery_section(ssq_result, dlt_result, qxc_result, backtest_result)

    return result


# ===== 🔴 v7.4: 重大事件告警机制 =====

ALERT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-alerts.json')

def detect_lottery_alerts(evolved_config=None, backtest_result=None, kelly_map=None,
                          ssq_result=None, dlt_result=None, qxc_result=None,
                          ssq_history=None, dlt_history=None, qxc_history=None):
    """
    🔴 v7.4: 重大事件告警检测
    检测7类重大事件，返回告警列表：
    1. GEPA重大更新（is_major=True）
    2. GEPA空转（连续t=0）
    3. 回测命中爆发（单注≥4个号）
    4. 冷号注首次命中
    5. Kelly值偏高（>3%）
    6. 重大策略调整（GEPA参数变化≥0.04）
    7. 规律发现（相关性/趋势/周期异常信号）
    """
    alerts = []
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # === 1. GEPA重大更新 ===
    if evolved_config:
        evo_log = evolved_config.get('evolution_log', [])
        if evo_log:
            latest = evo_log[-1]
            if latest.get('is_major'):
                alerts.append({
                    'level': '🔴',
                    'type': 'gepa_major',
                    'title': 'GEPA重大更新',
                    'detail': f"算法进化至{evolved_config.get('algo_version', '?')}，"
                              f"变更: {'; '.join(latest.get('changes', []))}",
                    'action': '检查新版权重是否合理，必要时手动回退',
                })

    # === 2. GEPA空转检测 ===
    if evolved_config:
        evo_log = evolved_config.get('evolution_log', [])
        if len(evo_log) >= 2:
            recent_2 = evo_log[-2:]
            if all(e.get('t_test', {}).get('t_value', 1) == 0 for e in recent_2):
                alerts.append({
                    'level': '⚠️',
                    'type': 'gepa_stall',
                    'title': 'GEPA连续空转',
                    'detail': f"最近{len(recent_2)}次进化t=0（不显著），权重可能已到局部最优",
                    'action': '建议锁定GEPA或重构进化机制（增大步长/扩大回测窗口）',
                })

    # === 3. 回测命中爆发 ===
    if backtest_result:
        for game in ['ssq', 'dlt', 'qxc']:
            if game not in backtest_result:
                continue
            game_name = LOTTERY_NAMES.get(game, game)
            hits = backtest_result[game].get('hits', [])
            for h in hits:
                total = h.get('total', 0)
                strategy = str(h.get('strategy', ''))
                if total >= 4:
                    alerts.append({
                        'level': '🎯',
                        'type': 'backtest_hit',
                        'title': f'{game_name}回测命中{total}个号！',
                        'detail': f"策略: {strategy}, 红球命中{h.get('red_hits', 0)}个"
                                  f"{(', 蓝球命中' if game == 'ssq' else ', 后区命中') if h.get('blue_hit' if game == 'ssq' else 'back_hits', 0) else ''}",
                        'action': '验证该策略是否可持续，注意是否为随机波动',
                    })
                    break  # 同彩种只报一次

    # === 4. 冷号注首次命中 ===
    if backtest_result:
        for game in ['ssq', 'dlt', 'qxc']:
            if game not in backtest_result:
                continue
            game_name = LOTTERY_NAMES.get(game, game)
            hits = backtest_result[game].get('hits', [])
            for h in hits:
                strategy = str(h.get('strategy', ''))
                if 'cold' in strategy.lower() and h.get('total', 0) >= 2:
                    # 检查历史冷号注命中率
                    bt_log = _load_backtest()
                    cold_hits_count = 0
                    for bt in bt_log[-10:]:
                        if game in bt:
                            for bh in bt[game].get('hits', []):
                                if 'cold' in str(bh.get('strategy', '')).lower() and bh.get('total', 0) >= 2:
                                    cold_hits_count += 1
                    if cold_hits_count <= 1:  # 首次或极罕见
                        alerts.append({
                            'level': '❄️',
                            'type': 'cold_first_hit',
                            'title': f'{game_name}冷号注命中！',
                            'detail': f"策略: {strategy}, 命中{h.get('total', 0)}个号（近10期冷号注仅命中{cold_hits_count}次）",
                            'action': '冷号注信号出现，关注后续是否形成趋势',
                        })
                        break

    # === 5. Kelly值偏高 ===
    if kelly_map:
        KELLY_HIGH_THRESHOLD = 0.03  # 3%以上视为偏高
        for game_key, kelly_val in kelly_map.items():
            game_name = LOTTERY_NAMES.get(game_key, game_key)
            if kelly_val > KELLY_HIGH_THRESHOLD:
                alerts.append({
                    'level': '💰',
                    'type': 'kelly_high',
                    'title': f'{game_name}Kelly值偏高！',
                    'detail': f"Kelly={kelly_val:.2%}（阈值{KELLY_HIGH_THRESHOLD:.0%}），"
                              f"数学期望为正，值得加注",
                    'action': f'考虑增加{game_name}投注额（Kelly建议比例的1/4~1/2）',
                })

    # === 6. 重大策略调整 ===
    if evolved_config:
        evo_log = evolved_config.get('evolution_log', [])
        if evo_log:
            latest = evo_log[-1]
            old_w = latest.get('old_weights', {})
            new_w = latest.get('new_weights', {})
            big_changes = []
            for key in ['freq', 'miss', 'trend', 'zone', 'cold_miss_front', 'cold_cycle_front',
                        'cold_miss_back', 'cold_cycle_back', 'neighbor_bonus', 'gamma']:
                old_v = old_w.get(key, 0)
                new_v = new_w.get(key, 0)
                diff = abs(new_v - old_v)
                if diff >= 0.03 and not latest.get('is_major'):  # 重大更新已在#1报过
                    big_changes.append(f"{key}: {old_v:.3f}→{new_v:.3f}(Δ{diff:.3f})")
            if big_changes:
                alerts.append({
                    'level': '🔧',
                    'type': 'strategy_shift',
                    'title': '策略参数显著调整',
                    'detail': '; '.join(big_changes),
                    'action': '关注调整后效果，如连续走差考虑回退',
                })

    # === 7. 规律发现 ===
    # 7a. 号码相关性异常（某对号码条件概率远高于先验）
    for game, history, game_name in [
        ('ssq', ssq_history, '双色球'),
        ('dlt', dlt_history, '大乐透'),
        ('qxc', qxc_history, '七星彩'),
    ]:
        if not history or len(history) < 8:
            continue
        try:
            wa = WeightedAnalyzer(history)
            analysis = getattr(wa, f'analyze_{game}')()
            corr = analysis.get('correlations', {})
            # 找条件概率最高的一对
            best_corr = None
            best_ratio = 0
            for (n, m), info in corr.items():
                if isinstance(info, dict):
                    ratio = info.get('ratio', 1.0)
                    cond_p = info.get('conditional', 0)
                    if ratio > best_ratio and cond_p > 0.15:
                        best_ratio = ratio
                        best_corr = (n, m, info)
            if best_corr and best_ratio >= 2.0:  # 条件概率是先验的2倍以上
                n, m, info = best_corr
                alerts.append({
                    'level': '🔍',
                    'type': 'pattern_correlation',
                    'title': f'{game_name}发现强关联规律',
                    'detail': f"上期出{m}→下期出{n}的条件概率={info.get('conditional', 0):.1%}，"
                              f"是先验{info.get('prior', 0):.1%}的{best_ratio:.1f}倍",
                    'action': '关联规律值得关注，但需更多样本验证是否为随机波动',
                })
        except Exception:
            pass  # 规律发现是锦上添花，不能影响主流程

    # 7b. 趋势异常（某号码遗漏值远超历史均值）
    for game, history, game_name, num_field in [
        ('ssq', ssq_history, '双色球', 'reds'),
        ('dlt', dlt_history, '大乐透', 'front'),
        ('qxc', qxc_history, '七星彩', 'digits'),
    ]:
        if not history or len(history) < 10:
            continue
        try:
            wa = WeightedAnalyzer(history)
            analysis = getattr(wa, f'analyze_{game}')()
            miss_info = analysis.get('miss_scores', {})
            # 找遗漏值最高的号码
            if isinstance(miss_info, dict):
                max_miss_num = None
                max_miss_val = 0
                for num, score in miss_info.items():
                    if isinstance(score, (int, float)) and score > max_miss_val:
                        max_miss_val = score
                        max_miss_num = num
                if max_miss_val >= 8:  # 遗漏8期以上
                    alerts.append({
                        'level': '📊',
                        'type': 'pattern_overdue',
                        'title': f'{game_name}号码{max_miss_num}严重遗漏',
                        'detail': f"遗漏得分={max_miss_val:.1f}，远超均值，回补概率升高",
                        'action': '可在冷号注中关注该号，但冷号命中率低需控制仓位',
                    })
        except Exception:
            pass

    return alerts


def _save_alerts(alerts, today_str):
    """保存告警到JSON文件，供scheduler读取发送"""
    data = {
        'date': today_str,
        'generated_at': datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(alerts),
        'alerts': alerts,
    }
    with open(ALERT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_lottery_alerts():
    """读取最新的告警（供scheduler调用）"""
    if not os.path.exists(ALERT_FILE):
        return None
    try:
        with open(ALERT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


if __name__ == '__main__':
    result = generate_lottery_recommendations()
    print(result)
