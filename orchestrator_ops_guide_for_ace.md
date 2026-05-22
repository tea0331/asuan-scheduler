# 🧠 刘海蟾点金 Orchestrator大脑 — 阿策运维手册

---

## 一、大脑是什么

Orchestrator是刘海蟾点金的**算法统筹管理器**，每天自动跑7步分析，产出动态context。

**类比**：如果WeightedAnalyzer是"手脚"（按公式选号），Orchestrator就是"大脑"（每天分析局势、调整策略、把手脚调得更准）。

**没大脑时**：用14天前手动设的静态权重选号，不管昨天出了什么号、市场有没有异常。
**有大脑后**：每天自动做贝叶斯修正+熵检测+马尔可夫预测+进化调参+Stacking投票+蒙特卡洛验证，推荐从"固定公式"变成"动态策略"。

---

## 二、每天自动发生什么

```
07:30 cron触发
  ↓
generate_full_daily.py 启动
  ↓
① Orchestrator.daily_run() 自动运行（约60-90秒）
   Step1: 结算昨日 + 贝叶斯更新（出过的号概率微降，没出的微升）
   Step2: 熵检测（分布是否偏离随机 → 输出conservative/normal/aggressive模式）
   Step3: 马尔可夫（追踪号码冷→热转换 → 输出"即将回补"的号）
   Step4: GEPA进化（根据模式自动调整进化步长）
   Step5: Stacking（5个基模型投票排序）
   Step6: 蒙特卡洛（500次模拟 → 输出命中数置信区间）
   Step7: 保存context到algo_state.db
  ↓
② lottery_analyzer 读取context
   - _load_orchestrator_context() 从DB读取最新context
   - 贝叶斯修正系数 → 融入WeightedAnalyzer._calc_weights()
   - 熵比/模式 → 告警系统判断
   - 马尔可夫信号 → 告警系统提示冷→热号
   - 蒙特卡洛置信区间 → 日报参考
  ↓
③ 生成推荐（用的是大脑修正后的动态权重）
  ↓
④ 发送邮件
```

**阿策不需要做任何事，全自动。**

---

## 三、context里有什么（你每天能看到的数据）

### 模式（mode）
| 值 | 含义 | 对系统的影响 |
|----|------|------------|
| `conservative` | 近期号码分布接近随机 | GEPA进化步长减半（0.01），保守微调 |
| `normal` | 有轻微规律 | 正常步长（0.02） |
| `aggressive` | 分布明显偏离随机 | GEPA步长×1.5（0.03），激进调参 |

### 熵比（entropy_ratio）
- 接近1.0 = 越随机，越难预测
- 低于0.85 = 有规律可循，系统进入aggressive
- 当前值约0.93-0.97 → normal/conservative

### 贝叶斯修正系数（bayesian_adj）
每个号码一个系数（0.8-1.2），乘在权重上：
- `>1.0`：该号近期未出，概率应上调（遗漏回补信号）
- `<1.0`：该号近期频繁出，概率应下调
- `=1.0`：无修正

### 马尔可夫信号（markov_signals）
三态（cold/warm/hot）转移概率：
- `transition_prob > 0.5`：cold→hot（即将从冷转热，**这是最有价值的信号**）
- 日报告警会自动提示这些号

### 蒙特卡洛置信区间（confidence）
模拟500次开奖的命中分布：
- `P50=1`：50%概率至少命中1个号
- `P95=3`：5%概率命中3个号
- 七星彩P50=2-3，均值2.5（因为7位中每位的命中率天然高）

### Stacking元权重
当前均匀0.25（4个基模型等权），积累数据后会分化。

---

## 四、你日常需要关注的

### 每天检查（自动，但你要知道怎么看）

**方式1：看日报邮件**
- 如果有告警"冷→热信号"→ 马尔可夫发现了即将回补的号
- 如果有告警"模式切换"→ 熵检测判断局势变了

