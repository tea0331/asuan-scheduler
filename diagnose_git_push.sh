#!/bin/bash
# 刘海蟾点金 - Git Push 诊断脚本
# 在服务器 /root/asuan-scheduler 上运行

set -e
REPO_DIR="/root/asuan-scheduler"

echo "============================================"
echo "  Git Push 诊断脚本"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

cd "$REPO_DIR" || { echo "❌ 目录不存在: $REPO_DIR"; exit 1; }

echo ""
echo "=== 1. Git 版本 ==="
git --version

echo ""
echo "=== 2. 当前分支 ==="
git branch -v

echo ""
echo "=== 3. 所有 Remote ==="
git remote -v

echo ""
echo "=== 4. 最近3个本地 commit ==="
git log --oneline -3

echo ""
echo "=== 5. 本地 vs 远程差异 ==="
git fetch origin 2>&1 || echo "⚠️ fetch失败"
echo "本地HEAD: $(git rev-parse HEAD)"
echo "远程HEAD: $(git rev-parse origin/main 2>/dev/null || echo '无法获取')"
echo "差异commits: $(git rev-list origin/main..HEAD --count 2>/dev/null || echo '无法比较')"

echo ""
echo "=== 6. 测试 Push (dry-run) ==="
git push --dry-run origin main 2>&1 || echo "❌ dry-run失败"

echo ""
echo "=== 7. 实际 Push (verbose) ==="
GIT_CURL_VERBOSE=1 git push -v origin main 2>&1 || echo "❌ push失败"

echo ""
echo "=== 8. Push 后验证 ==="
sleep 3
REMOTE_HEAD=$(git ls-remote origin main 2>/dev/null | awk '{print $1}')
LOCAL_HEAD=$(git rev-parse HEAD)
echo "本地 HEAD: $LOCAL_HEAD"
echo "远程 HEAD: $REMOTE_HEAD"
if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    echo "✅ 一致！Push成功！"
else
    echo "❌ 不一致！Push失败！"
fi

echo ""
echo "=== 9. Credential 配置 ==="
git config --list 2>/dev/null | grep -E "(credential|user\.|remote\.)" || echo "无credential配置"

echo ""
echo "============================================"
echo "  诊断完成"
echo "============================================"
