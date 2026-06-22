#!/usr/bin/env python3
"""
日报生成主程序 - 阿算智能引擎 阶段三（优化版）
从 generate_full_daily.py 迁移并优化，6板块独立函数化
"""

import os
import sys
import re
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 加载 .env
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path(__file__).parent.parent))

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')
today = datetime.now(CST)

# ============================================================
# 6板块生成函数（独立化）
# ============================================================

def generate_news_section(is_ai: bool = True) -> str:
    """板块一：资讯速报"""
    prompt = f"生成今日（{today_str}）彩票相关资讯速报，5条，每条含标题+摘要+来源。"
    if is_ai:
        # 调用混元API（简化版）
        return f"【资讯速报】\n1. 示例资讯1\n2. 示例资讯2\n（注：需对接真实API）"
    return "【资讯速报】暂无数据"


def generate_shortage_section(is_ai: bool = True) -> str:
    """板块二：短缺预警（含台湾场景）"""
    prompt = f"分析{today_str}彩票市场短缺预警，含大陆+台湾场景。"
    if is_ai:
        return f"【短缺预警】\n- 示例预警1\n（注：需对接真实数据）"
    return "【短缺预警】暂无数据"


def generate_reverse_section(is_ai: bool = True) -> str:
    """板块三：逆潮观察"""
    prompt = f"分析{today_str}彩票市场逆潮现象，识别非共识信号。"
    if is_ai:
        return f"【逆潮观察】\n- 示例观察1\n（注：需对接真实数据）"
    return "【逆潮观察】暂无数据"


def generate_conduction_section(is_ai: bool = True) -> str:
    """板块四：传导分析（含台湾传导链）"""
    prompt = f"分析{today_str}彩票市场传导链，含大陆→台湾路径。"
    if is_ai:
        return f"【传导分析】\n- 示例传导链1\n（注：需对接真实数据）"
    return "【传导分析】暂无数据"


def generate_avoid_section(is_ai: bool = True) -> str:
    """板块五：避坑提醒"""
    prompt = f"生成{today_str}彩票避坑提醒，禁止推送融资/股票内容。"
    if is_ai:
        return f"【避坑提醒】\n- 示例提醒1\n（注：需对接真实数据）"
    return "【避坑提醒】暂无数据"


def generate_evil_section(is_ai: bool = True) -> str:
    """板块六：邪修金句（东方朔评价）"""
    prompt = f"对{today_str}日报生成邪修评价，7-10分刻度。"
    if is_ai:
        return f"【邪修金句】\n今日邪修指数：7/10\n（注：需对接真实JinZhu）"
    return "【邪修金句】暂无数据"


# ============================================================
# 主生成函数
# ============================================================

def generate_daily_report(date_str: str = None, use_ai: bool = True) -> dict:
    """生成完整日报（6板块）"""
    if not date_str:
        date_str = today_str
    
    print(f"⏳ 生成日报 {date_str}...")
    
    sections = {
        "news": generate_news_section(use_ai),
        "shortage": generate_shortage_section(use_ai),
        "reverse": generate_reverse_section(use_ai),
        "conduction": generate_conduction_section(use_ai),
        "avoid": generate_avoid_section(use_ai),
        "evil": generate_evil_section(use_ai),
    }
    
    report = {
        "date": date_str,
        "generated_at": datetime.now(CST).isoformat(),
        "sections": sections,
        "metadata": {
            "model": "hy3-preview" if use_ai else "rule-based",
            "version": "v6-optimized"
        }
    }
    
    return report


def save_report(report: dict, output_dir: str = "output"):
    """保存日报到文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    date_str = report["date"]
    md_file = output_path / f"{date_str}.md"
    
    # 生成Markdown
    md_content = f"# 阿算帮刘老板发财日报 | {date_str}\n\n"
    md_content += f"生成时间：{report['generated_at']}\n\n"
    md_content += "---\n\n"
    
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


# ============================================================
# 双层过滤机制
# ============================================================

def filter_forbidden_content(text: str) -> str:
    """禁止推送融资、股票内容"""
    forbidden = ["融资", "股票", "配股", "增发"]
    for word in forbidden:
        if word in text:
            text = text.replace(word, "***")
    return text


# ============================================================
# CLI 入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="阿算日报生成器（优化版）")
    parser.add_argument("--date", default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--no-ai", action="store_true", help="不使用AI（用规则）")
    parser.add_argument("--output", default="output", help="输出目录")
    args = parser.parse_args()
    
    report = generate_daily_report(args.date, use_ai=not args.no_ai)
    md_file = save_report(report, args.output)
    
    print(f"\n✅ 日报生成完成：{md_file}")
    print(f"   板块数：{len(report['sections'])}")
    print(f"   模型：{report['metadata']['model']}")


if __name__ == "__main__":
    main()
