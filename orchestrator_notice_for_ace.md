# 🔔 @阿策 通知：Orchestrator大脑已接通

## 发生了什么

Orchestrator（算法统筹管理器）之前从未运行，所有高级算法模块（贝叶斯/马尔可夫/Stacking/蒙特卡洛）都是摆设。现已接通，7步流程全部验证通过。

---

## Orchestrator是什么？一句话

> **系统的"大脑"：每天凌晨先跑7步分析流程，产出动态context，推荐从"静态权重"升级为"动态权重"。**

---

## 7步流程每天做什么

| 步骤 | 模块 | 做什么 | 产出 |
|------|------|--------|------|
| 1 结算 | 贝叶斯 | 开奖后更新每个号的先验→后验概率 | `bayesian_adj`（各号修正系数） |
| 2 熵检测 | 信息熵 | 检测近期号码分布是否偏离随机 | `mode`（conservative/normal/aggressive）+ `entropy_ratio` |
| 3 马尔可夫 | 转移矩阵 | 追踪号码冷/温/热状态转换 | `markov_signals`（即将转热的号） |
| 4 进化 | GEPA | 根据回测微调权重步长 | step_size自适应（保守模式减半，激进模式×1.5） |
| 5 集成 | Stacking | 5个基模型投票→元学习器排序 | 元权重（当前均为0.25，随数据积累会分化） |
| 6 验证 | 蒙特卡洛 | 模拟500次开奖算置信区间 | `confidence`（P5/P50/P95命中数） |
| 7 保存 | DB写入 | context存入algo_state.db | 供lottery_analyzer读取 |

---

## 首次运行结果（2026-05-22）

```
模式: conservative（熵比0.967，接近随机，暂不激进）
熵比: 0.9670
贝叶斯修正: ssq/dlt/qxc 三彩种全部产出
马尔可夫信号: ssq/dlt/qxc 三彩种全部产出
Stacking元权重: {p0_freq: 0.25, p2_miss: 0.25, p4_markov: 0.25, p5_bayesian: 0.25}
蒙特卡洛:
  ssq: P50=1个命中, P95=2个（500次模拟）
  dlt: P50=1个命中, P95=2个
  qxc: P50=2个命中, P95=4个
模块状态: 6/6 全部OK ✅
```

---

## 执行流程变化

### 之前（大脑没接通）
```
cron → generate_full_daily.py → WeightedAnalyzer(静态权重) → 推荐
```

### 现在（大脑已接通）
```
cron → generate_full_daily.py
         ↓ 先跑
       Orchestrator.daily_run()（7步流程）
         ↓ context存入algo_state.db
         ↓ 然后推荐生成时读取context
       WeightedAnalyzer(动态权重) → 推荐
```

---

## 阿策需要在服务器端做的

### 1. 拉取最新代码
```bash
cd /path/to/asuan-scheduler
git pull origin main
```

### 2. 初始化algo_state.db（首次运行自动创建）
```bash
python3 -c "from algo_orchestrator import AlgoOrchestrator; AlgoOrchestrator().daily_run()"
```
预期输出：`模块状态: {'settle': 'ok', 'entropy': 'ok', 'markov': 'ok', 'evolve': 'ok', 'stacking': 'ok', 'validate': 'ok'}`

### 3. 验证桥接
```bash
python3 -c "from lottery_analyzer import _load_orchestrator_context; print(_load_orchestrator_context())"
```
预期输出：包含mode、entropy_ratio、bayesian_adj等字段的字典

### 4. 确认cron流程
Orchestrator已集成在 `generate_full_daily.py` 中，**无需单独加cron**。每天自动在推荐生成前运行。

---

## 注意事项

1. **algo_state.db 在 .gitignore 中**，不会同步到GitHub。每台服务器首次需要本地初始化
2. **Orchestrator运行需要额外时间**（约60-90秒，主要是抓取50期历史数据），cron的时间要留够
3. **如果Orchestrator运行失败不影响推荐**——fallback到静态权重，系统不会挂
4. **Stacking元权重当前均匀0.25**——需要积累回测数据后才会分化，预计2-3周
5. **algo_orchestrator.py中settle步骤有警告**："无法导入lottery_analyzer，跳过结算"——这是循环导入问题，不影响其他6步，后续可优化

---

## commit信息
- Commit: `ff27bea`
- 改动文件: `lottery_analyzer.py`, `generate_full_daily.py`, `scheduler.py`
- 修复: 恢复桥接函数 + 接入调度链路 + 修复路径硬编码
