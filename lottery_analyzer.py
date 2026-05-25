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
        return {'positions': pos_data, 'total_periods': total}

    def generate_recs_qxc(self, analysis):
        """根据加权分析生成七星彩推荐（逐位选号）
        核心注A: 每位权重最高（P0-35%）
        核心注B: 完全独立（权重TOP7-11，和A不重叠）（P0-35%）
        扩展1: 前3位核心+后4位次高权重（P1-20%）
        扩展2: 前2位核心+后5位中等频率（P2-23%）
        冷号注: 每位遗漏最高（P3-22%）
        """
        positions = analysis['positions']
        total = analysis.get('total_periods', 15)

        # 权重排序（每位前11个号码）
        all_pool = []
        for pos_idx, pos_data in enumerate(positions):
            weights = pos_data['weights']
            all_pool.append([n for n, w in weights[:11]])

        # 核心注A: 每位权重TOP1
        core_A = [pool[0] if pool else 0 for pool in all_pool]

        # 核心注B: 完全独立（TOP7-11，和A不重叠）
        core_B = []
        for pos_idx, pool in enumerate(all_pool):
            for n in pool[6:11]:  # TOP7-11
                if n not in core_A:
                    core_B.append(n)
                    break
            else:
                core_B.append(pool[1] if len(pool) > 1 else (pool[0] if pool else 0))

        # 扩展1: 前3位核心+后4位次高权重
        ext1 = list(core_A)
        for i in range(3, 7):
            weights = positions[i]['weights']
            ext1[i] = weights[1][0] if len(weights) > 1 else (weights[0][0] if weights else 0)

        # 扩展2: 前2位核心+后5位中等频率
        ext2 = list(core_A)
        for i in range(2, 7):
            freq = positions[i]['freq']
            mid = [n for n, c in freq.items() if 2 <= c <= 3]
            if not mid:
                miss = positions[i]['miss']
                mid = sorted(miss.keys(), key=lambda x: miss.get(x, 0), reverse=True)[:1]
            ext2[i] = mid[0] if mid else (positions[i]['weights'][0][0] if positions[i]['weights'] else 0)

        # 冷号注: 每位遗漏最高
        cold = []
        for pos_data in positions:
            miss = pos_data['miss']
            if miss:
                cold_num = sorted(miss.keys(), key=lambda x: miss[x], reverse=True)[0]
            else:
                cold_num = pos_data['weights'][0][0] if pos_data['weights'] else 0
            cold.append(cold_num)

        return [
            {'digits': core_A, 'strategy': '核心注(权重)A'},
            {'digits': core_B, 'strategy': '核心注(权重)B'},
            {'digits': ext1, 'strategy': '扩展1(次热)'},
            {'digits': ext2, 'strategy': '扩展2(回补)'},
            {'digits': cold, 'strategy': '冷号注(遗漏)'},
        ]

    def _smart_blue_select(self, analysis, mode='hot', exclude=None):
        """🔴 双色球蓝球智能选号(1-16)
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
                # 🟢 v6.5: hot模式加周期信号作负向 - 到期号反而不热
                blue_avg_interval = analysis.get('blue_avg_interval', {}).get(n, 10)
                cycle_signal = min(miss_val / max(blue_avg_interval, 1), 2.0)
                # cycle_signal>1=到期(冷号特征), 热模式应减分
                hot_penalty = max(0, (cycle_signal - 1.0)) * 1.5  # 到期号扣分
                scores[n] = weight_score * 0.4 + freq_score * 0.4 + miss_score * 0.2 - hot_penalty
            elif mode == 'mix':
                scores[n] = weight_score * 0.3 + freq_score * 0.3 + miss_score * 0.4
            elif mode == 'miss':
                # 🟢 v6.8: 冷号评分 - 权重从配置读取
                blue_avg_interval = analysis.get('blue_avg_interval', {}).get(n, 10)
                cycle_signal = min(miss_val / max(blue_avg_interval, 1), 2.0)  # >1=到期, <1=未到
                scores[n] = miss_score * self.cold_miss_back + cycle_signal * self.cold_cycle_back + freq_score * self.cold_freq_back

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[0][0] if ranked else 1

    def _select_blues_with_shape(self, analysis, n_blues=4):
        """🟢 v6.3: 蓝球整体选号 - 强制奇偶2:2、大小2:2形态约束
        先算每个蓝球综合得分,再在满足形态约束的组合中选总分最高的
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

        # 🟢 v6.3: 形态约束 - 奇偶2:2 + 大小2:2
        # 如果4个蓝球不能满足约束,放宽为3:1或2:2
        best_combo = None
        best_total = -1
        # 从TOP8中选4个,搜索满足约束的最佳组合
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
        # 回退:取TOP4
        return [n for n, s in sorted_blues[:n_blues]]

    def _select_backs_distributed(self, analysis, n_pairs=4):
        """🟢 v6.3: 大乐透后区分散选号 - 4组后区8个号尽量不重复
        每组2个后区号(1-12),4组共8个号最大覆盖
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

        # 贪心分配:每组选2个最高分但未用过的号
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
            # 奇偶约束:尽量一奇一偶
            if len(pair) == 2:
                odds = sum(1 for n in pair if n % 2 == 1)
                if odds == 2 or odds == 0:
                    # 全奇或全偶,尝试替换一个
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
        """🟢 v6.4: 形态优化选号 - 贪心搜索,支持大候选池
        candidates: 候选号码列表(支持20+个)
        n_select: 选几个号
        target_sum: 目标和值
        target_odd: 目标奇数个数
        target_big: 目标大号个数
        must_include: 必须包含的号码
        big_threshold: 大号阈值(SSQ=17, DLT=18)
        """
        must_include = must_include or []
        # 🟢 v6.4: 贪心搜索替代暴力枚举,支持20+候选
        # 策略:必须包含的号先加入,然后贪心添加最改善形态的号
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
                # 评分:和值偏差 + 奇偶偏差 + 大小偏差
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
        """根据加权分析生成双色球推荐(纯数学,不依赖AI)
        🟢 v6.5: SSQ gamma降到0.85,蓝球16选1也稀疏需更快衰减
        """
        self.gamma = min(self.gamma, 0.85)
        # 追热:权重最高的6个红球 + 最高权重蓝球
        hot_reds = sorted([n for n, w in analysis['red_weights'][:10]][:6])
        hot_blue = analysis['blue_weights'][0][0]

        # 回补:遗漏值最高的6个红球 + 最高遗漏蓝球
        miss_reds = sorted([(n, analysis['red_miss'].get(n, 0)) for n in range(1, 34)],
                          key=lambda x: x[1], reverse=True)[:6]
        miss_red_nums = sorted([n for n, m in miss_reds])
        miss_blues = sorted([(n, analysis['blue_miss'].get(n, 0)) for n in range(1, 17)],
                           key=lambda x: x[1], reverse=True)
        miss_blue = miss_blues[0][0]

        # 综合:频率中等+遗漏中等 的平衡选号
        mid_reds = sorted([(n, analysis['red_freq'].get(n, 0) + analysis['red_miss'].get(n, 0))
                          for n in range(1, 34)], key=lambda x: x[1], reverse=True)
        # 取频率3-6次的号码(中等热度)
        mid_pool = [n for n, f in mid_reds if 2 <= analysis['red_freq'].get(n, 0) <= 5][:6]
        if len(mid_pool) < 6:
            mid_pool = sorted([n for n, w in analysis['red_weights'][3:12]][:6])
        mid_blue = analysis['blue_weights'][1][0] if len(analysis['blue_weights']) > 1 else 1

        # 🟢 v6.1: Kelly驱动核心注 - kelly_bias调节热号/冷号比例
        # kelly_bias > 0 → 核心注偏热号(追求命中率,Kelly高时值得投)
        # kelly_bias < 0 → 核心注偏冷号(搏大奖小注,Kelly低时小博大)
        # kelly_bias = 0 → 默认均衡(纯权重排名)
        red_weight_dict = dict(analysis['red_weights'])
        all_pool = []
        for n in range(1, 34):
            w = red_weight_dict.get(n, 0)
            all_pool.append((n, w, analysis['red_freq'].get(n, 0), analysis['red_miss'].get(n, 0)))

        if kelly_bias > 0:
            # 🔥 Kelly高:核心注偏热 - 归一化频率+权重排序
            max_freq = max(x[2] for x in all_pool) or 1
            max_weight = max(x[1] for x in all_pool) or 1
            all_pool.sort(key=lambda x: (x[2]/max_freq) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
            strategy_tag = Strategy.CORE_HOT
        elif kelly_bias < 0:
            # ❄️ Kelly低:核心注偏冷 - 归一化遗漏+权重排序
            max_miss = max(x[3] for x in all_pool) or 1
            max_weight = max(x[1] for x in all_pool) or 1
            all_pool.sort(key=lambda x: (x[3]/max_miss) * 0.5 + (x[1]/max_weight) * 0.5, reverse=True)
            strategy_tag = Strategy.CORE_COLD
        else:
            # ⚖️ 默认:纯权重排序
            all_pool.sort(key=lambda x: x[1], reverse=True)
            strategy_tag = Strategy.CORE_WEIGHTED

        core_reds_by_weight = [n for n, w, f, m in all_pool[:6]]
        core_reds = sorted(core_reds_by_weight)
        # 🟢 v6.4: 蓝球按策略需求分配 - 核心注得热蓝,冷号注得周期回补蓝
        core_blue = self._smart_blue_select(analysis, mode='hot' if kelly_bias >= 0 else 'miss')
        ext1_blue = self._smart_blue_select(analysis, mode='mix', exclude={core_blue})
        ext2_blue = self._smart_blue_select(analysis, mode='mix', exclude={core_blue, ext1_blue})  # 🟢 v6.5: 扩展2红球偏热配均衡蓝
        cold_blue = self._smart_blue_select(analysis, mode='miss', exclude={core_blue, ext1_blue, ext2_blue})

        # 🔴 优化v7.5: P0核心注占35%(2注)，P1激进注降至20%(1注)
        # 观察期: 2026-05-21~05-23，3天后评估是否锁定
        # 旧值备用: P0=28% P1=29% P2=21% P3=21%
        # 核心注A: 权重TOP6
        core_reds_A = sorted(core_reds_by_weight[:6])
        # 核心注B: 完全独立（从 all_pool[6:11] 选6个，和A不重叠）
        if len(all_pool) >= 11:
            core_reds_B = sorted([n for n, w, f, m in all_pool[6:11]])
        else:
            # 数据不够时，B取权重TOP7-12（如果有的话）
            remaining = sorted(set([n for n, w, f, m in all_pool[6:]]) - set(core_reds_A))
            core_reds_B = sorted(list(remaining)[:6]) if remaining else core_reds_A


        core_blue = self._smart_blue_select(analysis, mode='hot' if kelly_bias >= 0 else 'miss')
        ext1_blue = self._smart_blue_select(analysis, mode='mix', exclude={core_blue})
        ext2_blue = self._smart_blue_select(analysis, mode='mix', exclude={core_blue, ext1_blue})
        cold_blue = self._smart_blue_select(analysis, mode='miss', exclude={core_blue, ext1_blue, ext2_blue})

        # 🔴 Bug修复:扩展注保留的是权重最高的号,不是号码最小的号
        # 扩展1(P1激进注): 保留权重最高的4号 + 替换2个为权重次高号
        ext1_keep = sorted(core_reds_by_weight[:4])
        ext1_new = sorted([n for n, w, f, m in all_pool[6:8] if n not in ext1_keep][:2])
        ext1_reds = sorted(ext1_keep + ext1_new)
        # 🟢 v6.4: 扩展2(P2回补注) - 形态模拟选号(从TOP20贪心搜索和值/奇偶/大小最优组合)
        target_sum = analysis.get('avg_sum', 100)
        target_odd = 3
        target_big = 3

        top20 = [n for n, w, f, m in all_pool[:20]]
        ext2_reds = self._shape_optimized_select(top20, 6, target_sum, target_odd, target_big,
                                                  core_reds_by_weight[:2])  # 🟢 v6.5: 只锁TOP2,留4号自由调形态

        # 🟢 v6.8: 冷号注红球 - 权重从配置读取,auto_evolve可调
        used_reds = set(core_reds_A) | set(core_reds_B) | set(ext1_reds) | set(ext2_reds)
        cold_scores = []
        red_avg_interval = analysis.get('red_avg_interval', {})
        for n in range(1, 34):
            miss_val = analysis['red_miss'].get(n, 0)
            miss_score = min(miss_val / 10.0, 3.0)
            avg_interval = red_avg_interval.get(n, 15)
            cycle_signal = min(miss_val / max(avg_interval, 1), 2.0)
            f = analysis['red_freq'].get(n, 0)
            f_score = min(f / 3.0, 1.5)
            score = miss_score * self.cold_miss_front + cycle_signal * self.cold_cycle_front + f_score * self.cold_freq_front
            cold_scores.append((n, score))
        cold_scores.sort(key=lambda x: x[1], reverse=True)
        cold_red_nums = sorted([n for n, s in cold_scores if n not in used_reds][:6])

        return [
            {'reds': core_reds_A, 'blue': core_blue, 'strategy': strategy_tag},  # P0核心注A
            {'reds': core_reds_B, 'blue': core_blue, 'strategy': strategy_tag},  # P0核心注B(35%)
            {'reds': ext1_reds, 'blue': ext1_blue, 'strategy': Strategy.EXT1_WEIGHTED},  # P1激进注(20%)
            {'reds': ext2_reds, 'blue': ext2_blue, 'strategy': Strategy.EXT2_WEIGHTED},  # P2回补注(23%)
            {'reds': cold_red_nums, 'blue': cold_blue, 'strategy': Strategy.COLD_MISS},  # P3冷号注(22%)
        ]

    def _smart_back_select(self, analysis, count=2, mode='hot', exclude=None):
        """🔴 大乐透后区智能选号(v2优化版)
        综合考虑:权重+遗漏+奇偶+大小+振幅,而非仅靠权重排名
        exclude: set of back numbers already used (for dispersion)

        mode:
          - 'hot': 热号为主(核心注)
          - 'mix': 热号+遗漏回补(扩展1)
          - 'miss': 遗漏回补为主(扩展2)
        """
        back_weight_dict = dict(analysis['back_weights'])
        back_miss = analysis['back_miss']
        back_freq = analysis['back_freq']

        # 综合评分:权重(40%) + 遗漏回补力(30%) + 近期活跃度(30%)
        scores = {}
        exclude = exclude or set()
        for n in range(1, 13):
            if n in exclude:
                continue
            weight_score = back_weight_dict.get(n, 0)
            # 遗漏回补力:遗漏越大,回补概率越高(但超过10期可能偏冷)
            miss_val = back_miss.get(n, 0)
            if miss_val >= 8:
                miss_score = 3.0  # 深度遗漏,强回补信号
            elif miss_val >= 5:
                miss_score = 2.5
            elif miss_val >= 3:
                miss_score = 1.5
            elif miss_val == 0:
                miss_score = 1.0  # 刚出,回补力弱
            else:
                miss_score = 0.8

            # 近期活跃度:近5期出现次数
            freq_score = min(back_freq.get(n, 0), 4) / 2.0

            if mode == 'hot':
                # 核心注:权重+活跃度优先
                scores[n] = weight_score * 0.4 + freq_score * 0.4 + miss_score * 0.2
            elif mode == 'mix':
                # 扩展1:均衡
                scores[n] = weight_score * 0.3 + freq_score * 0.3 + miss_score * 0.4
            elif mode == 'miss':
                # 🟢 v6.8: 冷号评分 - 权重从配置读取
                back_avg_interval = analysis.get('back_avg_interval', {}).get(n, 10)
                cycle_signal = min(miss_val / max(back_avg_interval, 1), 2.0)
                scores[n] = miss_score * self.cold_miss_back + cycle_signal * self.cold_cycle_back + freq_score * self.cold_freq_back

        # 按评分排序
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # 🔴 奇偶约束:优先选"一奇一偶"组合(占比47%,最高频)
        # 🔴 大小约束:优先选"一小一大"组合(占比60%,最高频)
        best_pair = None
        best_score = -1

        # 从TOP6候选中搜索最佳奇偶+大小组合
        candidates = [n for n, s in ranked[:6]]
        for i in range(len(candidates)):
            for j in range(i+1, len(candidates)):
                pair = sorted([candidates[i], candidates[j]])
                # 奇偶检查
                odd_count = sum(1 for n in pair if n % 2 == 1)
                # 大小检查(1-6小,7-12大)
                big_count = sum(1 for n in pair if n >= 7)

                bonus = 0
                # 奇偶加分:一奇一偶最优先
                if odd_count == 1:
                    bonus += 0.5
                # 大小加分:一小一大最优先
                if big_count == 1:
                    bonus += 0.5
                # 连号微调(出现概率17%,不算高但值得覆盖)
                if abs(pair[0] - pair[1]) == 1:
                    bonus += 0.2

                pair_score = scores[candidates[i]] + scores[candidates[j]] + bonus
                if pair_score > best_score:
                    best_score = pair_score
                    best_pair = pair

        if best_pair:
            return best_pair

        # 降级:直接取评分前2
        return sorted([ranked[0][0], ranked[1][0]])

    def generate_recs_dlt(self, analysis, kelly_bias=0.0):
        """根据加权分析生成大乐透推荐
        🟢 v6.1: Kelly驱动选号 - kelly_bias越高越偏热号,越低越偏冷号
        🔴 v6.8: 删除gamma=0.85 clamp,由GEPA统一管理gamma
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
        # 🔴 优化v7.5: P0核心注占35%(2注),P1降至20% - 观察期05-21~05-23
        core_front_A = sorted(core_front_by_weight[:5])
        # 核心注B: 完全独立(TOP6-10,和A不重叠)
        core_front_B_pool = [n for n, w, f, m in all_pool[5:10]]
        if len(core_front_B_pool) >= 5:
            core_front_B = sorted(core_front_B_pool)
        else:
            core_front_B = core_front_A  # fallback
        
        # 核心后区（DLT后区1-12）
        back_weight_list = analysis.get('back_weights', [])
        back_miss_dict = analysis.get('back_miss', {})
        core_back = back_weight_list[0][0] if back_weight_list else 1
        core_back_2 = back_weight_list[1][0] if len(back_weight_list) > 1 else core_back

        # 扩展1: 频率TOP3 + 次高2号（DLT前区5个号）
        top8 = sorted(all_pool, key=lambda x: x[1], reverse=True)
        ext1_keep = sorted([n for n, w, f, m in top8[:3]])
        ext1_new = sorted([n for n, w, f, m in top8[6:10] if n not in ext1_keep][:2])
        ext1_front = sorted(ext1_keep + ext1_new)
        # 扩展1后区: 权重第3+权重第4
        ext1_back_1 = back_weight_list[2][0] if len(back_weight_list) > 2 else core_back
        ext1_back_2 = back_weight_list[3][0] if len(back_weight_list) > 3 else core_back_2

        # 扩展2: 核心2号 + 频率中等号(出现2-3次)
        ext2_keep = sorted(core_front_by_weight[:2])
        mid_freq = sorted([(n, f) for n, w, f, m in all_pool if 2 <= f <= 3 and n not in core_front_by_weight][:3])
        if len(mid_freq) < 3:
            mid_freq = sorted([(n, f) for n, w, f, m in all_pool if f <= 1 and n not in core_front_by_weight][:3])
        ext2_front = sorted(ext2_keep + [n for n, f in mid_freq[:3]])
        # 扩展2后区: 权重次热+遗漏回补
        ext2_back_1 = back_weight_list[1][0] if len(back_weight_list) > 1 else core_back
        # 遗漏最高的后区号
        back_miss_sorted = sorted(back_miss_dict.items(), key=lambda x: x[1], reverse=True) if back_miss_dict else []
        ext2_back_2 = back_miss_sorted[0][0] if back_miss_sorted else core_back_2

        # 冷号注(遗漏最高的号码)
        miss_front = sorted([(n, m) for n, w, f, m in all_pool if m > 0], key=lambda x: x[1], reverse=True)
        if not miss_front:
            miss_front = sorted([(n, 0) for n in range(1, 36) if n not in [x[0] for x in all_pool[:5]]][:5])
        cold_front = sorted([n for n, m in miss_front[:5]])
        # 冷号后区: 遗漏最高的两个
        cold_back_1 = back_miss_sorted[0][0] if len(back_miss_sorted) > 0 else 1
        cold_back_2 = back_miss_sorted[1][0] if len(back_miss_sorted) > 1 else cold_back_1

        return [
            {'front': core_front_A, 'back': [core_back, core_back_2], 'strategy': '核心注(加权)A'},
            {'front': core_front_B, 'back': [core_back, core_back_2], 'strategy': '核心注(加权)B'},
            {'front': ext1_front, 'back': [ext1_back_1, ext1_back_2], 'strategy': '扩展1(加权)'},
            {'front': ext2_front, 'back': [ext2_back_1, ext2_back_2], 'strategy': '扩展2(加权)'},
            {'front': cold_front, 'back': [cold_back_1, cold_back_2], 'strategy': '冷号注(遗漏)'},
        ]


