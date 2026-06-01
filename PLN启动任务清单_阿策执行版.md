# PLN/LTN 修复框架文档
**生成时间**：2026-05-31 23:22  
**审查方**：阿算  
**执行方**：阿策  
**紧急度**：P0级（台湾彩种目前是空壳）  
**deadline压力**：2026-06-01 token到期，优先算法对齐

---

## 🔴 P0级致命缺陷清单

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| **P0-1** | `_gen_pln`/`_gen_ltn` **重复定义**两版 | 阿策直接叠代码没删旧版 | Python后者覆盖前者，行为不可预测 |
| **P0-2** | 生成算法是**随机换号**不是JinZhu算法 | `base.copy() → 随机改1-3位` | 完全绕过freq/miss/trend/zone四维加权，等于掷骰子 |
| **P0-3** | `_analyze()`不支持PLN/LTN | `analyze_map`里没有对应项 | 调用直接`KeyError`，根本没接入分析 |
| **P0-4** | `data/`目录和CSV文件**根本不存在** | 未初始化数据目录和历史数据 | 所有CSV读取必失败，永远走mock=纯随机 |

**结论**：台湾彩种目前是空壳——看起来接入了JinZhu，实际算法没接入、数据没接入、闭环没接入。

---

## ✅ 5阶段修复框架

### 阶段1：清淤（1天，必须优先完成）
**目标**：清理技术债，建立基础环境

**任务清单**：
1. **删重复方法**
   - 检查`generate_taiwan.py`，删除重复的`_gen_pln`/`_gen_ltn`定义
   - 只保留最新版，确保函数签名正确
   - ⚠️ 删完后跑`python3 -c "from generate_taiwan import _gen_pln, _gen_ltn"`验证

2. **建data目录+历史数据**
   ```bash
   mkdir -p /root/.openclaw/workspace/data
   # 下载或手动整理PLN/LTN历史数据
   # 格式：CSV，列=开奖号码（PLN:6位，LTN:5前+2后）
   # 最少需要30期历史数据才能跑加权算法
   ```

3. **修复CSV读取逻辑**
   - 检查`generate_taiwan.py`里所有`open('data/xxx.csv')`调用
   - 改为先检查文件是否存在，不存在则报错（而不是静默fallback到随机）

**交付物**：
- [ ] `generate_taiwan.py`只有一套`_gen_pln`/`_gen_ltn`
- [ ] `data/`目录存在，含`pln_history.csv`+`ltn_history.csv`
- [ ] CSV读取有存在性检查，不会静默失败

---

### 阶段2：算法对齐（2-3天，核心价值）
**目标**：台湾彩种真正接入JinZhu四维加权算法

**任务清单**：
1. **`WeightedAnalyzer`加PLN/LTN支持**
   - 在`lottery_analyzer.py`（或`games/`模块）里加：
     ```python
     def analyze_pln(self, history):
         # 威力彩：6球(1-38) + 特别号(1-8)
         # 四维加权：freq频率/miss遗漏/trend趋势/zone区间
         ...
     
     def analyze_ltn(self, history):
         # 大乐透：5前区(1-47) + 2后区(1-38)
         ...
     ```

2. **重写`_gen_pln`/`_gen_ltn`**
   - 根因：现在是`base.copy() → 随机改1-3位`
   - 修复：改为调用`analyze_pln()`/`analyze_ltn()`获取加权结果
   - 生成5注：P0×2 + P1 + P2 + P3（和双色球/大乐透对齐）

3. **更新`analyze_map`**
   - 在`generate_taiwan.py`或调度器里：
     ```python
     analyze_map = {
         'ssq': analyze_ssq,
         'dlt': analyze_dlt,
         'qxc': analyze_qxc,
         'pln': analyze_pln,  # ← 加这个
         'ltn': analyze_ltn,  # ← 加这个
     }
     ```

**交付物**：
- [ ] `analyze_pln()`/`analyze_ltn()`函数存在且实现四维加权
- [ ] `_gen_pln`/`_gen_ltn`调用分析函数，不再随机换号
- [ ] 生成5注/彩种，格式和双色球对齐

---

### 阶段3：闭环打通（1-2天）
**目标**：PLN/LTN加入完整生命周期（推荐→结算→进化）

**任务清单**：
1. **`daily_run()`加PLN/LTN**
   ```python
   # 在daily_run()里加：
   for game in ['ssq', 'dlt', 'qxc', 'pln', 'ltn']:  # ← 加后面两个
       ...
   ```

