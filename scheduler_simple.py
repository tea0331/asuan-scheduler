#!/usr/bin/env python3
"""
调度器 - 统一入口
调用 generate_full_daily.py 生成完整日报（新闻AI+彩票推荐），然后发送邮件。
不再独立生成内容，避免旁路脚本与主流程脱节。
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

# 邮件配置（优先读取环境变量）
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.163.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USER = os.getenv('SMTP_USER', 'tea0331@163.com')
SMTP_PASS = os.getenv('SMTP_PASSWORD', os.getenv('SMTP_PASS', ''))
SMTP_TO = os.getenv('SMTP_TO', 'tea0331@163.com')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    filename='/tmp/scheduler_simple.log', filemode='a')

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

OUTPUT_DIR = os.path.join(PROJECT_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def send_email(subject, body):
    """发送邮件：Markdown正文+HTML渲染双格式"""
    if not SMTP_PASS:
        logging.warning("[邮件] SMTP密码未配置，跳过发送")
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_TO
    # 纯文本版
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    # HTML渲染版
    try:
        import markdown as md
        html_body = md.markdown(body, extensions=['extra', 'nl2br'])
        html_wrapped = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
            font-size:15px;line-height:1.7;color:#333;max-width:680px;margin:0 auto;padding:20px;">
            {html_body}</body></html>"""
        msg.attach(MIMEText(html_wrapped, 'html', 'utf-8'))
    except Exception as e:
        logging.warning(f"[邮件] Markdown渲染失败，降级纯文本: {e}")
        # 已attach了plain版，不需要再添加
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


def main():
    logging.info(f"========== 日报任务开始 {today_str} ==========")

    # 1. 调用 generate_full_daily.py 生成完整日报
    content = None
    try:
        from generate_full_daily import generate_news_section, generate_lottery_section
        from generate_full_daily import _run_with_timeout

        logging.info("[生成] 开始生成完整日报（新闻AI+彩票推荐）...")

        # 新闻部分（150秒超时兜底）
        try:
            news_content = _run_with_timeout(generate_news_section, timeout=150)
        except Exception as e:
            logging.warning(f"[P1] 新闻生成异常: {e}")
            news_content = "## 一、每日资讯\n（今日新闻生成超时，下次自动恢复）\n"

        # 彩票部分
        try:
            lottery_content = generate_lottery_section()
        except Exception as e:
            logging.error(f"[P1] 彩票生成异常: {e}")
            lottery_content = "## 🎰 彩票推荐\n（今日彩票生成异常，下次自动恢复）\n"

        content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}"

    except Exception as e:
        logging.error(f"[生成] 完整日报生成失败: {e}")
        import traceback
        logging.error(traceback.format_exc())

    # 2. Fallback：生成失败时用最近的日报文件
    if not content:
        import glob
        files = glob.glob(os.path.join(OUTPUT_DIR, '*.md'))
        if files:
            fallback_file = max(files, key=os.path.getmtime)
            with open(fallback_file, 'r', encoding='utf-8') as f:
                content = f.read()
            logging.warning(f"[Fallback] 使用最近日报: {fallback_file}")
        else:
            logging.error("[P0] 没有找到任何日报文件")
            return

    # 3. 写文件
    filepath = os.path.join(OUTPUT_DIR, f'{today_str}.md')
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info(f"[写入] ✅ {filepath} ({len(content)}字符)")
    except Exception as e:
        logging.error(f"[P0] 写入日报文件失败: {e}")

    # 4. 发邮件
    if SMTP_PASS:
        subject = f'阿算帮刘老板发财日报 | {today_str}'
        send_email(subject, content)
    else:
        logging.warning("[P1] SMTP密码未配置，跳过邮件发送")

    logging.info(f"========== 日报任务完成 {today_str} ==========")


if __name__ == '__main__':
    main()
