#!/usr/bin/env python3
"""发送阿算日报邮件（含东方朔邪修评价）"""
import sys, os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

def main():
    # SMTP配置（从环境变量读取）
    SMTP_USER = os.environ.get('SMTP_USER', '') or os.environ.get('SMTP_USER', '')
    SMTP_PASS = os.environ.get('SMTP_PASS', '') or os.environ.get('SMTP_PASSWORD', '')
    SMTP_TO = os.environ.get('SMTP_TO', 'tea0331@163.com')

    if not SMTP_USER or not SMTP_PASS:
        print("❌ 缺少SMTP凭据 (SMTP_USER, SMTP_PASSWORD)")
        return False

    today_str = datetime.now(CST).strftime('%Y-%m-%d')
    
    # 读取日报文件
    report_path = os.path.join(os.path.dirname(__file__), 'output', f'{today_str}.md')
    if not os.path.exists(report_path):
        print(f"❌ 日报文件不存在: {report_path}")
        return False

    with open(report_path, 'r', encoding='utf-8') as f:
        report_content = f.read()

    # 转换Markdown为HTML（简单转换）
    html_content = report_content.replace('\n', '<br>')
    html_content = html_content.replace('### ', '<h3>').replace('## ', '<h2>').replace('# ', '<h1>')
    html_content = html_content.replace('**', '<strong>').replace('*', '</strong>')
    
    # 添加样式
    styled_html = f"""<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 14px; line-height: 1.7; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; }}
h1 {{ font-size: 22px; border-bottom: 2px solid #e74c3c; padding-bottom: 8px; color: #2c3e50; }}
h2 {{ font-size: 18px; color: #2c3e50; margin-top: 25px; border-left: 4px solid #3498db; padding-left: 12px; }}
h3 {{ font-size: 16px; color: #555; margin-top: 15px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: center; }}
th {{ background: #f5f5f5; font-weight: bold; }}
strong {{ color: #e74c3c; }}
blockquote {{ border-left: 3px solid #e74c3c; padding-left: 10px; color: #666; margin: 10px 0; background: #f9f9f9; padding: 10px; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 25px 0; }}
.evil-section {{ background: #fff5f5; border: 1px solid #e74c3c; padding: 15px; border-radius: 5px; margin: 20px 0; }}
</style>
</head><body>
<div class="evil-section">
{html_content}
</div>
<p style="color:#999;font-size:12px;margin-top:30px;">— 阿算帮刘老板发财日报 | 东方朔邪修评价系统</p>
</body></html>"""

    subject = f"阿算帮刘老板发财日报 | {today_str}（含东方朔邪修评价）"
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = SMTP_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(styled_html, 'html', 'utf-8'))

        server = smtplib.SMTP_SSL('smtp.163.com', 465, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SMTP_TO, msg.as_string())
        server.quit()
        print(f"✅ 日报邮件已发送至 {SMTP_TO}")
        print(f"   主题: {subject}")
        print(f"   内容: {len(styled_html)}字符")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
