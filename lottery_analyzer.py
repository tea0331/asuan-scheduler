#!/usr/bin/env python3
"""
彩票号码分析模块 v5.2 — 刘海蟾点金（加权统计+回测驱动+Kelly风控）
核心改动（v5.2）：
1. 🟢 P1修复：zone权重真正融入_calc_weights（之前20%权重被架空）
2. 🟢 P1实现：回测驱动权重自适应（adjust_weights_from_backtest）
3. 🟢 P2实现：Kelly仓位管理（风控提示，≤0则不建议投注）
4. 🔴 Bug修复：zone_size统一为11/12（与analyze_ssq/dlt的分区一致）
5. 🔴 Bug修复：趋势权重逻辑修正（下降趋势给负权重，不再abs(t)给正权重）
6. 🔴 Bug修复：adjust_weights策略名兼容新旧格式（追热策略→核心注，回补策略→扩展2）
7. 🔴 Bug修复：Kelly赔率匹配真实奖级，默认概率降为保守值
8. 🔴 Bug修复：_parse_qxc_recs重复return删除
9. 🔴 Bug修复：O(n²)权重查找优化为dict查找
10. 🔴 Bug修复：SimpleAnalyzer扩展注改用频率排序而非号码大小
11. 🔴 Bug修复：回测日期验证（predictions[-1]必须是昨天）
12. 🔴 优化：adjustments列表上限10条，权重30天周期性重置
13. 🔴 优化：归一化用高精度避免round误差积累
14. 🔴 优化：adjust_weights可调整trend/zone维度（不再只调freq/miss）

注意：彩票本质是随机事件，分析仅供娱乐参考。
"""

import requests
import re
import random
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 百炼API配置 — 🔴 优先环境变量，回退硬编码
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', 'sk-a6149c2fa4534ee08fc5e46f797d32ef')
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

# 🔴 办公室qwopus3.5（免费不限量！彩票零隐私，优先走这里）
OFFICE_API_BASE = 'http://1qm1752vy4744.vicp.fun:12305/v1'
OFFICE_API_KEY = os.environ.get('OFFICE_API_KEY', 'sk-lm-IPjU115B:U6iqyFE5DPKvznOf6M3a')
OFFICE_MODEL = 'qwopus3.5-27b-v3.5'
OFFICE_ENABLED = False  # ⏸️ qwopus3.5还不稳定，等朋友确认后再开

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

# 开奖日历的中文显示
WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


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

# 回测记录文件
BACKTEST_LOG = '/workspace/ai-memory/cron-scripts/lottery-backtest.json'
# 昨日推荐记录
PREDICTION_LOG = '/workspace/ai-memory/cron-scripts/lottery-predictions.json'


# ===== 硬编码Fallback数据（2026-04-18更新） =====

FALLBACK_SSQ = [
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
    {'period': '26040', 'front': [6, 12, 13, 21, 34], 'back': [8, 9]},
    {'period': '26039', 'front': [9, 11, 20, 26, 27], 'back': [6, 9]},
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
}


# ===== 数据抓取 =====

def fetch_ssq_history(periods=15):
    result = _fetch_ssq_500com(periods)
    if result and len(result) >= 3:
        return result
    result = _fetch_ssq_cjcp(periods)
    if result and len(result) >= 3:
        return result
    print("[双色球] 网络抓取失败，使用硬编码数据")
    return FALLBACK_SSQ[:periods]

def fetch_dlt_history(periods=15):
    result = _fetch_dlt_500com(periods)
    if result and len(result) >= 3:
        return result
    result = _fetch_dlt_cjcp(periods)
    if result and len(result) >= 3:
        return result
    print("[大乐透] 网络抓取失败，使用硬编码数据")
    return FALLBACK_DLT[:periods]

def fetch_qxc_history(periods=15):
    result = _fetch_qxc_500com(periods)
    if result and len(result) >= 3:
        return result
    result = _fetch_qxc_cjcp(periods)
    if result and len(result) >= 3:
        return result
    # 🔴 网络抓到少量数据也比硬编码好（硬编码会过时）
    if result and len(result) >= 1:
        print(f"[七星彩] 网络抓取到{len(result)}期，补充硬编码数据")
        fallback = [f for f in FALLBACK_QXC if not any(f['period'] == r['period'] for r in result)]
        return result + fallback[:periods - len(result)]
    print("[七星彩] 网络抓取失败，使用硬编码数据")
    return FALLBACK_QXC[:periods]


def _fetch_ssq_500com(periods):
    try:
        url = 'https://datachart.500.com/ssq/history/newinc/history.php'
        resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://datachart.500.com/ssq/history/'}, timeout=15)
        resp.encoding = 'gb2312'
        return _parse_ssq_html(resp.text, periods)
    except Exception as e:
        print(f"[双色球-500] 抓取失败: {e}")
        return None

