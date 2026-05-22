#!/usr/bin/env python3
"""生成正确日报 - 修复回测彩种匹配问题"""
import os
import sys
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import json

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')
yesterday = (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d')

SMTP_SERVER = 'smtp.163.com'
SMTP_PORT = 465
SMTP_USER = 'tea0331@163.com'
SMTP_PASS = 'NYuLnGar8wT8RBit'
SMTP_TO = 'tea0331@163.com'

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def send_email(subject, body):
    """发送邮件"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_TO
    html = body.replace('\n', '<br>')
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [SMTP_TO], msg.as_string())
        server.quit()
        logging.info(f"✅ 邮件发送成功: {subject}")
        return True
    except Exception as e:
        logging.error(f"❌ 邮件发送失败: {e}")
        return False

def get_yesterday_lottery_type():
    """根据日期判断昨天开什么彩"""
    # 双色球: 二四日(0=周一,1=周二...) → 周一(0)的昨天是周日(6)=双色球
    # 简单算法: 昨天是周几?
    weekday = (datetime.now(CST) - timedelta(days=1)).weekday()
    # 0=周一 1=周二 2=周三 3=周四 4=周五 5=周六 6=周日
    if weekday in [0, 3, 6]:  # 周一/周四/周日 → 昨天开双色球
        return 'ssq'
    elif weekday in [2, 5]:  # 周三/周六 → 昨天开大乐透
        return 'dlt'
    else:
        return 'qxc'  # 周二/周五 → 昨天开七星彩

def backtest_yesterday():
    """回测昨天的推荐"""
    try:
        import lottery_analyzer as la
    except Exception as e:
        return f"导入失败: {e}"
    
    lottery_type = get_yesterday_lottery_type()
    today_weekday = datetime.now(CST).weekday()
    
    result = f"### 📊 开奖回测（旧版推荐记录）\n"
    result += f"昨日开奖: {'双色球' if lottery_type=='ssq' else '大乐透' if lottery_type=='dlt' else '七星彩'}\n\n"
    
    # 读取昨天的推荐
    try:
        with open('/root/asuan-scheduler/lottery-predictions.json', 'r') as f:
            predictions = json.load(f)
        
        yesterday_pred = None
        for item in predictions:
            if item.get('date') == yesterday and lottery_type == 'ssq':
                yesterday_pred = item.get('ssq_recs', [])
                break
        
        if yesterday_pred:
            result += f"找到{len(yesterday_pred)}条昨日推荐\n"
            # 获取实际开奖
            if lottery_type == 'ssq':
                history = la.fetch_ssq_history(5)
                if history:
                    latest = history[0]
                    result += f"🟡 **双色球** 第{latest.get('period')}期 开奖: {latest.get('reds')} + 蓝{latest.get('blue')}\n"
        else:
            result += "未找到昨日推荐记录\n"
    except Exception as e:
        result += f"读取推荐记录失败: {e}\n"
    
    return result

def generate_full_report():
    """生成完整日报"""
    try:
        import lottery_analyzer as la
    except Exception as e:
        return f"导入失败: {e}"
    
    now = datetime.now(CST).strftime('%Y-%m-%d %H:%M')
    report = f"刘海蟾点金日报 {today_str}\n{'='*50}\n\n"
    
    # 回测部分
    report += backtest_yesterday()
    report += "\n---\n\n"
    
    # 双色球
    try:
        ssq_data = la.fetch_ssq_history(15)
        report += f"### 🔴 双色球\n\n"
        report += f"**近期开奖：**\n| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
        for d in ssq_data[:3]:
            reds = d.get('reds', [])
            blue = d.get('blue', 0)
            report += f"| {d.get('period')} | {' '.join(map(str, reds))} | {blue:02d} |\n"
        
        # 简单推荐（基于最新一期）
        if ssq_data:
            latest = ssq_data[0]
            reds = latest.get('reds', [])
            blue = latest.get('blue', 0)
            # 生成5注（P0×2 + P1 + P2 + P3）
            new_reds_A = sorted([min(33, r+1) if r < 33 else 1 for r in reds[:6]])
            new_blue_A = min(16, blue+1) if blue < 16 else 1
            report += f"\n**下期推荐（简化版）：**\n"
            report += f"- [核心注A] {' '.join(map(str, new_reds_A))} + 蓝球{new_blue_A:02d}\n"
        report += "\n"
    except Exception as e:
        report += f"[双色球] 错误: {e}\n\n"
    
    # 大乐透
    try:
        dlt_data = la.fetch_dlt_history(15)
        report += f"### 🟡 大乐透\n\n"
        report += f"**近期开奖：**\n| 期号 | 前区 | 后区 |\n|------|------|------|\n"
        for d in dlt_data[:3]:
            front = d.get('front', [])
            back = d.get('back', [])
            report += f"| {d.get('period')} | {' '.join(map(str, front))} | {' '.join(map(str, back))} |\n"
        report += "\n"
    except Exception as e:
        report += f"[大乐透] 错误: {e}\n\n"
    
    # 七星彩
    try:
        qxc_data = la.fetch_qxc_history(15)
        report += f"### 🟢 七星彩\n\n"
        report += f"**近期开奖：**\n| 期号 | 号码 |\n|------|------|\n"
        for d in qxc_data[:3]:
            digits = d.get('digits', d.get('numbers', []))
            report += f"| {d.get('period')} | {' '.join(map(str, digits))} |\n"
        report += "\n"
    except Exception as e:
        report += f"[七星彩] 错误: {e}\n\n"
    
    report += f"\n生成时间: {now}\n"
    return report

if __name__ == '__main__':
    logging.info(f"========== 生成日报 {today_str} ==========")
    content = generate_full_report()
    print(content[:800])
    
    # 写文件
    output_path = f'/root/asuan-scheduler/output/{today_str}.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    logging.info(f"✅ 已写入: {output_path}")
    
    # 发邮件
    subject = f'刘海蟾点金日报 {today_str}'
    send_email(subject, content)
    logging.info(f"========== 完成 {today_str} ==========")
