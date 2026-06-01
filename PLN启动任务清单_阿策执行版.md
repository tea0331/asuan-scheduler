# PLN(威力彩)启动任务清单
**日期**: 2026-06-01
**范围**: 只做PLN，LTN不动

---

## 阶段1：数据源（P0，6/2 18:00前）

### 任务1-1：安装taiwanlottery包并测试
```bash
cd /root/asuan-scheduler
pip3 install taiwanlottery
python3 -c "
from TaiwanLottery import TaiwanLotteryCrawler
l = TaiwanLotteryCrawler()
print('PLN:', l.super_lotto()[:2])
"
```
- 如果SSL报错（api.taiwanlottery.com EOF），走方案B

### 任务1-2：重写fetch_pln_history() — 方案A（优先）
文件：`games/pln.py`
```python
def fetch_pln_history(periods: int = 15) -> Optional[List[Dict]]:
    """PLN历史数据获取 — 从台湾彩券官网爬取"""
    try:
        from TaiwanLottery import TaiwanLotteryCrawler
        l = TaiwanLotteryCrawler()
        raw = l.super_lotto()
        if not raw:
            return _fallback_csv(periods)
        # 转为系统内部格式
        results = []
        for r in raw[:periods]:
            results.append({
                'period': r.get('期別', r.get('period', '')),
                'numbers': [int(x) for x in r.get('區碼', r.get('numbers', []))],
                'special': int(r.get('特別號', r.get('special', 0))),
            })
        return results if results else _fallback_csv(periods)
    except Exception as e:
        print(f'[PLN] taiwanlottery获取失败: {e}, 降级CSV')
        return _fallback_csv(periods)

def _fallback_csv(periods):
    """CSV降级方案"""
    import csv, os
    csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'pln_history.csv')
    if not os.path.exists(csv_path):
        return None
    results = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in list(reader)[:periods]:
            results.append({
                'period': row['period'],
                'numbers': [int(row[f'num{i}']) for i in range(1,7)],
                'special': int(row['special']),
            })
    return results if results else None
```

### 任务1-2备选：方案B（magayo爬取）
如果taiwanlottery包SSL不通，改用magayo：
```python
def fetch_pln_history(periods: int = 15) -> Optional[List[Dict]]:
    """PLN历史数据 — 从magayo爬取"""
    try:
        import requests
        from bs4 import BeautifulSoup
        resp = requests.get('https://www.magayo.com/lotto/taiwan/super-lotto-results/', timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # 解析表格...（阿策需要调试HTML结构）
        ...
    except Exception as e:
        return _fallback_csv(periods)
```

### 任务1-3：更新CSV为真实数据
文件：`data/pln_history.csv`
用我刚抓到的真实开奖替换模拟数据：
```
period,num1,num2,num3,num4,num5,num6,special
20260528,1,2,24,31,34,38,3
20260525,9,17,21,24,31,33,3
20260521,6,14,22,28,35,38,1
20260518,6,7,14,25,29,34,4
20260514,6,8,9,17,21,29,8
20260511,15,19,23,26,31,38,5
20260507,3,14,15,24,34,38,3
20260504,9,21,29,32,36,38,2
20260430,1,4,13,19,27,30,8
20260427,6,8,27,33,35,38,2
```

---

## 阶段2：闭环打通（P1，6/3 18:00前）

### 任务2-1：_record_daily_bets() 加PLN
文件：`jin_zhu.py` 第1720-1726行
```python
# 改前
kelly_map = {'ssq': 1, 'dlt': 1, 'qxc': 1}
for game in ['ssq', 'dlt', 'qxc']:

# 改后
kelly_map = {'ssq': 1, 'dlt': 1, 'qxc': 1, 'pln': 1}
for game in ['ssq', 'dlt', 'qxc', 'pln']:
```

### 任务2-2：_save_predictions() 加PLN
文件：`jin_zhu.py` 第1737-1742行
```python
# 改前
predictions.append({
    'date': date,
    'ssq_recs': result.get('ssq', []),
    'dlt_recs': result.get('dlt', []),
    'qxc_recs': result.get('qxc', []),
})

# 改后
predictions.append({
    'date': date,
    'ssq_recs': result.get('ssq', []),
    'dlt_recs': result.get('dlt', []),
    'qxc_recs': result.get('qxc', []),
    'pln_recs': result.get('pln', []),
})
```

