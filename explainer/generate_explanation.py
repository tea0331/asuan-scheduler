#!/usr/bin/env python3
"""
解释模块 - 阿算智能引擎 阶段二
调用混元API，将推荐结果转为自然语言解释
"""

import json
import os
import sys
from pathlib import Path

# 混元API配置（从环境变量或配置读取）
HY_API_URL = "https://api.hunyuan.cloud.tencent.com/v1/chat/completions"
# 注意：实际token需从 OpenClaw 配置读取，这里用占位符
HY_TOKEN = os.getenv("HY_TOKEN", "YOUR_HY_TOKEN_HERE")

def generate_explanation(recommendation: dict, lottery_name: str) -> str:
    """
    生成推荐解释文本
    输入：recommendation（JinZhu输出格式）
    输出：自然语言解释字符串
    """
    if not recommendation:
        return "暂无推荐数据"

    # 构造prompt
    if lottery_name == "SSQ":
        numbers = recommendation.get("numbers", [])
        if len(numbers) >= 7:
            red = numbers[:6]
            blue = numbers[6]
            prompt = f"双色球最新推荐：红球 {red}，蓝球 {blue}。请用一句话解释这个推荐组合的特点（如号码分布、奇偶比、冷热号等）。"
        else:
            prompt = f"双色球推荐数据：{recommendation}"
    elif lottery_name == "DLT":
        numbers = recommendation.get("numbers", [])
        if len(numbers) >= 7:
            front = numbers[:5]
            back = numbers[5:]
            prompt = f"大乐透最新推荐：前区 {front}，后区 {back}。请用一句话解释推荐特点。"
        else:
            prompt = f"大乐透推荐数据：{recommendation}"
    else:
        prompt = f"{lottery_name}推荐数据：{recommendation}"

    # 调用混元API（简化版，实际需用 requests）
    # 这里先返回占位文本，后续对接真实API
    explanation = f"【{lottery_name}推荐解释】\n根据JinZhu算法分析，{prompt.split('。')[0]}。\n（注：此为测试文本，实际将调用混元API生成）"
    return explanation

def main():
    # 测试
    test_rec = {
        "lottery": "SSQ",
        "issue": "2026070",
        "numbers": [3, 8, 14, 20, 26, 32, 11],
        "sales": 0,
        "pool": 0
    }
    explanation = generate_explanation(test_rec, "SSQ")
    print(explanation)

if __name__ == "__main__":
    main()
