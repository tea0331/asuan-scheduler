#!/usr/bin/env python3
"""
马斯克系统 Web 页面 — Streamlit
端口 8501 | 自由输入市场信息 → 缺口推演 + 合规评估

复用 musk_push.py 的核心函数：call_hy3, run_inference, ask_hy3_for_law, query_laws_db, self_evaluate
"""
import streamlit as st
import os
import sys
import json
from datetime import datetime, timezone, timedelta

# 路径配置 — 确保能 import musk_push.py
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))  # asuan-scheduler/
sys.path.insert(0, PROJECT_DIR)

CST = timezone(timedelta(hours=8))

st.set_page_config(
    page_title="马斯克 · 市场缺口推演",
    page_icon="🔮",
    layout="wide"
)

# ============================================================
# 样式
# ============================================================
st.markdown("""
<style>
    .musk-title { font-size: 2rem; font-weight: 700; color: #e74c3c; margin-bottom: 0; }
    .musk-subtitle { color: #888; font-size: 0.9rem; margin-top: -10px; margin-bottom: 20px; }
    .gap-box { background: #fff5f5; border-left: 4px solid #e74c3c; padding: 15px; border-radius: 4px; margin: 10px 0; }
    .law-box { background: #f0f8ff; border-left: 4px solid #3498db; padding: 15px; border-radius: 4px; margin: 10px 0; }
    .eval-box { background: #f5f5f5; padding: 10px; border-radius: 4px; margin: 10px 0; }
    .risk-green { color: #27ae60; font-weight: 600; }
    .risk-yellow { color: #f39c12; font-weight: 600; }
    .risk-red { color: #e74c3c; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 加载数据
# ============================================================
@st.cache_data(ttl=3600)
def load_data():
    """加载案例库和方法论"""
    data = {
        'gap_cases': [],
        'case_count': 0,
        'social_mood': None,
        'methodology': None
    }
    
    gap_path = os.path.join(PROJECT_DIR, 'data', 'musk', 'gap-cases.json')
    if os.path.exists(gap_path):
        with open(gap_path, 'r', encoding='utf-8') as f:
            cases = json.load(f)
        data['gap_cases'] = cases if isinstance(cases, list) else []
        data['case_count'] = len(data['gap_cases'])
    
    mood_path = os.path.join(PROJECT_DIR, 'data', 'musk', 'social-mood-report.json')
    if os.path.exists(mood_path):
        with open(mood_path, 'r', encoding='utf-8') as f:
            data['social_mood'] = json.load(f)
    
    method_path = os.path.join(PROJECT_DIR, 'data', 'musk', 'methodology-engine.json')
    if os.path.exists(method_path):
        with open(method_path, 'r', encoding='utf-8') as f:
            data['methodology'] = json.load(f)
    
    return data

# ============================================================
# 推演函数（封装 musk_push.py 调用）
# ============================================================
def do_inference(user_input):
    """执行推演"""
    from musk_push import call_hy3, ask_hy3_for_law, query_laws_db, self_evaluate
    
    data = load_data()
    gap_cases = data['gap_cases']
    
    # 从案例库提取上下文
    case_summary = ""
    if gap_cases:
        sample = gap_cases[:10]
        case_summary = "\n".join([
            f"- {c.get('title', '')}: {c.get('gap_description', '')[:60]}"
            for c in sample
        ])
    
    system_msg = """你是马斯克系统，专门分析市场缺口和套利空间。

核心原则：
- 邪修不是做传统业务——流水业务满足企业缺业绩，FDI指标满足政府缺指标
- 找系统性缺口（体制的/市场的/人性的/规则的）
- 找谁有需求填这个缺口（具体到角色和KPI）
- 在规则边缘找操作路径
- 禁止模板化输出，每次推演都要独特

必须回答两个问题：
1. 这个信息暴露了什么系统性缺口？
2. 谁有需求填这个缺口？

如果涉及资源短缺，推演必须包含"短缺传导路径"。
如果操作路径有坑，必须给出"具体止损方式"。
输出格式：Markdown，结构化，800-1500字。"""

    user_msg = f"""基于以下市场信息，识别最有操作空间的缺口模式，生成推演分析。

市场信息：
{user_input[:3000]}

参考案例库：
{case_summary}

请生成推演分析。"""

    inference_text = call_hy3(system_msg, user_msg, max_tokens=2500, temperature=0.4)
    if not inference_text:
        return None, None, None
    
    # 法律评估
    law_refs = ask_hy3_for_law(inference_text)
    matched_laws = query_laws_db(law_refs)
    
    # 自评估
    evaluation = self_evaluate(inference_text, gap_cases)
    
    return inference_text, matched_laws, evaluation


# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.markdown("## 🔮 马斯克系统")
    st.markdown("---")
    
    data = load_data()
    
    st.metric("缺口案例库", f"{data['case_count']} 个案例")
    
    if data['social_mood']:
        mood = data['social_mood']
        st.markdown("### 社会心态")
        if 'mood_distribution' in mood:
            top_mood = sorted(mood['mood_distribution'].items(), key=lambda x: x[1], reverse=True)
            for name, pct in top_mood[:3]:
                st.write(f"{name}: {pct}%")
    
    if data['methodology']:
        patterns = data['methodology'].get('gap_patterns', [])
        st.markdown(f"### 缺口模式")
        st.write(f"已识别 {len(patterns)} 个模式")
    
    st.markdown("---")
    st.caption("马斯克 v2 · 独立推演引擎")
    st.caption(f"数据路径: `data/musk/`")

# ============================================================
# 主页面
# ============================================================
st.markdown('<p class="musk-title">🔮 马斯克 · 市场缺口推演</p>', unsafe_allow_html=True)
st.markdown('<p class="musk-subtitle">输入任意市场信息，识别系统性缺口，在规则边缘寻找操作路径</p>', unsafe_allow_html=True)

# 输入区
user_input = st.text_area(
    "📝 输入市场信息 / 新闻 / 观察",
    placeholder="粘贴任意市场信息...\n\n例如：\n- 某公司宣布H100算力集群上线，首批3000张卡\n- 日元兑人民币跌破4.6，创20年新低\n- 某省发布数据出境安全评估新规\n- 跨境电商9610出口退税政策调整",
    height=180
)

col1, col2, col3 = st.columns([2, 1, 2])
with col2:
    run_btn = st.button("🔮 马斯克推演", type="primary", use_container_width=True)

if run_btn and user_input.strip():
    with st.spinner("马斯克正在分析缺口..."):
        inference_text, matched_laws, evaluation = do_inference(user_input.strip())
    
    if inference_text:
        st.markdown("---")
        
        # 推演结果
        st.markdown("### 📊 推演结果")
        st.markdown(f'<div class="gap-box">{inference_text}</div>', unsafe_allow_html=True)
        
        # 法律评估
        if matched_laws:
            st.markdown("### ⚖️ 合规评估")
            for law in matched_laws:
                risk_class = "risk-green" if "🟢" in law.get('risk', '') else ("risk-yellow" if "🟡" in law.get('risk', '') else "risk-red")
                st.markdown(f"""
                <div class="law-box">
                <strong>{law.get('law_name', '')} {law.get('article_number', '')}</strong><br>
                风险等级：<span class="{risk_class}">{law.get('risk', '🟢合规')}</span><br>
                触及原因：{law.get('reason', '')}<br>
                合规变通：{law.get('compliance_path', '待评估')}
                </div>
                """, unsafe_allow_html=True)
        
        # 自评估
        if evaluation:
            total = evaluation.get('total_score', 0)
            grade = evaluation.get('grade', '?')
            grade_color = "#27ae60" if grade == 'A' else "#f39c12" if grade == 'B' else "#e67e22" if grade == 'C' else "#e74c3c"
            st.markdown(f"""
            <div class="eval-box">
            <strong>📊 推演质量自评估：<span style="color:{grade_color}">{total}/100（{grade}级）</span></strong>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.error("推演失败 — API 调用异常，请检查 HUNYUAN_API_KEY 环境变量")

elif run_btn and not user_input.strip():
    st.warning("请输入市场信息后再推演")

# 底部
st.markdown("---")
st.caption("马斯克系统 v2 · 独立推演引擎 | 不构成投资建议 | 仅供研究参考")
