#!/usr/bin/env python3
"""极简日报生成 - 不依赖缺失函数"""
import sys
import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')

# 直接调用底层函数
def generate_simple():
    """极简版：抓数据 + 生成推荐"""
    try:
        import lottery_analyzer as la
    except Exception as e:
        return f"导入失败: {e}"

    result = f"刘海蟾点金日报 {today_str}\n{'='*50}\n\n"

    # 双色球
    try:
        ssq_data = la.fetch_ssq_history(15)
        result += f"[双色球] 获取{len(ssq_data)}期历史数据\n"
        if ssq_data:
            latest = ssq_data[0]
            result += f"最新: {latest.get('period', '?')} 红={latest.get('reds', '?')} 蓝={latest.get('blue', '?')}\n"
        result += "\n"
    except Exception as e:
        result += f"[双色球] 错误: {e}\n\n"

    # 大乐透
    try:
        dlt_data = la.fetch_dlt_history(15)
        result += f"[大乐透] 获取{len(dlt_data)}期历史数据\n"
        if dlt_data:
            latest = dlt_data[0]
            result += f"最新: {latest.get('period', '?')} 前={latest.get('front', '?')} 后={latest.get('back', '?')}\n"
        result += "\n"
    except Exception as e:
        result += f"[大乐透] 错误: {e}\n\n"

    # 七星彩
    try:
        qxc_data = la.fetch_qxc_history(15)
        result += f"[七星彩] 获取{len(qxc_data)}期历史数据\n"
        if qxc_data:
            latest = qxc_data[0]
            digits = latest.get('digits', latest.get('numbers', '?'))
            result += f"最新: {latest.get('period', '?')} 号码={digits}\n"
        result += "\n"
    except Exception as e:
        result += f"[七星彩] 错误: {e}\n\n"

    result += f"\n生成时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}\n"
    return result


if __name__ == '__main__':
    content = generate_simple()
    print(content)
    # 写文件
    output_path = f'/root/asuan-scheduler/output/{today_str}.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"\n✅ 已写入: {output_path}")
