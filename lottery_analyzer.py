#!/usr/bin/env python3
"""
彩票号码分析模块 v3.0 — 刘海蟾点金（加权统计+GEPA自动进化+Kelly驱动选号+冷号注+休市+预算策略+多奖级EV+相关性分析+统计显著性+scrapling降级引擎+和值约束引导+重大事件告警+AI去抄答案）

v7.5核心改动（P0权重优化）：
1. 🔴 P0核心注占35%(2注)，P1激进注降至20%(1注）
2. 🔴 观察期2026-05-21~05-23，旧值备用P0=28% P1=29%
3. 🔴 AI独立回测：重新调混元生成，不做recs转发
4. 🔴 极简版一体化：先生成日报再发送，fallback到最近文件

v7.4核心改动(重大事件告警):
1. 🔴 新增detect_lottery_alerts():检测7类重大事件并生成告警
2. 🔴 告警写入lottery-alerts.json,供scheduler发送单独告警邮件
3. 🔴 GEPA重大更新、回测命中、规律发现、Kelly偏高、策略调整等均可触发告警

v7.3核心改动(和值约束引导):
1. 🔴 修复GEPA从未生效bug:回测记录只有1条时GEPA需要2条,改为至少1条+6样本
2. 🔴 GEPA加统计显著性检验:Welch t-test,差异不显著时保守微调
3. 🔴 GEPA重大变更加样本门槛:20样本以下只允许微调±0.03,不允许大改
4. 🔴 清理旧版adjustments/last_reset_date遗留字段
5. 🔴 号码相关性分析:条件概率P(n|上期m)显著高于先验P(n)时加分
6. 🔴 GEPA进化日志加入sample_size和t_test记录

v7.0核心改动(GEPA自动进化闭环):
1. 🔴 回测重构:不再读旧版推荐记录,用当前代码+开奖前数据实时生成推荐再对比开奖号
2. 🔴 GEPA自动进化:回测→诊断→调参→版本更新,每日闭环
3. 🔴 冷号注权重分前后区:前区miss主导(0.40/0.30),后区cycle主导(0.30/0.40)
4. 🔴 所有可调参数统一收归weight-config.json(冷号权重/邻号bonus/gamma)
5. 🔴 执行顺序修正:回测→进化→推荐(避免正反馈环路)
6. 🔴 归一化下限保护:zone≥0.05, cold_freq≥0.05
7. 🔴 七星彩miss_score评分尺度统一
8. 🔴 回测记录权重快照(weight_snapshot)
9. 🔴 删除DLT gamma=0.85 clamp,由GEPA统一管理

v6.8核心改动(回测重构):
1. 🟢 邻号加分:上期开出的号±1获得0.03权重bonus(球机机械偏差)
2. 🟢 分区平衡约束:选号贪心搜索中加入分区覆盖评分,后验检查确保每注至少覆盖2个区

v6.6核心改动(回测优化):
1. 🟢 冷号注前区权重:遗漏0.30→0.40, 周期0.40→0.30(回测26020-26045期验证,总奖金+150%)
2. 🟢 冷号注红球权重:同步调整遗漏0.30→0.40, 周期0.40→0.30

v6.2核心改动(P0-P2全面优化):
1. 🟢 Kelly→bias连续映射(tanh消除硬断层)
2. 🟢 排序键归一化(freq/miss/weight统一到[0,1]再组合)
3. 🟢 统一STRATEGY_MAP + Strategy枚举常量(消除字符串散落)
4. 🟢 冷号注w_score修正(w*4.0替代w/5.0)
5. 🟢 DLT FALLBACK补充 + SSQ/DLT fallback merge逻辑
6. 🟢 蓝球分散(exclude参数避免4注同蓝球)
7. 🟢 回测噪声过滤(领先需≥3次+命中均值更优才调整权重)
8. 🟢 趋势权重对称化(上升1.0x/下降0.8x,无先验偏好)
9. 🟢 OFFICE_ENABLED改环境变量 + HOLIDAYS动态生成2025-2028
10. 🟢 权重重置改日期间隔(30天而非version计数)
11. 🟢 QXC加Kelly驱动+冷号注(与SSQ/DLT对齐)
12. 🟢 多奖级Kelly EV计算(替代单一赔率50/100)
13. 🟢 遗漏值平均间隔维度("到期号"额外加分)

v6吸收chinese-lottery-predict优势:
1. 🟢 新增冷号注策略:遗漏值最高号码组合,与核心注(追热)互补覆盖
2. 🟢 新增节假日休市判断:春节/国庆休市自动跳过,标注休市提醒
3. 🟢 新增购彩预算策略:按预算算注数,推荐单式/复式方案
4. 🟢 新增下期开奖日期计算(含休市跳过)

注意:彩票本质是随机事件,分析仅供娱乐参考。
"""

