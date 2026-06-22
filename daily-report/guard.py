#!/usr/bin/env python3
"""
日报质量守护 - 阿算智能引擎 阶段三
每次发送前验证6大板块完整性 + 内容动态性 + 邪修进化
"""

import re
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')

# ============================================================
# 日报内容契约（不可修改）
# ============================================================
DAILY_REPORT_CONTRACT = {
    "required_sections": [
        ("资讯速报", "一、每日资讯"),
        ("短缺预警", "二、资源短缺预警"),
        ("逆潮观察", "三、逆潮观察"),
        ("传导分析", "四、传导分析"),
        ("避坑提醒", "五、避坑提醒"),
        ("邪修金句", "六、邪修金句"),
    ],
    "forbidden_patterns": [
        r"融资", r"股票", r"配股", r"增发",  # 双层过滤
    ],
    "min_length": 100,  # 每板块最少字符
}

# ============================================================
# 守护函数
# ============================================================

def validate_report_sections(content: str) -> dict:
    """验证6大板块完整性"""
    result = {"valid": True, "missing": [], "extra": []}
    
    for section_name, section_keyword in DAILY_REPORT_CONTRACT["required_sections"]:
        if section_keyword not in content:
            result["valid"] = False
            result["missing"].append(section_name)
    
    return result

def validate_no_forbidden(content: str) -> dict:
    """验证无禁止内容"""
    result = {"valid": True, "found": []}
    
    for pattern in DAILY_REPORT_CONTRACT["forbidden_patterns"]:
        if re.search(pattern, content):
            result["valid"] = False
            result["found"].append(pattern)
    
    return result

def validate_dynamic(content: str, history_file: str = None) -> dict:
    """验证内容动态性（非硬编码模板）"""
    result = {"valid": True, "static_count": 0}
    
    # 检查邪修金句是否动态（与昨天不同）
    if history_file and Path(history_file).exists():
        with open(history_file, encoding="utf-8") as f:
            history = f.read()
        # 简单检查：如果邪修金句完全相同，认为静态
        if "邪修金句" in history and "邪修金句" in content:
            old_evil = re.search(r"邪修金句.*?\n(.*?)\n", history, re.DOTALL)
            new_evil = re.search(r"邪修金句.*?\n(.*?)\n", content, re.DOTALL)
            if old_evil and new_evil and old_evil.group(1) == new_evil.group(1):
                result["valid"] = False
                result["static_count"] += 1
    
    return result

def guard_report(content: str, history_file: str = None) -> dict:
    """完整守护检查"""
    print(f"🛡️  日报守护 - 开始验证...")
    
    # 1. 板块完整性
    section_result = validate_report_sections(content)
    if not section_result["valid"]:
        print(f"  ❌ 板块缺失：{section_result['missing']}")
    else:
        print(f"  ✅ 板块完整性：6/6")
    
    # 2. 禁止内容
    forbidden_result = validate_no_forbidden(content)
    if not forbidden_result["valid"]:
        print(f"  ❌ 发现禁止内容：{forbidden_result['found']}")
    else:
        print(f"  ✅ 禁止内容过滤：通过")
    
    # 3. 动态性
    dynamic_result = validate_dynamic(content, history_file)
    if not dynamic_result["valid"]:
        print(f"  ❌ 内容静态：{dynamic_result['static_count']}处")
    else:
        print(f"  ✅ 内容动态性：通过")
    
    overall = section_result["valid"] and forbidden_result["valid"] and dynamic_result["valid"]
    print(f"\n🛡️  守护结果：{'✅ 通过' if overall else '❌ 未通过'}")
    
    return {
        "overall": overall,
        "section": section_result,
        "forbidden": forbidden_result,
        "dynamic": dynamic_result,
    }

# ============================================================
# CLI 入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="日报质量守护")
    parser.add_argument("--file", required=True, help="日报文件路径")
    parser.add_argument("--history", default=None, help="历史日报路径（用于动态性检查）")
    args = parser.parse_args()
    
    if not Path(args.file).exists():
        print(f"❌ 文件不存在：{args.file}")
        return
    
    with open(args.file, encoding="utf-8") as f:
        content = f.read()
    
    result = guard_report(content, args.history)
    
    if not result["overall"]:
        exit(1)

if __name__ == "__main__":
    main()
