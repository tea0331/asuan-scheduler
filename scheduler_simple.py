#!/usr/bin/env python3
"""
调度器 - 最终版
新闻：调 generate_full_daily.generate_news_section()（有超时保护）
彩票：读 lottery-predictions.json
保证7:30准时发邮件，不卡死。
"""
import os
import sys
import glob
import json
import logging
import smtplib
import subprocess
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')
today_display = datetime.now(CST).strftime('%Y年%m月%d日')
yesterday_str = (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d')

# 邮件配置
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.163.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USER = os.getenv('SMTP_USER', 'tea0331@163.com')
SMTP_PASS = os.getenv('SMTP_PASSWORD', os.getenv('SMTP_PASS', 'WNpyg7vTPx4KTQ9s'))
SMTP_TO = os.getenv('SMTP_TO', 'tea0331@163.com')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    filename='/tmp/scheduler_simple.log', filemode='a')

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
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    try:
        import markdown as md
        html_body = md.markdown(body, extensions=['extra', 'nl2br'])
        html_wrapped = ('<html><body style="font-family:-apple-system,BlinkMacSystemFont,'
                       'Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.7;'
                       'color:#333;max-width:680px;margin:0 auto;padding:20px;">'
                       + html_body + '</body></html>')
        msg.attach(MIMEText(html_wrapped, 'html', 'utf-8'))
    except Exception as e:
        logging.warning(f"[邮件] Markdown渲染失败，降级纯文本: {e}")
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [SMTP_TO], msg.as_string())
        server.quit()
        logging.info(f"[邮件] 发送成功: {subject}")
        return True
    except Exception as e:
        logging.error(f"[邮件] 发送失败: {e}")
        return False


def format_lottery_section():
    """从 lottery-predictions.json 生成彩票展示部分"""
    pred_path = os.path.join(PROJECT_DIR, 'lottery-predictions.json')
    if not os.path.exists(pred_path):
        return "\n---\n## 🎰 彩票推荐\n（lottery-predictions.json 未找到）\n---\n"

    with open(pred_path, 'r', encoding='utf-8') as f:
        predictions = json.load(f)

    recs_today = {}
    recs_yesterday = {}
    if isinstance(predictions, list):
        for item in predictions:
            if not isinstance(item, dict):
                continue
            if item.get('date') == today_str:
                recs_today = item
            elif item.get('date') == yesterday_str:
                recs_yesterday = item
    recs = recs_today or recs_yesterday

    lines = [
        "\n---\n",
        "## 🎰 彩票号码推荐 - 刘海蟾点金·金主引擎(仅供娱乐参考)\n",
        "> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n\n"
    ]

    game_map = [
        ('ssq_recs', '🔴 双色球', ['reds', 'blue'], '红={} 蓝={}'),
        ('dlt_recs', '🔵 大乐透', ['front', 'back'], '前={} 后={}'),
        ('qxc_recs', '🟢 七星彩', ['digits'], '号码={}'),
    ]

    for rec_key, label, fields, fmt in game_map:
        game_recs = recs.get(rec_key, [])
        if not game_recs:
            continue
        lines.append(f"### {label}\n")
        for i, rec in enumerate(game_recs[:5]):
            if 'digits' in rec:
                nums = rec['digits']
                display = ' '.join(str(int(d)) for d in nums)
            elif 'reds' in rec:
                reds = ' '.join(f"{int(r):02d}" for r in rec['reds'])
                blue = int(rec.get('blue', 0))
                display = f"{reds} + {blue:02d}"
            elif 'front' in rec:
                front = ' '.join(f"{int(f):02d}" for f in rec['front'])
                back = ' '.join(f"{int(b):02d}" for b in rec['back'])
                display = f"{front} + {back}"
            else:
                display = str(rec)
            strategy = rec.get('strategy', '策略')
            lines.append(f"  - 注{i+1}: {display}  [{strategy}]\n")
        lines.append("\n")

    if not recs:
        lines.append("（推荐数据暂未同步，下次自动恢复）\n")

    return ''.join(lines)


def main():
    logging.info(f"========== 日报任务开始 {today_str} ==========")

    # 新闻部分（调 generate_full_daily.generate_news_section，有超时保护）
    try:
        from generate_full_daily import generate_news_section
        logging.info("[新闻] 开始生成（调 generate_full_daily）...")
        news_content = generate_news_section()
        logging.info(f"[新闻] ✅ 生成成功: {len(news_content)}字符")
    except TimeoutError:
        logging.warning("[新闻] 生成超时(150秒），使用降级模式")
        news_content = "## 一、每日资讯\n\n> 新闻生成超时，下次自动恢复。\n\n"
    except Exception as e:
        logging.warning(f"[新闻] 生成异常: {e}，使用降级模式")
        news_content = "## 一、每日资讯\n\n> 新闻生成异常，下次自动恢复。\n\n"

    # 彩票部分
    lottery = format_lottery_section()

    content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery}"

    # 写文件
    filepath = os.path.join(OUTPUT_DIR, f'{today_str}.md')
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info(f"[写入] {filepath} ({len(content)}字符)")
    except Exception as e:
        logging.error(f"[P0] 写入日报文件失败: {e}")

    # 发邮件
    subject = f'阿算帮刘老板发财日报 | {today_str}'
    send_email(subject, content)

    logging.info(f"========== 日报任务完成 {today_str} ==========")


if __name__ == '__main__':
    main()
