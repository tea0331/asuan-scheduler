#!/usr/bin/env python3
"""
JinZhu 多角色推荐增强 v1.0
基于 JinZhu 的分析数据，多角色各自给出推荐意见，输出对比版推荐

工作流:
  1. 读 jinzhu_analysis.json
  2. 4个角色独立评价
  3. 输出推荐对比表
  4. 写入 lottery-predictions.json 扩展字段

调用:
  python3 jinzhu_multi_role.py           # 默认今天
  python3 jinzhu_multi_role.py ssq       # 指定彩种
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime('%Y-%m-%d')

MODULE_DIR = '/root/asuan-scheduler'
ANALYSIS_PATH = os.path.join(MODULE_DIR, 'jinzhu_analysis.json')
PREDICTIONS_PATH = os.path.join(MODULE_DIR, 'lottery-predictions.json')
OUTPUT_PATH = os.path.join(MODULE_DIR, 'data', 'lottery-roundtable.json')

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

ROLES = {
    "西蒙斯·量化": {
        "emoji": "📊",
        "prompt": """你是量化交易员西蒙斯。只看数据，不信直觉。
分析 JinZhu 的策略分析数据，评估：
1. 哪个策略的统计显著性最高？（不要只看命中率，要看ROI和样本量）
2. 策略之间是否有相关性？是否存在过拟合？
3. 给定当前数据，你会怎么分配投注比例？
输出格式：【最优策略】【分配方案】【风险警告】"""
    },
    "巴菲特·赔率": {
        "emoji": "🐂",
        "prompt": """你是巴菲特。只关注安全边际和长期赔率。
分析 JinZhu 的策略分析数据，评估：
1. 哪个策略的赔率最高？（盈亏比）
2. 最坏情况下会亏多少？安全边际在哪？
3. 你会建议买还是不买？买多少？
输出格式：【赔率评估】【安全边际】【建议】"""
    },
    "老王·韭菜": {
        "emoji": "🀄",
        "prompt": """你是老王，做了20年彩票的老韭菜。
看 JinZhu 的分析数据，用散户的视角：
1. 这些数字看起来诱人吗？哪里是坑？
2. 散户看到这个会怎么操作？
3. 反着来会怎样？
输出格式：【第一反应】【陷阱提示】【反操作建议】"""
    },
    "算命先生·老周": {
        "emoji": "🔮",
        "prompt": """你是老周，民间算命先生。
用五行、干支、流年看彩票：
1. 当前流年运势适合什么彩种？
2. 结合分析数据，哪些数字组合有"气"？
3. 今天忌什么？
输出格式：【流年运势】【吉数组合】【今日禁忌】"""
    }
}


def call_deepseek(system_msg, user_msg, max_tokens=1000, temperature=0.7, retries=2):
    if not API_KEY:
        return "❌ API Key 未配置"
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
    for attempt in range(retries + 1):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=90)
            if resp.status_code == 200:
                result = resp.json()['choices'][0]['message']['content']
                if result and result.strip():
                    return result.strip()
            if attempt < retries:
                print(f"  [重试{attempt+1}] ", end='')
        except Exception as e:
            if attempt < retries:
                print(f"  [重试{attempt+1}] {e}")


def load_analysis():
    """加载分析数据"""
    if not os.path.exists(ANALYSIS_PATH):
        print(f"❌ 不存在: {ANALYSIS_PATH}")
        return None
    with open(ANALYSIS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_predictions():
    """加载现有预测"""
    if not os.path.exists(PREDICTIONS_PATH):
        return {}
    with open(PREDICTIONS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_summary(analysis_data):
    """提取精简分析摘要（去掉嵌套详情，只留指标）"""
    summary = {}
    strategy = analysis_data.get('strategy_analysis', {})
    for sname, sdata in strategy.items():
        entry = {}
        for k in ['hit_rate', 'effective_hit_rate', 'roi', 'total_bets', 'total_cost', 'total_won', 'profit']:
            if k in sdata:
                entry[k] = sdata[k]
        if 'analysis' in sdata and isinstance(sdata['analysis'], dict):
            entry['conclusion'] = sdata['analysis'].get('conclusion', '')
        summary[sname] = entry
    return summary


def run_role(role_name, role_cfg, analysis_data, target_game):
    """单个角色评价"""
    summary = extract_summary(analysis_data)
    analysis_str = json.dumps(summary, ensure_ascii=False, indent=2)
    if len(analysis_str) > 2000:
        analysis_str = analysis_str[:2000]
    
    user_msg = f"""JinZhu 彩票分析数据（{TODAY}，目标彩种: {target_game}）：

{analysis_str}

请以【{role_name}】的身份给出你的推荐意见。"""
    
    result = call_deepseek(role_cfg['prompt'], user_msg, max_tokens=800, temperature=0.7)
    return result


def main():
    target_game = sys.argv[1] if len(sys.argv) > 1 else 'ssq'
    
    print(f"=== JinZhu 多角色推荐 {TODAY} [{target_game}] ===\n")
    
    # 加载数据
    analysis = load_analysis()
    if not analysis:
        sys.exit(1)
    print("✅ 分析数据加载完成")
    
    # 提取目标彩种的数据
    game_data = {}
    if 'strategy_analysis' in analysis and target_game in analysis['strategy_analysis']:
        game_data['strategy_analysis'] = analysis['strategy_analysis'][target_game]
    if 'reverse_backtest' in analysis and target_game in analysis['reverse_backtest']:
        game_data['reverse_backtest'] = analysis['reverse_backtest'][target_game]
    if 'monte_carlo_validation' in analysis:
        game_data['monte_carlo_validation'] = analysis['monte_carlo_validation']
    
    # 串行调用4角色（API限速，避免并发超时）
    print(f"🤖 启动 {len(ROLES)} 个角色评价...")
    results = {}
    for name, cfg in ROLES.items():
        print(f"  🔄 {name}...", end='', flush=True)
        result = run_role(name, cfg, game_data, target_game)
        if result:
            results[name] = result
            print(f" ✅")
        else:
            print(f" ❌")
    
    if not results:
        print("❌ 所有角色评价失败")
        sys.exit(1)
    
    # 生成输出
    output = []
    output.append(f"## 🎲 {target_game.upper()} 多角色推荐 | {TODAY}")
    output.append("")
    
    for name, content in results.items():
        cfg = ROLES[name]
        output.append(f"### {cfg['emoji']} {name}")
        output.append(content)
        output.append("")
    
    # 保存
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    roundtable_data = {
        "date": TODAY,
        "game": target_game,
        "roles": results,
        "generated_at": datetime.now(CST).isoformat()
    }
    
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(roundtable_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 多角色推荐已保存: {OUTPUT_PATH}")
    print(f"📊 参与角色: {len(results)}/{len(ROLES)}")
    
    # 也追加到 predictions 里（扩展字段）
    predictions = load_predictions()
    if predictions and isinstance(predictions, dict):
        if 'multi_role' not in predictions:
            predictions['multi_role'] = {}
        predictions['multi_role'][TODAY] = {
            "game": target_game,
            "roles": list(results.keys()),
            "consensus": "见 roundtable 详细输出"
        }
        with open(PREDICTIONS_PATH, 'w', encoding='utf-8') as f:
            json.dump(predictions, f, ensure_ascii=False, indent=2)
        print("✅ 已扩展到 predictions 文件")


if __name__ == '__main__':
    main()