import os
import requests
import re
import random
import json
import sqlite3
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

# 🟢 v7.2: scrapling降级引擎(requests被封时自动启用)
try:
    from scrapling import Fetcher as _ScraplingFetcher, DynamicFetcher as _ScraplingDynamic
    _SCRAPLING_AVAILABLE = True
except ImportError:
    _SCRAPLING_AVAILABLE = False

CST = timezone(timedelta(hours=8))


# 🔴 办公室Qwen3.6-abliterated(免费不限量!彩票零隐私,优先走这里)
OFFICE_API_BASE = os.environ.get('OFFICE_API_BASE', '')
OFFICE_API_KEY = os.environ.get('OFFICE_API_KEY', '')
OFFICE_MODEL = 'huihui-qwen3.6-27b-abliterated'
# 🟢 v6.5: OFFICE_ENABLED改用环境变量开关,默认开启(新模型更稳定)
OFFICE_ENABLED = os.environ.get('OFFICE_ENABLED', 'true').lower() in ('true', '1', 'yes')

# 🔴 开奖日历(周几开奖,周一=0,周日=6)
LOTTERY_SCHEDULE = {
    'ssq': [1, 3, 6],    # 双色球:周二四日
    'dlt': [0, 2, 5],    # 大乐透:周一三六
    'qxc': [1, 4, 6],    # 七星彩:周二五日
}

LOTTERY_NAMES = {
    'ssq': '双色球',
    'dlt': '大乐透',
    'qxc': '七星彩',
}

# 🟢 v6吸收:节假日休市配置(源自chinese-lottery-predict)
# 🟢 v6.2: 改用函数动态判断,不再只硬编码特定年份
def _build_holidays():
    """动态生成节假日表,覆盖2025-2028年"""
    holidays = {}
    # 春节休市:农历正月初一前后各3天 ≈ 每年1月下旬~2月中旬
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
    # 国庆休市:每年10月1日-7日
    for year in range(2025, 2029):
        for day in range(1, 8):
            holidays[f'{year}-10-{day:02d}'] = '国庆休市'
    return holidays

HOLIDAYS = _build_holidays()

# 🟢 v6吸收:购彩预算配置(源自chinese-lottery-predict)
BUDGET_CONFIG = {
    'default': 10,       # 默认预算(元)
    'price_per_bet': 2,  # 单注价格(元)
}

# 开奖日历的中文显示
WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 🟢 v6.2: 统一策略名映射(全局常量,避免散落各处不一致)
# 🔴 v6.2: 策略名常量 - 替代字符串字面量,减少拼写错误风险
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
    """🟢 v6吸收:检查是否在节假日休市期间"""
    return HOLIDAYS.get(date_str)


