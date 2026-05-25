"""
数据获取模块 - 统一爬虫接口
v4.0 重构: 从 lottery_analyzer.py 拆出，提供通用数据获取接口
"""

import re
import time
import requests
from typing import Optional, List, Dict

# 导入原有常量/工具
# 导入原有常量/工具
from lottery_analyzer import HEADERS, _SCRAPLING_AVAILABLE

class DataFetcher:
    """通用彩票数据获取器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
    
    def fetch_ssq(self, periods: int = 15, retries: int = 3) -> Optional[List[Dict]]:
        """双色球历史数据"""
        return self._fetch_with_fallback(
            game='ssq',
            periods=periods,
            retries=retries,
            url_500com='https://datachart.500.com/ssq/history/newinc/history.php',
            referer_500com='https://datachart.500.com/ssq/history/',
            parse_fn=_parse_ssq_html,
            expected_fn=_get_expected_ssq_period,
            url_cjcp=f'https://www.cjcp.cn/kaijiang/ssq/{periods}qi.html'
        )
    
    def fetch_dlt(self, periods: int = 15, retries: int = 3) -> Optional[List[Dict]]:
        """大乐透历史数据"""
        return self._fetch_with_fallback(
            game='dlt',
            periods=periods,
            retries=retries,
            url_500com='https://datachart.500.com/dlt/history/newinc/history.php',
            referer_500com='https://datachart.500.com/dlt/history/',
            parse_fn=_parse_dlt_html,
            expected_fn=_get_expected_dlt_period,
            url_cjcp=f'https://www.cjcp.cn/kaijiang/dlt/{periods}qi.html'
        )
    
    def fetch_qxc(self, periods: int = 15) -> Optional[List[Dict]]:
        """七星彩历史数据 - 从kaijiang.500.com抓取"""
        try:
            results = []
            index_url = 'https://kaijiang.500.com/qxc.shtml'
            resp = self.session.get(index_url, timeout=15)
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
                results.append({
                    'period': unique_periods[0], 
                    'digits': [int(d) for d in current_digits[:7]]
                })
                print(f"[七星彩-500] 主页当期: {unique_periods[0]} → {current_digits[:7]}")

            # 历史期逐期抓详情页
            start_idx = 1 if current_digits and len(current_digits) >= 7 else 0
            for period in unique_periods[start_idx:periods]:
                try:
                    page_url = f'https://kaijiang.500.com/shtml/qxc/{period}.shtml'
                    page_resp = self.session.get(page_url, timeout=10)
                    page_resp.encoding = 'gb2312'
                    digits = re.findall(r'class="ball_orange">\s*(\d{1,2})\s*</li>', page_resp.text)
                    if len(digits) >= 7:
                        results.append({'period': period, 'digits': [int(d) for d in digits[:7]]})
                    else:
                        digits = re.findall(r'class="[^"]*ball[^"]*"[^>]*>\s*(\d{1,2})\s*<', page_resp.text)
                        if len(digits) >= 7:
                            results.append({'period': period, 'digits': [int(d) for d in digits[:7]]})
                except Exception:
                    continue

            if results:
                results.sort(key=lambda x: x['period'], reverse=True)
                print(f"[七星彩-500] 抓取成功: {len(results)}期 (最新{results[0]['period']})")
            return results if results else None
        except Exception as e:
            print(f"[七星彩-500] 抓取失败: {e}")
            return None
    
    def _fetch_with_fallback(self, game, periods, retries, 
                           url_500com, referer_500com, parse_fn, expected_fn,
                           url_cjcp=None):
        """通用抓取逻辑：500com → scrapling降级 → cjcp备用"""
        # 动态导入解析函数（避免循环导入）
        if parse_fn.__name__ == '_parse_ssq_html':
            from lottery_analyzer import _parse_ssq_html as parse_fn
        elif parse_fn.__name__ == '_parse_dlt_html':
            from lottery_analyzer import _parse_dlt_html as parse_fn
        
        for attempt in range(retries):
            try:
                ts = int(time.time())
                url = f'{url_500com}?t={ts}'
                print(f"[{game}-500] 请求 (尝试{attempt+1}/{retries}): {url}")
                resp = self.session.get(url, timeout=15)
                print(f"[{game}-500] 状态码: {resp.status_code}, 长度: {len(resp.text)}")
                
                if resp.status_code != 200:
                    print(f"[{game}-500] HTTP错误: {resp.status_code}")
                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    return None
                
                resp.encoding = 'gb2312'
                result = parse_fn(resp.text, periods)
                
                if result and len(result) > 0:
                    latest_period = result[0]['period']
                    print(f"[{game}-500] 获取到期号: {latest_period}")
                    expected_min = expected_fn() - 8
                    if int(latest_period) < expected_min:
                        print(f"[{game}-500] 警告: 数据过期,期望至少 {expected_min}")
                        if attempt < retries - 1:
                            time.sleep(2)
                            continue
                        return None
                    return result
                else:
                    print(f"[{game}-500] 解析结果为空")
                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    return None
            except Exception as e:
                import traceback
                print(f"[{game}-500] 抓取失败 (尝试{attempt+1}/{retries}): {type(e).__name__}: {e}")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                print(f"[{game}-500] 堆栈: {traceback.format_exc()[:200]}")
                return None
        
        # scrapling降级
        html = None  # scrapling已移除
        if html:
            result = parse_fn(html, periods)
            if html:
                result = parse_fn(html, periods)
                if result and len(result) > 0:
                    print(f"[{game}-500] ✅ scrapling降级成功: {len(result)} 期")
                    return result
        
        # cjcp备用
        if url_cjcp:
            try:
                print(f"[{game}-cjcp] 尝试备用源: {url_cjcp}")
                resp = requests.get(url_cjcp, headers=HEADERS, timeout=15)
                resp.encoding = 'utf-8'
                result = parse_fn(resp.text, periods)
                if result:
                    print(f"[{game}-cjcp] ✅ 备用源成功: {len(result)} 期")
                    return result
            except Exception as e:
                print(f"[{game}-cjcp] 备用源失败: {e}")
        
        print(f"[{game}] 所有数据源失败")
        return None


# 便捷函数（保持与原接口兼容）
def fetch_ssq_history(periods=15):
    return DataFetcher().fetch_ssq(periods)

def fetch_dlt_history(periods=15):
    return DataFetcher().fetch_dlt(periods)

def fetch_qxc_history(periods=15):
    return DataFetcher().fetch_qxc(periods)
