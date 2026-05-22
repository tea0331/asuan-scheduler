# 🔧 阿策技能安装清单

> 基于v3.0开发过程中暴露的10类问题，针对性推荐技能安装

---

## 问题→技能映射

| # | 暴露的问题 | 需要的能力 | 对应技能 |
|---|-----------|-----------|---------|
| 1 | 删函数不检查依赖 | 依赖分析 | `comprehensive-review` |
| 2 | 命名不一致(blue/back) | 代码审查 | `code-review-ai` |
| 3 | 越界访问(list[6:11]) | 静态分析 | `commands-code-analysis-testing` |
| 4 | 格式错误(DLT用SSQ逻辑) | 代码审查 | `code-review-ai` |
| 5 | 缺失实现(函数不存在) | 测试验证 | `unit-testing` |
| 6 | 未验证就push | 测试自动化 | `hooks-testing` |
| 7 | 仓库污染(22个临时文件) | 仓库清理 | `codebase-cleanup` |
| 8 | 路径硬编码 | 安全/规范检查 | `security-scanning` |
| 9 | 服务器和GitHub不同步 | Git工作流 | `git-pr-workflows` |
| 10 | 静态文本未更新 | 代码审查 | `code-review-ai` |

---

## 🔴 必装（3个）——解决最致命的问题

### 1. `unit-testing` — 单元测试自动生成

**解决的问题**：3次push都有BUG、函数缺失、越界访问

**能力**：
- Python/JS单元测试自动生成
- 自我修复测试（测试失败时自动分析原因）
- CI/CD集成

**安装后效果**：
- 修改`generate_recs_dlt`后自动生成测试用例
- 发现`core_by_freq`未定义→测试直接报错，不用等push后才发现
- 发现`generate_recs_qxc`不存在→测试直接报错

**安装命令**：
```
/install unit-testing
```

---

### 2. `code-review-ai` — AI代码审查

**解决的问题**：命名不一致、格式错误、删函数不检查依赖

**能力**：
- Opus模型深度审查（架构+逻辑+规范）
- 检测跨函数依赖断裂
- 检测命名不一致（blue_weights vs back_weights）
- 检测格式错误（DLT用SSQ的6红球逻辑）

**安装后效果**：
- push前自动审查：发现`blue_weights`在DLT中不存在
- 发现删函数后调用方未更新
- 发现DLT返回`{'reds', 'blue'}`格式错误

**安装命令**：
```
/install code-review-ai
```

---

### 3. `hooks-testing` — 修改后自动测试

**解决的问题**：未验证就push

**能力**：
- `run-tests-after-changes`：文件修改后自动运行相关测试
- `test-runner`：自动识别并运行受影响的测试

**安装后效果**：
- 修改`lottery_analyzer.py`后自动跑测试
- 测试失败→阻止提交
- 彻底杜绝"改完就push"的坏习惯

**安装命令**：
```
/install hooks-testing
```

---

## 🟡 推荐装（2个）——提高开发质量和效率

### 4. `comprehensive-review` — 多维度审查

**解决的问题**：删函数不检查依赖、架构级问题

**能力**：
- 3个Agent协作：架构审查 + 代码质量 + 安全审计
- PR增强：自动补充测试覆盖、错误处理
- 适合重大改动前的全面评审

**安装后效果**：
- 删30个函数前自动分析影响范围
- 发现Orchestrator链路断裂

**安装命令**：
```
/install comprehensive-review
```

---

### 5. `codebase-cleanup` — 技术债务清理

**解决的问题**：仓库污染(22个临时文件)、代码冗余

**能力**：
- 技术债务检测和削减
- 依赖审计
- 自动清理无用代码/文件
- `refactor-clean`：重构清理命令

**安装后效果**：
- 自动识别.bak/.backup/fix_*等临时文件
- 发现未使用的导入和函数
- 保持仓库整洁

**安装命令**：
```
/install codebase-cleanup
```

---

## 🟢 可选装（2个）——锦上添花

### 6. `git-pr-workflows` — Git工作流自动化

**解决的问题**：服务器和GitHub代码不同步

**能力**：
- 多Agent协作的Git工作流
- 提交前自动质量检查
- PR增强（补充描述、测试覆盖）
- 团队入职流程

**安装后效果**：
- push前自动检查代码质量
- 防止代码不同步

**安装命令**：
```
/install git-pr-workflows
```

---

### 7. `security-scanning` — 安全扫描

**解决的问题**：路径硬编码、API key泄露

**能力**：
- SAST静态安全分析
- 依赖项漏洞扫描
- OWASP Top 10合规检查
- 检测硬编码路径、密钥泄露

**安装后效果**：
- 检测`/root/asuan-scheduler/`硬编码路径
- 检测API key明文写入代码
- 检测SQL注入风险

**安装命令**：
```
/install security-scanning
```

---

## 安装优先级总结

| 优先级 | 技能 | 安装命令 | 解决的核心问题 |
|--------|------|----------|--------------|
| 🔴 P0 | `unit-testing` | `/install unit-testing` | 未验证就push |
| 🔴 P0 | `code-review-ai` | `/install code-review-ai` | 命名不一致/格式错误 |
| 🔴 P0 | `hooks-testing` | `/install hooks-testing` | 修改后不测试 |
| 🟡 P1 | `comprehensive-review` | `/install comprehensive-review` | 删代码不检查依赖 |
| 🟡 P1 | `codebase-cleanup` | `/install codebase-cleanup` | 仓库污染 |
| 🟢 P2 | `git-pr-workflows` | `/install git-pr-workflows` | 代码不同步 |
| 🟢 P2 | `security-scanning` | `/install security-scanning` | 硬编码/key泄露 |

---

## AGENTS.md 建议新增的铁律

安装技能后，建议在AGENTS.md中加入以下规则：

```
## 交付规则（v3.0新增）

1. 代码改动完成后，必须运行 `unit-testing` 生成测试并全部通过
2. push前必须通过 `code-review-ai` 审查，无报错才能提交
3. 删除函数/方法前，必须用 `comprehensive-review` 分析依赖影响
4. 每周运行一次 `codebase-cleanup` 清理临时文件
5. 违反以上规则 = 输出作废/失信
```

---

## 已安装技能（保留，不需要重装）

- `code-review` — 基础代码审查
- `code-simplifier` — 代码简化
- `commit-commands` — Git提交工作流
- `feature-dev` — 功能开发工作流
- `github` — GitHub集成
- `pr-review-toolkit` — PR审查
- `security-guidance` — 安全提醒
- `security-scan` — 安全扫描
- `testbuddy` — 测试用例生成
