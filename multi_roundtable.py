#!/usr/bin/env python3
"""
多角色圆桌推演系统 v1.0
全面替代东方朔单向评价 + 马斯克独立推演

工作流:
  1. 读当日日报
  2. 6个固定角色并行独立评价
  3. 随机抽取2个副角色参与
  4. 检测观点冲突 → 多轮辩论
  5. 加权汇总 → 输出共识
  6. 追加到日报文件末尾

调用方式:
  python3 multi_roundtable.py [YYYY-MM-DD]

依赖:
  - roundtable_agents/prompts.py (角色定义)
  - 日报文件: /root/asuan-scheduler/output/YYYY-MM-DD.md
  - jinzhu_analysis.json (可选,供东方朔等角色参考)
"""

import os
import sys
import json
import re
import random
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from roundtable_agents.prompts import AGENT_PROMPTS, SIDE_AGENTS

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime('%Y-%m-%d')

# 路径
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(MODULE_DIR, 'output')
JINZHU_ANALYSIS_PATH = os.path.join(MODULE_DIR, 'jinzhu_analysis.json')

# API 配置
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
if not API_KEY:
    env_path = os.path.join(MODULE_DIR, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('DEEPSEEK_API_KEY='):
                    API_KEY = line.split('=', 1)[1]
                    break

MODEL = "deepseek-v4-flash"


def log(msg):
    print(f"[圆桌] {msg}")


def call_deepseek(system_msg, user_msg, max_tokens=800, temperature=0.7, timeout=60):
    """调用 DeepSeek API"""
    if not API_KEY:
        log("❌ API_KEY 未设置")
        return None
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        else:
            log(f"❌ API返回 {resp.status_code}")
            return None
    except Exception as e:
        log(f"❌ API调用失败: {e}")
        return None


def load_daily_report(date_str):
    """加载当日日报"""
    report_path = os.path.join(OUTPUT_DIR, f'{date_str}.md')
    if not os.path.exists(report_path):
        log(f"❌ 日报不存在: {report_path}")
        return None, None
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return content, report_path


def load_jinzhu_analysis():
    """加载 JinZhu 分析数据"""
    if os.path.exists(JINZHU_ANALYSIS_PATH):
        with open(JINZHU_ANALYSIS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def build_agent_user_msg(daily_content, jinzhu_data, agent_name, agent_config):
    """为每个角色构建个性化输入 - 聚焦新闻内容，不讨论JinZhu/彩票"""
    # 提取新闻部分（从## 一、每日资讯到下一个行首##之前，避免被###误匹配）
    news_section = ""
    m = re.search(r'## 一、每日资讯(.+?)(?=\n## |\Z)', daily_content, re.DOTALL)
    if m:
        news_section = m.group(1).strip()[:2000]

    # 提取逆潮观察
    nichao_section = ""
    m = re.search(r'## 二、逆潮观察(.+?)(?=\n## |\Z)', daily_content, re.DOTALL)
    if m:
        nichao_section = m.group(1).strip()[:1000]

    # 从新闻中提取标题
    news_titles = re.findall(r'\*\*(.+?)\*\*', news_section)[:8]

    # 角色特定的关注点 - 全部聚焦新闻，不涉及彩票
    focus_map = {
        "东方朔": "剥离新闻中的公关话术，提纯事实，追溯利益关系",
        "反共识思考者": "挑战新闻中隐含的产业共识，寻找被忽视的盲区",
        "纲纳·缪达尔": "追踪新闻事件的循环累积因果链，识别正/负反馈环",
        "蓝海赛道设计师": "从新闻中挖掘可落地的商业机会和新赛道",
        "政策专家": "解读政策信号的真实意图，预测传导效应和制度套利空间",
        "老王": "从一线供需水位和情绪风向判断市场实际温度",
        "雷军": "判断新闻事件对普通人和下沉市场的实际影响，趋势拐点分析",
    }
    focus = focus_map.get(agent_name, "全面评价今日新闻")

    user_msg = f"""你是【{agent_name}】({agent_config['title']})，请评价以下日报中的**新闻内容**（不包括彩票分析部分）。

【你的关注点】
{focus}

【日报新闻标题摘要】
日期: {TODAY}
{json.dumps(news_titles, ensure_ascii=False, indent=2)}

【每日资讯详细内容】
{news_section}

【逆潮观察】
{nichao_section}

⚠️ 请只评价上述新闻内容。不要涉及彩票/JinZhu策略分析。

请按你的角色输出评价（包含评分、核心发现、推荐操作）。"""

    return user_msg


def run_single_agent(agent_name, agent_config, daily_content):
    """单个 agent 执行评价，只关注新闻内容"""
    log(f"  开始评价: {agent_name}")
    # 不传 jinzhu_data，让角色只看新闻
    user_msg = build_agent_user_msg(daily_content, None, agent_name, agent_config)
    result = call_deepseek(agent_config['system_prompt'], user_msg)
    if result:
        log(f"  ✅ {agent_name} 评价完成")
        return {"name": agent_name, "emoji": agent_config['emoji'], "title": agent_config['title'],
                "weight": agent_config['weight'], "content": result}
    else:
        log(f"  ❌ {agent_name} 评价失败")
        return None


def extract_score(text):
    """从 agent 输出中提取评分"""
    m = re.search(r'【评分】\s*(\d+(?:\.\d+)?)\s*/?\s*10', text)
    if m:
        return float(m.group(1))
    return None


def detect_conflicts(results):
    """检测观点冲突：评分差距 > 3 分的 pair"""
    conflicts = []
    scored = [(r['name'], extract_score(r['content'])) for r in results if extract_score(r['content']) is not None]
    for i, (name1, score1) in enumerate(scored):
        for name2, score2 in scored[i+1:]:
            if abs(score1 - score2) >= 3:
                conflicts.append({
                    "topic": f"{name1}({score1}) vs {name2}({score2})",
                    "a": name1, "b": name2,
                    "diff": abs(score1 - score2)
                })
    return conflicts


def run_debate(conflict, results_map):
    """两个观点冲突的 agent 进行辩论"""
    agent_a = conflict['a']
    agent_b = conflict['b']
    a_content = results_map[agent_a]['content'][:500]
    b_content = results_map[agent_b]['content'][:500]

    log(f"  辩论: {agent_a} vs {agent_b}")

    # 第一轮：A反驳B
    debate_prompt_a = f"""{agent_b} 的观点如下：
{b_content}

你的观点如下：
{a_content}

你和 {agent_b} 存在明显分歧（差距{conflict['diff']}分）。
请反驳 {agent_b} 的观点，指出其逻辑漏洞。限100字。"""
    r1 = call_deepseek(AGENT_PROMPTS[agent_a]['system_prompt'], debate_prompt_a, max_tokens=300, temperature=0.8)

    # 第二轮：B反驳A
    debate_prompt_b = f"""{agent_a} 的观点如下：
{a_content}

你的观点如下：
{b_content}

你和 {agent_a} 存在明显分歧（差距{conflict['diff']}分）。
{agent_a} 反驳了你，说：{r1[:200] if r1 else '(无回应)'}

请回击。你可以坚持原判或部分让步。限100字。"""
    r2 = call_deepseek(AGENT_PROMPTS[agent_b]['system_prompt'], debate_prompt_b, max_tokens=300, temperature=0.8)

    return {
        "topic": conflict['topic'],
        "a_rebuttal": r1,
        "b_rebuttal": r2,
        "a_final": agent_a,
        "b_final": agent_b
    }


def calculate_consensus(results, debates):
    """加权共识计算"""
    total_weight = 0
    weighted_score = 0
    details = []

    for r in results:
        score = extract_score(r['content'])
        if score is not None:
            weighted_score += score * r['weight']
            total_weight += r['weight']
            details.append(f"{r['emoji']} {r['name']}: {score}/10 (权重{r['weight']})")

    consensus_score = round(weighted_score / total_weight, 1) if total_weight > 0 else 0

    # 分歧分析
    # 用冲突分数作为分歧大小的代理
    max_conflict = max(debates, key=lambda d: d.get('diff', 0)) if debates else None

    return {
        "score": consensus_score,
        "details": details,
        "max_conflict": max_conflict,
        "debate_count": len(debates)
    }


def check_already_appended(report_path):
    """检查日报是否已有今日圆桌推演"""
    if not os.path.exists(report_path):
        return False
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    markers = ['【多角色圆桌推演】', '多角色圆桌推演']
    for m in markers:
        if m in content:
            # 检查是否今日内容（在 marker 附近找日期）
            idx = content.rfind(m)
            context = content[max(0, idx-50):idx+200]
            if TODAY in context:
                return True
    return False


def generate_report_output(results, debates, consensus, side_names):
    """生成完整的日报追加内容"""
    output = ['\n\n---', '## 🔄 多角色圆桌推演', '']

    # 参与角色
    all_names = []
    for r in results:
        all_names.append(r['emoji'] + r['name'] + '(' + r['title'] + ')')
    for sn in side_names:
        all_names.append(SIDE_AGENTS[sn]['emoji'] + sn)
    output.append('**参与角色**: ' + ' | '.join(all_names))
    output.append('')

    # 个人评分
    output.append('### 个人评价')
    for r in results:
        line = '\n**' + r['emoji'] + ' ' + r['name'] + '（' + r['title'] + '）**'
        output.append(line)
        output.append(r['content'])
    output.append('')

    # 圆桌辩论（如果有）
    if debates:
        output.append('### ⚡ 圆桌辩论')
        output.append(f'检测到 {len(debates)} 个重大分歧：')
        for d in debates:
            output.append(f'\n**焦点**: {d["topic"]}')
            if d.get('a_rebuttal'):
                output.append(f'- 🔴 {d["a_final"]} → {d["a_rebuttal"]}')
            if d.get('b_rebuttal'):
                output.append(f'- 🔵 {d["b_final"]} → {d["b_rebuttal"]}')
    output.append('')

    # 加权共识
    output.append('### 📊 加权共识')
    output.append(f'**综合评分**: {consensus["score"]}/10')
    output.append(f'**评价明细**:')
    for d in consensus['details']:
        output.append(f'- {d}')
    if consensus['max_conflict']:
        output.append(f'**最大分歧**: {consensus["max_conflict"]["topic"]}（差距{consensus["max_conflict"]["diff"]}分）')
    output.append(f'**辩论场次**: {consensus["debate_count"]}')
    output.append('')

    # 一句话结论
    output.append('### 🎯 圆桌结论')
    if consensus['score'] >= 7:
        output.append('✅ **共识偏乐观**：多数角色认为今日日报质量可接受，逻辑基本自洽')
    elif consensus['score'] >= 4:
        output.append('⚡ **争议较大**：角色间存在显著分歧，建议重点关注辩论环节')
    else:
        output.append('❌ **共识偏悲观**：多数角色对今日日报质量不满意，需复盘')

    return '\n'.join(output)


def append_to_daily(report_path, report_output):
    """追加到日报文件"""
    with open(report_path, 'a', encoding='utf-8') as f:
        f.write(report_output)
    log(f"✅ 圆桌推演已追加到: {report_path}")


def main():
    """主流程"""
    date_str = sys.argv[1] if len(sys.argv) > 1 else TODAY
    log(f"=== 多角色圆桌推演 {date_str} ===\n")

    # 1. 检查是否已存在
    date = date_str
    report_path = os.path.join(OUTPUT_DIR, f'{date}.md')
    if check_already_appended(report_path):
        log(f"⚠️ 今日圆桌推演已存在，跳过")
        return

    # 2. 加载数据
    daily_content, report_path = load_daily_report(date_str)
    if not daily_content:
        sys.exit(1)
    jinzhu_data = load_jinzhu_analysis()
    log("✅ 数据加载完成")

    # 3. 随机抽取副角色
    side_count = random.randint(1, 2)
    side_names = random.sample(list(SIDE_AGENTS.keys()), min(side_count, len(SIDE_AGENTS)))
    log(f"🎲 抽取副角色: {side_names}")

    # 4. 并行执行独立评价
    log("\n1. 多角色独立评价...")
    all_agents = {}
    all_agents.update(AGENT_PROMPTS)
    for sn in side_names:
        all_agents[sn] = SIDE_AGENTS[sn]

    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(run_single_agent, name, cfg, daily_content): name
            for name, cfg in all_agents.items()
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    if not results:
        log("❌ 所有角色评价失败")
        sys.exit(1)
    log(f"✅ {len(results)}/{len(all_agents)} 角色评价成功")

    # 5. 检测冲突 → 辩论
    log("\n2. 检测观点冲突...")
    conflicts = detect_conflicts(results)
    debates = []
    if conflicts:
        # 取最严重的冲突辩论
        top_conflicts = sorted(conflicts, key=lambda c: c['diff'], reverse=True)[:2]
        log(f"⚡ 发现 {len(top_conflicts)} 个重大分歧，开始辩论...")
        results_map = {r['name']: r for r in results}
        for conflict in top_conflicts:
            debate = run_debate(conflict, results_map)
            if debate:
                debates.append(debate)
    else:
        log("✅ 无重大分歧")

    # 6. 加权共识
    log("\n3. 计算加权共识...")
    consensus = calculate_consensus(results, debates)
    log(f"📊 综合评分: {consensus['score']}/10")

    # 7. 生成输出并追加
    log("\n4. 生成推演报告...")
    report_output = generate_report_output(results, debates, consensus, side_names)
    append_to_daily(report_path, report_output)

    print("\n" + "=" * 50)
    print(f"✅ 多角色圆桌推演完成")
    print(f"📊 综合评分: {consensus['score']}/10")
    print(f"👥 参与角色: {len(results)}")
    print(f"⚡ 辩论场次: {len(debates)}")
    print("=" * 50)


if __name__ == '__main__':
    main()
