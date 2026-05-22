#!/usr/bin/env python3
"""
极简版scheduler - 生成+发送一体化
不再依赖隔夜文件,改为先生成日报,再发送
"""
import os
import sys
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')

# 邮件配置
SMTP_SERVER = 'smtp.163.com'
SMTP_PORT = 465
SMTP_USER = 'tea0331@163.com'
SMTP_PASS = 'NYuLnGar8wT8RBit'
SMTP_TO = 'tea0331@163.com'

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    filename='/tmp/scheduler_simple.log', filemode='a')

OUTPUT_DIR = '/root/asuan-scheduler/output'
os.makedirs(OUTPUT_DIR, exist_ok=True)


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


def generate_daily_report():
    """生成日报(调用lottery_analyzer)"""
    try:
        import lottery_analyzer
        logging.info("[生成] 开始调用lottery_analyzer...")
        result = lottery_analyzer.generate_lottery_recommendations()
        logging.info(f"[生成] 完成,长度={len(result)}字符")

        # 写文件
        filepath = os.path.join(OUTPUT_DIR, f'{today_str}.md')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(result)
        logging.info(f"[生成] 已写入: {filepath}")
        return result
    except Exception as e:
        logging.error(f"[生成] 失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def main():
    logging.info(f"========== 极简版日报任务开始 {today_str} ==========")

    # 1. 尝试生成日报
    content = None
    try:
        content = generate_daily_report()
    except Exception as e:
        logging.error(f"生成失败: {e}，fallback到最近文件")

    # 2. Fallback：生成失败时用最近文件
    if not content:
        output_dir = '/root/asuan-scheduler/output'
        files = __import__('glob').glob(os.path.join(output_dir, '*.md'))
        if files:
            fallback_file = max(files, key=os.path.getmtime)
            with open(fallback_file, 'r', encoding='utf-8') as f:
                content = f.read()
            logging.info(f"Fallback到: {fallback_file}")
        else:
            logging.error("没有找到任何日报文件")
            sys.exit(1)

    # 3. 发邮件
    subject = f'刘海蟾点金日报 {today_str}'
    send_email(subject, content)

    logging.info(f"========== 极简版日报任务完成 {today_str} ==========")


if __name__ == '__main__':
    main()