# ===== 格式化输出 =====

def format_lottery_section(ssq_result=None, dlt_result=None, qxc_result=None, backtest_result=None):
    lines = []
    lines.append("\n---\n")
    lines.append("## 🎰 彩票号码推荐 - 刘海蟾点金(仅供娱乐参考)\n")
    lines.append("> ⚠️ 彩票本质是随机事件,以下由刘海蟾点金算法基于历史数据规律推算,不构成任何投注建议。理性购彩,量力而行。\n")

    # 🔴 开奖日历提示 + 🟢 v6吸收:下期开奖日期+休市提示
    today_games = get_draw_games()
    tomorrow_games = get_draw_games_tomorrow()
    if today_games:
        today_names = '、'.join(LOTTERY_NAMES.get(g, g) for g in today_games)
        lines.append(f"📅 **今天开奖**: {today_names}\n")
    if tomorrow_games:
        tomorrow_names = '、'.join(LOTTERY_NAMES.get(g, g) for g in tomorrow_games)
        lines.append(f"📅 **明天开奖**: {tomorrow_names}\n")

    # 🟢 v6吸收:下期开奖日期(含休市跳过)+ 今日是否休市
    today_str = datetime.now(CST).strftime('%Y-%m-%d')
    today_holiday = is_holiday(today_str)
    if today_holiday:
        lines.append(f"🔴 **休市提醒**: 今日({today_str})处于{today_holiday}期间,暂停开奖\n")
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

    # 🔴 增强版回测结果(逐号对比)- v6.8: 用当前版本代码回测
    if backtest_result:
        draw_games = backtest_result.get('draw_games', [])
        draw_names_str = '、'.join(LOTTERY_NAMES.get(g, g) for g in draw_games)
        method = backtest_result.get('backtest_method', 'legacy')
        method_note = '(当前版本算法回测)' if method == 'current_version' else '(旧版推荐记录)'
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
                prize_tag = f" 🏆{h.get('prize_name', '')}({h.get('prize_amount', 0)}元)" if h.get('prize_tier', 0) > 0 else ''
                lines.append(f"  {h['strategy']}: {pred_r} + 蓝{h['predicted_blue']:02d} → 红球{h['red_hits']}/6({hit_nums}) 蓝球{blue_status} = {h['total']}{prize_tag}")
            lines.append(f"  ▶ 最佳: {ssq['best_strategy']}({ssq['best_total']}个)")
            # 🔴 v7.4: 奖金汇总+基线对比
            total_prize = ssq.get('total_prize', 0)
            total_cost = ssq.get('total_cost', 0)
            lines.append(f"  💰 奖金: {total_prize}元 / 投入: {total_cost}元")
            baseline = ssq.get('baseline', {})
            if baseline:
                lines.append(f"  📊 随机基线: 均值{baseline['avg']}个(100次) vs 策略最佳{ssq['best_total']}个")
            ai_hit = ssq.get('ai_hit', {})
            if ai_hit:
                lines.append(f"  🤖 AI推荐回测: 最佳{ai_hit.get('best_total', 0)}个, 奖金{ai_hit.get('total_prize', 0)}元")
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
                lines.append(f"  {h['strategy']}: {pred_f} + 后{' '.join(f'{n:02d}' for n in h['predicted_back'])} → 前区{h['front_hits']}/5({hit_f}) 后区{h['back_hits']}/2({hit_b}) = {h['total']}" +
                             (f" 🏆{h.get('prize_name', '')}({h.get('prize_amount', 0)}元)" if h.get('prize_tier', 0) > 0 else ''))
            lines.append(f"  ▶ 最佳: {dlt['best_strategy']}({dlt['best_total']}个)")
            # 🔴 v7.4: 奖金汇总+基线对比
            total_prize = dlt.get('total_prize', 0)
            total_cost = dlt.get('total_cost', 0)
            lines.append(f"  💰 奖金: {total_prize}元 / 投入: {total_cost}元")
            baseline = dlt.get('baseline', {})
            if baseline:
                lines.append(f"  📊 随机基线: 均值{baseline['avg']}个(100次) vs 策略最佳{dlt['best_total']}个")
            ai_hit = dlt.get('ai_hit', {})
            if ai_hit:
                lines.append(f"  🤖 AI推荐回测: 最佳{ai_hit.get('best_total', 0)}个, 奖金{ai_hit.get('total_prize', 0)}元")
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
                lines.append(f"  {h['strategy']}: {pred_d} → {pos_marks}= {h['digit_hits']}/7" +
                             (f" 🏆{h.get('prize_name', '')}({h.get('prize_amount', 0)}元)" if h.get('prize_tier', 0) > 0 else ''))
            lines.append(f"  ▶ 最佳: {qxc['best_strategy']}({qxc['best_total']}个)")
            # 🔴 v7.4: 奖金汇总+基线对比
            total_prize = qxc.get('total_prize', 0)
            total_cost = qxc.get('total_cost', 0)
            lines.append(f"  💰 奖金: {total_prize}元 / 投入: {total_cost}元")
            baseline = qxc.get('baseline', {})
            if baseline:
                lines.append(f"  📊 随机基线: 均值{baseline['avg']}个(100次) vs 策略最佳{qxc['best_total']}个")
            ai_hit = qxc.get('ai_hit', {})
            if ai_hit:
                lines.append(f"  🤖 AI推荐回测: 最佳{ai_hit.get('best_total', 0)}个, 奖金{ai_hit.get('total_prize', 0)}元")
            lines.append("")

    if ssq_result:
        history, recs = ssq_result
        lines.append("### 🔴 双色球")
        lines.append(f"(近{len(history)}期数据,刘海蟾点金)\n")
        lines.append("**近期开奖:**")
        lines.append("| 期号 | 红球 | 蓝球 |")
        lines.append("|------|------|------|")
        for draw in history[:3]:
            reds_str = ' '.join(f'{n:02d}' for n in draw['reds'])
            lines.append(f"| {draw['period']} | {reds_str} | {draw['blue']:02d} |")
        if recs:
            lines.append("\n**下期推荐:**")
            for rec in recs:
                reds_str = ' '.join(f'{n:02d}' for n in rec['reds'])
                lines.append(f"- [{rec['strategy']}] {reds_str} + 蓝球{rec['blue']:02d}")
        else:
            lines.append("\n**⚠️ 推算失败**")

    if dlt_result:
        history, recs = dlt_result
        lines.append("### 🟡 大乐透")
        lines.append(f"(近{len(history)}期数据,刘海蟾点金)\n")
        lines.append("**近期开奖:**")
        lines.append("| 期号 | 前区 | 后区 |")
        lines.append("|------|------|------|")
        for draw in history[:3]:
            front_str = ' '.join(f'{n:02d}' for n in draw['front'])
            back_str = ' '.join(f'{n:02d}' for n in draw['back'])
            lines.append(f"| {draw['period']} | {front_str} | {back_str} |")
        if recs:
            lines.append("\n**下期推荐:**")
            for rec in recs:
                front_str = ' '.join(f'{n:02d}' for n in rec['front'])
                back_str = ' '.join(f'{n:02d}' for n in rec['back'])
                lines.append(f"- [{rec['strategy']}] `{front_str}` + 🔵`{back_str}`")
        else:
            lines.append("\n**⚠️ 推算失败**")

    if qxc_result:
        history, recs = qxc_result
        lines.append("### 🟢 七星彩")
        lines.append(f"(近{len(history)}期数据,刘海蟾点金)\n")
        lines.append("**近期开奖:**")
        lines.append("| 期号 | 号码 |")
        lines.append("|------|------|")
        for draw in history[:3]:
            digits_str = ' '.join(str(n) for n in draw['digits'])
            lines.append(f"| {draw['period']} | {digits_str} |")
        if recs:
            lines.append("\n**下期推荐:**")
            for rec in recs:
                digits_str = ' '.join(str(n) for n in rec['digits'])
                lines.append(f"- [{rec['strategy']}] `{digits_str}`")
        else:
            lines.append("\n**⚠️ 推算失败**")

    # 🔴 开奖日历速查
    lines.append("\n📅 **开奖日历**: 大乐透(一三六) | 双色球(二四日) | 七星彩(二五日)")

    # 🟢 P2: Kelly仓位建议 + 🔴 Kelly>5%重点关注复式建议
    import json
    try:
        with open('/root/asuan-scheduler/weight-config.json', 'r') as f:
            config = json.load(f)
    except Exception:
        config = {}
    lines.append(f"\n⚖️ **风控提示**:")

    # 收集Kelly>5%的彩种,用于生成复式建议
    high_kelly_games = []

    for game_name, game_key, total_nums in [('双色球', 'ssq', 7), ('大乐透', 'dlt', 7), ('七星彩', 'qxc', 7)]:
        hit_prob = estimate_hit_probability(game_key, 4, total_nums)
        # 🔴 BugD修复:Kelly赔率匹配真实奖级
        odds_map = {'ssq': 50, 'dlt': 50, 'qxc': 100}
        k = kelly_fraction(hit_prob, odds_map.get(game_key, 200))
        if k > 0:
            lines.append(f"  {game_name}核心注: Kelly={k:.2%}(建议投入≤本金的{k:.1%})")
            if k > 0.05:
                high_kelly_games.append((game_name, game_key, k))
        else:
            lines.append(f"  {game_name}核心注: Kelly≤0(❌不建议本期投注)")

    # 🔴 Kelly>5%重点关注:复式购买建议
    if high_kelly_games:
        lines.append(f"\n🔥 **Kelly>5%重点关注**:")
        for game_name, game_key, k in high_kelly_games:
            lines.append(f"\n**{game_name}** Kelly={k:.2%} ⬆️ 值得加码")

            # 根据彩种生成复式建议
            if game_key == 'ssq':
                lines.append("  📋 复式方案建议:")
                lines.append("  - 🔹 小复式:红7+1(14元)- 覆盖1个额外红球")
                lines.append("  - 🔸 中复式:红8+1(56元)- 覆盖2个额外红球")
                lines.append("  - 🔶 大复式:红6+2(12元)- 覆盖1个额外蓝球")
                lines.append("  - 💡 推荐:红7+1或红6+2,性价比最高")
            elif game_key == 'dlt':
                lines.append("  📋 复式方案建议:")
                lines.append("  - 🔹 小复式:前6+2(12元)- 覆盖1个额外前区")
                lines.append("  - 🔸 中复式:前7+2(42元)- 覆盖2个额外前区")
                lines.append("  - 🔶 大复式:前5+3(18元)- 覆盖1个额外后区")
                lines.append("  - 💡 推荐:前6+2或前5+3,性价比最高")
            elif game_key == 'qxc':
                lines.append("  📋 复式方案建议:")
                lines.append("  - 🔹 小复式:选8个号码复式(16元)- 多1位覆盖")
                lines.append("  - 🔸 中复式:选9个号码复式(36元)- 多2位覆盖")
                lines.append("  - 💡 推荐:选8个号码复式,性价比最高")

            lines.append(f"  ⚠️ Kelly={k:.1%}意味着建议用本金的{k:.1%}投注,不要超过此比例")
    else:
        lines.append(f"\n📌 本期无Kelly>5%彩种,建议单式小额为主")

    # 🟢 v6吸收:购彩策略建议(源自chinese-lottery-predict预算模块)
    budget = BUDGET_CONFIG['default']
    price = BUDGET_CONFIG['price_per_bet']
    max_bets = budget // price
    lines.append(f"\n💡 **购彩策略** (预算{budget}元):")
    if max_bets >= 4:
        lines.append(f"  - 可购{max_bets}注(每注{price}元),推荐:核心注×1 + 扩展1×1 + 冷号注×1 + 备选×1")
        lines.append(f"  - 💰 省钱方案:核心注×1 + 冷号注×1 = {price*2}元(覆盖追热+搏冷)")
    elif max_bets >= 2:
        lines.append(f"  - 可购{max_bets}注,推荐:核心注×1 + 冷号注×1")
    elif max_bets >= 1:
        lines.append(f"  - 可购{max_bets}注,推荐:核心注×1")
    else:
        lines.append(f"  - ⚠️ 预算不足{price}元,无法购买完整注")
    lines.append(f"  - 🎯 核心注=权重追热 | 冷号注=遗漏搏冷 | 两者互补覆盖面最广")

    algo_ver = config.get('algo_version', 'v3.0')
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