def get_next_draw_date(game, from_date=None):
    """🟢 v6吸收:计算下期开奖日期(含节假日跳过)
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
    # 2周内都是休市?返回第一个开奖日(带休市标记)
    for offset in range(1, 30):
        check = current + timedelta(days=offset)
        if check.weekday() in draw_days:
            date_str = check.strftime('%Y-%m-%d')
            return (check.strftime('%m月%d日'), WEEKDAY_NAMES[check.weekday()], bool(is_holiday(date_str)))
    return None


def get_draw_games(date=None):
    """返回指定日期开奖的彩种列表,默认今天"""
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
    """返回命中的号码列表(排序)"""
    return sorted(set(predicted) & set(actual))


def _get_miss_numbers(predicted, actual):
    """返回预测中未命中的号码"""
    return sorted(set(predicted) - set(actual))

_BASE_DIR = os.environ.get('BASE_DIR', os.path.dirname(os.path.abspath(__file__)))
# 回测记录文件
BACKTEST_LOG = os.path.join(_BASE_DIR, 'lottery-backtest.json')
# 昨日推荐记录
PREDICTION_LOG = os.path.join(_BASE_DIR, 'lottery-predictions.json')


# ===== 硬编码Fallback数据(2026-04-18更新) =====

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


# ===== 期望期号计算(用于验证数据新鲜度)=====

def _get_expected_ssq_period():
    """根据当前日期估算双色球最新期号(用于数据新鲜度验证)
    双色球每周二、四、日开奖,一年约153期
    🔴 注意:此为估算值,实际期号由彩票中心分配,可能有调整
    """
    now = datetime.now(CST)
    year_start = datetime(2026, 1, 1, tzinfo=CST)
    if now < year_start:
        return 26001
    # 简单估算:自1月1日起每天约0.43期(3期/7天)
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
    print(f"\n[双色球] 开始抓取,目标 {periods} 期...")
    min_required = min(periods, 3)  # 🔴 修复:回测只请求1期时,不能要求>=3
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
    # 🟢 v6.2: 网络抓到少量数据也比纯硬编码好(与QXC逻辑一致)
    if result and len(result) >= 1:
        print(f"[双色球] 网络抓取到{len(result)}期,补充硬编码数据")
        fallback = [f for f in FALLBACK_SSQ if not any(f['period'] == r['period'] for r in result)]
        merged = result + fallback[:periods - len(result)]
        return merged
    print("[双色球] ⚠️ 所有网络源失败,使用硬编码数据")
    return FALLBACK_SSQ[:periods]

def fetch_dlt_history(periods=15):
    print(f"\n[大乐透] 开始抓取,目标 {periods} 期...")
    min_required = min(periods, 3)  # 🔴 修复:回测只请求1期时,不能要求>=3
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
    # 🟢 v6.2: 网络抓到少量数据也比纯硬编码好(与SSQ/QXC逻辑一致)
    if result and len(result) >= 1:
        print(f"[大乐透] 网络抓取到{len(result)}期,补充硬编码数据")
        fallback = [f for f in FALLBACK_DLT if not any(f['period'] == r['period'] for r in result)]
        merged = result + fallback[:periods - len(result)]
        return merged
    print("[大乐透] ⚠️ 所有网络源失败,使用硬编码数据")
    return FALLBACK_DLT[:periods]

def fetch_qxc_history(periods=15):
    min_required = min(periods, 3)  # 🔴 修复:回测只请求1期时,不能要求>=3
    result = _fetch_qxc_500com(periods)
    if result and len(result) >= min_required:
        return result
    result = _fetch_qxc_cjcp(periods)
    if result and len(result) >= min_required:
        return result
    # 🔴 网络抓到少量数据也比硬编码好(硬编码会过时)
    if result and len(result) >= 1:
        print(f"[七星彩] 网络抓取到{len(result)}期,补充硬编码数据")
        fallback = [f for f in FALLBACK_QXC if not any(f['period'] == r['period'] for r in result)]
        return result + fallback[:periods - len(result)]
    print("[七星彩] 网络抓取失败,使用硬编码数据")
    return FALLBACK_QXC[:periods]


def fetch_pln_history(periods=15):
    """抓取台湾威力彩(PLN)历史数据"""
    import csv
    try:
        with open('data/pln_history.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            result = []
            for row in reader:
                # 兼容两种格式: num1-num6 或 numbers
                if 'numbers' in row:
                    nums = [int(x) for x in row['numbers'].split(',')]
                else:
                    nums = [int(row.get(f'num{i}', 0)) for i in range(1, 7)]
                result.append({
                    'period': row['period'],
                    'numbers': nums,
                    'special': int(row.get('special', row.get('num7', 0)))
                })
            result.sort(key=lambda x: x['period'], reverse=True)
            return result[:periods]
    except Exception as e:
        print(f"[PLN] CSV读取失败: {e}，使用空数据")
        return []

def fetch_ltn_history(periods=15):
    """抓取台湾大乐透(LTN)历史数据"""
    import csv
    try:
        with open('data/ltn_history.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            result = []
            for row in reader:
                result.append({
                    'period': row['period'],
                    'front': [int(row[f'front{i}']) for i in range(1, 6)],
                    'back': [int(row[f'back{i}']) for i in range(1, 3)]
                })
            result.sort(key=lambda x: x['period'], reverse=True)
            return result[:periods]
    except Exception as e:
        print(f"[LTN] CSV读取失败: {e}，使用空数据")
        return []

def _scrapling_fallback_get(url, referer='', timeout=15):
    """🟢 v7.2: scrapling降级请求 - 当requests被封/超时时自动启用
    优先用Fetcher(curl_cffi+反指纹),失败则用DynamicFetcher(Playwright)
    """
    if not _SCRAPLING_AVAILABLE:
        return None
    try:
        # 方案1: Fetcher(快,反指纹)
        fetcher = _ScraplingFetcher(auto_match=False)
        page = fetcher.get(url, headers={'Referer': referer} if referer else {})
        if page and page.status == 200:
            return page.body.decode('gb2312', errors='replace') if isinstance(page.body, bytes) else page.body
    except Exception as e:
        print(f"[scrapling-Fetcher] 失败: {type(e).__name__}: {str(e)[:80]}")
    try:
        # 方案2: DynamicFetcher(Playwright驱动,能跑JS)
        fetcher2 = _ScraplingDynamic()
        page2 = fetcher2.fetch(url, referer=referer if referer else None)
        if page2 and page2.status == 200:
            return page2.body.decode('gb2312', errors='replace') if isinstance(page2.body, bytes) else page2.body
    except Exception as e:
        print(f"[scrapling-DynamicFetcher] 失败: {type(e).__name__}: {str(e)[:80]}")
    return None

def _fetch_ssq_500com(periods, retries=3):
    """双色球历史数据 - datachart 页面(带重试)"""
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
                expected_min = _get_expected_ssq_period() - 8  # 🔴 放宽容差,避免误判
                if int(latest_period) < expected_min:
                    print(f"[双色球-500] 警告: 数据过期,期望至少 {expected_min}")
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
    # 🟢 v7.2: scrapling降级 - requests全部失败后自动启用
    print("[双色球-500] requests失败,尝试scrapling降级...")
    html = _scrapling_fallback_get(url, referer='https://datachart.500.com/ssq/history/')
    if html:
        result = _parse_ssq_html(html, periods)
        if result and len(result) > 0:
            print(f"[双色球-500] ✅ scrapling降级成功: {len(result)} 期")
            return result
    print("[双色球-500] scrapling降级也失败")
    return None

def _fetch_dlt_500com(periods, retries=3):
    """大乐透历史数据 - datachart 页面(带重试)"""
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
                expected_min = _get_expected_dlt_period() - 8  # 🔴 放宽容差,避免误判
                if int(latest_period) < expected_min:
                    print(f"[大乐透-500] 警告: 数据过期,期望至少 {expected_min}")
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
    print("[大乐透-500] requests失败,尝试scrapling降级...")
    html = _scrapling_fallback_get(url, referer='https://datachart.500.com/dlt/history/')
    if html:
        result = _parse_dlt_html(html, periods)
        if result and len(result) > 0:
            print(f"[大乐透-500] ✅ scrapling降级成功: {len(result)} 期")
            return result
    print("[大乐透-500] scrapling降级也失败")
    return None

def _fetch_qxc_500com(periods):
    """七星彩:从kaijiang.500.com主页+详情页逐期抓取
    v3.0修复: 正则适配ball_orange class + 支持换行/空格
    """
    try:
        results = []
        # 先从开奖主页获取最新期号列表
        index_url = 'https://kaijiang.500.com/qxc.shtml'
        resp = requests.get(index_url, headers=HEADERS, timeout=15)
        resp.encoding = 'gb2312'

        # 主页直接有当期号码
        current_digits = re.findall(r'class="ball_orange">\s*(\d{1,2})\s*</li>', resp.text)
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

        # 当期号码直接从主页拿
        if current_digits and len(current_digits) >= 7:
            results.append({'period': unique_periods[0], 'digits': [int(d) for d in current_digits[:7]]})
            print(f"[七星彩-500] 主页当期: {unique_periods[0]} → {current_digits[:7]}")

        # 历史期逐期抓详情页(跳过已拿到的当期)
        start_idx = 1 if current_digits and len(current_digits) >= 7 else 0
        for period in unique_periods[start_idx:periods]:
            try:
                page_url = f'https://kaijiang.500.com/shtml/qxc/{period}.shtml'
                page_resp = requests.get(page_url, headers=HEADERS, timeout=10)
                page_resp.encoding = 'gb2312'
                # 修复正则: ball_orange后可能有换行/空格,支持1-2位数字(最后一位0-14)
                digits = re.findall(r'class="ball_orange">\s*(\d{1,2})\s*</li>', page_resp.text)
                if len(digits) >= 7:
                    results.append({'period': period, 'digits': [int(d) for d in digits[:7]]})
                else:
                    # 备用正则: 任意ball class,支持1-2位数字
                    digits = re.findall(r'class="[^"]*ball[^"]*"[^>]*>\s*(\d{1,2})\s*<', page_resp.text)
                    if len(digits) >= 7:
                        results.append({'period': period, 'digits': [int(d) for d in digits[:7]]})
            except Exception:
                continue

        if results:
            # 🔴 按期间号倒序排序（最新在前）
            results.sort(key=lambda x: x['period'], reverse=True)
            print(f"[七星彩-500] 抓取成功: {len(results)}期 (最新{results[0]['period']})")
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
    """备用:kaijiang.500.com 双色球单页抓取"""
    try:
        # 先获取最新期号列表(跟随重定向)
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
            print(f"[双色球-kaijiang] 未找到期号列表,响应长度: {len(resp.text)}")
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
    """备用:kaijiang.500.com 大乐透单页抓取"""
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
                # 提取前区号码(class包含ball_red或ball_1)
                front_balls = re.findall(r'class="ball_red">(\d+)</span>', page_resp.text)
                # 提取后区号码(class包含ball_blue)
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
    # 🔴 修复:500.com的HTML在期号前多了一个<td>(星期几),
    # 所以pattern1从期号直接开始已经匹配不到了
    # 改用更健壮的tr/td逐行解析
    tr_pattern = r'<tr[^>]*>(.*?)</tr>'
    for tr_match in re.findall(tr_pattern, html, re.DOTALL)[:100]:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_match, re.DOTALL)
        clean_tds = [re.sub(r'<[^>]+>', '', td).strip() for td in tds]
        # 找到期号位置:5位数字且以26开头
        period_idx = None
        for i, td in enumerate(clean_tds):
            if re.match(r'^2\d{4}$', td):
                period_idx = i
                break
        if period_idx is None:
            continue
        # 期号后6个td=红球,再1个td=蓝球
        if len(clean_tds) >= period_idx + 8:
            try:
                period = clean_tds[period_idx]
                reds = [int(clean_tds[period_idx + j]) for j in range(1, 7)]
                blue = int(clean_tds[period_idx + 7])
                # 验证红球范围1-33,蓝球1-16
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
        # 期号后5个td=前区,再2个td=后区
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


# ===== 🟢 加权统计算法(v5新增 - 方案A) =====

class WeightedAnalyzer:
    """
    基于多维度加权的号码分析器。
    不依赖AI,纯数学计算,结果喂给AI作为参考。

    维度:
    1. 频率加权:近N期出现次数越多权重越高
    2. 遗漏加权:连续未出现期数越多,回补权重越高
    3. 近期趋势加权:最近5期比前10期出现多的号加分(趋势上升)
    4. 连号分析:统计连号对出现频率
    5. 和值分析:统计和值范围
    6. 🟢 v6.7: 邻号加分 - 上期开出的号±1获得额外权重(球机机械偏差)
    """

    def __init__(self, history, weight_freq=None, weight_miss=None, weight_trend=None, weight_zone=None, gamma=None):
        self.history = history
        # 🟢 v6.3: gamma可配置,默认0.88,可从配置文件读取
        import json
        try:
            with open('/root/asuan-scheduler/weight-config.json', 'r') as f: config = json.load(f)
        except Exception: config = {}
        self.w_freq = weight_freq if weight_freq is not None else config.get('freq', 0.30)
        self.w_miss = weight_miss if weight_miss is not None else config.get('miss', 0.25)
        self.w_trend = weight_trend if weight_trend is not None else config.get('trend', 0.25)
        self.w_zone = weight_zone if weight_zone is not None else config.get('zone', 0.20)
        self.gamma = gamma if gamma is not None else config.get('gamma', 0.88)  # 🟢 v6.3
        # 🔴 v6.8: 邻号bonus和冷号注权重也从配置读取
        # 🔴 分前后区:前区/红球miss主导,后区/蓝球/七星彩cycle主导
        self.neighbor_bonus = config.get('neighbor_bonus', 0.03)
        self.cold_miss_front = config.get('cold_miss_front', 0.40)
        self.cold_cycle_front = config.get('cold_cycle_front', 0.30)
        self.cold_freq_front = config.get('cold_freq_front', 0.30)
        self.cold_miss_back = config.get('cold_miss_back', 0.30)
        self.cold_cycle_back = config.get('cold_cycle_back', 0.40)
        self.cold_freq_back = config.get('cold_freq_back', 0.30)

    def _load_bayesian_adj(self, number_range):
        """v3.0: 从DB读取贝叶斯修正系数

        读取algo_bayesian_weights表中最新一条记录,
        根据number_range判断是哪个game(33=ssq, 35=dlt, else=qxc)
        返回: dict {number: adjustment} 或 None(无数据时)
        """
        try:
            import sqlite3
            db_path = os.path.join(_BASE_DIR, 'algo_state.db')
            if not os.path.exists(db_path):
                return None

            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            # 判断game
            if max(number_range) == 33:
                game = 'ssq'
            elif max(number_range) == 35:
                game = 'dlt'
            else:
                game = 'qxc'

            # 读取最新修正系数
            c.execute('''SELECT adjustments FROM algo_bayesian_weights
                         WHERE game=? ORDER BY date DESC LIMIT 1''', (game,))
            row = c.fetchone()
            conn.close()

            if row:
                adj = json.loads(row[0])
                # 确保key是int
                return {int(k): v for k, v in adj.items()}
        except Exception as e:
            # 静默失败,不影响主流程
            pass
        return None

    def _calc_weights(self, number_range, extract_fn, total_periods):
        """通用加权计算
        extract_fn(history_item) -> list of numbers
        🟢 v6.3: 频率改为指数衰减,近期数据权重提升2-3倍,解冻号码粘滞
        """
        # 🟢 v6.3: 指数衰减频率统计 - γ=0.88,近1期权重≈远期5倍
        # 等权旧方式: freq = Counter(); freq.update(extract_fn(d)) - 15期前和1期前等权
        # 新方式: freq[n] = Σ(γ^idx × 出现标记) / Σ(γ^idx),idx=0为最近期
        gamma = self.gamma  # 🟢 v6.3: 可配置衰减因子
        decay_freq = Counter()
        decay_total = 0.0
        for idx, d in enumerate(self.history):
            w = gamma ** idx  # idx=0最近期权重最大
            decay_total += w
            for n in extract_fn(d):
                decay_freq[n] += w

        # 等权频率也保留(供冷号注等需要原始频率的场景)
        raw_freq = Counter()
        for d in self.history:
            raw_freq.update(extract_fn(d))

        # 遗漏值:连续未出现期数
        miss = {}
        # 🟢 v6.2: 平均遗漏间隔(历史平均隔几期出现一次)
        avg_miss_interval = {}
        for n in number_range:
            count = 0
            # 当前遗漏
            for d in self.history:
                if n in extract_fn(d):
                    break
                count += 1
            miss[n] = count
            # 平均遗漏间隔:找所有出现位置,计算间隔均值
            positions = [i for i, d in enumerate(self.history) if n in extract_fn(d)]
            if len(positions) >= 2:
                intervals = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
                avg_miss_interval[n] = sum(intervals) / len(intervals)
            elif len(positions) == 1:
                avg_miss_interval[n] = positions[0] if positions[0] > 0 else len(self.history)
            else:
                avg_miss_interval[n] = len(self.history)  # 从未出现

        # 近期趋势:最近5期 vs 前10期
        recent = Counter()
        older = Counter()
        mid = min(5, len(self.history))
        for d in self.history[:mid]:
            recent.update(extract_fn(d))
        for d in self.history[mid:mid*2]:
            older.update(extract_fn(d))

        # 🟢 P1修复:分区平衡真正融入权重
        # 🔴 Bug3修复:zone_size统一,与analyze_ssq(n//11)/analyze_dlt(n//12)一致
        # _calc_weights是通用函数,需要根据number_range动态计算正确的zone边界
        if max(number_range) == 33:  # 双色球红球1-33,分区1-11/12-22/23-33
            zone_size = 11
        elif max(number_range) == 35:  # 大乐透前区1-35,分区1-12/13-24/25-35
            zone_size = 12
        else:  # 七星彩每位0-9,分区0-3/4-6/7-9
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
            # 🔴 Bug4修复:趋势权重逻辑修正
            # t > 0 表示近5期比前10期出现多(上升趋势),应给正权重
            # t < 0 表示近5期比前10期出现少(下降趋势),应给负权重或零权重
            # 之前abs(t)给下降趋势正权重是错误的
            if t > 0:
                t_weight = t * 1.0  # 🟢 v6.2: 上升趋势(对称,无先验偏好)
            elif t < 0:
                t_weight = t * 0.8  # 🟢 v6.2: 下降趋势轻微衰减(0.8而非0.5,不过度惩罚)
            else:
                t_weight = 0

            # 🟢 分区平衡:偏低区的号加分,偏高区的号减分
            z = min(n // zone_size, 2)
            z_factor = max(0, (zone_expected - zone_counts[z]) / max(zone_expected, 1))

            # 🟢 v6.2: 遗漏周期加分 - 当前遗漏 > 平均遗漏间隔时,说明"到期"
            avg_interval = avg_miss_interval.get(n, total_periods)
            overdue_bonus = 0
            if avg_interval > 0 and miss.get(n, 0) > avg_interval:
                overdue_bonus = min((miss.get(n, 0) - avg_interval) / max(avg_interval, 1) * 0.15, 0.3)

            # 🟢 v6.7: 邻号加分 - 上期开出的号±1获得微弱加分
            # 球机有机械偏差,相邻号码统计相关性略高
            # 只看最近1期开出的号,邻号获得0.03的bonus(约权重1-2%的提升)
            neighbor_bonus = 0
            if self.history:
                last_drawn = set(extract_fn(self.history[0]))
                if (n - 1) in last_drawn or (n + 1) in last_drawn:
                    neighbor_bonus = self.neighbor_bonus

            # 🟢 v7.1→v3.0: 号码相关性bonus - 某号出现时,历史中与其同区/连号的号也出现概率更高
            # 计算条件概率:P(n出现 | 上期某号出现) vs P(n出现)
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
                        # 🔴 v7.2 修复:条件概率 P(n | 上期m) 正确计算
                        # 逻辑:若第i期出现m,统计第i+1期是否出现n
                        co_occur = 0
                        m_occur = 0
                        for i in range(len(self.history) - 1):
                            if m in extract_fn(self.history[i]):
                                m_occur += 1
                                if n in extract_fn(self.history[i + 1]):
                                    co_occur += 1
                        # 🔴 v7.2 修复:在for i循环外、for m循环内计算lift
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
                correlation_bonus  # 🟢 v7.1→v3.0: 号码相关性加分
            )

        # === v3.0: 贝叶斯动态权重修正 ===
        # 从DB读取Orchestrator计算的修正系数,对权重做±20%微调
        bayesian_adj = self._load_bayesian_adj(number_range)
        if bayesian_adj:
            adj_count = 0
            for n in number_range:
                adj = bayesian_adj.get(n, 1.0)
                if adj != 1.0:
                    weights[n] *= adj
                    adj_count += 1
            if adj_count > 0:
                print(f"  [Bayesian] 修正{adj_count}个号码权重")

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

        # 🔴 Bug3修复:zone_size统一为11(与_calc_weights中max=33时的zone_size一致)
        # 红球分区权重(1-11/12-22/23-33三区)
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

        # 🔴 v7.3: 和值约束检查 - 选中的6个红球的和值是否接近历史均值
        # 注意:实际选号在调用处完成,此处仅提供avg_sum供参考
        # 调用处应使用:abs(sum(selected_6_reds) - avg_sum) < avg_sum * 0.15 来判断是否接近

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
            'sum_value_guidance': f"选中6个红球的和值应接近{avg_sum:.1f}(偏差<15%)",
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

        # 🔴 Bug3修复:zone_size统一为12(与_calc_weights中max=35时的zone_size一致)
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
            # 🔴 v7.3: 和值约束引导 - 前区5个号+后区2个号的和值应接近历史均值
            'sum_value_guidance': f"前区5个号的和值应接近{avg_sum:.1f}(偏差<15%),后区2个号的和值应接近{avg_sum*2/36:.1f}",
            'consec_rate': consec_rate,
            'total_periods': total,
        }

    def analyze_qxc(self):
        """七星彩加权分析(逐位统计)"""
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

    def analyze_pln(self):
        """台湾威力彩(PLN)加权分析 (6/38 + 1/8)"""
        # 强制转换历史数据中的数字为int
        for d in self.history:
            d['numbers'] = [int(x) if isinstance(x, str) else x for x in d['numbers']]
            d['special'] = int(d['special']) if isinstance(d['special'], str) else d['special']
        total = len(self.history)
        if total == 0:
            return {'weights': [], 'total_periods': 0}
        
        # 主号权重（1-38）
        main_weights, main_freq, main_miss, main_avg_interval = self._calc_weights(
            range(1, 39), lambda d: d['numbers'], total
        )
        
        # 特别号权重（1-8）
        special_weights, special_freq, special_miss, special_avg_interval = self._calc_weights(
            range(1, 9), lambda d: [d['special']], total
        )
        
        # 分区权重（1-12/13-25/26-38三区）
        zone_balance = [0, 0, 0]
        for d in self.history[:5]:
            for n in d['numbers']:
                num = int(n) if isinstance(n, str) else n
                zone = min((num-1) // 13, 2)
                zone_balance[zone] += 1
        
        # 和值范围
        sums = [sum(d['numbers']) for d in self.history]
        avg_sum = sum(sums) / len(sums) if sums else 0
        
        # 按权重排序
        hot_mains = sorted(main_weights.items(), key=lambda x: x[1], reverse=True)
        hot_specials = sorted(special_weights.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'main_weights': hot_mains,
            'special_weights': hot_specials,
            'main_freq': main_freq,
            'special_freq': special_freq,
            'main_miss': main_miss,
            'special_miss': special_miss,
            'zone_balance': zone_balance,
            'avg_sum': avg_sum,
            'total_periods': total,
        }


    def analyze_ltn(self):
        """台湾大乐透(LTN)加权分析 (5/47 + 2/38)"""
        # 强制转换历史数据中的数字为int
        for d in self.history:
            d['front'] = [int(x) if isinstance(x, str) else x for x in d['front']]
            d['back'] = [int(x) if isinstance(x, str) else x for x in d['back']]
        total = len(self.history)
        if total == 0:
            return {'weights': [], 'total_periods': 0}
        
        # 前区权重（1-47）
        front_weights, front_freq, front_miss, front_avg_interval = self._calc_weights(
            range(1, 48), lambda d: d['front'], total
        )
        
        # 后区权重（1-38）
        back_weights, back_freq, back_miss, back_avg_interval = self._calc_weights(
            range(1, 39), lambda d: d['back'], total
        )
        
        # 前区分区（1-15/16-31/32-47三区）
        zone_balance = [0, 0, 0]
        for d in self.history[:5]:
            for n in d['front']:
                num = int(n) if isinstance(n, str) else n
                zone = min((num-1) // 16, 2)
                zone_balance[zone] += 1
        
        # 和值范围
        sums = [sum(d['front']) for d in self.history]
        avg_sum = sum(sums) / len(sums) if sums else 0
        
        # 按权重排序
        hot_fronts = sorted(front_weights.items(), key=lambda x: x[1], reverse=True)
        hot_backs = sorted(back_weights.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'front_weights': hot_fronts,
            'back_weights': hot_backs,
            'front_freq': front_freq,
            'back_freq': back_freq,
            'front_miss': front_miss,
            'back_miss': back_miss,
            'zone_balance': zone_balance,
            'avg_sum': avg_sum,
            'total_periods': total,
        }