2. **`settle()`加PLN/LTN**
   - 确保开奖结果能正确写入`settle_history.json`
   - 确认`pln`/`ltn`的号码格式解析正确

3. **`evolve()`加PLN/LTN**
   - 权重进化要包含台湾彩种
   - 确保`weight-config.json`里有`pln`/`ltn`的权重配置

4. **虚拟用户生成加PLN/LTN**
   - 如果用户配置了台湾彩种，也能生成对应的虚拟用户推荐

**交付物**：
- [ ] `daily_run()`包含5彩种
- [ ] `settle()`正确结算PLN/LTN
- [ ] `evolve()`包含PLN/LTN权重进化
- [ ] 虚拟用户支持台湾彩种

---

### 阶段4：展示+数据源（1-2天）
**目标**：日报正确展示，数据源从CSV升级到在线抓取

**任务清单**：
1. **日报展示区**
   - 确保`generate_full_daily.py`能正确渲染PLN/LTN推荐
   - 格式：5注/彩种，含分析说明

2. **`games/pln.py` + `games/ltn.py`**
   - 参考`games/ssq.py`等，建立独立模块
   - 包含：`fetch_pln_history()`/`fetch_ltn_history()` + 分析 + 生成

3. **`data_fetcher`在线抓取**（可选，deadline后做）
   - 找台湾彩票官网API或爬取页面
   - 替代手动CSV更新

**交付物**：
- [ ] 日报包含PLN/LTN板块，格式正确
- [ ] `games/pln.py` + `games/ltn.py`存在且可独立运行
- [ ] （可选）在线数据源接入

---

### 阶段5：端到端验证（1天）
**目标**：全流程5彩种跑通，无遗留bug

**验证清单**：
```bash
# 1. 生成测试
python3 generate_taiwan.py
# 预期：输出PLN 5注 + LTN 5注，不是随机乱码

# 2. 全流程测试
python3 lottery_analyzer.py  # 或对应入口
# 预期：5彩种都走完 analyze → generate → settle → evolve

# 3. 日报集成测试
python3 generate_full_daily.py
# 预期：日报包含5彩种推荐，且不是随机生成的

# 4. 回测验证
# 检查lottery-predictions.json里有pln/ltn记录
# 跑回测，确认能对比开奖号
```

**交付物**：
- [ ] 5彩种全流程跑通
- [ ] 生成结果符合JinZhu算法（非随机）
- [ ] 日报展示正确
- [ ] 回测功能正常

---

## ⚠️ 风险提示

1. **6月1日token到期**：
   - 如果06-01前完不成阶段2（算法对齐），台湾彩种将**永久失效**
   - 建议：阶段1和2优先，阶段3~5可在token到期前用备用方案（本地调用）

2. **数据质量风险**：
   - 如果CSV历史数据不足30期，加权算法效果会很差
   - 建议：至少收集50期历史数据

3. **算法对齐难度**：
   - PLN（6+1，范围1-38+1-8）和LTN（5+2，范围1-47+1-38）的规则和大陆彩种不同
   - 需要仔细实现`analyze_pln()`/`analyze_ltn()`，不能简单复制SSQ/DLT

---

## 📋 执行跟踪

| 阶段 | 状态 | 开始日期 | 完成日期 | 备注 |
|------|------|----------|----------|------|
| 1. 清淤 | ✅ 已完成 | 2026-05-31 | 2026-05-31 | 删重复函数/建data目录/CSV基础 |
| 2. 算法对齐 | ✅ 已完成 | 2026-05-31 | 2026-05-31 | analyze_pln/ltn已完成/games模块完成 |
| 3. 闭环打通 | 🔄 进行中 | 2026-06-01 | - | daily_run/settle/evolve已加pln/ltn |
| 4. 展示+数据源 | ⏳ 待开始 | - | - | 可延后 |
| 5. 端到端验证 | ⏳ 待开始 | - | - | 最后一道门 |

---

**阿策承诺**：
1. ✅ 阶段1（清淤）06-01当天完成，不留技术债
2. ✅ 阶段2（算法对齐）06-01前完成核心代码，确保台湾彩种不是随机乱码
3. ✅ 每次改动增量测试，不一次改5个地方
4. ✅ 删代码前先检查依赖，不出现KeyError/ImportError
5. ✅ 交付前跑`python3 generate_taiwan.py`验证，贴输出证据

**刘老板监督点**：
- 06-01 检查`generate_taiwan.py`输出，确认不是随机换号
- 06-01 检查`data/`目录，确认CSV文件存在且有真实历史数据
- 06-01 token到期前，确认台湾彩种能正常调用JinZhu算法
