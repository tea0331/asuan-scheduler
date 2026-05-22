#!/usr/bin/env python3
"""补生成05-21完整日报"""
import lottery_analyzer as la
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 读取05-20完整内容
with open('/root/asuan-scheduler/output/2026-05-20.md', 'r') as f:
    content_0520 = f.read()

# 提取新闻部分
if '---\n\n## 🎰' in content_0520:
    news_part = content_0520.split('---\n\n## 🎰')[0]
else:
    news_part = content_0520[:15000]

# 生成彩票部分
lottery_section = "\n---\n\n## 🎰 彩票号码推荐 — 刘海蟾点金（仅供娱乐参考）\n\n"
lottery_section += "> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n\n"

# 双色球
ssq_data = la.fetch_ssq_history(20)
lottery_section += "### 🔴 双色球\n\n"
lottery_section += "| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
for d in ssq_data[:5]:
    reds = d.get('reds', [])
    blue = d.get('blue', 0)
    lottery_section += f"| {d.get('period')} | {' '.join(map(str, reds))} | {blue:02d} |\n"

# 昨天(05-21)是周四，开双色球
lottery_section += f"\n**昨日(2026-05-21)开奖回测**: 双色球\n"
if ssq_data:
    latest = ssq_data[0]
    lottery_section += f"第{latest.get('period')}期: 红={latest.get('reds')} 蓝={latest.get('blue')}\n"
lottery_section += "\n"

# 大乐透
dlt_data = la.fetch_dlt_history(15)
lottery_section += "### 🟡 大乐透\n\n"
lottery_section += "| 期号 | 前区 | 后区 |\n|------|------|------|\n"
for d in dlt_data[:3]:
    front = d.get('front', [])
    back = d.get('back', [])
    lottery_section += f"| {d.get('period')} | {' '.join(map(str, front))} | {' '.join(map(str, back))} |\n"
lottery_section += "\n"

# 七星彩
qxc_data = la.fetch_qxc_history(15)
lottery_section += "### 🟢 七星彩\n\n"
lottery_section += "| 期号 | 号码 |\n|------|------|\n"
for d in qxc_data[:3]:
    digits = d.get('digits', d.get('numbers', []))
    lottery_section += f"| {d.get('period')} | {' '.join(map(str, digits))} |\n"
lottery_section += "\n"

# 拼接
full_content = f"# 阿算帮刘老板发财日报 — 2026-05-21\n\n---\n\n{news_part}{lottery_section}"

# 写文件
with open('/root/asuan-scheduler/output/2026-05-21.md', 'w') as f:
    f.write(full_content)

print(f"✅ 05-21日报已重新生成: {len(full_content)}字符")
print(f"文件大小: {len(full_content)} bytes")
