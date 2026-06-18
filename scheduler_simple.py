#!/usr/bin/env python3
"""
调度器 V6 — 日报调度层（只调度不生成）

架构:
  scheduler_simple.py（调度层）
    ├── generate_all_sections() → generate_full_daily.py (6板块AI生成)
    ├── generate_lottery_section() → generate_full_daily.py → jin_zhu.py
    ├── generate_taiwan_section() → generate_full_daily.py → generate_taiwan.py
    └── daily_report_guard.py（验证层，发送前检查）

⚠️ 本文件只负责调度+发送，不生成任何新闻内容
⚠️ 日报架构修改权限: 仅WorkBuddy，阿策禁止修改
"""
import os
import sys
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')
today_display = datetime.now(CST).strftime('%Y年%m月%d日')
yesterday_str = (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d')

# 邮件配置 (从环境变量读取，不硬编码)
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.163.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASSWORD', os.getenv('SMTP_PASS', ''))
SMTP_TO = os.getenv('SMTP_TO', '')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    filename='/tmp/scheduler_simple.log', filemode='a')

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def send_email(subject, body):
    """发送邮件: Markdown正文+HTML渲染双格式"""
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


def main():
    logging.info(f"========== 日报调度开始 {today_str} ==========")

    # 1. 生成6板块新闻分析 (调 generate_full_daily，有超时保护)
    news_content = ""
    try:
        from generate_full_daily import generate_all_sections
        logging.info("[调度] 开始生成6板块新闻分析...")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(generate_all_sections)
            news_content = future.result(timeout=200)
        logging.info(f"[调度] ✅ 新闻分析完成: {len(news_content)}字符")
    except TimeoutError:
        logging.warning("[调度] 新闻生成超时(200秒)，使用降级模式")
        news_content = "## 一、每日资讯\n\n> 新闻生成超时，降级模式运行。\n\n"
    except Exception as e:
        logging.warning(f"[调度] 新闻生成异常: {e}，使用降级模式")
        try:
            from generate_full_daily import _fallback_all_sections
            news_content = _fallback_all_sections([], [])
        except Exception:
            news_content = "## 一、每日资讯\n\n> 新闻生成异常，降级模式运行。\n\n"

    # 2. 生成彩票部分
    lottery_content = ""
    try:
        from generate_full_daily import generate_lottery_section
        logging.info("[调度] 开始生成彩票推荐...")
        lottery_content = generate_lottery_section()
        logging.info(f"[调度] ✅ 彩票推荐完成: {len(lottery_content)}字符")
    except Exception as e:
        logging.warning(f"[调度] 彩票生成异常: {e}")
        lottery_content = "## 🎰 彩票推荐\n（今日彩票生成异常）\n"

    # 3. 生成台湾彩种
    taiwan_content = ""
    try:
        from generate_full_daily import generate_taiwan_section
        taiwan_content = generate_taiwan_section()
        logging.info(f"[调度] ✅ 台湾彩种完成: {len(taiwan_content)}字符")
    except Exception as e:
        logging.warning(f"[调度] 台湾彩种异常: {e}")

    # 4. 拼接完整日报
    content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}{taiwan_content}"

    # 5. 质量守护 — 发送前验证
    guard_passed = True
    try:
        from daily_report_guard import validate_report
        guard_result = validate_report(content)
        if guard_result['valid']:
            logging.info(f"[守护] ✅ 日报质量通过 (得分: {guard_result['score']}/100)")
        else:
            logging.warning(f"[守护] ⚠️ 日报质量不通过: {guard_result['errors']}")
            guard_passed = False
            if guard_result.get('warnings'):
                for w in guard_result['warnings']:
                    logging.warning(f"[守护] {w}")
    except Exception as e:
        logging.warning(f"[守护] 验证异常(不阻塞): {e}")

    # 6. 写文件
    filepath = os.path.join(OUTPUT_DIR, f'{today_str}.md')
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info(f"[写入] {filepath} ({len(content)}字符)")
    except Exception as e:
        logging.error(f"[P0] 写入日报文件失败: {e}")

    # 7. 发邮件 (即使守护不通过也发送，但标记质量)
    if not SMTP_PASS:
        logging.warning("[P1] SMTP密码未配置，跳过邮件发送")
    else:
        quality_tag = "" if guard_passed else " [质量待审]"
        subject = f'阿算帮刘老板发财日报{quality_tag} | {today_str}'
        send_email(subject, content)

    logging.info(f"========== 日报调度完成 {today_str} ==========")


if __name__ == '__main__':
    main()
