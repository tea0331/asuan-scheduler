#!/usr/bin/env python3
"""
阿算智能引擎 - Streamlit Dashboard
日报系统面板（asuan-scheduler）
"""

import streamlit as st
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).parent.parent
CST = timezone(timedelta(hours=8))
today_str = datetime.now(CST).strftime('%Y-%m-%d')

# 页面配置
st.set_page_config(
    page_title="阿算日报系统",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 侧边栏导航
st.sidebar.title("📰 阿算日报系统")
page = st.sidebar.radio(
    "导航",
    ["📰 日报浏览", "📈 模型评测", "🔗 JinZhu 回测"]
)

# ============================================================
# 页面1：日报浏览
# ============================================================
if page == "📰 日报浏览":
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
# 页面2：模型评测
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
# 页面3：JinZhu 回测（链接）
# ============================================================
elif page == "🔗 JinZhu 回测":
    st.title("🔗 JinZhu 回测")
    st.caption("JinZhu 引擎回测结果（在 asuan-jinzhu 仓库）")
    
    st.info("""
    JinZhu 回测结果已迁移到独立仓库：
    [tea0331/asuan-jinzhu](https://github.com/tea0331/asuan-jinzhu)
    
    回测文件位置：`backtest/results/`
    """)
    
    # 尝试读取本地 asuan-jinzhu 的回测结果
    jinzhu_dir = Path("/root/asuan-jinzhu")
    if jinzhu_dir.exists():
        results_dir = jinzhu_dir / "backtest/results"
        if results_dir.exists():
            files = list(results_dir.glob("*.json"))
            if files:
                st.subheader("本地 JinZhu 回测结果")
                for f in files:
                    st.write(f"📊 {f.name}")
            else:
                st.warning("本地 asuan-jinzhu/backtest/results/ 为空")
        else:
            st.warning("本地 asuan-jinzhu/backtest/results/ 不存在")
    else:
        st.warning("本地 asuan-jinzhu 仓库不存在")

# ============================================================
# 页脚
# ============================================================
st.sidebar.markdown("---")
st.sidebar.caption(f"当前时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
