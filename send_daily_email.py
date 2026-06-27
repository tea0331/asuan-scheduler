#!/usr/bin/env python3
"""
发送日报邮件（含东方朔评价 + 马斯克推演）
读取 output/YYYY-MM-DD.md，发送完整内容到 163 邮箱。
"""
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime('%Y-%m-%d')

def load_env():
    """加载 .env 配置"""
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        print(f'❌ .env 文件不存在: {env_path}')
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env

def send_email(report_path, date_str):
    """读取日报文件并发送邮件"""
    env = load_env()
    smtp_server = env.get('SMTP_SERVER', 'smtp.163.com')
    smtp_port = int(env.get('SMTP_PORT', '465'))
    smtp_user = env.get('SMTP_USER', '')
    smtp_pass = env.get('SMTP_PASSWORD', '') or env.get('SMTP_PASS', '')
    smtp_to = env.get('SMTP_TO', '')

    if not smtp_pass:
        print('❌ SMTP密码未配置')
        return False

    if not os.path.exists(report_path):
        print(f'❌ 日报文件不存在: {report_path}')
        return False

    with open(report_path, 'r', encoding='utf-8') as f:
        full_body = f.read()

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'阿算帮刘老板发财日报 | {date_str}（含东方朔邪修评价 + 马斯克推演）'
    msg['From'] = smtp_user
    msg['To'] = smtp_to
    msg.attach(MIMEText(full_body, 'plain', 'utf-8'))

    # 尝试发送 HTML 版本
    try:
        import markdown as md
        html_body = md.markdown(full_body, extensions=['extra', 'nl2br'])
        html_wrapped = f'<html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.7;color:#333;max-width:680px;margin:0 auto;padding:20px;">{html_body}</body></html>'
        msg.attach(MIMEText(html_wrapped, 'html', 'utf-8'))
    except Exception:
        pass

    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [smtp_to], msg.as_string())
        server.quit()
        print(f'✅ 邮件发送成功: {msg["Subject"]}')
        return True
    except Exception as e:
        print(f'❌ 邮件发送失败: {e}')
        return False

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else TODAY
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', f'{date_str}.md')

    print(f'📧 发送日报邮件: {report_path}')
    send_email(report_path, date_str)

if __name__ == '__main__':
    main()
