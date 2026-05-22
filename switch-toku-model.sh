#!/bin/bash
# 一键切换 Toku Agent 模型：DeepSeek → 混元
# 执行前确保已设置 GH_TOKEN

set -e

REPO_URL="https://${GH_TOKEN}@github.com/tea0331/asuan-scheduler.git"
CLONE_DIR="/root/asuan-scheduler-temp"

echo "📦 克隆仓库..."
rm -rf "$CLONE_DIR"
git clone "$REPO_URL" "$CLONE_DIR"
cd "$CLONE_DIR"

echo "🔄 替换 toku_agent.py..."
sed -i 's/DASHSCOPE_API_KEY/HUNYUAN_API_KEY/g' toku_agent.py
sed -i 's|https://dashscope.aliyuncs.com/compatible-mode/v1|https://api.hunyuan.cloud.tencent.com/v1|g' toku_agent.py
sed -i 's/deepseek-chat/hunyuan-turbos-latest/g' toku_agent.py
sed -i 's/call_deepseek/call_hunyuan/g' toku_agent.py
sed -i 's/def call_deepseek/def call_hunyuan/g' toku_agent.py
sed -i 's/DeepSeek API错误/混元API错误/g' toku_agent.py
sed -i 's/DeepSeek调用失败/混元调用失败/g' toku_agent.py

echo "🔄 替换 toku-agent.yml..."
sed -i 's/DASHSCOPE_API_KEY/HUNYUAN_API_KEY/g' .github/workflows/toku-agent.yml

echo "📤 提交并推送..."
git config user.email "github-actions@users.noreply.github.com"
git config user.name "github-actions[bot]"
git add toku_agent.py .github/workflows/toku-agent.yml
git commit -m "chore: 切换DeepSeek→混元 (hunyuan-turbos-latest)"
git push "$REPO_URL" main

echo "✅ 完成！"
cd /
rm -rf "$CLONE_DIR"