def _fetch_dlt_500com(periods):
    try:
        url = 'https://datachart.500.com/dlt/history/newinc/history.php'
        resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://datachart.500.com/dlt/history/'}, timeout=15)
        resp.encoding = 'gb2312'
        return _parse_dlt_html(resp.text, periods)
    except Exception as e:
        print(f"[大乐透-500] 抓取失败: {e}")
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
            if re.match(r'^2[56]\d{3}$', td):
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
            if re.match(r'^2[56]\d{3}$', td):
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
            if re.match(r'^2[56]\d{3}$', td):
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
    """

    def __init__(self, history, weight_freq=None, weight_miss=None, weight_trend=None, weight_zone=None):
        self.history = history
        # 🟢 优先用参数传入的权重，否则从配置文件读，否则用默认值
        config = _load_weight_config()
        self.w_freq = weight_freq if weight_freq is not None else config.get('freq', 0.30)
        self.w_miss = weight_miss if weight_miss is not None else config.get('miss', 0.25)
        self.w_trend = weight_trend if weight_trend is not None else config.get('trend', 0.25)
        self.w_zone = weight_zone if weight_zone is not None else config.get('zone', 0.20)

    def _calc_weights(self, number_range, extract_fn, total_periods):
        """通用加权计算
        extract_fn(history_item) -> list of numbers
        """
        # 频率统计
        freq = Counter()
        for d in self.history:
            freq.update(extract_fn(d))

        # 遗漏值：连续未出现期数
        miss = {}
        for n in number_range:
            count = 0
            for d in self.history:
                if n in extract_fn(d):
                    break
                count += 1
            miss[n] = count

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
            f = freq.get(n, 0) / max(total_periods, 1)
            m = math.log1p(miss.get(n, 0)) / math.log1p(total_periods)
            t = (recent.get(n, 0) - older.get(n, 0)) / max(mid, 1)
            # 🔴 Bug4修复：趋势权重逻辑修正
            # t > 0 表示近5期比前10期出现多（上升趋势），应给正权重
            # t < 0 表示近5期比前10期出现少（下降趋势），应给负权重或零权重
            # 之前abs(t)给下降趋势正权重是错误的
            if t > 0:
                t_weight = t * 1.5  # 上升趋势加权放大
            elif t < 0:
                t_weight = t * 0.5  # 下降趋势给小负权重（轻微惩罚，不完全排除）
            else:
                t_weight = 0

            # 🟢 分区平衡：偏低区的号加分，偏高区的号减分
            z = min(n // zone_size, 2)
            z_factor = max(0, (zone_expected - zone_counts[z]) / max(zone_expected, 1))

            weights[n] = (
                self.w_freq * f +
                self.w_miss * m +
                self.w_trend * t_weight +
                self.w_zone * z_factor  # 🟢 zone终于生效
            )

        return weights, freq, miss

    def analyze_ssq(self):
        """双色球加权分析"""
        total = len(self.history)

        # 红球权重
        red_weights, red_freq, red_miss = self._calc_weights(
            range(1, 34), lambda d: d['reds'], total
        )

        # 蓝球权重
        blue_weights, blue_freq, blue_miss = self._calc_weights(
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

        return {
            'red_weights': hot_reds,
            'red_freq': red_freq,
            'red_miss': red_miss,
            'blue_weights': hot_blues,
            'blue_freq': blue_freq,
            'blue_miss': blue_miss,
            'zone_balance': zone_balance,
            'avg_sum': avg_sum,
            'consec_rate': consec_rate,
            'total_periods': total,
        }

    def analyze_dlt(self):
        """大乐透加权分析"""
        total = len(self.history)

        front_weights, front_freq, front_miss = self._calc_weights(
            range(1, 36), lambda d: d['front'], total
        )
        back_weights, back_freq, back_miss = self._calc_weights(
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
            'back_weights': hot_backs,
            'back_freq': back_freq,
            'back_miss': back_miss,
            'zone_balance': zone_balance,
            'avg_sum': avg_sum,
            'consec_rate': consec_rate,
            'total_periods': total,
        }

    def analyze_qxc(self):
        """七星彩加权分析（逐位统计）"""
        total = len(self.history)
        pos_data = []
        for pos in range(7):
            weights, freq, miss = self._calc_weights(
                range(10), lambda d: [d['digits'][pos]], total
            )
            hot = sorted(weights.items(), key=lambda x: x[1], reverse=True)
            pos_data.append({
                'weights': hot,
                'freq': freq,
                'miss': miss,
            })
        return {'positions': pos_data, 'total_periods': total}

    def generate_recs_ssq(self, analysis):
        """根据加权分析生成双色球推荐（纯数学，不依赖AI）"""
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

        # 🟢 核心注：追热+回补的TOP6合并（权重最高6个）
        # 🔴 Bug5修复：O(n²)→O(n)，用dict查找权重
        red_weight_dict = dict(analysis['red_weights'])
        all_pool = []
        for n in range(1, 34):
            w = red_weight_dict.get(n, 0)
            all_pool.append((n, w, analysis['red_freq'].get(n, 0), analysis['red_miss'].get(n, 0)))
        all_pool.sort(key=lambda x: x[1], reverse=True)
        core_reds_by_weight = [n for n, w, f, m in all_pool[:6]]  # 🔴 保持权重排序（不sorted！）
        core_reds = sorted(core_reds_by_weight)  # 只用于显示
        core_blue = analysis['blue_weights'][0][0]

        # 🔴 Bug修复：扩展注保留的是权重最高的号，不是号码最小的号
        # 扩展1：保留权重最高的4号 + 替换权重最低的2号
        ext1_keep = sorted(core_reds_by_weight[:4])  # 权重TOP4
        ext1_new = sorted([n for n, w, f, m in all_pool[6:8] if n not in ext1_keep][:2])
        ext1_reds = sorted(ext1_keep + ext1_new)
        ext1_blue = analysis['blue_weights'][1][0] if len(analysis['blue_weights']) > 1 else 1

        # 扩展2：保留权重最高的3号 + 替换权重最低的3号
        ext2_keep = sorted(core_reds_by_weight[:3])  # 权重TOP3
        ext2_new = sorted([n for n, w, f, m in all_pool[8:11] if n not in ext2_keep][:3])
        ext2_reds = sorted(ext2_keep + ext2_new)
        ext2_blue = analysis['blue_weights'][2][0] if len(analysis['blue_weights']) > 2 else ext1_blue

        return [
            {'reds': core_reds, 'blue': core_blue, 'strategy': '核心注(加权)'},
            {'reds': ext1_reds, 'blue': ext1_blue, 'strategy': '扩展1(加权)'},
            {'reds': ext2_reds, 'blue': ext2_blue, 'strategy': '扩展2(加权)'},
        ]

    def generate_recs_dlt(self, analysis):
        """根据加权分析生成大乐透推荐"""
        hot_front = sorted([n for n, w in analysis['front_weights'][:8]][:5])
        hot_back = sorted([analysis['back_weights'][0][0], analysis['back_weights'][1][0]])

        miss_fronts = sorted([(n, analysis['front_miss'].get(n, 0)) for n in range(1, 36)],
                            key=lambda x: x[1], reverse=True)[:5]
        miss_front_nums = sorted([n for n, m in miss_fronts])
        miss_backs = sorted([(n, analysis['back_miss'].get(n, 0)) for n in range(1, 13)],
                           key=lambda x: x[1], reverse=True)[:2]
        miss_back_nums = sorted([n for n, m in miss_backs])

        mid_pool = [n for n, f in analysis['front_freq'].items() if 2 <= f <= 4]
        mid_front = sorted(mid_pool[:5]) if len(mid_pool) >= 5 else sorted([n for n, w in analysis['front_weights'][3:10]][:5])
        mid_back = sorted([analysis['back_weights'][1][0], analysis['back_weights'][2][0]]) if len(analysis['back_weights']) > 2 else [1, 2]

        # 🟢 核心注：权重最高5个前区 + 最高权重后区
        # 🔴 Bug5修复：O(n²)→O(n)，用dict查找权重
        front_weight_dict = dict(analysis['front_weights'])
        all_pool = []
        for n in range(1, 36):
            w = front_weight_dict.get(n, 0)
            all_pool.append((n, w, analysis['front_freq'].get(n, 0), analysis['front_miss'].get(n, 0)))
        all_pool.sort(key=lambda x: x[1], reverse=True)
        core_front_by_weight = [n for n, w, f, m in all_pool[:5]]  # 🔴 保持权重排序
        core_front = sorted(core_front_by_weight)  # 只用于显示
        core_back = sorted([analysis['back_weights'][0][0], analysis['back_weights'][1][0]])

        # 🔴 Bug修复：保留权重最高的号，不是号码最小的号
        # 扩展1：保留权重TOP3 + 替换权重最低的2个
        ext1_keep = sorted(core_front_by_weight[:3])  # 权重TOP3
        ext1_new = sorted([n for n, w, f, m in all_pool[5:7] if n not in ext1_keep][:2])
        ext1_front = sorted(ext1_keep + ext1_new)
        ext1_back = sorted([analysis['back_weights'][0][0], analysis['back_weights'][2][0]]) if len(analysis['back_weights']) > 2 else core_back

        # 扩展2：保留权重TOP2 + 替换权重最低的3个
        ext2_keep = sorted(core_front_by_weight[:2])  # 权重TOP2
        ext2_new = sorted([n for n, w, f, m in all_pool[7:10] if n not in ext2_keep][:3])
        ext2_front = sorted(ext2_keep + ext2_new)
        ext2_back = sorted([analysis['back_weights'][1][0], analysis['back_weights'][2][0]]) if len(analysis['back_weights']) > 2 else core_back

        return [
            {'front': core_front, 'back': core_back, 'strategy': '核心注(加权)'},
            {'front': ext1_front, 'back': ext1_back, 'strategy': '扩展1(加权)'},
            {'front': ext2_front, 'back': ext2_back, 'strategy': '扩展2(加权)'},
        ]

    def generate_recs_qxc(self, analysis):
        """根据加权分析生成七星彩推荐"""
        # 🟢 核心注：每位权重最高的数字
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

        recs = [
            {'digits': core_digits, 'strategy': '核心注(加权)'},
            {'digits': ext1_digits, 'strategy': '扩展1(加权)'},
            {'digits': ext2_digits, 'strategy': '扩展2(加权)'},
        ]
        return recs


# ===== 数据格式化（给刘海蟾看） =====

def _format_ssq_for_ai(history):
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
    weighted_recs = wa.generate_recs_ssq(analysis)
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

def _format_dlt_for_ai(history):
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

    weighted_recs = wa.generate_recs_dlt(analysis)
    for rec in weighted_recs:
        front_str = ' '.join(f'{n:02d}' for n in rec['front'])
        back_str = ' '.join(f'{n:02d}' for n in rec['back'])
        stats.append(f"📊{rec['strategy']}: {front_str} + 后{back_str}")

    zb = analysis['zone_balance']
    total_z = sum(zb) or 1
    stats.append(f"📊近5期分区比: 一区{zb[0]}({zb[0]*100//total_z}%) 二区{zb[1]}({zb[1]*100//total_z}%) 三区{zb[2]}({zb[2]*100//total_z}%)")
    stats.append(f"📊和值均值: {analysis['avg_sum']:.0f}, 连号概率: {analysis['consec_rate']:.1f}对/期")

    return '\n'.join(lines) + '\n\n' + '\n'.join(stats)

def _format_qxc_for_ai(history):
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

    weighted_recs = wa.generate_recs_qxc(analysis)
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
WEIGHT_CONFIG_FILE = '/workspace/ai-memory/cron-scripts/weight-config.json'

DEFAULT_WEIGHT_CONFIG = {
    'freq': 0.30,
    'miss': 0.25,
    'trend': 0.25,
    'zone': 0.20,
    'version': 1,
    'adjustments': []  # 记录每次调整
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
    🟢 P1核心：根据回测命中率自动微调权重
    逻辑：
    - 追热策略持续最佳 → 频率维度加0.02
    - 回补策略持续最佳 → 遗漏维度加0.02
    - 综合策略持续最佳 → 趋势维度加0.02
    - 每次调整后归一化，确保总和=1.0
    - 单次最大调整±0.03，防止震荡
    """
    backtest_log = _load_backtest()
    if len(backtest_log) < 5:
        return None  # 数据不足

    config = _load_weight_config()
    recent = backtest_log[-7:]

    # 统计各策略胜率
    strategy_wins = Counter()
    strategy_hits_detail = defaultdict(list)
    for bt in recent:
        for game in ['ssq', 'dlt', 'qxc']:
            if game not in bt:
                continue
            best = bt[game].get('best_strategy', '')
            strategy_wins[best] += 1
            for h in bt[game].get('hits', []):
                strategy_hits_detail[h.get('strategy', '')].append(h.get('total', 0))

    # 判断调整方向
    # 🔴 Bug修复：兼容新旧策略名
    # 旧名映射：追热策略→核心注, 回补策略→扩展2, 综合策略→扩展1
    strategy_map = {
        '追热策略': '核心注', '回补策略': '扩展2', '综合策略': '扩展1',
        '核心注(加权)': '核心注', '扩展1(加权)': '扩展1', '扩展2(加权)': '扩展2',
    }
    mapped_wins = Counter()
    for name, count in strategy_wins.items():
        mapped_name = strategy_map.get(name, name)
        mapped_wins[mapped_name] += count

    adjustments = {}
    step = 0.02
    # 核心注/追热领先 → 频率权重+step，遗漏-step
    # 扩展2/回补领先 → 遗漏权重+step，频率-step
    # 扩展1/综合领先 → 趋势权重+step
    hot_wins = mapped_wins.get('核心注', 0)
    cold_wins = mapped_wins.get('扩展2', 0)
    mid_wins = mapped_wins.get('扩展1', 0)

    if hot_wins > cold_wins + 2 and hot_wins > mid_wins:
        adjustments = {'freq': step, 'miss': -step}
    elif cold_wins > hot_wins + 2 and cold_wins > mid_wins:
        adjustments = {'miss': step, 'freq': -step}
    elif mid_wins > hot_wins and mid_wins > cold_wins + 1:
        # 🔴 新增：综合策略领先时调整趋势维度
        adjustments = {'trend': step, 'zone': -step}

    if not adjustments:
        return None

    # 应用调整（限幅±0.03）
    for key, delta in adjustments.items():
        old_val = config.get(key, DEFAULT_WEIGHT_CONFIG[key])
        new_val = max(0.10, min(0.50, old_val + delta))
        config[key] = round(new_val, 2)

    # 归一化（🔴 Bug修复：用高精度避免round误差积累）
    total = config['freq'] + config['miss'] + config['trend'] + config['zone']
    if total > 0:
        config['freq'] = round(config['freq'] / total, 4)
        config['miss'] = round(config['miss'] / total, 4)
        config['trend'] = round(config['trend'] / total, 4)
        config['zone'] = round(1.0 - config['freq'] - config['miss'] - config['trend'], 4)  # 余量给zone

    config['version'] = config.get('version', 1) + 1
    from datetime import datetime as _dt
    config['adjustments'].append({
        'date': _dt.now(CST).strftime('%Y-%m-%d'),
        'direction': 'freq+' if adjustments.get('freq', 0) > 0 else ('miss+' if adjustments.get('miss', 0) > 0 else 'trend+'),
        'hot_wins': hot_wins,
        'cold_wins': cold_wins,
        'mid_wins': mid_wins,
        'new_weights': {k: config[k] for k in ['freq', 'miss', 'trend', 'zone']}
    })

    # 🔴 风险2修复：adjustments列表上限10条
    if len(config['adjustments']) > 10:
        config['adjustments'] = config['adjustments'][-10:]

    # 🔴 风险1修复：每30天周期性重置权重（防止局部最优）
    if config['version'] % 30 == 0:
        config['freq'] = DEFAULT_WEIGHT_CONFIG['freq']
        config['miss'] = DEFAULT_WEIGHT_CONFIG['miss']
        config['trend'] = DEFAULT_WEIGHT_CONFIG['trend']
        config['zone'] = DEFAULT_WEIGHT_CONFIG['zone']
        config['adjustments'].append({
            'date': _dt.now(CST).strftime('%Y-%m-%d'),
            'direction': 'reset',
            'hot_wins': 0, 'cold_wins': 0, 'mid_wins': 0,
            'new_weights': {k: config[k] for k in ['freq', 'miss', 'trend', 'zone']}
        })

    _save_weight_config(config)
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
    """回测昨日推荐 vs 今日开奖结果（🔴只回测昨天开奖的彩种）"""
    predictions = _load_predictions()
    backtest_log = _load_backtest()
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    if not predictions:
        print("[回测] 无昨日推荐记录，跳过回测")
        return None

    # 🔴 只回测昨天开奖的彩种
    draw_games = get_draw_games_yesterday()
    if not draw_games:
        print("[回测] 昨天无彩种开奖，跳过回测")
        return None

    draw_names = [LOTTERY_NAMES.get(g, g) for g in draw_games]
    print(f"[回测] 昨天开奖彩种: {', '.join(draw_names)}")

    # 取最近一条推荐（昨天的）
    yesterday_pred = predictions[-1]
    if yesterday_pred.get('date') == today_str:
        print("[回测] 今日推荐已生成，跳过回测")
        return None

    # 🔴 Bug2修复：验证predictions[-1]确实是昨天的推荐
    yesterday = (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d')
    if yesterday_pred.get('date') != yesterday:
        print(f"[回测] 最近推荐日期={yesterday_pred.get('date')}，非昨日{yesterday}，跳过回测")
        return None

    backtest_result = {
        'date': yesterday_pred.get('date', ''),
        'backtest_date': today_str,
        'draw_games': draw_games,  # 🔴 记录哪些彩种开奖了
    }

    # 双色球回测 — 只在昨天开奖时回测
    if 'ssq' in draw_games and yesterday_pred.get('ssq_recs'):
        ssq_actual = fetch_ssq_history(1)
        if ssq_actual:
            actual = ssq_actual[0]
            hits = []
            for rec in yesterday_pred['ssq_recs']:
                red_hit_nums = _get_hit_numbers(rec['reds'], actual['reds'])
                blue_hit = 1 if rec['blue'] == actual['blue'] else 0
                hits.append({
                    'strategy': rec['strategy'],
                    'red_hits': len(red_hit_nums),
                    'red_hit_nums': red_hit_nums,  # 🔴 命中的具体号码
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
                'actual_reds': actual['reds'],  # 🔴 开奖号码
                'actual_blue': actual['blue'],
            }
            print(f"[回测] 双色球 第{actual['period']}期: 最佳策略={backtest_result['ssq']['best_strategy']}, 命中={backtest_result['ssq']['best_total']}个")

    # 大乐透回测 — 只在昨天开奖时回测
    if 'dlt' in draw_games and yesterday_pred.get('dlt_recs'):
        dlt_actual = fetch_dlt_history(1)
        if dlt_actual:
            actual = dlt_actual[0]
            hits = []
            for rec in yesterday_pred['dlt_recs']:
                front_hit_nums = _get_hit_numbers(rec['front'], actual['front'])
                back_hit_nums = _get_hit_numbers(rec['back'], actual['back'])
                hits.append({
                    'strategy': rec['strategy'],
                    'front_hits': len(front_hit_nums),
                    'front_hit_nums': front_hit_nums,  # 🔴 命中的具体号码
                    'back_hits': len(back_hit_nums),
                    'back_hit_nums': back_hit_nums,  # 🔴 命中的具体号码
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
                'actual_front': actual['front'],  # 🔴 开奖号码
                'actual_back': actual['back'],
            }
            print(f"[回测] 大乐透 第{actual['period']}期: 最佳策略={backtest_result['dlt']['best_strategy']}, 命中={backtest_result['dlt']['best_total']}个")

    # 七星彩回测 — 只在昨天开奖时回测
    if 'qxc' in draw_games and yesterday_pred.get('qxc_recs'):
        qxc_actual = fetch_qxc_history(1)
        if qxc_actual:
            actual = qxc_actual[0]
            hits = []
            for rec in yesterday_pred['qxc_recs']:
                digit_hits_detail = [(i, rec['digits'][i], actual['digits'][i], rec['digits'][i] == actual['digits'][i]) for i in range(7)]
                digit_hit_count = sum(1 for _, _, _, hit in digit_hits_detail if hit)
                hits.append({
                    'strategy': rec['strategy'],
                    'digit_hits': digit_hit_count,
                    'digit_hits_detail': digit_hits_detail,  # 🔴 逐位对比详情
                    'total': digit_hit_count,
                    'predicted': rec['digits'],
                    'actual': actual['digits'],
                })
            backtest_result['qxc'] = {
                'period': actual['period'],
                'hits': hits,
                'best_strategy': max(hits, key=lambda x: x['total'])['strategy'] if hits else None,
                'best_total': max(hits, key=lambda x: x['total'])['total'] if hits else 0,
                'actual_digits': actual['digits'],  # 🔴 开奖号码
            }
            print(f"[回测] 七星彩 第{actual['period']}期: 最佳策略={backtest_result['qxc']['best_strategy']}, 命中={backtest_result['qxc']['best_total']}个")

    # 保存回测结果
    if any(k in backtest_result for k in ['ssq', 'dlt', 'qxc']):
        # 🔴 去重：检查是否已有相同日期+彩种的回测记录
        existing_keys = set()
        for bt in backtest_log:
            bt_date = bt.get('date', '')
            for g in ['ssq', 'dlt', 'qxc']:
                if g in bt:
                    existing_keys.add(f"{bt_date}_{g}")
        new_date = backtest_result.get('date', '')
        for g in ['ssq', 'dlt', 'qxc']:
            if g in backtest_result:
                key = f"{new_date}_{g}"
                if key in existing_keys:
                    del backtest_result[g]
                    print(f"[回测] 去重：跳过已存在的{new_date}_{g}")

        if any(k in backtest_result for k in ['ssq', 'dlt', 'qxc']):
            backtest_log.append(backtest_result)
            _save_backtest(backtest_log)
            return backtest_result

    return None


def _format_backtest_for_ai(backtest_result):
    """把回测结果格式化成刘海蟾能读的反馈（🔴含逐号对比详情）"""
    if not backtest_result:
        return ''

    draw_names = [LOTTERY_NAMES.get(g, g) for g in backtest_result.get('draw_games', [])]
    lines = [f'\n=== 昨日开奖回测（{", ".join(draw_names)}开奖，用于改进算法）===']

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

        # 🟢 追热策略是否持续领先？给出具体调整建议
        # 🔴 兼容新旧策略名
        strategy_map = {
            '追热策略': '核心注', '回补策略': '扩展2', '综合策略': '扩展1',
            '核心注(加权)': '核心注', '扩展1(加权)': '扩展1', '扩展2(加权)': '扩展2',
            '核心注(兜底)': '核心注', '扩展1(兜底)': '扩展1', '扩展2(兜底)': '扩展2',
        }
        mapped_scores = Counter()
        for name, count in strategy_scores.items():
            mapped_name = strategy_map.get(name, name)
            mapped_scores[mapped_name] += count
        hot_count = mapped_scores.get('核心注', 0)
        cold_count = mapped_scores.get('扩展2', 0)
        mid_count = mapped_scores.get('扩展1', 0)
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
    prompt = f"""请基于以下近15期开奖数据，分别为三个彩种推算下期号码。

=== 双色球（红球1-33选6，蓝球1-16选1）===
{ssq_text}

=== 大乐透（前区1-35选5，后区1-12选2）===
{dlt_text}

=== 七星彩（7位数字0-9）===
{qxc_text}
{backtest_feedback}
请为每个彩种给出3组推荐号码，格式严格要求如下（不要输出其他内容）：

双色球核心注：红球 NN NN NN NN NN NN | 蓝球 NN
双色球扩展1：红球 NN NN NN NN NN NN | 蓝球 NN
双色球扩展2：红球 NN NN NN NN NN NN | 蓝球 NN
大乐透核心注：前区 NN NN NN NN NN | 后区 NN NN
大乐透扩展1：前区 NN NN NN NN NN | 后区 NN NN
大乐透扩展2：前区 NN NN NN NN NN | 后区 NN NN
七星彩核心注：N N N N N N N
七星彩扩展1：N N N N N N N
七星彩扩展2：N N N N N N N

🔴 核心注生成规则（最重要！）：
- 核心注 = 从加权号码池的追热+回补+综合三组中，选综合权重最高的6个号
- 追热和回补覆盖了不同号码区间，合并选TOP6可以同时覆盖冷热号
- 核心注的目标是最大化单注命中数（而不是分散覆盖）
- 蓝球/后区选加权权重最高的1-2个

🔴 扩展注生成规则：
- 扩展1：保留核心注4个号 + 替换2个为权重次高的号（1号微调）
- 扩展2：保留核心注3个号 + 替换3个为权重第7-12高的号（大换血）
- 这样3注形成"核心→微调→大换"梯度，既保核心命中又扩展覆盖

红球/前区从小到大排列，用两位数（如02 07 12）。"""

    system_msg = '你是刘海蟾，求是方法论驱动的彩票分析AI。v5.1升级：核心注+缩水扩展策略。核心改进：历史回测显示追热和回补分别命中不同号，分开写每组只中2-3个，但合并后单注可命中5-6个！所以核心注=追热+回补的TOP6合并（权重最高6个号），不再按策略分散。规则：1.核心注必须从加权池追热+回补+综合三组中取综合权重TOP6；2.扩展1保留核心4号换2号，扩展2保留3号换3号；3.严格按格式输出，不输出分析过程。彩票本质随机，求是让过程系统可追溯，不提高中奖率。'

    # 🔴 优先办公室qwopus3.5（彩票零隐私，免费不限量）
    if OFFICE_ENABLED:
        result = _call_llm(OFFICE_API_BASE, OFFICE_API_KEY, OFFICE_MODEL, system_msg, prompt, max_tokens=1000, timeout=120)
        if result:
            print(f"[刘海蟾] 办公室qwopus3.5推算完成: {len(result)}字符")
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
    strategies = ['核心注', '扩展1', '扩展2']
    # 兼容新旧格式
    pattern = r'双色球(?:核心注|推荐1)[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
    m = re.search(pattern, ai_text)
    if m:
        recs.append({
            'reds': [int(m.group(j)) for j in range(1, 7)],
            'blue': int(m.group(7)),
            'strategy': '核心注'
        })
    pattern2 = r'双色球扩展1[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
    m2 = re.search(pattern2, ai_text)
    if m2:
        recs.append({
            'reds': [int(m2.group(j)) for j in range(1, 7)],
            'blue': int(m2.group(7)),
            'strategy': '扩展1'
        })
    pattern3 = r'双色球扩展2[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
    m3 = re.search(pattern3, ai_text)
    if m3:
        recs.append({
            'reds': [int(m3.group(j)) for j in range(1, 7)],
            'blue': int(m3.group(7)),
            'strategy': '扩展2'
        })
    # 兜底：旧格式
    if not recs:
        old_pattern = r'双色球推荐\d[：:]\s*红球\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*蓝球\s+(\d{2})'
        matches = re.findall(old_pattern, ai_text)
        for i, m in enumerate(matches[:3]):
            recs.append({
                'reds': [int(m[j]) for j in range(6)],
                'blue': int(m[6]),
                'strategy': strategies[i] if i < len(strategies) else f'策略{i+1}'
            })
    return recs

def _parse_dlt_recs(ai_text):
    recs = []
    strategies = ['核心注', '扩展1', '扩展2']
    # 新格式
    pattern = r'大乐透(?:核心注|推荐1)[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
    m = re.search(pattern, ai_text)
    if m:
        recs.append({
            'front': [int(m.group(j)) for j in range(1, 6)],
            'back': [int(m.group(j)) for j in range(6, 8)],
            'strategy': '核心注'
        })
    pattern2 = r'大乐透扩展1[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
    m2 = re.search(pattern2, ai_text)
    if m2:
        recs.append({
            'front': [int(m2.group(j)) for j in range(1, 6)],
            'back': [int(m2.group(j)) for j in range(6, 8)],
            'strategy': '扩展1'
        })
    pattern3 = r'大乐透扩展2[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
    m3 = re.search(pattern3, ai_text)
    if m3:
        recs.append({
            'front': [int(m3.group(j)) for j in range(1, 6)],
            'back': [int(m3.group(j)) for j in range(6, 8)],
            'strategy': '扩展2'
        })
    # 兜底旧格式
    if not recs:
        old_pattern = r'大乐透推荐\d[：:]\s*前区\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s*\|\s*后区\s+(\d{2})\s+(\d{2})'
        matches = re.findall(old_pattern, ai_text)
        for i, m in enumerate(matches[:3]):
            recs.append({
                'front': [int(m[j]) for j in range(5)],
                'back': [int(m[j]) for j in range(5, 7)],
                'strategy': strategies[i] if i < len(strategies) else f'策略{i+1}'
            })
    return recs

def _parse_qxc_recs(ai_text):
    recs = []
    strategies = ['核心注', '扩展1', '扩展2']
    # 新格式
    pattern = r'七星彩(?:核心注|推荐1)[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
    m = re.search(pattern, ai_text)
    if m:
        recs.append({
            'digits': [int(m.group(j)) for j in range(1, 8)],
            'strategy': '核心注'
        })
    pattern2 = r'七星彩扩展1[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
    m2 = re.search(pattern2, ai_text)
    if m2:
        recs.append({
            'digits': [int(m2.group(j)) for j in range(1, 8)],
            'strategy': '扩展1'
        })
    pattern3 = r'七星彩扩展2[：:]\s*(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)\s+(\d)'
    m3 = re.search(pattern3, ai_text)
    if m3:
        recs.append({
            'digits': [int(m3.group(j)) for j in range(1, 8)],
            'strategy': '扩展2'
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
        # 扩展2：遗漏号
        cold = sorted([n for n in range(1, 34) if red_counter.get(n, 0) <= 1][:6])
        cold_blues = [n for n in range(1, 17) if blue_counter.get(n, 0) == 0]
        return [
            {'reds': core, 'blue': core_blue, 'strategy': '核心注(兜底)'},
            {'reds': sorted(ext1_keep + ext1_new), 'blue': ext1_blue, 'strategy': '扩展1(兜底)'},
            {'reds': cold, 'blue': cold_blues[0] if cold_blues else 1, 'strategy': '扩展2(兜底)'},
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
        cold = sorted([n for n in range(1, 36) if front_counter.get(n, 0) <= 1][:5])
        cold_back = [n for n in range(1, 13) if back_counter.get(n, 0) <= 1][:2]
        return [
            {'front': core, 'back': core_back, 'strategy': '核心注(兜底)'},
            {'front': sorted(ext1_keep + ext1_new), 'back': ext1_back, 'strategy': '扩展1(兜底)'},
            {'front': cold, 'back': sorted(cold_back) if len(cold_back) >= 2 else [1, 2], 'strategy': '扩展2(兜底)'},
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
        # 扩展2：前2位核心 + 后5位遗漏
        ext2 = list(core)
        for pos in range(2, 7):
            counter = Counter(d['digits'][pos] for d in history)
            cold = [n for n in range(10) if counter.get(n, 0) <= 1]
            ext2[pos] = cold[0] if cold else counter.most_common()[-1][0]
        recs = [
            {'digits': core, 'strategy': '核心注(兜底)'},
            {'digits': ext1, 'strategy': '扩展1(兜底)'},
            {'digits': ext2, 'strategy': '扩展2(兜底)'},
        ]
        return recs


# ===== 格式化输出 =====

def format_lottery_section(ssq_result=None, dlt_result=None, qxc_result=None, backtest_result=None):
    lines = []
    lines.append("\n---\n")
    lines.append("## 🎰 彩票号码推荐 — 刘海蟾点金（仅供娱乐参考）\n")
    lines.append("> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n")

    # 🔴 开奖日历提示
    today_games = get_draw_games()
    tomorrow_games = get_draw_games_tomorrow()
    if today_games:
        today_names = '、'.join(LOTTERY_NAMES.get(g, g) for g in today_games)
        lines.append(f"📅 **今天开奖**: {today_names}\n")
    if tomorrow_games:
        tomorrow_names = '、'.join(LOTTERY_NAMES.get(g, g) for g in tomorrow_games)
        lines.append(f"📅 **明天开奖**: {tomorrow_names}\n")
    if not today_games and not tomorrow_games:
        lines.append("📅 今明两天无开奖\n")

    # 🔴 增强版回测结果（逐号对比）
    if backtest_result:
        draw_games = backtest_result.get('draw_games', [])
        draw_names_str = '、'.join(LOTTERY_NAMES.get(g, g) for g in draw_games)
        lines.append("### 📊 开奖回测")
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

    # 🟢 P2: Kelly仓位建议
    config = _load_weight_config()
    lines.append(f"\n⚖️ **风控提示**:")
    for game_name, game_key, total_nums in [('双色球', 'ssq', 7), ('大乐透', 'dlt', 7), ('七星彩', 'qxc', 7)]:
        hit_prob = estimate_hit_probability(game_key, 4, total_nums)
        # 🔴 BugD修复：Kelly赔率匹配真实奖级
        # 双色球：6+1=500万倍, 6+0=18万倍, 5+1=3000倍, 5+0=200倍, 4+1=200倍, 4+0=10倍
        # 大乐透：5+2=1000万倍, 5+1=5万倍, 5+0=3000倍, 4+2=3000倍, 4+1=200倍
        # 七星彩：全中=500万倍, 6中=5万倍, 5中=3000倍
        # 这里用"命中4个号"对应的合理赔率（约10-200倍，取50倍保守估计）
        odds_map = {'ssq': 50, 'dlt': 50, 'qxc': 100}
        k = kelly_fraction(hit_prob, odds_map.get(game_key, 200))
        if k > 0:
            lines.append(f"  {game_name}核心注: Kelly={k:.2%}（建议投入≤本金的{k:.1%}）")
        else:
            lines.append(f"  {game_name}核心注: Kelly≤0（❌不建议本期投注）")

    lines.append(f"\n📊 **算法参数**: 权重v{config.get('version',1)} 频率={config.get('freq',0.3):.0%} 遗漏={config.get('miss',0.25):.0%} 趋势={config.get('trend',0.25):.0%} 分区={config.get('zone',0.2):.0%}")
    lines.append("---\n")
    return '\n'.join(lines)


# ===== 主入口 =====

def generate_lottery_recommendations():
    """主函数：回测昨日 → 权重自适应 → 抓取数据 → 刘海蟾点金 → 格式化 → 保存记录"""
    print("[彩票] 开始生成推荐（刘海蟾点金模式）...")
    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # 🟢 P1: 回测驱动权重自适应
    new_weights = adjust_weights_from_backtest()
    if new_weights:
        print(f"[权重] 回测驱动调整: freq={new_weights['freq']}, miss={new_weights['miss']}, trend={new_weights['trend']}, zone={new_weights['zone']} (v{new_weights['version']})")
    else:
        new_weights = _load_weight_config()

    fallback = SimpleAnalyzer()
    ssq_result = None
    dlt_result = None
    qxc_result = None

    # 0. 回测昨日推荐
    print("[回测] 对比昨日推荐与今日开奖...")
    backtest_result = _run_backtest()
    backtest_feedback = _format_backtest_for_ai(backtest_result)
    if backtest_feedback:
        print(f"[回测] 已生成回测反馈: {len(backtest_feedback)}字符")

    # 1. 抓取所有数据
    print("[彩票] 抓取双色球数据...")
    ssq_history = fetch_ssq_history(15)
    print("[彩票] 抓取大乐透数据...")
    dlt_history = fetch_dlt_history(15)
    print("[彩票] 抓取七星彩数据...")
    qxc_history = fetch_qxc_history(15)

    # 2. 刘海蟾一次性推算（带回测反馈）
    all_data_ok = (ssq_history and len(ssq_history) >= 5 and
                   dlt_history and len(dlt_history) >= 5 and
                   qxc_history and len(qxc_history) >= 5)

    if all_data_ok:
        ssq_text = _format_ssq_for_ai(ssq_history)
        dlt_text = _format_dlt_for_ai(dlt_history)
        qxc_text = _format_qxc_for_ai(qxc_history)

        print("[彩票] 调用刘海蟾一次性推算三个彩种（含回测反馈）...")
        ai_output = _call_jiran(ssq_text, dlt_text, qxc_text, backtest_feedback)

        if ai_output:
            ssq_recs = _parse_ssq_recs(ai_output)
            dlt_recs = _parse_dlt_recs(ai_output)
            qxc_recs = _parse_qxc_recs(ai_output)

            ssq_result = (ssq_history, ssq_recs if ssq_recs else fallback.analyze_ssq(ssq_history))
            dlt_result = (dlt_history, dlt_recs if dlt_recs else fallback.analyze_dlt(dlt_history))
            qxc_result = (qxc_history, qxc_recs if qxc_recs else fallback.analyze_qxc(qxc_history))

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

    # 4. 在输出中附加回测结果
    result = format_lottery_section(ssq_result, dlt_result, qxc_result, backtest_result)

    return result


if __name__ == '__main__':
    result = generate_lottery_recommendations()
    print(result)
