#!/usr/bin/env python3
"""生成完整日报 - 含新闻(API) + 今日推荐 + 昨日回测"""
import os
import sys
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import json
import requests
import random

# 添加项目根目录到path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

# 确保output目录存在
output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(output_dir, exist_ok=True)

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

def _search_news(keyword, count=3):
    """用搜索引擎抓取真实新闻"""
    try:
        url = "https://news.baidu.com/ns"
        params = {
            "word": keyword,
            "tn": "news",
            "from": "news",
            "cl": "2",
            "rn": str(count),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for item in soup.select('div.result')[:count]:
            title_tag = item.select_one('h3 a')
            source_tag = item.select_one('p.c-author') or item.select_one('span.c-color-gray')
            summary_tag = item.select_one('div.c-summary') or item.select_one('div.c-abstract')
            
            title = title_tag.get_text(strip=True) if title_tag else ""
            source = source_tag.get_text(strip=True) if source_tag else ""
            summary = summary_tag.get_text(strip=True) if summary_tag else ""
            
            if title:
                results.append({
                    'title': title,
                    'source': source,
                    'summary': summary.replace('\n', ' ').strip()
                })
        return results
    except Exception as e:
        logging.warning(f"[新闻] 搜索'{keyword}'失败: {e}")
        return []


def _search_news_multi(keyword, count=5):
    """多源搜索新闻（百度+360），取最好的结果"""
    results = _search_news(keyword, count)
    if len(results) < 2:
        # 补充：用简单API
        try:
            url = f"https://www.so.com/s"
            params = {"q": keyword, "tn": "news", "count": str(count)}
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                for item in soup.select('div.res-title')[:count]:
                    a = item.select_one('a')
                    if a:
                        title = a.get_text(strip=True)
                        if title and not any(r['title'] == title for r in results):
                            results.append({'title': title, 'source': '', 'summary': ''})
        except:
            pass
    return results[:count]


def generate_news_section():
    """基于真实搜索生成新闻日报（非AI编造）"""
    logging.info("[新闻] 开始抓取真实新闻...")
    
    sections = []
    
    # 1. AI/科技资讯
    sections.append("## 一、每日资讯\n")
    sections.append("### 🤖 AI/科技\n")
    ai_news = _search_news_multi("人工智能 AI 科技 2026", 3)
    if ai_news:
        for n in ai_news:
            sections.append(f"- **{n['title']}**")
            if n['summary']:
                sections.append(f"  > {n['summary'][:100]}")
    else:
        sections.append("- （今日暂未抓取到AI/科技新闻）")
    
    # 2. 商业/金融
    sections.append("\n### 💰 商业/金融\n")
    biz_news = _search_news_multi("商业 金融 投资 创业 2026", 3)
    if biz_news:
        for n in biz_news:
            sections.append(f"- **{n['title']}**")
            if n['summary']:
                sections.append(f"  > {n['summary'][:100]}")
    else:
        sections.append("- （今日暂未抓取到商业/金融新闻）")
    
    # 3. 热搜/时事
    sections.append("\n### 🔥 热搜/时事\n")
    hot_news = _search_news_multi("热搜 今日 要闻", 3)
    if hot_news:
        for n in hot_news:
            sections.append(f"- **{n['title']}**")
    else:
        sections.append("- （今日暂未抓取到热搜新闻）")
    
    # 4. 市场缺口扫描
    sections.append("\n## 二、市场缺口扫描\n")
    sections.append("### 固定领域缺口\n")
    for domain in ["算力芯片", "AI应用", "跨境电商"]:
        domain_news = _search_news_multi(f"{domain} 缺口 机会 2026", 2)
        if domain_news:
            n = domain_news[0]
            sections.append(f"- **{domain}**：{n['title']}")
        else:
            sections.append(f"- **{domain}**：暂无明显缺口信号")
    
    sections.append("\n### 动态缺口\n")
    dynamic_news = _search_news_multi("新兴市场 供需错配 投资机会", 3)
    for n in dynamic_news:
        sections.append(f"- {n['title']}")
    
    # 5. 逆潮观察
    sections.append("\n## 三、逆潮观察\n")
    contra_news = _search_news_multi("行业下滑 裁员 逆势", 3)
    for n in contra_news:
        sections.append(f"- {n['title']}")
    
    # 6. 用混元API做深度分析（基于真实新闻，非凭空编造）
    news_digest = "\n".join(sections)
    analysis_prompt = f"""基于以下今日真实新闻摘要，请补充深度分析：

{news_digest}

请补充：
1. 新闻推演：选2条最重要的新闻，做5层传导分析+天之道（损有余补不足）解读
2. 创业机会：基于上述缺口，推荐3个创业方向（含成本/风险/回报/退出路径）

直接输出markdown，从"## 四、深度分析"开始。"""
    
    api_key = "[HUNYUAN_API_KEY]"
    url = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "hunyuan-turbos-latest",
        "messages": [{"role": "user", "content": analysis_prompt}],
        "max_tokens": 3000,
        "temperature": 0.7,
    }
    
    try:
        logging.info("[新闻] 基于真实新闻调用混元做深度分析...")
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        if resp.status_code == 200:
            result = resp.json()
            analysis = result['choices'][0]['message']['content']
            logging.info(f"[新闻] ✅ 深度分析生成成功: {len(analysis)}字符")
            sections.append("\n" + analysis)
        else:
            logging.warning(f"[新闻] 混元API失败: {resp.status_code}")
            sections.append("\n## 四、深度分析\n（今日AI分析生成失败）\n")
    except Exception as e:
        logging.warning(f"[新闻] 混元API超时: {e}")
        sections.append("\n## 四、深度分析\n（今日AI分析生成失败）\n")
    
    content = "\n".join(sections)
    logging.info(f"[新闻] ✅ 日报新闻部分完成: {len(content)}字符（基于真实搜索+AI分析）")
    return content

