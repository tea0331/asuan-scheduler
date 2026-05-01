#!/usr/bin/env python3
"""一键发送彩票推荐邮件 — 从本地状态文件读取推荐结果，发送到老板邮箱"""
import sys, json, os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

def main():
    # SMTP配置（从环境变量读取，GitHub Actions会自动注入secrets）
    SMTP_USER = os.environ.get('SMTP_USER', '')
    SMTP_PASS = os.environ.get('SMTP_PASSWORD', '')
    SMTP_TO = os.environ.get('SMTP_TO', 'tea0331@163.com')

    if not SMTP_USER or not SMTP_PASS:
        print("❌ 缺少SMTP凭据 (SMTP_USER, SMTP_PASSWORD)")
        return False

    today_str = datetime.now(CST).strftime('%Y-%m-%d')

    # 读取推荐结果
    predictions_path = os.path.join(os.path.dirname(__file__), 'lottery-predictions.json')
    if not os.path.exists(predictions_path):
        print("❌ 无推荐文件 lottery-predictions.json")
        return False

    with open(predictions_path) as f:
        preds = json.load(f)

    latest = preds[-1] if preds else None
    if not latest:
        print("❌ 推荐文件为空")
        return False

    # 读取权重
    config_path = os.path.join(os.path.dirname(__file__), 'weight-config.json')
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    # 读取回测
    backtest_path = os.path.join(os.path.dirname(__file__), 'lottery-backtest.json')
    backtest_log = []
    if os.path.exists(backtest_path):
        with open(backtest_path) as f:
            backtest_log = json.load(f)

    # 读取告警
    alerts_path = os.path.join(os.path.dirname(__file__), 'lottery-alerts.json')
    alerts_data = {}
    if os.path.exists(alerts_path):
        with open(alerts_path) as f:
            alerts_data = json.load(f)

    # ===== 构建邮件内容 =====
    algo_ver = config.get('algo_version', 'v7.4')
    subject = f"🎰 刘海蟾点金 | {today_str} | {algo_ver} 推荐邮件"

    # 推荐号码
    recs_html = ''
    game_names = {'ssq': '双色球', 'dlt': '大乐透', 'qxc': '七星彩'}
    for game_key, game_name in game_names.items():
        game_recs = latest.get(f'{game_key}_recs', [])
        if not game_recs:
            continue
        recs_html += f'<h2>{game_name}</h2><table><tr><th>策略</th><th>推荐号码</th></tr>'
        for r in game_recs:
            strategy = r.get('strategy', '?')
            if game_key == 'ssq':
                nums = ' '.join(f'{n:02d}' for n in r.get('reds', [])) + f' | 蓝球 {r.get("blue", 0):02d}'
            elif game_key == 'dlt':
                front = ' '.join(f'{n:02d}' for n in r.get('front', []))
                back = ' '.join(f'{n:02d}' for n in r.get('back', []))
                nums = f'{front} | 后区 {back}'
            else:
                nums = ' '.join(str(n) for n in r.get('digits', []))
            recs_html += f'<tr><td><strong>{strategy}</strong></td><td style="font-size:16px;letter-spacing:2px;">{nums}</td></tr>'
        recs_html += '</table>'

    # GEPA进化信息
    evo_log = config.get('evolution_log', [])
    latest_evo = evo_log[-1] if evo_log else None
    evo_html = ''
    if latest_evo:
        evo_html = f'''<h2>📊 GEPA进化状态</h2>
<p><strong>版本</strong>: {algo_ver} | <strong>触发</strong>: {latest_evo.get('trigger', '?')} | <strong>样本</strong>: {latest_evo.get('sample_size', 0)}</p>'''
        if latest_evo.get('changes'):
            evo_html += '<ul>'
            for c in latest_evo['changes']:
                evo_html += f'<li>{c}</li>'
            evo_html += '</ul>'

    # 权重表
    weights_html = f'''<h3>当前权重</h3>
<table><tr><th>参数</th><th>值</th></tr>
<tr><td>freq(频率)</td><td>{config.get('freq', 0.33)}</td></tr>
<tr><td>miss(遗漏)</td><td>{config.get('miss', 0.22)}</td></tr>
<tr><td>trend(趋势)</td><td>{config.get('trend', 0.25)}</td></tr>
<tr><td>zone(分区)</td><td>{config.get('zone', 0.20)}</td></tr>
<tr><td>gamma(衰减)</td><td>{config.get('gamma', 0.88)}</td></tr>
</table>'''

    # 回测摘要
    bt_html = ''
    if backtest_log:
        latest_bt = backtest_log[-1]
        bt_html = '<h2>📋 最近回测</h2>'
        for game_key, game_name in game_names.items():
            game_bt = latest_bt.get(game_key, {})
            if not game_bt:
                continue
            best = game_bt.get('best_strategy', '?')
            best_total = game_bt.get('best_total', 0)
            prize = game_bt.get('total_prize', 0)
            cost = game_bt.get('total_cost', 0)
            baseline = game_bt.get('baseline', {})
            baseline_avg = baseline.get('avg', '?') if baseline else '?'
            bt_html += f'<p>{game_name} 第{game_bt.get("period", "?")}期: 最佳={best}({best_total}个) 奖金{prize}元/成本{cost}元 基线{baseline_avg}</p>'

    # 告警
    alert_html = ''
    if alerts_data and alerts_data.get('count', 0) > 0:
        alert_html = '<h2>🚨 重大事件告警</h2>'
        for a in alerts_data.get('alerts', []):
            level = a.get('level', '⚠️')
            title = a.get('title', '')
            detail = a.get('detail', '')
            action = a.get('action', '')
            alert_html += f'<p>{level} <strong>{title}</strong>: {detail}'
            if action:
                alert_html += f' <em>→ {action}</em>'
            alert_html += '</p>'

    # 组装完整邮件
    body = f"""<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 14px; line-height: 1.7; color: #333; max-width: 800px; margin: 0 auto; padding: 10px; }}
h1 {{ font-size: 20px; border-bottom: 2px solid #e74c3c; padding-bottom: 6px; }}
h2 {{ font-size: 17px; color: #2c3e50; margin-top: 20px; border-left: 4px solid #3498db; padding-left: 10px; }}
h3 {{ font-size: 15px; color: #555; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: center; }}
th {{ background: #f5f5f5; }}
blockquote {{ border-left: 3px solid #e74c3c; padding-left: 10px; color: #666; margin: 10px 0; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 20px 0; }}
</style>
</head><body>
<h1>🎰 刘海蟾点金 — {today_str}</h1>

{evo_html}
{weights_html}
{alert_html}
<hr>
{recs_html}
{bt_html}

<hr>
<p style="color:#999;font-size:12px;">— 阿算 | 刘海蟾点金 {algo_ver} | {datetime.now(CST).strftime('%H:%M')}</p>
<p style="color:#999;font-size:11px;">⚠️ 彩票本质随机，分析仅供娱乐参考。</p>
</body></html>"""

    # 发送
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = SMTP_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html', 'utf-8'))

        server = smtplib.SMTP_SSL('smtp.163.com', 465, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SMTP_TO, msg.as_string())
        server.quit()
        print(f"✅ 彩票推荐邮件已发送至 {SMTP_TO}")
        print(f"   主题: {subject}")
        print(f"   内容: {len(body)}字符")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
