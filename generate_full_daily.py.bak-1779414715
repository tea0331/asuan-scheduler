#!/usr/bin/env python3
"""生成完整日报 - 含新闻(API) + 今日推荐 + 昨日回测"""
import os
import sys
import logging
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import json
import requests

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')
yesterday = (datetime.now(CST) - timedelta(days=1))
today = datetime.now(CST)

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

def generate_news_section():
    """调用混元API生成新闻分析部分"""
    api_key = "sk-TjZgBJKZJA1FjrkMHIotwyBafg8gXnRdYBLDvyHNkGSkQAcq"
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    
    prompt = f"""生成今日({today_str})的AI/科技/金融/创业新闻分析日报，必须包含：

1. 时事新闻(3条)
2. 科技/AI资讯(3条)  
3. 商业/创业资讯(3条)
4. 热搜话题(3条)
5. 市场缺口扫描(3个固定领域+3个动态缺口)
6. 新闻推演(2条新闻的5层传导+天之道分析)
7. 逆潮观察(3条)
8. 创业项目(3个，含成本/风险/回报/退出)

格式参考之前的"阿算帮刘老板发财日报"，直接输出markdown格式内容（从"## 一、每日资讯"开始）。"""
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
        "temperature": 0.7,
        "timeout": 30
    }
    
    try:
        logging.info("[API] 调用混元生成新闻分析...")
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            result = resp.json()
            content = result['choices'][0]['message']['content']
            logging.info(f"[API] ✅ 生成成功: {len(content)}字符")
            return content
        else:
            logging.error(f"[API] 失败: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"[API] 异常: {e}")
        return None

def generate_lottery_section():
    """生成彩票部分：今日推荐 + 昨日回测"""
    try:
        import lottery_analyzer as la
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐生成失败: {e}\n---\n"
    
    section = "\n---\n\n## 🎰 彩票号码推荐 — 刘海蟾点金（仅供娱乐参考）\n\n"
    section += "> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n\n"
    
    yesterday_weekday = yesterday.weekday()  # 0=周一 1=周二...
    today_weekday = today.weekday()
    
    # 双色球
    try:
        ssq_data = la.fetch_ssq_history(15)
        section += "### 🔴 双色球\n\n"
        section += "| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
        for d in ssq_data[:3]:
            reds = d.get('reds', [])
            blue = d.get('blue', 0)
            section += f"| {d.get('period')} | {' '.join(map(str, reds))} | {blue:02d} |\n"
        
        # 今日推荐（所有彩种每天都生成）
        try:
            recs = la.analyze_ssq(ssq_data)  # 直接调用独立函数
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                section += f"  - {rec.get('strategy', '未知')}: 红={rec.get('reds', [])} 蓝={rec.get('blue', 0):02d}\n"
        except Exception as e:
            section += f"\n(推荐生成失败: {e})\n"
        
        # 回测：只有当昨天开双色球时才显示
        if yesterday_weekday in [1, 3, 6]:  # 昨天是周二/周四/周日
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 双色球\n"
            if ssq_data:
                latest = ssq_data[0]
                section += f"第{latest.get('period')}期: 红={latest.get('reds')} 蓝={latest.get('blue')}\n"
                
                # 读取昨日推荐并对比
                try:
                    with open('/root/asuan-scheduler/lottery-predictions.json', 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            ssq_recs = item.get('ssq_recs', [])
                            if ssq_recs:
                                section += f"\n刘海蟾推荐({len(ssq_recs)}注):\n"
                                for rec in ssq_recs:
                                    rec_reds = rec.get('reds', [])
                                    rec_blue = rec.get('blue', 0)
                                    hit_reds = set(rec_reds) & set(latest.get('reds', []))
                                    hit_blue = rec_blue == latest.get('blue', 0)
                                    section += f"  - {rec.get('strategy', '未知')}: 红={rec_reds} 蓝={rec_blue:02d} "
                                    if hit_reds:
                                        section += f"✅ 中{list(hit_reds)}"
                                    if hit_blue:
                                        section += f" ✅ 中蓝"
                                    section += "\n"
                                section += f"\n💰 回测完成\n"
                            break
                except Exception as e:
                    section += f"\n(未找到昨日推荐记录: {e})\n"
        section += "\n"
    except Exception as e:
        section += f"[双色球] 错误: {e}\n\n"
    
    # 大乐透
    try:
        dlt_data = la.fetch_dlt_history(15)
        section += "### 🟡 大乐透\n\n"
        section += "| 期号 | 前区 | 后区 |\n|------|------|------|\n"
        for d in dlt_data[:3]:
            front = d.get('front', [])
            back = d.get('back', [])
            section += f"| {d.get('period')} | {' '.join(map(str, front))} | {' '.join(map(str, back))} |\n"
        
        # 今日推荐（所有彩种每天都生成）
        try:
            from collections import Counter
            front_counter = Counter()
            back_counter = Counter()
            for d in dlt_data:
                front_counter.update(d['front'])
                back_counter.update(d['back'])
            top7 = front_counter.most_common(7)
            core_by_freq = [n for n, _ in top7][:5]
            core = sorted(core_by_freq)
            core_back = sorted([back_counter.most_common(1)[0][0], back_counter.most_common(2)[1][0]])
            ext1_keep = sorted(core_by_freq[:3])
            ext1_new = sorted([n for n, _ in top7[5:10] if n not in ext1_keep][:2])
            ext1_back = sorted([back_counter.most_common(1)[0][0], back_counter.most_common(3)[1][0]]) if len(back_counter.most_common(3)) > 1 else core_back
            ext2_keep = sorted(core_by_freq[:2])
            mid_freq_front = sorted([n for n in range(1, 36) if 2 <= front_counter.get(n, 0) <= 3 and n not in core_by_freq][:3])
            if len(mid_freq_front) < 3:
                mid_freq_front = sorted([n for n in range(1, 36) if front_counter.get(n, 0) <= 1 and n not in core_by_freq][:3])
            ext2_front = sorted(ext2_keep + mid_freq_front[:3])
            ext2_back_candidates = sorted([n for n in range(1, 13) if 1 <= back_counter.get(n, 0) <= 2 and n not in core_back][:2])
            if len(ext2_back_candidates) < 2:
                ext2_back_candidates = sorted([n for n in range(1, 13) if back_counter.get(n, 0) <= 1 and n not in core_back][:2])
            if len(ext2_back_candidates) < 2:
                ext2_back_candidates = core_back
            miss_front = sorted([n for n in range(1, 36) if n not in front_counter or front_counter.get(n, 0) == 0][:5])
            miss_back = sorted([n for n in range(1, 13) if n not in back_counter or back_counter.get(n, 0) == 0][:2])
            if len(miss_front) < 5:
                miss_front = sorted([n for n in range(1, 36) if front_counter.get(n, 0) <= 1 and n not in core_by_freq][:5])
            if len(miss_back) < 2:
                miss_back = sorted([n for n in range(1, 13) if back_counter.get(n, 0) <= 1 and n not in core_back][:2])
            if len(miss_back) < 2:
                miss_back = [1, 2]
            recs = [
                {'front': core, 'back': core_back, 'strategy': '核心注(频率)'},
                {'front': sorted(ext1_keep + ext1_new), 'back': ext1_back, 'strategy': '扩展1(频率)'},
                {'front': ext2_front, 'back': ext2_back_candidates, 'strategy': '扩展2(频率)'},
                {'front': miss_front, 'back': miss_back, 'strategy': '冷号注(遗漏)'},
            ]
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                section += f"  - {rec.get('strategy', '未知')}: 前={rec.get('front', [])} 后={rec.get('back', [])}\n"
        except Exception as e:
            section += f"\n(推荐生成失败: {e})\n"
        
        # 回测：只有当昨天开大乐透时才显示
        if yesterday_weekday in [0, 2, 5]:  # 昨天是周一/周三/周六
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 大乐透\n"
            if dlt_data:
                latest = dlt_data[0]
                section += f"第{latest.get('period')}期: 前={latest.get('front')} 后={latest.get('back')}\n"
                
                # 读取昨日推荐并对比
                try:
                    with open('/root/asuan-scheduler/lottery-predictions.json', 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            dlt_recs = item.get('dlt_recs', [])
                            if dlt_recs:
                                section += f"\n刘海蟾推荐({len(dlt_recs)}注):\n"
                                for rec in dlt_recs:
                                    rec_front = rec.get('front', [])
                                    rec_back = rec.get('back', [])
                                    hit_front = set(rec_front) & set(latest.get('front', []))
                                    hit_back = set(rec_back) & set(latest.get('back', []))
                                    section += f"  - {rec.get('strategy', '未知')}: 前={rec_front} 后={rec_back} "
                                    if hit_front:
                                        section += f"✅ 中{list(hit_front)}"
                                    if hit_back:
                                        section += f" ✅ 中{list(hit_back)}"
                                    section += "\n"
                                section += f"\n💰 回测完成\n"
                            break
                except Exception as e:
                    section += f"\n(未找到昨日推荐记录: {e})\n"
        section += "\n"
    except Exception as e:
        section += f"[大乐透] 错误: {e}\n\n"
    
    # 七星彩
    try:
        qxc_data = la.fetch_qxc_history(15)
        section += "### 🟢 七星彩\n\n"
        section += "| 期号 | 号码 |\n|------|------|\n"
        for d in qxc_data[:3]:
            digits = d.get('digits', d.get('numbers', []))
            section += f"| {d.get('period')} | {' '.join(map(str, digits))} |\n"
        
        # 今日推荐（所有彩种每天都生成）
        try:
            wa = la.WeightedAnalyzer(qxc_data)
            recs = wa.analyze_qxc(qxc_data)  # 直接返回推荐列表
            # 去重：如果推荐和最新开奖高度相似，微调
            if qxc_data:
                latest = qxc_data[0]
                latest_digits = latest.get('digits', latest.get('numbers', []))
                for rec in recs:
                    rec_digits = rec.get('digits', [])
                    if rec_digits and latest_digits:
                        same_count = sum(1 for a, b in zip(rec_digits, latest_digits) if a == b)
                        if same_count >= 6:  # 6位以上相同，微调最后一位
                            import random
                            # 随机改1-2位（不改变策略本质）
                            for _ in range(min(2, len(rec_digits)-1)):
                                pos = random.randint(0, 5)  # 前6位
                                old_val = rec_digits[pos]
                                new_val = (old_val + random.randint(1, 5)) % 10
                                rec_digits[pos] = new_val
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                section += f"  - {rec.get('strategy', '未知')}: 号码={rec.get('digits', [])}\n"
        except Exception as e:
            section += f"\n(推荐生成失败: {e})\n"
        
        # 回测：只有当昨天开七星彩时才显示
        if yesterday_weekday in [1, 4]:  # 昨天是周二/周五
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 七星彩\n"
            if qxc_data:
                latest = qxc_data[0]
                section += f"第{latest.get('period')}期: 号码={latest.get('digits', latest.get('numbers'))}\n"
                
                # 读取昨日推荐并对比
                try:
                    with open('/root/asuan-scheduler/lottery-predictions.json', 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            qxc_recs = item.get('qxc_recs', [])
                            if qxc_recs:
                                section += f"\n刘海蟾推荐({len(qxc_recs)}注):\n"
                                for rec in qxc_recs:
                                    rec_digits = rec.get('digits', rec.get('numbers', []))
                                    hit_digits = set(rec_digits) & set(latest.get('digits', latest.get('numbers', [])))
                                    section += f"  - {rec.get('strategy', '未知')}: 号码={rec_digits} "
                                    if hit_digits:
                                        section += f"✅ 中{list(hit_digits)}"
                                    section += "\n"
                                section += f"\n💰 回测完成\n"
                            break
                except Exception as e:
                    section += f"\n(未找到昨日推荐记录: {e})\n"
        section += "\n"
    except Exception as e:
        section += f"[七星彩] 错误: {e}\n\n"
    
    return section

if __name__ == '__main__':
    logging.info(f"========== 生成完整日报 {today_str} ==========")
    
    # 1. 生成新闻分析部分
    news_content = generate_news_section()
    if not news_content:
        # Fallback: 用昨天的
        logging.warning("[新闻] API失败，尝试用昨日内容")
        try:
            with open('/root/asuan-scheduler/output/2026-05-20.md', 'r', encoding='utf-8') as f:
                old_content = f.read()
            # 提取新闻部分（到"---\n\n## 🎰"之前）
            if '---\n\n## 🎰' in old_content:
                news_content = old_content.split('---\n\n## 🎰')[0]
            else:
                news_content = old_content[:2000]  # 前2000字符
        except Exception as e:
            logging.error(f"[新闻] Fallback也失败: {e}")
            news_content = "## 每日资讯生成失败，请稍后查看\n"
    
    # 2. 生成彩票部分
    lottery_content = generate_lottery_section()
    
    # 3. 拼接完整日报
    full_content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}"
    
    # 4. 写文件
    output_path = f'/root/asuan-scheduler/output/{today_str}.md'
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    logging.info(f"✅ 已写入: {output_path} ({len(full_content)}字符)")
    
    # 5. 发邮件
    subject = '阿算帮刘老板发财日报 | ' + today_str
    send_email(subject, full_content)
    logging.info(f"========== 完成 {today_str} ==========")
