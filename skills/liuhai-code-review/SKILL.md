---
name: liuhai-code-review
description: 刘海蟾点金代码审查 — 针对彩票系统的专项审查规则。触发词：代码审查、code review、审查、检查代码、review
---

# 刘海蟾点金代码审查规则

你是刘海蟾点金项目的代码审查员。审查时必须检查以下项目特定规则，而非通用规则。

## 彩种数据规范（最常出错）

| 彩种 | 前区/红球 | 后区/蓝球 | 返回格式 | analysis键名 |
|------|----------|----------|---------|-------------|
| SSQ(双色球) | 红6个, 1-33 | 蓝1个, 1-16 | `{'reds','blue'}` | `blue_weights`, `blue_freq`, `blue_miss` |
| DLT(大乐透) | 前5个, 1-35 | 后2个, 1-12 | `{'front','back'}` | `back_weights`, `back_freq`, `back_miss` |
| QXC(七星彩) | 7位, 前6位0-9, 第7位0-14 | — | `{'digits'}` | `positions` |

**最常见的BUG**：DLT代码里用了SSQ的键名(`blue_weights`/`blue_freq`)或格式(`{'reds','blue'}`)。

## 审查检查清单

### A. 命名一致性（🔴 高频出错）
- [ ] DLT相关代码用`back_`前缀，不用`blue_`
- [ ] SSQ相关代码用`blue_`前缀，不用`back_`
- [ ] QXC相关代码用`positions`/`digits`

### B. 数据格式（🔴 高频出错）
- [ ] DLT推荐返回`{'front', 'back', 'strategy'}`
- [ ] SSQ推荐返回`{'reds', 'blue', 'strategy'}`
- [ ] QXC推荐返回`{'digits', 'strategy'}`
- [ ] DLT前区5个号（不是6个！SSQ红球才6个）
- [ ] DLT后区2个号，范围1-12（不是1-16！那是SSQ蓝球范围）

### C. 依赖完整性（🔴 阿策常犯）
- [ ] 删除函数前，grep确认无调用方
- [ ] 新增调用时，确认目标函数/方法存在
- [ ] WeightedAnalyzer的方法：`analyze_ssq/dlt/qxc`, `generate_recs_ssq/dlt/qxc`——确认都存在

### D. 路径规范
- [ ] 不硬编码`/root/asuan-scheduler/`，用`os.path.dirname(os.path.abspath(__file__))`
- [ ] 不硬编码API key，从环境变量或配置文件读取

### E. Git规范
- [ ] 不push `.bak`/`.backup`/`fix_`/`cold_`/`ssq_*`/`start.sh`等临时文件
- [ ] commit信息清晰说明改了什么
- [ ] 服务器端改完后必须push到GitHub

### F. Orchestrator相关
- [ ] 不删`_load_orchestrator_context()`函数
- [ ] 不在`generate_lottery_recommendations()`里重新加`run_algo_evolve()`
- [ ] 不改`_safe_run`为不捕获异常

## 审查输出格式

```
📋 代码审查结果

🔴 阻断问题（必须修复）:
  1. [命名] 第XXX行: DLT代码使用了blue_weights，应为back_weights
  2. [格式] 第XXX行: DLT推荐返回{'reds','blue'}，应为{'front','back'}

🟡 建议改进:
  1. [路径] 第XXX行: 硬编码路径，建议改为os.path.join()

✅ 通过项: A(3/4), B(5/5), C(2/2), D(1/1), E(2/2), F(3/3)

结论: ❌ 阻断，修复后重新审查
```
