#!/usr/bin/env python3
"""
阿算智能引擎 - Streamlit Dashboard
阶段四交付物
"""

import streamlit as st
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 修复 Windows 11 的 os.path 问题
if sys.platform == "win32" or True:  # 强制使用 pathlib
    import pathlib
    Path = pathlib.Path

BASE_DIR = Path(__file__).parent.parent
CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')

# 页面配置
st.set_page_config(
    page_title="阿算智能引擎",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 侧边栏导航
st.sidebar.title("🧠 阿算智能引擎")
page = st.sidebar.radio(
    "导航",
    ["📊 策略回测", "🎯 实时推荐", "📰 日报浏览", "📈 模型评测"]
)

# ============================================================
# 页面1：策略回测
# ============================================================
if page == "📊 策略回测":
    st.title("📊 策略回测")
    st.caption("加载 backtest/results/ 数据")
    
    results_dir = BASE_DIR / "backtest/results"
    
    if not results_dir.exists():
        st.warning("⚠️ backtest/results/ 目录不存在")
    else:
        # 列出所有回测文件
        files = list(results_dir.glob("*.json"))
        if not files:
            st.info("暂无回测结果")
        else:
            selected = st.selectbox("选择回测文件", [f.name for f in files])
            if selected:
                with open(results_dir / selected, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                st.metric("总期数", len(data))
                
                # 统计命中率
                if data:
                    levels = {}
                    for r in data:
                        lvl = r.get("hit", {}).get("level", 0)
                        levels[lvl] = levels.get(lvl, 0) + 1
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("奖级分布")
                        st.bar_chart(levels)
                    with col2:
                        st.subheader("详细数据")
                        st.json(data[:5])  # 展示前5期

# ============================================================
# 页面2：实时推荐
# ============================================================
elif page == "🎯 实时推荐":
    st.title("🎯 实时推荐")
    st.caption("展示 JinZhu 今日推荐")
    
    # 读取解释模块输出
    explainer_dir = BASE_DIR / "explainer"
    
    st.subheader("双色球 SSQ")
    st.info("调用 generate_explanation.py 生成解释文本")
    
    st.subheader("大乐透 DLT")
    st.info("调用 generate_explanation.py 生成解释文本")
    
    if st.button("🔄 重新生成推荐"):
        st.success("推荐已更新（模拟）")

# ============================================================
# 页面3：日报浏览
# ============================================================
elif page == "📰 日报浏览":
    st.title("📰 日报浏览")
    st.caption("展示 daily-report/output/ 生成的日报")
    
    output_dir = BASE_DIR / "daily-report/output"
    
    if not output_dir.exists():
        st.warning("⚠️ daily-report/output/ 目录不存在")
    else:
        files = list(output_dir.glob("*.md"))
        if not files:
            st.info("暂无日报")
        else:
            selected = st.selectbox("选择日报", [f.name for f in sorted(files, reverse=True)])
            if selected:
                with open(output_dir / selected, "r", encoding="utf-8") as f:
                    content = f.read()
                st.markdown(content)

# ============================================================
# 页面4：模型评测
# ============================================================
elif page == "📈 模型评测":
    st.title("📈 模型评测")
    st.caption("展示 model-eval/results/ 评测结果")
    
    results_dir = BASE_DIR / "model-eval/results"
    
    if not results_dir.exists():
        st.warning("⚠️ model-eval/results/ 目录不存在")
    else:
        files = list(results_dir.glob("*.json"))
        if not files:
            st.info("暂无评测结果")
        else:
            selected = st.selectbox("选择评测结果", [f.name for f in files])
            if selected:
                with open(results_dir / selected, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                st.metric("评测用例数", len(data))
                
                # 按模型分组
                models = {}
                for r in data:
                    model = r.get("model", "unknown")
                    if model not in models:
                        models[model] = []
                    models[model].append(r)
                
                for model, results in models.items():
                    st.subheader(f"模型：{model}")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        avg_time = sum(r["time_seconds"] for r in results) / len(results)
                        st.metric("平均耗时", f"{avg_time:.2f}s")
                    with col2:
                        avg_tokens = sum(r["tokens_used"] for r in results) / len(results)
                        st.metric("平均Token", f"{avg_tokens:.0f}")
                    with col3:
                        avg_fmt = sum(r["format_score"] for r in results) / len(results)
                        st.metric("格式得分", f"{avg_fmt:.1%}")

# ============================================================
# 页脚
# ============================================================
st.sidebar.markdown("---")
st.sidebar.caption(f"当前时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
