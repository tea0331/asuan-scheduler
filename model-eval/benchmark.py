#!/usr/bin/env python3
"""
模型评测框架 - 阿算智能引擎 阶段三
对比混元API和其他模型在日报生成任务上的表现
"""

import json
import time
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')

# ============================================================
# 评测维度
# ============================================================

EVAL_DIMENSIONS = {
    "content_quality": "内容质量（因果链是否成立）",
    "format_compliance": "输出格式（是否符合6板块规范）",
    "token_cost": "Token消耗（成本对比）",
    "speed": "生成速度（秒）",
}

# ============================================================
# 评测用例
# ============================================================

TEST_CASES = [
    {
        "id": "news_section",
        "name": "资讯速报生成",
        "prompt": "生成今日彩票相关资讯速报，5条，每条含标题+摘要+来源。",
        "expected_sections": 1,
        "max_tokens": 500,
    },
    {
        "id": "shortage_section",
        "name": "短缺预警生成",
        "prompt": "分析彩票市场短缺预警，含大陆+台湾场景。",
        "expected_sections": 1,
        "max_tokens": 500,
    },
    {
        "id": "full_report",
        "name": "完整日报生成",
        "prompt": "生成完整日报，包含6大板块：资讯速报、短缺预警、逆潮观察、传导分析、避坑提醒、邪修金句。",
        "expected_sections": 6,
        "max_tokens": 2000,
    },
]

# ============================================================
# 模型调用（简化版）
# ============================================================

def call_hunyuan(prompt: str, max_tokens: int = 500) -> dict:
    """调用混元API"""
    # 实际应调用 requests.post("https://api.hunyuan.cloud.tencent.com/v1/chat/completions", ...)
    # 这里用占位返回
    start = time.time()
    time.sleep(1)  # 模拟API调用
    end = time.time()
    
    return {
        "model": "hy3-preview",
        "response": f"【测试回复】{prompt[:50]}...（注：实际需对接真实API）",
        "tokens_used": max_tokens,
        "time_seconds": end - start,
        "success": True,
    }

def call_openrouter(prompt: str, max_tokens: int = 500) -> dict:
    """调用OpenRouter API（备用）"""
    start = time.time()
    time.sleep(1.5)  # 模拟
    end = time.time()
    
    return {
        "model": "openrouter-auto",
        "response": f"【OpenRouter测试】{prompt[:50]}...",
        "tokens_used": max_tokens,
        "time_seconds": end - start,
        "success": True,
    }

# ============================================================
# 评测逻辑
# ============================================================

def evaluate_response(response: dict, test_case: dict) -> dict:
    """评测单次响应"""
    result = {
        "test_id": test_case["id"],
        "test_name": test_case["name"],
        "model": response["model"],
        "success": response["success"],
        "tokens_used": response["tokens_used"],
        "time_seconds": response["time_seconds"],
        "response_length": len(response["response"]),
    }
    
    # 格式合规性检查
    if test_case["id"] == "full_report":
        required_keywords = ["资讯速报", "短缺预警", "逆潮观察", "传导分析", "避坑提醒", "邪修金句"]
        found = sum(1 for kw in required_keywords if kw in response["response"])
        result["format_score"] = found / len(required_keywords)
    else:
        result["format_score"] = 1.0 if len(response["response"]) > 100 else 0.0
    
    return result

def run_benchmark(models: list = None):
    """运行评测"""
    if models is None:
        models = ["hy3-preview", "openrouter-auto"]
    
    print(f"=== 模型评测开始 {today_str} ===")
    print(f"模型：{models}")
    print(f"用例数：{len(TEST_CASES)}")
    print()
    
    all_results = []
    
    for test_case in TEST_CASES:
        print(f"📊 测试用例：{test_case['name']}")
        
        for model in models:
            if model == "hy3-preview":
                response = call_hunyuan(test_case["prompt"], test_case["max_tokens"])
            else:
                response = call_openrouter(test_case["prompt"], test_case["max_tokens"])
            
            eval_result = evaluate_response(response, test_case)
            all_results.append(eval_result)
            
            print(f"  {model}: {eval_result['time_seconds']:.2f}s, {eval_result['tokens_used']} tokens, 格式{eval_result['format_score']:.1%}")
    
    # 保存结果
    output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"benchmark_{today_str}.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 评测完成，结果保存至：{output_file}")
    
    # 汇总
    print(f"\n=== 评测汇总 ===")
    for model in models:
        model_results = [r for r in all_results if r["model"] == model]
        avg_time = sum(r["time_seconds"] for r in model_results) / len(model_results)
        avg_tokens = sum(r["tokens_used"] for r in model_results) / len(model_results)
        avg_format = sum(r["format_score"] for r in model_results) / len(model_results)
        
        print(f"{model}:")
        print(f"  平均耗时：{avg_time:.2f}s")
        print(f"  平均Token：{avg_tokens:.0f}")
        print(f"  格式得分：{avg_format:.1%}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="模型评测框架")
    parser.add_argument("--models", nargs="+", default=["hy3-preview", "openrouter-auto"], help="模型列表")
    args = parser.parse_args()
    
    run_benchmark(args.models)

if __name__ == "__main__":
    main()
