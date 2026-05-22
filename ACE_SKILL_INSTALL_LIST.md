# 🔧 阿策技能安装清单 v2（已验证安装命令）

> 上一版的安装命令是错的，这次所有命令都从skills.sh实际搜索验证过

---

## 🔴 必装3个

### 1. Python单元测试
```bash
npx skills add mindrally/skills@python-testing -g -y
```
**405次安装** | 解决：改完代码没验证就push

### 2. 代码审查
```bash
npx skills add wshobson/agents@code-review-excellence -g -y
```
**19.4K次安装** | 解决：命名不一致、格式错误、删函数不检查依赖

### 3. Git钩子（提交前自动测试）
```bash
npx skills add aj-geddes/useful-ai-prompts@git-hooks-setup -g -y
```
**328次安装** | 解决：文件修改后不自动跑测试

---

## 🟡 推荐装2个

### 4. 代码清理重构
```bash
npx skills add sickn33/antigravity-awesome-skills@codebase-cleanup-refactor-clean -g -y
```
**626次安装** | 解决：仓库污染（.bak/fix_等临时文件）

### 5. 安全扫描（密钥泄露+依赖漏洞）
```bash
npx skills add ghostsecurity/skills@ghost-scan-secrets -g -y
```
**1.8K次安装** | 解决：API key明文、路径硬编码

---

## 🟢 可选装2个

### 6. Git推送工作流
```bash
npx skills add sickn33/antigravity-awesome-skills@git-pushing -g -y
```
**642次安装** | 解决：服务器和GitHub代码不同步

### 7. 安全依赖扫描
```bash
npx skills add ghostsecurity/skills@ghost-scan-deps -g -y
```
**1.7K次安装** | 解决：依赖漏洞检测

---

## 一键全部安装

```bash
# 必装3个
npx skills add mindrally/skills@python-testing -g -y
npx skills add wshobson/agents@code-review-excellence -g -y
npx skills add aj-geddes/useful-ai-prompts@git-hooks-setup -g -y

# 推荐装2个
npx skills add sickn33/antigravity-awesome-skills@codebase-cleanup-refactor-clean -g -y
npx skills add ghostsecurity/skills@ghost-scan-secrets -g -y

# 可选装2个
npx skills add sickn33/antigravity-awesome-skills@git-pushing -g -y
npx skills add ghostsecurity/skills@ghost-scan-deps -g -y
```

---

## 安装后验证

```bash
npx skills check
```
确认所有技能都显示为已安装。
