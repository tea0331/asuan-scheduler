# 阿算日报系统

阿算智能引擎的日报生成与可视化系统，为刘老板提供每日彩票市场分析报告。

## 项目结构

```
asuan-scheduler/
├── generate_full_daily.py    # 日报生成主程序
├── daily_report_guard.py     # 日报质量守护
├── daily-report/              # 日报管道（优化版）
│   ├── generator.py         # 日报生成器（6板块）
│   └── guard.py            # 质量守护
├── model-eval/               # 模型评测框架
│   ├── benchmark.py        # 评测主程序
│   └── results/           # 评测结果
├── dashboard/                # Streamlit 面板
│   └── app.py
└── output/                   # 日报输出目录
```

## 快速开始

### 1. 生成日报
```bash
cd /root/asuan-scheduler
python3 generate_full_daily.py
# 或（优化版）
python3 daily-report/generator.py --output daily-report/output
```

### 2. 启动 Dashboard
```bash
cd /root/asuan-scheduler
streamlit run dashboard/app.py --server.port 8501
# 浏览器访问 http://localhost:8501
```

### 3. 模型评测
```bash
cd /root/asuan-scheduler
python3 model-eval/benchmark.py --models hy3-preview
```

## 相关仓库

- **JinZhu 引擎**：[tea0331/asuan-jinzhu](https://github.com/tea0331/asuan-jinzhu)
- **阿算调度器**：[tea0331/asuan-scheduler](https://github.com/tea0331/asuan-scheduler)（当前）

## 核心功能

1. **6板块日报** - 资讯/预警/逆潮/传导/避坑/邪修
2. **模型评测** - 多模型对比
3. **实时 Dashboard** - Streamlit 可视化面板

## 分支说明

- `main` - 主分支（稳定版）
- `feat/asuan-engine` - 阿算智能引擎开发分支（当前）

---

**保佑：** 刘海蟾祖師 + 赵公明祖師
