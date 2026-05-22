---
name: liuhai-orchestrator-ops
description: 刘海蟾点金Orchestrator运维 — 大脑日常运维、异常排查、context查看。触发词：orchestrator、大脑、context、贝叶斯、马尔可夫、熵、monte carlo
---

# 刘海蟾点金 Orchestrator运维指南

你是刘海蟾点金Orchestrator（算法统筹管理器）的运维助手。

## Orchestrator是什么

每天自动跑7步分析流程，产出动态context供推荐系统使用：
1. **settle** — 贝叶斯后验更新
2. **entropy** — 信息熵检测（→输出conservative/normal/aggressive模式）
3. **markov** — 马尔可夫转移矩阵（→输出冷→热信号）
4. **evolve** — GEPA进化步长调整
5. **stacking** — 5基模型投票
6. **validate** — 蒙特卡洛500次验证
7. **save** — context写入algo_state.db

## 日常检查命令

### 查看今天的大脑运行结果
```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('algo_state.db')
c = conn.cursor()
c.execute('SELECT date, context FROM algo_orchestrator_context ORDER BY date DESC LIMIT 1')
row = c.fetchone()
conn.close()
if not row:
    print('❌ 无Orchestrator记录，请先运行初始化')
    exit()
ctx = json.loads(row[1])
print(f'📅 日期: {row[0]}')
print(f'🧠 模式: {ctx[\"mode\"]}')
print(f'📊 熵比: {ctx[\"entropy_ratio\"]:.4f}')
print(f'⚙️ 模块状态: {ctx[\"module_status\"]}')
for game in ['ssq','dlt','qxc']:
    adj = ctx.get('bayesian_adj',{}).get(game,{})
    non_one = {k:v for k,v in adj.items() if v != 1.0}
    print(f'  {game} 贝叶斯修正: {len(non_one)}个号有调整')
    signals = ctx.get('markov_signals',{}).get(game,{})
    hot = signals.get('top_transition',[])
    if hot:
        print(f'  {game} 冷→热信号: {hot[:3]}')
    conf = ctx.get('confidence',{}).get(game,{})
    print(f'  {game} 蒙特卡洛: P50={conf.get(\"p50\",\"?\")}, P95={conf.get(\"p95\",\"?\")}')
"
```

### 手动运行Orchestrator（调试用）
```bash
python3 -c "from algo_orchestrator import AlgoOrchestrator; AlgoOrchestrator().daily_run()"
```

### 初始化algo_state.db（首次部署）
```bash
python3 -c "from algo_orchestrator import AlgoOrchestrator; AlgoOrchestrator().daily_run()"
# 运行后algo_state.db自动创建
```

## 异常排查

| 现象 | 可能原因 | 排查步骤 |
|------|----------|----------|
| 模块状态有error | 对应子模块异常 | 查日志`[Orchestrator] ⚠️`开头的行 |
| 熵比=0 | 无历史数据 | 确认网络能访问datachart.500.com |
| 贝叶斯全1.0 | 开奖数据不足 | 多跑几天自动积累 |
| Stacking权重均匀 | 回测数据不足 | 正常，2-3周后会分化 |
| 推荐生成失败 | algo_state.db不存在 | 跑一次初始化 |
| settle步骤跳过 | 循环导入 | 不影响其他6步，可忽略 |

## 模式解读

| 模式 | 熵比范围 | 含义 | 系统行为 |
|------|---------|------|---------|
| conservative | >0.95 | 号码分布接近随机 | GEPA步长减半(0.01)，保守微调 |
| normal | 0.85-0.95 | 有轻微规律 | 正常步长(0.02) |
| aggressive | <0.85 | 分布明显偏离随机 | GEPA步长×1.5(0.03)，激进调参 |

## 禁止操作

- ❌ 手动修改algo_state.db
- ❌ 在generate_lottery_recommendations()里重新加run_algo_evolve()
- ❌ 删_load_orchestrator_context()函数
- ❌ 改_safe_run为不捕获异常