def generate_lottery_section():
    """生成彩票部分：今日推荐 + 昨日回测 + 虚拟下注记录"""
    try:
        import lottery_analyzer as la
        import games.ssq
        import games.dlt
        import games.qxc
    except Exception as e:
        return f"\n---\n## 🎰 彩票推荐生成失败: {e}\n---\n"

    # 🔴 闭环1: 外层变量收集推荐结果（供虚拟下注+推荐记录使用）
    ssq_recs = None
    dlt_recs = None
    qxc_recs = None

    # 🔴 v3.0: 先跑Orchestrator（大脑），产出context供推荐使用
    try:
        from algo_orchestrator import AlgoOrchestrator
        orch = AlgoOrchestrator()
        context = orch.daily_run()
        print(f"[日报] ✅ Orchestrator运行完成: 模式={context.get('mode')}, 熵比={context.get('entropy_ratio', 0):.4f}")
    except Exception as e:
        print(f"[日报] ⚠️ Orchestrator运行失败(不影响推荐): {e}")

    section = "\n---\n\n## 🎰 彩票号码推荐 — 刘海蟾点金（仅供娱乐参考）\n\n"
    section += "> ⚠️ 彩票本质是随机事件，以下由刘海蟾点金算法基于历史数据规律推算，不构成任何投注建议。理性购彩，量力而行。\n\n"
    
    yesterday_weekday = yesterday.weekday()  # 0=周一 1=周二...
    today_weekday = today.weekday()
    
    # 双色球
    try:
        ssq_data = games.ssq.fetch_ssq_history(15)
        section += "### 🔴 双色球\n\n"
        section += "| 期号 | 红球 | 蓝球 |\n|------|------|------|\n"
        for d in ssq_data[:3]:
            reds = d.get('reds', [])
            blue = d.get('blue', 0)
            section += f"| {d.get('period')} | {' '.join(map(str, reds))} | {blue:02d} |\n"
        
        # 今日推荐（所有彩种每天都生成）
        try:
            # 使用WeightedAnalyzer生成推荐
            analysis = games.ssq.analyze_ssq(ssq_data)
            recs = games.ssq.generate_recs_ssq(analysis)
            ssq_recs = recs  # 🔴 闭环1: 收集推荐供虚拟下注使用
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                rec_reds = rec.get('reds', [])
                rec_blue = rec.get('blue', 0)
                section += f"  - {rec.get('strategy', '未知')}: 红={rec_reds} 蓝={rec_blue:02d}\n"
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
                    predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
                    with open(predictions_path, 'r') as f:
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
        dlt_data = games.dlt.fetch_dlt_history(15)
        section += "### 🟡 大乐透\n\n"
        section += "| 期号 | 前区 | 后区 |\n|------|------|------|\n"
        for d in dlt_data[:3]:
            front = d.get('front', [])
            back = d.get('back', [])
            section += f"| {d.get('period')} | {' '.join(map(str, front))} | {' '.join(map(str, back))} |\n"
        
        # 今日推荐（所有彩种每天都生成）
        try:
            # 使用WeightedAnalyzer生成推荐
            analysis = games.dlt.analyze_dlt(dlt_data)
            recs = games.dlt.generate_recs_dlt(analysis)
            dlt_recs = recs  # 🔴 闭环1: 收集推荐供虚拟下注使用
            section += f"\n**今日推荐({len(recs)}注)**:\n"
            for rec in recs:
                rec_front = rec.get('front', [])
                rec_back = rec.get('back', [])
                section += f"  - {rec.get('strategy', '未知')}: 前={rec_front} 后={rec_back}\n"
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
                    predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
                    with open(predictions_path, 'r') as f:
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
        qxc_data = games.qxc.fetch_qxc_history(15)
        section += "### 🟢 七星彩\n\n"
        section += "| 期号 | 号码 |\n|------|------|\n"
        for d in qxc_data[:3]:
            digits = d.get('digits', d.get('numbers', []))
            section += f"| {d.get('period')} | {' '.join(map(str, digits))} |\n"
        
        # 今日推荐（所有彩种每天都生成）
        try:
            # 使用WeightedAnalyzer生成推荐
            analysis = games.qxc.analyze_qxc(qxc_data)
            recs = games.qxc.generate_recs_qxc(analysis)
            qxc_recs = recs  # 🔴 闭环1: 收集推荐供虚拟下注使用
            # 去重：如果推荐和最新开奖高度相似，微调
            if qxc_data:
                latest = qxc_data[0]
                latest_digits = latest.get('digits', latest.get('numbers', []))
                for rec in recs:
                    rec_digits = rec.get('digits', [])
                    if rec_digits and latest_digits:
                        same_count = sum(1 for a, b in zip(rec_digits, latest_digits) if a == b)
                        if same_count >= 6:  # 6位以上相同，微调最后一位
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
        if yesterday_weekday in [1, 4, 6]:  # 昨天是周二/周五/周日
            section += f"\n**昨日({yesterday.strftime('%Y-%m-%d')})开奖回测**: 七星彩\n"
            if qxc_data:
                latest = qxc_data[0]
                section += f"第{latest.get('period')}期: 号码={latest.get('digits', latest.get('numbers'))}\n"
                
                # 读取昨日推荐并对比
                try:
                    predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
                    with open(predictions_path, 'r') as f:
                        predictions = json.load(f)
                    yesterday_str = yesterday.strftime('%Y-%m-%d')
                    for item in predictions:
                        if item.get('date') == yesterday_str:
                            qxc_recs = item.get('qxc_recs', [])
                            if qxc_recs:
                                section += f"\n刘海蟾推荐({len(qxc_recs)}注):\n"
                                for rec in qxc_recs:
                                    rec_digits = rec.get('digits', rec.get('numbers', []))
                                    hit_count = sum(1 for i in range(min(len(rec_digits), len(latest_digits))) if i < len(rec_digits) and i < len(latest_digits) and rec_digits[i] == latest_digits[i])
                                    section += f"  - {rec.get('strategy', '未知')}: 号码={rec_digits} "
                                    if hit_count > 0:
                                        section += f"✅ 中{hit_count}位"
                                    section += "\n"
                                section += f"\n💰 回测完成\n"
                            break
                except Exception as e:
                    section += f"\n(未找到昨日推荐记录: {e})\n"
        section += "\n"
    except Exception as e:
        section += f"[七星彩] 错误: {e}\n\n"
    
    # 🔴 闭环1: 虚拟下注 — 推荐写入 algo_bets 表（供 settle 结算使用）
    try:
        from algo_module import AlgoDB, ROITracker
        tracker = ROITracker(AlgoDB())
        kelly_map = {'ssq': 0, 'dlt': 0, 'qxc': 0}
        if ssq_recs:
            tracker.record_bets(today_str, 'ssq', ssq_recs, kelly_map)
            logging.info(f"[彩票] ✅ SSQ虚拟下注记录: {len(ssq_recs)}注")
        if dlt_recs:
            tracker.record_bets(today_str, 'dlt', dlt_recs, kelly_map)
            logging.info(f"[彩票] ✅ DLT虚拟下注记录: {len(dlt_recs)}注")
        if qxc_recs:
            tracker.record_bets(today_str, 'qxc', qxc_recs, kelly_map)
            logging.info(f"[彩票] ✅ QXC虚拟下注记录: {len(qxc_recs)}注")
    except Exception as e:
        logging.warning(f"[彩票] 虚拟下注记录失败: {e}")
    
    # 🔴 闭环4: 保存今日推荐到 lottery-predictions.json（供明日回测使用）
    try:
        predictions_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lottery-predictions.json')
        predictions = []
        if os.path.exists(predictions_path):
            with open(predictions_path, 'r', encoding='utf-8') as f:
                predictions = json.load(f)
        # 去重：同日覆盖
        predictions = [p for p in predictions if p.get('date') != today_str]
        today_prediction = {
            'date': today_str,
            'ssq_recs': ssq_recs,
            'dlt_recs': dlt_recs,
            'qxc_recs': qxc_recs,
        }
        predictions.append(today_prediction)
        with open(predictions_path, 'w', encoding='utf-8') as f:
            json.dump(predictions, f, ensure_ascii=False, indent=2)
        logging.info(f"[彩票] ✅ 今日推荐已保存(供明日回测)")
    except Exception as e:
        logging.warning(f"[彩票] 保存推荐记录失败: {e}")
    
    return section

if __name__ == '__main__':
    logging.info(f"========== 生成完整日报 {today_str} ==========")
    
    # 1. 生成新闻分析部分（基于真实搜索，已内置fallback）
    news_content = generate_news_section()
    
    # 2. 生成彩票部分
    lottery_content = generate_lottery_section()
    
    # 3. 拼接完整日报
    full_content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}"
    
    # 4. 写文件
    output_path = os.path.join(output_dir, f"{today_str}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    logging.info(f"✅ 已写入: {output_path} ({len(full_content)}字符)")
    
    # 5. 发邮件
    subject = '阿算帮刘老板发财日报 | ' + today_str
    send_email(subject, full_content)
    logging.info(f"========== 完成 {today_str} ==========")
