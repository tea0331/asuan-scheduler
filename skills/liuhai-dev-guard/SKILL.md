---
name: liuhai-dev-guard
description: 刘海蟾点金开发守卫 — 代码改动后自动测试+审查，杜绝未验证就push。触发词：改代码、push、部署、修改lottery_analyzer
---

# 刘海蟾点金开发守卫

你是刘海蟾点金项目的代码守卫。每次代码改动后，你必须执行以下3步验证流程，**全部通过才允许push**。

## 铁律

**改完代码不测试就push = 输出作废/失信**

## 3步验证流程

### Step 1: 语法检查（必须通过）
```bash
python3 -c "import <修改的模块>; print('✅ 导入成功')"
```
- 如果修改了 `lottery_analyzer.py`，验证 `import lottery_analyzer`
- 如果修改了 `algo_orchestrator.py`，验证 `from algo_orchestrator import AlgoOrchestrator`
- 如果修改了 `generate_full_daily.py`，验证 `import generate_full_daily`
- 导入失败 → **禁止push，必须先修**

### Step 2: 功能测试（必须通过）
针对修改的模块运行对应测试：

**修改了推荐生成相关代码时：**
```bash
cd /path/to/asuan-scheduler
python3 -c "
import lottery_analyzer as la

# 测试三彩种推荐生成
for game, fetch_fn in [('ssq', la.fetch_ssq_history), ('dlt', la.fetch_dlt_history), ('qxc', la.fetch_qxc_history)]:
    data = fetch_fn(15)
    wa = la.WeightedAnalyzer(data)
    if game == 'ssq':
        analysis = wa.analyze_ssq()
        recs = wa.generate_recs_ssq(analysis)
        assert len(recs) >= 4, f'{game}推荐数不足: {len(recs)}'
        for r in recs:
            assert 'reds' in r and 'blue' in r, f'{game}推荐格式错误: {r.keys()}'
            assert all(1 <= n <= 33 for n in r['reds']), f'{game}红球超范围'
            assert 1 <= r['blue'] <= 16, f'{game}蓝球超范围'
    elif game == 'dlt':
        analysis = wa.analyze_dlt()
        recs = wa.generate_recs_dlt(analysis)
        assert len(recs) >= 4, f'{game}推荐数不足: {len(recs)}'
        for r in recs:
            assert 'front' in r and 'back' in r, f'{game}推荐格式错误: {r.keys()}'
            assert all(1 <= n <= 35 for n in r['front']), f'{game}前区超范围'
            assert all(1 <= n <= 12 for n in r['back']), f'{game}后区超范围'
            assert len(r['front']) == 5, f'{game}前区数量错误: {len(r[\"front\"])}'
    elif game == 'qxc':
        analysis = wa.analyze_qxc()
        recs = wa.generate_recs_qxc(analysis)
        assert len(recs) >= 3, f'{game}推荐数不足: {len(recs)}'
        for r in recs:
            assert 'digits' in r, f'{game}推荐格式错误: {r.keys()}'
            assert len(r['digits']) == 7, f'{game}位数错误: {len(r[\"digits\"])}'
    print(f'  ✅ {game}: {len(recs)}注推荐生成成功')
print('✅ 所有彩种推荐测试通过')
"
```

**修改了Orchestrator相关代码时：**
```bash
python3 -c "
from algo_orchestrator import AlgoOrchestrator
orch = AlgoOrchestrator()
context = orch.daily_run()
status = context.get('module_status', {})
for step, s in status.items():
    assert s == 'ok', f'Orchestrator步骤{step}失败: {s}'
print('✅ Orchestrator 7步全部通过')
"
```

### Step 3: 代码审查检查项（逐项确认）

| # | 检查项 | 怎么查 |
|---|--------|--------|
| 1 | 命名一致性 | DLT用`back_`不用`blue_`，SSQ用`blue_`不用`back_` |
| 2 | 前区/红球数量 | DLT前区5个，SSQ红球6个 |
| 3 | 号码范围 | DLT前1-35后1-12，SSQ红1-33蓝1-16，QXC前6位0-9第7位0-14 |
| 4 | 返回格式 | DLT→`{'front','back'}`, SSQ→`{'reds','blue'}`, QXC→`{'digits'}` |
| 5 | 删函数前 | grep确认没有其他地方调用该函数 |
| 6 | 路径 | 不硬编码`/root/asuan-scheduler/`，用`os.path.dirname(__file__)` |
| 7 | 临时文件 | 不push `.bak`/`.backup`/`fix_`/`cold_`/`ssq_`等临时文件 |

## 验证通过后

3步全部通过后，输出：
```
✅ 开发守卫验证通过
  Step1 语法: ✅
  Step2 功能: ✅
  Step3 审查: ✅
可以push。
```

任何一步失败，**禁止push**，先修BUG。