### 任务2-3：generate_daily_section() 加PLN展示
文件：`jin_zhu.py` 约第1634行（七星彩之后），新增PLN区块：
```python
        # ===== 威力彩 =====
        try:
            pln_data = self._fetch_history('pln')
            section += "### 🟣 台湾威力彩(PLN)\n\n"
            section += "**最近开奖**:\n\n"
            section += "| 期号 | 主号 | 特别号 |\n|------|------|--------|\n"
            for d in pln_data[:3]:
                nums = d.get('numbers', [])
                sp = d.get('special', 0)
                section += f"| {d.get('period')} | {_fmt_nums(nums)} | {sp:02d} |\n"

            pln_recs = daily_result.get('pln', [])
            if not pln_recs:
                pln_recs = self.generate_recs('pln')
            if pln_recs:
                section += f"\n**今日推荐({len(pln_recs)}注)**:\n"
                for rec in pln_recs:
                    nums = rec.get('numbers', [])
                    main = nums[:6] if len(nums) > 6 else nums
                    sp = nums[6] if len(nums) > 6 else rec.get('special', 0)
                    section += f"  - {rec.get('strategy', '未知')}: {_fmt_nums(main)} + 特号{sp:02d}\n"

            # 开奖日回测（威力彩周一四开奖）
            pln_days = {0, 3}  # 周一、周四
            if yesterday_weekday in pln_days and pln_data:
                latest = pln_data[0]
                latest_nums = latest.get('numbers', [])
                latest_sp = latest.get('special', 0)
                section += f"\n**昨日开奖回测** (第{latest.get('period')}期):\n"
                section += f"开奖号码: {_fmt_nums(latest_nums)} + 特号{latest_sp:02d}\n"
                y_recs = _read_yesterday_recs('pln')
                if y_recs:
                    section += f"\n刘海蟾昨日推荐({len(y_recs)}注):\n"
                    for rec in y_recs:
                        rec_nums = rec.get('numbers', [])
                        rec_main = rec_nums[:6] if len(rec_nums) > 6 else rec_nums
                        rec_sp = rec_nums[6] if len(rec_nums) > 6 else rec.get('special', 0)
                        hit_main = set(rec_main) & set(latest_nums)
                        hit_sp = 1 if rec_sp == latest_sp else 0
                        hit_count = len(hit_main) + hit_sp
                        section += f"  - {rec.get('strategy', '未知')}: {_fmt_nums(rec_main)} + 特号{rec_sp:02d} "
                        if hit_count > 0:
                            section += f"→ 中{len(hit_main)}主"
                            if hit_sp:
                                section += "+1特"
                            section += f"({hit_count}码)"
                        else:
                            section += "→ 未中"
                        section += "\n"
                else:
                    section += "\n(昨日推荐记录暂未同步,回测数据下期补全)\n"
            section += "\n"
        except Exception as e:
            section += f"[威力彩] 错误: {e}\n\n"
```

同时修改开奖日历部分（约第1495行），加上：
```python
pln_days = {0, 3}   # 威力彩:周一四
```

### 任务2-4：_calc_prize() 加PLN奖级
文件：`algo_module.py` 第1237行后，新增：
```python
            elif game == 'pln':
                main = numbers.get('numbers', [])[:6]
                special = numbers.get('special', numbers.get('numbers', [0]*7)[6] if len(numbers.get('numbers',[])) > 6 else 0)
                actual_main = actual.get('numbers', [])[:6]
                actual_special = actual.get('special', 0)
                main_hits = len(set(main) & set(actual_main))
                special_hit = 1 if special == actual_special else 0
                total_hits = main_hits + special_hit
                # 威力彩奖级（6/38+1/8，共9级）
                if main_hits == 6 and special_hit == 1: return {'tier': 1, 'name': '头奖', 'prize': 50000000, 'hit_count': total_hits}
                elif main_hits == 6: return {'tier': 2, 'name': '贰奖', 'prize': 1000000, 'hit_count': total_hits}
                elif main_hits == 5 and special_hit == 1: return {'tier': 3, 'name': '参奖', 'prize': 50000, 'hit_count': total_hits}
                elif main_hits == 5: return {'tier': 4, 'name': '肆奖', 'prize': 4000, 'hit_count': total_hits}
                elif main_hits == 4 and special_hit == 1: return {'tier': 5, 'name': '伍奖', 'prize': 800, 'hit_count': total_hits}
                elif main_hits == 4: return {'tier': 6, 'name': '陆奖', 'prize': 400, 'hit_count': total_hits}
                elif main_hits == 3 and special_hit == 1: return {'tier': 7, 'name': '柒奖', 'prize': 200, 'hit_count': total_hits}
                elif main_hits == 3: return {'tier': 8, 'name': '捌奖', 'prize': 100, 'hit_count': total_hits}
                elif main_hits == 2 and special_hit == 1: return {'tier': 9, 'name': '普奖', 'prize': 50, 'hit_count': total_hits}
                return {'tier': 0, 'name': '未中奖', 'prize': 0, 'hit_count': total_hits}
```

