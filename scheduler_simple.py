#!/usr/bin/env python3
"""
调度器 - 邪修版（天之道框架 + 价格传导分析）
新闻：固定模板（含传导链+人脉掮客角度）
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


def fetch_baidu_hot_curl(count=15):
    """用curl抓百度热搜（不依赖requests）"""
    try:
        result = subprocess.run(
            ['curl', '-s', '-H', 'User-Agent: Mozilla/5.0', '--max-time', '10',
             'https://top.baidu.com/board?tab=realtime'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return []
        html = result.stdout
        titles = re.findall(r'<div class="c-single-text-ellipsis">([^<]+)</div>', html)
        if not titles:
            titles = re.findall(r'title="([^"]+)"', html)[:20]
        results = []
        for t in titles[:count]:
            t = t.strip()
            if t:
                results.append({'title': t, 'source': '百度热搜', 'summary': ''})
        return results
    except Exception as e:
        logging.warning(f"[新闻] 百度热搜抓取失败: {e}")
        return []


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
                reds = ' '.join(f"{r:02d}" for r in rec['reds'])
                blue = int(rec.get('blue', 0))
                display = f"{reds} + {blue:02d}"
            elif 'front' in rec:
                front = ' '.join(f"{f:02d}" for f in rec['front'])
                back = ' '.join(f"{b:02d}" for b in rec['back'])
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

    # 新闻部分（邪修版：天之道框架 + 价格传导分析）
    news_lines = [f"## 一、每日资讯（{today_display}）\n"]

    # 天之道分析框架（固定模板，含传导链+人脉掮客角度）
    news_lines.append("### 🌐 市场缺口扫描（天之道）\n")
    news_lines.append("- **供需缺口**：铜/铝/锂价格信号 → 下游传导路径\n")
    news_lines.append("  > 📊 传导信号：铜涨→硫酸→磷肥→粮食（未定价环节：磷肥/粮食）\n")
    news_lines.append("  > 💰 落地动作：关注磷肥股/粮食期货/供应链中间人\n")
    news_lines.append("- **价值缺口**：AI算力需求 → 芯片/散热/电源供应链\n")
    news_lines.append("  > 📊 传导信号：英伟达H200→散热需求→VC均热板（未定价：散热模组）\n")
    news_lines.append("  > 💰 落地动作：关注散热/电源供应商/算力租赁\n")
    news_lines.append("- **政策缺口**：国内政策 → 受益标的/进出口套利\n")
    news_lines.append("  > 📊 传导信号：出口退税→跨境结算→汇率对冲（未定价：跨境结算）\n")
    news_lines.append("  > 💰 落地动作：政策解读/合规套利/跨境结算\n\n")

    # 人脉掮客（台湾角色）
    news_lines.append("### 🌉 人脉掮客机会（台湾视角）\n")
    news_lines.append("- **中间人角色**：一半人知道的传导链，你在中间撮合谁和谁？\n")
    news_lines.append("  > 例：铜涨价→台湾冶炼厂→大陆PCB厂，你撮合长单锁定价格\n")
    news_lines.append("- **信息差套利**：台湾早大陆3-6个月知道的电子代工转单信号\n")
    news_lines.append("  > 例：苹果供应链转单→提前卡位替代材料（铝/镁合金）\n")
    news_lines.append("- **合规套利**：利用两岸政策时间差，做合规通道业务\n")
    news_lines.append("  > 例：大陆限电→台湾产能补位→你做合规转单通道\n\n")

    # 百度热搜（真实标题）
    hot_items = fetch_baidu_hot_curl(20)
    if hot_items:
        news_lines.append("### 🔥 热搜/时事\n")
        for item in hot_items[:10]:
            news_lines.append(f"- **{item['title']}**  [百度热搜]\n")
        news_lines.append("\n> 以上内容由百度热搜生成，AI分析模块维护中。\n\n")
    else:
        news_lines.append("- **热搜抓取失败，下次重试**\n\n")

    news = ''.join(news_lines)

    # 彩票部分
    lottery = format_lottery_section()

    content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news}{lottery}"

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
