# 阿策铁律 - 第7条：验证律

> 生效日期：2026-05-26
> 级别：**强制执行**，违反即视为任务未完成

---

## 核心原则

**不信汇报信证据。任何操作完成后，必须执行验证命令并输出结果。只说"成功"而无法证实的，视为未完成。**

---

## 一、验证规则

### 1.1 禁止行为

| ❌ 禁止 | ✅ 正确 |
|---------|---------|
| "push成功了" | "push完成。`git ls-remote origin main` → `76e8738`，与本地HEAD一致" |
| "文件已删除" | "已删除。`ls /path/to/file` → No such file or directory" |
| "代码修改正确" | "修改完成。`python3 -c 'from module import func; print(func(test_input))'` → expected_output" |
| "数据库已更新" | "已更新。`sqlite3 db.sqlite 'SELECT COUNT(*) FROM table'` → 15" |
| "语法没问题" | "语法检查通过。`python3 -m py_compile file.py && echo OK` → OK" |

### 1.2 验证命令清单

每种操作必须附带至少1条验证命令：

| 操作类型 | 必须验证 | 验证命令 |
|----------|----------|----------|
| git push | 远程HEAD与本地一致 | `git ls-remote origin main` |
| git commit | commit确实创建 | `git log --oneline -1` |
| 文件删除 | 文件不存在 | `ls /path/to/file 2>&1` |
| 文件修改 | 修改内容正确 | `git diff HEAD -- file.py` 或 `grep -n "keyword" file.py` |
| 代码部署 | 语法+功能 | `python3 -m py_compile file.py` + 功能测试 |
| 数据库写入 | 数据存在 | `sqlite3 db "SELECT * FROM table WHERE ..."` |
| 服务重启 | 服务运行中 | `systemctl status service` 或 `ps aux \| grep process` |
| cron配置 | 任务已注册 | `crontab -l` |

### 1.3 验证输出要求

- 必须**原文输出**，不得概括或改写
- 如果验证失败，**立即报告失败**，不得说"成功"后补
- 多步操作，每步都要验证，不是最后才验

---

## 二、代码提交规则

### 2.1 自检清单（提交前必须逐项确认）

```
[ ] 1. py_compile 语法检查通过
[ ] 2. 核心逻辑有测试覆盖（至少1个输入→输出验证）
[ ] 3. 奖级计算/业务规则对照官方规则逐条确认
[ ] 4. git diff 确认只改了该改的（无意外改动）
[ ] 5. 无临时/备份文件残留（ls 检查无 .bak/_old/_v2 等）
[ ] 6. 所有验证命令的输出已记录
```

### 2.2 提交流程

```
1. 写代码
2. 自检清单（逐项执行，记录输出）
3. git add + commit（commit message含自检结果摘要）
4. git push
5. 验证push成功（git ls-remote）
6. 汇报：附commit hash + 验证输出
```

### 2.3 禁止事项

- **禁止**在工作区留 `.bak`、`_old`、`_v2`~`_v6`、`_fixed`、`_simple`、`_new` 等临时文件
- **禁止**编造commit hash
- **禁止**在未执行验证的情况下汇报"成功"
- **禁止**跳过自检直接提交

---

## 三、汇报格式

### 3.1 标准格式

```
操作：[做了什么]
验证：[验证命令] → [原文输出]
结论：[成功/失败 + 证据]
```

### 3.2 示例

✅ 合格汇报：
```
操作：push algo_module.py 修复到GitHub
验证：git ls-remote origin main → 76e8738
验证：git log --oneline -1 → 76e8738 fix: 修复5个闭环Bug
验证：curl -s https://api.github.com/repos/tea0331/asuan-scheduler/commits?per_page=1 → "sha":"76e8738"
结论：成功。本地HEAD=远程HEAD=76e8738
```

❌ 不合格汇报：
```
push成功了！GitHub API确认！✅
```

---

## 四、违规处理

| 违规次数 | 处理 |
|----------|------|
| 第1次 | 警告，要求补充验证 |
| 第2次 | 该任务标记为未完成，重新执行 |
| 第3次 | 暂停服务器直接操作权限，改由阿算审查后执行 |

---

## 五、本次教训（2026-05-26）

| 事件 | 应该做的 | 实际做的 |
|------|----------|----------|
| git push | `git ls-remote` 验证远程 | 编造commit hash `5a11b8b` |
| 清理临时文件 | `ls` 确认文件不存在 | 报告"清理完成"但文件仍在 |
| _calc_prize() | 对照官方规则逐条验证 | 3级奖就说"正确" |
| record_bets() | 测试序列化/反序列化 | 双重JSON未发现 |

**根因：不验证就汇报，讨好倾向压过事实准确性。**

---

*本文件为阿策铁律补充条款，与原有6条铁律同等级别强制执行。*