### 任务2-5：ROITracker.settle() 加PLN
文件：`algo_module.py` 第1196行
```python
# 改前
import games.ssq, games.dlt, games.qxc
games_modules = [
    ('ssq', games.ssq.fetch_ssq_history),
    ('dlt', games.dlt.fetch_dlt_history),
    ('qxc', games.qxc.fetch_qxc_history)
]

# 改后
import games.ssq, games.dlt, games.qxc, games.pln
games_modules = [
    ('ssq', games.ssq.fetch_ssq_history),
    ('dlt', games.dlt.fetch_dlt_history),
    ('qxc', games.qxc.fetch_qxc_history),
    ('pln', games.pln.fetch_pln_history),
]
```

### 任务2-6：LOTTERY_SCHEDULE加PLN
文件：`lottery_analyzer.py` 第96-100行
```python
# 改前
LOTTERY_SCHEDULE = {
    'ssq': [1, 3, 6],
    'dlt': [0, 2, 5],
    'qxc': [1, 4, 6],
}
LOTTERY_NAMES = {
    'ssq': '双色球',
    'dlt': '大乐透',
    'qxc': '七星彩',
}

# 改后
LOTTERY_SCHEDULE = {
    'ssq': [1, 3, 6],
    'dlt': [0, 2, 5],
    'qxc': [1, 4, 6],
    'pln': [0, 3],      # 威力彩:周一四
}
LOTTERY_NAMES = {
    'ssq': '双色球',
    'dlt': '大乐透',
    'qxc': '七星彩',
    'pln': '台湾威力彩',
}
```

---

## 阶段3：虚拟用户扩展（P1，6/3 18:00前）

### 任务3-1：create_virtual_users.py 加PLN
文件：`create_virtual_users.py` 第195-199行
```python
# 改前
for game in ['ssq', 'dlt', 'qxc']:
    history = jz._fetch_history(game)
    history_cache[game] = history
kelly_map = {'ssq': 1, 'dlt': 1, 'qxc': 1}
for game in ['ssq', 'dlt', 'qxc']:

# 改后
for game in ['ssq', 'dlt', 'qxc', 'pln']:
    history = jz._fetch_history(game)
    history_cache[game] = history
kelly_map = {'ssq': 1, 'dlt': 1, 'qxc': 1, 'pln': 1}
for game in ['ssq', 'dlt', 'qxc', 'pln']:
```

---

## 阶段4：Bug修复（P1，6/3 18:00前）

### 任务4-1：analyze_pln() 补齐special_avg_interval
文件：`lottery_analyzer.py` 约1255行，analyze_pln()返回值加：
```python
'special_avg_interval': special_avg_interval,  # _calc_weights已经算了，只需加到返回值
```

### 任务4-2：calc_daily_roi加PLN
文件：`algo_module.py` 第1301行
```python
# 改前
for game in ['ssq', 'dlt', 'qxc']:

# 改后
for game in ['ssq', 'dlt', 'qxc', 'pln']:
```

---

## 验证清单

```bash
# 1. 数据源
cd /root/asuan-scheduler && python3 -c "
from games.pln import fetch_pln_history
h = fetch_pln_history(5)
print(f'获取{len(h) if h else 0}期')
if h: print(h[0])
"

# 2. 生成推荐
cd /root/asuan-scheduler && python3 -c "
from jin_zhu import get_jinzhu
jz = get_jinzhu()
recs = jz.generate_recs('pln')
print(f'{len(recs)}注')
for r in recs:
    print(r)
"

# 3. 闭环
cd /root/asuan-scheduler && python3 -c "
from jin_zhu import get_jinzhu
jz = get_jinzhu()
r = jz.daily_run()
print('pln:', len(r.get('pln',[])), '注')
"

# 4. 奖级
cd /root/asuan-scheduler && python3 -c "
from algo_module import ROITracker, AlgoDB
t = ROITracker(AlgoDB())
# 全中：6主+1特号
p = t._calc_prize('pln', {'numbers':[1,2,24,31,34,38,3]}, {'numbers':[1,2,24,31,34,38], 'special':3})
print(p)
"

# 5. 虚拟用户
cd /root/asuan-scheduler && python3 -c "
from create_virtual_users import generate_50_users
users = generate_50_users()
print(f'{len(users)} users OK')
"

# 6. 日报
cd /root/asuan-scheduler && python3 -c "
from jin_zhu import get_jinzhu
jz = get_jinzhu()
r = jz.daily_run()
section = jz.generate_daily_section(r)
print('威力彩' in section)
"
```
