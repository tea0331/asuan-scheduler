#!/usr/bin/env python3
"""生成完整日报 + 发邮件"""
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

def generate_full_report():
    """生成完整日报（手动拼接）"""
    try:
        import lottery_analyzer as la
    except Exception as e:
        return f"导入失败: {e}", None

    now = datetime.now(CST).strftime('%Y-%m-%d %H:%M')
    report = f"刘海蟾点金日报 {today_str}\n{'='*50}\n\n"

    # 双色球
    try:
        ssq_data = la.fetch_ssq_history(15)
        report += f"【双色球】\n获取{len(ssq_data)}期历史数据\n"
        if ssq_data:
            latest = ssq_data[0]
            report += f"最新: {latest.get('period', '?')} 红={latest.get('reds', '?')} 蓝={latest.get('blue', '?')}\n"
            # 生成推荐（简化版）
            reds = latest.get('reds', [])
            blue = latest.get('blue', 0)
            if reds and blue:
                # 简单推荐：基于最近一期，微调
                new_reds = [min(33, r+1) if r < 33 else 1 for r in reds[:5]]
                new_blue = min(16, blue+1) if blue < 16 else 1
                report += f"推荐: 红={new_reds} 蓝={new_blue}\n"
        report += "\n"
    except Exception as e:
        report += f"[双色球] 错误: {e}\n\n"

    # 大乐透
    try:
        dlt_data = la.fetch_dlt_history(15)
        report += f"【大乐透】\n获取{len(dlt_data)}期历史数据\n"
        if dlt_data:
            latest = dlt_data[0]
            report += f"最新: {latest.get('period', '?')} 前={latest.get('front', '?')} 后={latest.get('back', '?')}\n"
        report += "\n"
    except Exception as e:
        report += f"[大乐透] 错误: {e}\n\n"

    # 七星彩
    try:
        qxc_data = la.fetch_qxc_history(15)
        report += f"【七星彩】\n获取{len(qxc_data)}期历史数据\n"
        if qxc_data:
            latest = qxc_data[0]
            digits = latest.get('digits', latest.get('numbers', '?'))
            report += f"最新: {latest.get('period', '?')} 号码={digits}\n"
        report += "\n"
    except Exception as e:
        report += f"[七星彩] 错误: {e}\n\n"

    report += f"\n生成时间: {now}\n"
    return report, None

if __name__ == '__main__':
    logging.info(f"========== 生成日报 {today_str} ==========")
    content, _ = generate_full_report()
    print(content[:500])
    
    # 写文件
    output_path = f'/root/asuan-scheduler/output/{today_str}.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    logging.info(f"✅ 已写入: {output_path}")
    
    # 发邮件
    subject = f'刘海蟾点金日报 {today_str}'
    send_email(subject, content)
    logging.info(f"========== 完成 {today_str} ==========")
