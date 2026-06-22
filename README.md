# 阿算智能引擎

JinZhu 驱动的彩票智能分析系统，为刘老板提供数据驱动的彩票推荐与风险预警。

## 项目结构

```
asuan-scheduler/
├── jin_zhu.py                 # JinZhu 核心引擎
├── generate_full_daily.py    # 日报生成主程序
├── daily_report_guard.py     # 日报质量守护
├── data_fetcher.py           # 数据采集模块
├── lottery_analyzer.py       # 彩票分析器
├── backtest/                  # 回测框架
│   └── runner.py             # 回测执行脚本
├── daily-report/              # 日报管道（优化版）
│   ├── generator.py         # 日报生成器（6板块）
│   └── guard.py            # 质量守护
├── data-pipeline/            # 数据采集管道
│   ├── raw/               # 原始数据（JSON）
│   ├── processed/         # 清洗后数据
│   └── scripts/           # 采集脚本
├── explainer/                # 解释模块
│   └── generate_explanation.py
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

### 2. 运行回测
```bash
cd /root/asuan-scheduler
python3 backtest/runner.py
# 结果保存至 backtest/results/
```

### 3. 启动 Dashboard
```bash
cd /root/asuan-scheduler
streamlit run dashboard/app.py --server.port 8501
# 浏览器访问 http://localhost:8501
```

### 4. 模型评测
```bash
cd /root/asuan-scheduler
python3 model-eval/benchmark.py --models hy3-preview
```

## 彩种支持

| 彩种 | 代码 | 数据源 | 状态 |
|------|------|---------|------|
| 双色球 | SSQ | datachart.500.com | ✅ 1965期 |
| 大乐透 | DLT | datachart.500.com | ✅ 2886期 |
| 七星彩 | QXC | kaijiang.500.com | ⏳ 21期（受限） |
| 台湾威力彩 | PLN | gdf99.com | ⏳ AI生成 |
| 台湾大乐透 | LTN | gdf99.com | ⏳ 600期 |

## 核心功能

1. **JinZhu 推荐引擎** - 多策略融合推荐
2. **6板块日报** - 资讯/预警/逆潮/传导/避坑/邪修
3. **回测框架** - 历史命中率验证
4. **模型评测** - 多模型对比
5. **实时 Dashboard** - Streamlit 可视化面板

## 依赖安装

```bash
pip install crawl4ai streamlit pandas pyarrow altair requests
```

## 分支说明

- `main` - 主分支（稳定版）
- `feat/asuan-engine` - 阿算智能引擎开发分支（当前）

## 版本历史

- **V18** - 邪修操作卡升级
- **V33** - 当前版本（2026-06-22 阶段四交付）

---

**保佑：** 刘海蟾祖師 + 赵公明祖師