# ===== Orchestrator桥接 =====

def _load_orchestrator_context():
    """从DB读取Orchestrator最新context（v3.0统一进化路径）
    Orchestrator.daily_run()产出context写入algo_state.db
    此函数供lottery_analyzer读取，替代原来直接调run_algo_evolve()的双路径问题
    返回dict: {mode, entropy_ratio, bayesian_adj, markov_signals, confidence, ...} 或 None
    """
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'algo_state.db')
    if not os.path.exists(db_path):
        print("[Orchestrator桥接] algo_state.db不存在，Orchestrator尚未运行")
        return None
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''SELECT context FROM algo_orchestrator_context
                     ORDER BY date DESC LIMIT 1''')
        row = c.fetchone()
        conn.close()
        if row:
            context = json.loads(row[0])
            mode = context.get('mode', '?')
            entropy = context.get('entropy_ratio', '?')
            print(f"[Orchestrator桥接] 读取成功: 模式={mode}, 熵比={entropy}")
            return context
        else:
            print("[Orchestrator桥接] DB中无context记录")
            return None
    except Exception as e:
        print(f"[Orchestrator桥接] 读取失败: {e}")
        return None


# ===== 主入口 =====

def generate_lottery_recommendations():
    """主函数:回测昨日 → GEPA自动进化 → 抓取数据 → 刘海蟾点金 → 格式化 → 保存记录"""
    print("[彩票] 开始生成推荐(刘海蟾点金模式)...")
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # 🔴 v6.8→v3.0: 执行顺序 = 回测→读取Orchestrator进化结果→推荐
    # 第1步:先用当前权重回测昨日(测试的是"昨天推荐时的权重")
    print("[回测] 用当前版本代码回测昨日开奖...")
    backtest_result = None
    try:
        backtest_result = _run_backtest()
    except NameError:
        print("[回测] _run_backtest未定义,跳过回测")
    except Exception as e:
        print(f"[回测] 回测失败: {e}")
    backtest_feedback = _format_backtest_for_ai(backtest_result) if backtest_result else None
    if backtest_feedback:
        print(f"[回测] 已生成回测反馈: {len(backtest_feedback)}字符")

    # 第2步(v3.0重构):从DB读取Orchestrator已产出的进化结果,不再独立调run_algo_evolve
    # 原因:generate_lottery_recommendations()和Orchestrator.daily_run()都有进化逻辑,
    # 双路径会互相覆盖权重。v3.0统一由Orchestrator负责进化,此处只读取结果。
    evolved_config = _load_orchestrator_context()
    if evolved_config:
        print(f"[AlgoEngine] 读取Orchestrator进化结果: 模式={evolved_config.get('mode', '?')}, "
              f"熵比={evolved_config.get('entropy_ratio', '?')}")
    else:
        import json
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'weight-config.json'), 'r') as f: config = json.load(f)
        except Exception: config = {}
        print("[AlgoEngine] 无Orchestrator记录,使用当前权重配置")

    ssq_result = None
    dlt_result = None
    qxc_result = None

    # 🟢 v6.2: Kelly驱动选号 - 用多奖级EV替代单一赔率
    kelly_map = {}  # {game_key: kelly_value}
    for game_name, game_key, total_nums in [('双色球', 'ssq', 7), ('大乐透', 'dlt', 7), ('七星彩', 'qxc', 7)]:
        k_ev, eff_odds = kelly_ev_multitier(game_key)
        # 也用旧方法算一个,取较大值(多奖级EV更保守时用旧方法兜底)
        hit_prob = estimate_hit_probability(game_key, 4, total_nums)
        k_simple = kelly_fraction(hit_prob, eff_odds)
        kelly_map[game_key] = max(k_ev, k_simple)
    # 🟢 v6.2: Kelly→选号偏向连续映射(消除硬断层)
    # 用tanh平滑过渡: Kelly=0→bias=0, Kelly>5%→bias趋近+0.5, Kelly<0→bias趋近-0.5
    def _kelly_to_bias(k):
        import math
        return math.tanh(k * 20) * 0.5  # 连续映射,无硬断层
    kelly_bias_map = {g: _kelly_to_bias(k) for g, k in kelly_map.items()}
    print(f"[Kelly] 双色球={kelly_map['ssq']:.2%}(bias={kelly_bias_map['ssq']:+.1f}) 大乐透={kelly_map['dlt']:.2%}(bias={kelly_bias_map['dlt']:+.1f}) 七星彩={kelly_map['qxc']:.2%}(bias={kelly_bias_map['qxc']:+.1f})")

    # 第3步:抓取数据并生成推荐(用进化后的权重)(🟢 v6.2: 七星彩请求30期因为隔期开奖,15期只能拿到6-8期)
    print("[彩票] 抓取双色球数据...")
    ssq_history = fetch_ssq_history(15)
    print("[彩票] 抓取大乐透数据...")
    dlt_history = fetch_dlt_history(15)
    print("[彩票] 抓取七星彩数据...")
    qxc_history = fetch_qxc_history(30)

    # 2. 刘海蟾一次性推算(带回测反馈)
    all_data_ok = (ssq_history and len(ssq_history) >= 5 and
                   dlt_history and len(dlt_history) >= 5 and
                   qxc_history and len(qxc_history) >= 5)

    # 第4步:生成推荐(用代码生成5注:P0×2+P1+P2+P3)
    # AI只用于回测对比,不覆盖主推荐
    def _gen_code_recs(game, history, kelly_bias=0.0):
        """用代码生成5注(P0核心×2 + P1激进 + P2回补 + P3冷号)"""
        wa = WeightedAnalyzer(history)
        analyze_method = f'analyze_{game}'
        analysis = getattr(wa, analyze_method)()
        gen_method = f'generate_recs_{game}'
        return getattr(wa, gen_method)(analysis, kelly_bias=kelly_bias)

    if ssq_history and len(ssq_history) >= 5:
        ssq_code_recs = _gen_code_recs('ssq', ssq_history, kelly_bias=kelly_bias_map.get('ssq', 0.0))
        ssq_result = (ssq_history, ssq_code_recs)
        print(f"[彩票] ✅ 双色球: {len(ssq_code_recs)}组(代码生成)")

    if dlt_history and len(dlt_history) >= 5:
        dlt_code_recs = _gen_code_recs('dlt', dlt_history, kelly_bias=kelly_bias_map.get('dlt', 0.0))
        dlt_result = (dlt_history, dlt_code_recs)
        print(f"[彩票] ✅ 大乐透: {len(dlt_code_recs)}组(代码生成)")

    if qxc_history and len(qxc_history) >= 5:
        qxc_code_recs = _gen_code_recs('qxc', qxc_history, kelly_bias=kelly_bias_map.get('qxc', 0.0))
        qxc_result = (qxc_history, qxc_code_recs)
        print(f"[彩票] ✅ 七星彩: {len(qxc_code_recs)}组(代码生成)")

    # 第5步:AI推算(仅用于回测对比,不覆盖主推荐)
    if all_data_ok:
        ssq_text = _format_ssq_for_ai(ssq_history, kelly_bias=kelly_bias_map.get('ssq', 0.0))
        dlt_text = _format_dlt_for_ai(dlt_history, kelly_bias=kelly_bias_map.get('dlt', 0.0))
        qxc_text = _format_qxc_for_ai(qxc_history, kelly_bias=kelly_bias_map.get('qxc', 0.0))
        print("[彩票] 调用刘海蟾(仅用于回测对比)...")
        ai_output = _call_jiran(ssq_text, dlt_text, qxc_text, backtest_feedback)
        if ai_output:
            print("[彩票] ✅ AI调用成功(用于独立回测)")
        else:
            print("[彩票] ⚠️ AI调用失败(不影响主推荐)")
    else:
        print("[彩票] 部分数据不足,仅用代码生成")

    # 3. 保存今日推荐(供明天回测用)
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
    # 如果今天已经有记录了,覆盖
    predictions = [p for p in predictions if p.get('date') != today_str]
    predictions.append(today_prediction)
    _save_predictions(predictions)
    print(f"[彩票] 今日推荐已保存(供明天回测)")

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
        print(f"[告警] 检测到{len(alerts)}个重大事件!已写入lottery-alerts.json")
    else:
        _save_alerts([], today_str)  # 清空旧告警
        print("[告警] 无重大事件")

    # 4. 在输出中附加回测结果
    result = format_lottery_section(ssq_result, dlt_result, qxc_result, backtest_result)

    # 🟢 v8.0→v3.0: 算法模块 - 策略自适应+组合优化
    try:
        from algo_module import run_algo_optimize
        algo_result = run_algo_optimize(ssq_result, dlt_result, qxc_result, kelly_map, BUDGET_CONFIG['default'])
        if algo_result:
            result += algo_result.format_section()
            print("[Algo] 算法模块输出已追加")
    except Exception as e:
        print(f"[Algo] 算法模块跳过: {e}")

    return result


# ===== 🔴 v7.4: 重大事件告警机制 =====

ALERT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-alerts.json')

def detect_lottery_alerts(evolved_config=None, backtest_result=None, kelly_map=None,
                          ssq_result=None, dlt_result=None, qxc_result=None,
                          ssq_history=None, dlt_history=None, qxc_history=None):
    """
    🔴 v7.4→v3.0: 重大事件告警检测
    检测9类重大事件,返回告警列表:
    1. Orchestrator模式切换(保守/激进)
    2. 熵比异常(偏低/偏高)
    3. 马尔可夫冷→热信号
    4. 回测命中爆发(单注≥4个号)
    5. 回测中奖通知(任何奖级≥4等)
    6. 冷号注首次命中
    7. Kelly值偏高(>3%)
    8. 规律发现(相关性/趋势/周期异常信号)
    9. 策略优于/劣于随机基线
    """
    alerts = []
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # === 1. Orchestrator模式切换告警(v3.0替换原GEPA重大更新) ===
    if evolved_config:
        mode = evolved_config.get('mode', 'normal')
        if mode != 'normal':
            mode_cn = {'conservative': '保守', 'aggressive': '激进'}.get(mode, mode)
            alerts.append({
                'level': '🔴',
                'type': 'orchestrator_mode',
                'title': f'Orchestrator进入{mode_cn}模式',
                'detail': f"当前模式={mode}, 熵比={evolved_config.get('entropy_ratio', '?')}",
                'action': '保守模式→缩小步长防过拟合;激进模式→加大步长捕捉趋势',
            })

    # === 2. 熵比异常检测(v3.0替换原GEPA空转检测) ===
    if evolved_config:
        entropy_ratio = evolved_config.get('entropy_ratio', 1.0)
        if isinstance(entropy_ratio, (int, float)):
            if entropy_ratio < 0.75:
                alerts.append({
                    'level': '⚠️',
                    'type': 'entropy_low',
                    'title': '号码分布熵比偏低!',
                    'detail': f"熵比={entropy_ratio:.4f}(阈值0.75),分布明显偏离均匀,可能有规律可循",
                    'action': '关注马尔可夫信号和贝叶斯修正,当前是捕捉规律的好时机',
                })
            elif entropy_ratio > 0.98:
                alerts.append({
                    'level': '📊',
                    'type': 'entropy_high',
                    'title': '号码分布接近随机',
                    'detail': f"熵比={entropy_ratio:.4f}(接近1.0),分布均匀,规律性弱",
                    'action': '当前不适合激进策略,建议保守投注',
                })

    # === 4. 回测命中爆发 + 中奖通知 + 基线对比 ===
    if backtest_result:
        for game in ['ssq', 'dlt', 'qxc']:
            if game not in backtest_result:
                continue
            game_name = LOTTERY_NAMES.get(game, game)
            hits = backtest_result[game].get('hits', [])
            baseline = backtest_result[game].get('baseline', {})
            ai_hit = backtest_result[game].get('ai_hit', {})

            # 命中爆发
            for h in hits:
                total = h.get('total', 0)
                strategy = str(h.get('strategy', ''))
                prize_name = h.get('prize_name', '未中奖')
                prize_amount = h.get('prize_amount', 0)

                if total >= 4:
                    alerts.append({
                        'level': '🎯',
                        'type': 'backtest_hit',
                        'title': f'{game_name}回测命中{total}个号!',
                        'detail': f"策略: {strategy}, 奖级: {prize_name}({prize_amount}元)",
                        'action': '验证该策略是否可持续,注意是否为随机波动',
                    })
                    break

                # 中奖通知(≥五等奖)
                if h.get('prize_tier', 0) >= 4:
                    alerts.append({
                        'level': '🏆',
                        'type': 'backtest_prize',
                        'title': f'{game_name}回测{prize_name}!',
                        'detail': f"策略: {strategy}, 命中{total}个号, {prize_name}({prize_amount}元)",
                        'action': '回测中奖信号,持续关注该策略实战表现',
                    })
                    break

            # 策略 vs 随机基线
            if baseline and hits:
                best_total = max(h.get('total', 0) for h in hits)
                baseline_avg = baseline.get('avg', 0)
                if best_total > baseline_avg + 1.5:
                    alerts.append({
                        'level': '📈',
                        'type': 'beat_baseline',
                        'title': f'{game_name}策略优于随机基线',
                        'detail': f"最佳命中{best_total}个 vs 随机均值{baseline_avg}个(超出{best_total - baseline_avg:.1f})",
                        'action': '策略有效,继续观察稳定性',
                    })
                elif best_total < baseline_avg - 0.5:
                    alerts.append({
                        'level': '📉',
                        'type': 'below_baseline',
                        'title': f'{game_name}策略劣于随机基线!',
                        'detail': f"最佳命中{best_total}个 vs 随机均值{baseline_avg}个(低于{baseline_avg - best_total:.1f})",
                        'action': '策略可能失效,考虑回退权重或调整参数',
                    })

            # AI推荐回测
            if ai_hit and ai_hit.get('best_total', 0) > 0:
                ai_best = ai_hit['best_total']
                rule_best = max(h.get('total', 0) for h in hits) if hits else 0
                if ai_best > rule_best:
                    alerts.append({
                        'level': '🤖',
                        'type': 'ai_beats_rules',
                        'title': f'{game_name}AI推荐优于规则推荐',
                        'detail': f"AI命中{ai_best}个 vs 规则{rule_best}个, AI奖金{ai_hit.get('total_prize', 0)}元",
                        'action': 'AI推荐更准,考虑给AI推荐更高权重',
                    })

    # === 5. 冷号注首次命中 ===
    if backtest_result:
        for game in ['ssq', 'dlt', 'qxc']:
            if game not in backtest_result:
                continue
            game_name = LOTTERY_NAMES.get(game, game)
            hits = backtest_result[game].get('hits', [])
            for h in hits:
                strategy = str(h.get('strategy', ''))
                if 'cold' in strategy.lower() and h.get('total', 0) >= 2:
                    bt_log = _load_backtest()
                    cold_hits_count = 0
                    for bt in bt_log[-10:]:
                        if game in bt:
                            for bh in bt[game].get('hits', []):
                                if 'cold' in str(bh.get('strategy', '')).lower() and bh.get('total', 0) >= 2:
                                    cold_hits_count += 1
                    if cold_hits_count <= 1:
                        prize_name = h.get('prize_name', '未中奖')
                        alerts.append({
                            'level': '❄️',
                            'type': 'cold_first_hit',
                            'title': f'{game_name}冷号注命中!',
                            'detail': f"策略: {strategy}, 命中{h.get('total', 0)}个号, {prize_name}(近10期冷号注仅命中{cold_hits_count}次)",
                            'action': '冷号注信号出现,关注后续是否形成趋势',
                        })
                        break

    # === 6. Kelly值偏高 ===
    if kelly_map:
        KELLY_HIGH_THRESHOLD = 0.03
        for game_key, kelly_val in kelly_map.items():
            game_name = LOTTERY_NAMES.get(game_key, game_key)
            if kelly_val > KELLY_HIGH_THRESHOLD:
                alerts.append({
                    'level': '💰',
                    'type': 'kelly_high',
                    'title': f'{game_name}Kelly值偏高!',
                    'detail': f"Kelly={kelly_val:.2%}(阈值{KELLY_HIGH_THRESHOLD:.0%}),数学期望为正",
                    'action': f'考虑增加{game_name}投注额(Kelly建议比例的1/4~1/2)',
                })

    # === 3. 马尔可夫冷→热信号告警(v3.0替换原GEPA策略调整通知) ===
    if evolved_config:
        markov_signals = evolved_config.get('markov_signals', {})
        for game, signals in markov_signals.items():
            game_name = LOTTERY_NAMES.get(game, game)
            top_trans = signals.get('top_transition', [])
            if top_trans and isinstance(top_trans, list):
                # 取最显著的冷→热信号
                for sig in top_trans[:3]:
                    num = sig.get('number', '?')
                    prob = sig.get('transition_prob', 0)
                    if prob > 0.5:  # 转移概率>50%
                        alerts.append({
                            'level': '🔧',
                            'type': 'markov_cold_to_hot',
                            'title': f'{game_name}号码{num}冷→热信号',
                            'detail': f"转移概率={prob:.1%}, 当前状态={sig.get('current_state', '?')}",
                            'action': '马尔可夫信号提示该号可能回补,结合贝叶斯修正判断',
                        })

    # === 4. 回测命中爆发 ===
    # 7a. 号码相关性异常(某对号码条件概率远高于先验)
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
                    'detail': f"上期出{m}→下期出{n}的条件概率={info.get('conditional', 0):.1%},"
                              f"是先验{info.get('prior', 0):.1%}的{best_ratio:.1f}倍",
                    'action': '关联规律值得关注,但需更多样本验证是否为随机波动',
                })
        except Exception:
            pass  # 规律发现是锦上添花,不能影响主流程

    # 7b. 趋势异常(某号码遗漏值远超历史均值)
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
                        'detail': f"遗漏得分={max_miss_val:.1f},远超均值,回补概率升高",
                        'action': '可在冷号注中关注该号,但冷号命中率低需控制仓位',
                    })
        except Exception:
            pass

    return alerts


def _save_alerts(alerts, today_str):
    """保存告警到JSON文件,供scheduler读取发送"""
    data = {
        'date': today_str,
        'generated_at': datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(alerts),
        'alerts': alerts,
    }
    with open(ALERT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_lottery_alerts():
    """读取最新的告警(供scheduler调用)"""
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
