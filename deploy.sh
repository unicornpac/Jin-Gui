#!/bin/bash
# ============================================================
# 从本机触发服务器端安全部署
# 用法：bash deploy.sh [user@host]
# 默认：root@YOUR_SERVER_IP
# ============================================================
set -Eeuo pipefail

HOST="${1:-root@YOUR_SERVER_IP}"
REMOTE_SCRIPT="/tmp/jingui-deploy.sh"

echo "========================================"
echo "  部署到 ${HOST}"
echo "========================================"

echo ""
echo "[1/2] 上传安全部署脚本..."
scp server_deploy.sh "${HOST}:${REMOTE_SCRIPT}"

echo ""
echo "[2/2] 执行服务器端部署..."
ssh "${HOST}" "sudo bash ${REMOTE_SCRIPT}"