**方式2：看algo_state.db**
```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('algo_state.db')
c = conn.cursor()
c.execute('SELECT date, context FROM algo_orchestrator_context ORDER BY date DESC LIMIT 1')
row = c.fetchone()
conn.close()
ctx = json.loads(row[1])
print(f'日期: {row[0]}')
print(f'模式: {ctx[\"mode\"]}')
print(f'熵比: {ctx[\"entropy_ratio\"]:.4f}')
print(f'模块状态: {ctx[\"module_status\"]}')
for game in ['ssq','dlt','qxc']:
    conf = ctx.get('confidence',{}).get(game,{})
    print(f'  {game}: P50={conf.get(\"p50\",\"?\")}, P95={conf.get(\"p95\",\"?\")}')
"
```

### 异常情况处理

| 现象 | 原因 | 处理 |
|------|------|------|
| 日报推荐正常但Orchestrator未运行 | algo_state.db不存在 | 跑一次 `python3 -c "from algo_orchestrator import AlgoOrchestrator; AlgoOrchestrator().daily_run()"` |
| 模块状态有`error` | 对应子模块异常 | 不影响推荐（fallback到静态权重），但需排查。查日志里`[Orchestrator] ⚠️`开头的行 |
| 熵比突然降低（<0.80） | 近期号码分布异常 | 系统自动进aggressive模式，不需要手动干预 |
| 贝叶斯修正全为1.0 | 没有历史开奖数据 | 多跑几天就好，Orchestrator每天结算会积累 |

---

## 五、绝对不能做的事

| ❌ 禁止 | 原因 |
|---------|------|
| 手动修改algo_state.db | 会破坏Orchestrator的连续性 |
| 在generate_lottery_recommendations()里重新加run_algo_evolve() | 双进化路径会互相覆盖权重（v3.0已修复的问题） |
| 删_load_orchestrator_context()函数 | 推荐会退回静态权重，大脑白接 |
| 改Orchestrator的_safe_run为不捕获异常 | 一个模块崩溃会连锁搞垮整个流程 |

---

## 六、context如何影响推荐的——技术细节

```
Orchestrator.daily_run()
  ↓ 写入DB
_load_orchestrator_context()  ← lottery_analyzer调用
  ↓ 返回evolved_config
  ├── WeightedAnalyzer._calc_weights() 中：
  │   └── bayesian_adj → weights[n] *= adj  ← 直接修正每个号的权重
  ├── detect_lottery_alerts() 中：
  │   ├── mode → 告警"模式切换"
  │   ├── entropy_ratio → 告警"分布异常"/"分布均匀"
  │   └── markov_signals → 告警"冷→热信号"
  └── format_lottery_section() 中：
      └── evolved_config传入 → 控制回测和告警输出
```

**关键链路**：Orchestrator → DB → _load_orchestrator_context() → WeightedAnalyzer._calc_weights() → 推荐号码

---

## 七、首次部署清单

```bash
cd /path/to/asuan-scheduler
git pull origin main

# 1. 初始化algo_state.db
python3 -c "from algo_orchestrator import AlgoOrchestrator; AlgoOrchestrator().daily_run()"

# 2. 验证桥接
python3 -c "from lottery_analyzer import _load_orchestrator_context; ctx=_load_orchestrator_context(); print(f'模式={ctx[\"mode\"]}, 熵比={ctx[\"entropy_ratio\"]:.4f}') if ctx else print('❌失败')"

# 3. 验证推荐
python3 generate_full_daily.py 2>&1 | tail -20

# 4. 确认cron
# Orchestrator已集成在generate_full_daily.py中，无需额外配置
# 每天自动在推荐生成前运行
```

---

## 八、预期演进时间线

| 时间 | 预期变化 |
|------|----------|
| 第1-3天 | 贝叶斯修正系数开始分化（从全1.0到0.8-1.2范围） |
| 第1-2周 | Stacking元权重从均匀0.25开始分化 |
| 第2-4周 | GEPA进化积累足够回测数据，权重自动调优 |
| 1个月+ | 模式切换（conservative↔aggressive）开始响应市场变化 |

**不需要人工干预，让系统自己跑。**
