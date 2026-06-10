# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice
**Areas**: frontend | backend | infra | tests | docs | config
**Statuses**: pending | in_progress | resolved | wont_fix | promoted | promoted_to_skill

## Status Definitions

| Status | Meaning |
|--------|---------|
| `pending` | Not yet addressed |
| `in_progress` | Actively being worked on |
| `resolved` | Issue fixed or knowledge integrated |
| `wont_fix` | Decided not to address (reason in Resolution) |
| `promoted` | Elevated to CLAUDE.md, AGENTS.md, or copilot-instructions.md |
| `promoted_to_skill` | Extracted as a reusable skill |

## Skill Extraction Fields

When a learning is promoted to a skill, add these fields:

```markdown
**Status**: promoted_to_skill
**Skill-Path**: skills/skill-name
```

---

## [LRN-20260604-001] architecture

**Logged**: 2026-06-04T06:00:00+08:00
**Priority**: critical
**Status**: pending
**Area**: backend

### Summary
台湾彩种 PLN/LTN 尚未接入日报主流程，lottery-predictions.json 缺少 pln_recs/ltn_recs

### Details
- `lottery-predictions.json` 最新记录(2026-06-03)只有 ssq/dlt/qxc，无 pln/ltn
- `generate_full_daily.py` L2112-2118 调用 `generate_taiwan.py`，但 `generate_taiwan.py` 是独立脚本（违反架构铁律）
- `jin_zhu.py` 已有 `_gen_pln()`/`_gen_ltn()` 方法，但 `daily_run()` 未包含 PLN/LTN
- `games/pln.py` 和 `games/ltn.py` 存在，但 `generate_taiwan.py` 未调用它们（走的是绕路逻辑）

### Suggested Action
1. 删除 `generate_taiwan.py`（独立脚本，违反架构铁律）
2. 修改 `jin_zhu.py` 的 `daily_run()` 加入 PLN/LTN 调用，与 SSQ/DLT 对齐
3. 修改 `generate_full_daily.py` 的 `generate_taiwan_section()` 改为调用 `jz.generate_recs('pln'/'ltn')`
4. 验证：`python3 -c "from jin_zhu import JinZhu; jz=JinZhu(); print(jz.generate_recs('pln'))"` 有输出

### Metadata
- Source: self_improving_audit
- Related Files: jin_zhu.py, generate_full_daily.py, generate_taiwan.py, games/pln.py, games/ltn.py
- Tags: architecture, taiwan, pln, ltn, violation
- Recurrence-Count: 1
- First-Seen: 2026-06-04
- Last-Seen: 2026-06-04

---

## [LRN-20260604-002] best_practice

**Logged**: 2026-06-04T06:00:00+08:00
**Priority**: high
**Status**: pending
**Area**: backend

### Summary
日报 AI 生成有 7 个降级函数(_fallback_*)，但降级不是修复——违反降级铁律

### Details
- `generate_full_daily.py` 有 7 个 `_fallback_*` 函数：
  - `_fallback_all_sections()` — 整体降级（关键词推断6板块）
  - `_fallback_gap_scan()`, `_fallback_contra_tide()`, `_fallback_deep_chain()`, `_fallback_pitfall()`, `_fallback_quote()` — 单板块降级
  - `_fallback_lottery_display()` — 彩票展示降级
- 降级触发条件：AI内容过短/超时180秒/异常 → 直接走降级，没有修复动作
- 根据 AGENTS.md 降级铁律：修复=恢复功能+加保护，不是砍功能
- 当前降级路径缺失：超时重试、换模型重试、降级内容质量监控

### Suggested Action
1. 在 `_run_with_timeout()` 加重试逻辑（当前只有1次超时）
2. 超时/失败后记录到 `memory/heartbeat-state.json` 的 `degrade_events`
3. 添加降级内容质量告警：如果连续3次降级，发消息通知刘老板
4. 禁止永久性降级：`_fallback_all_sections()` 必须加 TODO 和恢复死线

### Metadata
- Source: self_improving_audit
- Related Files: generate_full_daily.py
- Tags: degrade, fallback, violation, daily_report
- Recurrence-Count: 1
- First-Seen: 2026-06-04
- Last-Seen: 2026-06-04

---

## [LRN-20260604-003] best_practice

**Logged**: 2026-06-04T06:00:00+08:00
**Priority**: medium
**Status**: pending
**Area**: config

### Summary
Heartbeat 静默时段(23:00-08:00)未完全遵守，cron 任务可能在此时间段执行

### Details
- AGENTS.md 规定：23:00-08:00 为 HEARTBEAT_OK 静默时段，不主动打扰刘老板
- 当前 cron `self-improving-daily` 设定在 06:00 执行（正好在静默时段内）
- 如果任务产生消息/通知，会违反静默规则
- 建议：将主动通知类 cron 移到 08:00 之后，或加时间判断不发送消息

### Suggested Action
1. 检查所有 cron 任务的执行时间，确保不在 23:00-08:00 发送消息
2. 在消息发送逻辑前加时间判断：
   ```python
   import datetime
   now_hour = datetime.datetime.now().hour
   if 23 <= now_hour or now_hour < 8:
       return  # 静默时段，不发送
   ```
3. 将 `self-improving-daily` 改为 08:30 执行（如果需发送通知）

### Metadata
- Source: self_improving_audit
- Related Files: AGENTS.md, HEARTBEAT.md
- Tags: heartbeat, quiet_hours, cron, violation
- Recurrence-Count: 1
- First-Seen: 2026-06-04
- Last-Seen: 2026-06-04

---
