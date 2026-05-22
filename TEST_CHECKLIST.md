# 刘海蟾点金日报系统 - 阿算验证清单

## 修改概述
日期：2026-05-22
修改人：阿策

### 主要修复
1. ✅ **所有彩种每天生成推荐**（不管当天是否开奖）
2. ✅ **回测按开奖日历显示**（只显示昨天实际开奖的彩种）
3. ✅ **七星彩推荐去重**（避免和开奖号码高度相似）
4. ✅ **大乐透推荐修复**（直接实现，不依赖WeightedAnalyzer类冲突）
5. ✅ **混元API fallback**（超时30秒，自动用昨日新闻）

## 验证步骤

### 1. 拉取最新代码
```bash
cd /path/to/asuan-scheduler
git pull origin main
```

### 2. 检查关键文件
```bash
# 应该存在这些文件
ls -lh generate_full_daily.py  # 新的主生成脚本
ls -lh lottery_analyzer.py   # 已修复缺失函数问题
ls -lh scheduler.py          # 已更新fallback逻辑
```

### 3. 测试推荐生成（不发送邮件）
```bash
cd /root/asuan-scheduler
python3 -c "
from lottery_analyzer import fetch_ssq_history, fetch_dlt_history, fetch_qxc_history
from collections import Counter

# 测试双色球
print('=== 双色球 ===')
ssq = fetch_ssq_history(15)
print(f'数据条数: {len(ssq)}')
if ssq:
    print(f'最新: {ssq[0].get(\"period\")} 红={ssq[0].get(\"reds\")} 蓝={ssq[0].get(\"blue\")}')

# 测试大乐透
print('\\n=== 大乐透 ===')
dlt = fetch_dlt_history(15)
print(f'数据条数: {len(dlt)}')

# 测试七星彩
print('\\n=== 七星彩 ===')
qxc = fetch_qxc_history(15)
print(f'数据条数: {len(qxc)}')
"
```

### 4. 测试完整日报生成（静默模式）
```bash
cd /root/asuan-scheduler
python3 generate_full_daily.py 2>&1 | grep -E "INFO|ERROR" | grep -v "\[彩票\]|\[回测\]|\[AlgoEngine\]|\[Kelly\]"
```

### 5. 检查输出文件
```bash
today=$(date +%Y-%m-%d)
cat output/${today}.md | grep -E "今日推荐\(|刘海蟾推荐\("
```

**预期结果**：
- ✅ 双色球：今日推荐(5注)
- ✅ 大乐透：今日推荐(4注)
- ✅ 七星彩：今日推荐(4注)
- ✅ 回测：只显示昨天实际开奖的彩种

### 6. 验证开奖日历逻辑
| 星期 | 当天开奖 | 回测显示 |
|------|---------|---------|
| 周一 | 双色球+大乐透 | 周日双色球 |
| 周二 | 双色球+七星彩 | 周一的大乐透 |
| 周三 | 大乐透 | 周二的七星彩 |
| 周四 | 双色球 | 周三的大乐透 |
| 周五 | 双色球+七星彩 | 周四的双色球 |
| 周六 | 大乐透 | 周五的七星彩 |
| 周日 | 双色球 | 周六的大乐透 |

### 7. 检查Cron配置
```bash
crontab -l | grep generate_full_daily
```
**预期**：每天07:30自动运行

## 已知问题
1. ⚠️ **混元API偶尔超时**（30秒），会自动fallback到昨日新闻
2. ⚠️ **双色球推荐策略标签**显示为"刘海蟾推荐"，实际上是"核心注(加权)"等

## 联系
有问题直接微信@阿策或@刘老板
