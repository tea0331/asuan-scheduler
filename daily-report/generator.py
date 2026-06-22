#!/usr/bin/env python3
"""
日报生成主程序 - 阿算智能引擎（openai SDK 版）
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from openai import OpenAI

# 强制加载 .env
_env_path = '/root/asuan-scheduler/.env'
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

BASE_DIR = Path(__file__).parent.parent
CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime("%Y-%m-%d")

def call_hunyuan(prompt: str) -> str:
    """调用混元API（openai SDK）"""
    api_key = os.environ.get("HUNYUAN_API_KEY", "")
    base_url = os.environ.get("HUNYUAN_BASE_URL", "https://api.lkeap.cloud.tencent.com/plan/v3")
    if not api_key:
        return "（混元API未配置）"
    
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model="hy3-preview",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"（API调用失败：{e}）"

def rule_based_section(title: str) -> str:
    """规则版板块（不依赖AI）"""
    templates = {
        "资讯速报": "今日暂无新增资讯（规则版）。",
        "短缺预警": "历史数据回顾：供需平衡（规则版）。",
        "逆潮观察": "市场动态观察：无异常（规则版）。",
        "传导分析": "行业关联梳理：大陆←→台湾（规则版）。",
        "避坑提醒": "理性购彩须知：警惕诈骗（规则版）。",
        "邪修金句": "合规投注理念：小额娱乐（规则版）。",
    }
    return templates.get(title, "暂无数据")

def generate_section(title: str, prompt: str, use_ai: bool) -> str:
    """生成一个板块"""
    if use_ai:
        content = call_hunyuan(prompt)
        # 降级判断：合规拒绝关键词
        if any(kw in content for kw in ["合规", "拒绝", "不提供", "无法提供", "涉嫌"]):
            return f"【{title}】\n（AI合规拦截，切换规则版）\n" + rule_based_section(title)
        return f"【{title}】\n{content}"
    else:
        return f"【{title}】\n" + rule_based_section(title)

def generate_daily_report(date_str: str = None, use_ai: bool = True) -> dict:
    """生成完整日报"""
    if not date_str:
        date_str = today_str
    
    print(f"⏳ 生成日报 {date_str}...")
    
    sections = {
        "news": generate_section("资讯速报", f"生成今日（{date_str}）彩票相关资讯速报，5条，每条含标题+摘要+来源。\n重要声明：仅供历史数据回顾和公益科普，不构成任何投注建议。", use_ai),
        "shortage": generate_section("短缺预警", f"历史数据回顾（仅供参考）：彩票市场供需情况。\n重要声明：不涉及预测，仅做合规科普。", use_ai),
        "reverse": generate_section("逆潮观察", f"市场动态观察（不构成建议）：彩票市场非共识现象。\n重要声明：以合规、公益、科普口吻输出。", use_ai),
        "conduction": generate_section("传导分析", f"行业关联梳理：大陆与台湾彩票市场关联。\n重要声明：不涉及预测，仅做历史回顾。", use_ai),
        "avoid": generate_section("避坑提醒", f"基于回测数据，列出近期持续低于预期的策略方向（仅供参考，不构成投注建议）。\n重要声明：以合规、公益、科普口吻输出。", use_ai),
        "evil": generate_section("邪修金句", f"对{date_str}日报生成邪修评价，7-10分刻度。\n重要声明：不涉及预测，仅做理念分享。", use_ai),
    }
    
    return {
        "date": date_str,
        "generated_at": datetime.now(CST).isoformat(),
        "sections": sections,
        "metadata": {"model": "hy3-preview" if use_ai else "rule-based"}
    }

def save_report(report: dict, output_dir: str = "output"):
    """保存日报"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    date_str = report["date"]
    md_file = output_path / f"{date_str}.md"
    
    md_content = f"# 阿算帮刘老板发财日报 | {date_str}\n\n"
    md_content += f"生成时间：{report['generated_at']}\n\n---\n\n"
    
    for key, title in [
        ("news", "📰 资讯速报"),
        ("shortage", "⚠️ 短缺预警"),
        ("reverse", "🔄 逆潮观察"),
        ("conduction", "🔗 传导分析"),
        ("avoid", "🚫 避坑提醒"),
        ("evil", "😈 邪修金句"),
    ]:
        md_content += f"## {title}\n\n{report['sections'][key]}\n\n---\n\n"
    
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    print(f"✅ 日报已保存：{md_file}")
    return str(md_file)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="阿算日报生成器（openai SDK版）")
    parser.add_argument("--date", default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--no-ai", action="store_true", help="不使用AI")
    parser.add_argument("--output", default="daily-report/output", help="输出目录")
    args = parser.parse_args()
    
    report = generate_daily_report(args.date, use_ai=not args.no_ai)
    md_file = save_report(report, args.output)
    
    print(f"\n✅ 日报生成完成：{md_file}")
    print(f"   板块数：{len(report['sections'])}")
    print(f"   模型：{report['metadata']['model']}")

if __name__ == "__main__":
    main()

    # 自动 push 日报到 GitHub
    import subprocess
    from datetime import datetime
    try:
        subprocess.run(['git', 'add', 'daily-report/output/'], check=True)
        subprocess.run(['git', 'commit', '-m', f'daily: {datetime.now().strftime("%Y-%m-%d")}'], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print('✅ 日报已推送到 GitHub')
    except Exception as e:
        print(f'⚠️ Git push 失败: {e}')
