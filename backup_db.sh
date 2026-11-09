#!/bin/bash
# ============================================================
#  金匮系统 — 从本机拉取服务器生产数据库备份
#  用法：bash backup_db.sh [user@host]
#  默认：root@YOUR_SERVER_IP
# ============================================================
set -e

HOST="${1:-root@YOUR_SERVER_IP}"
REMOTE_DB="/var/lib/jingui/tcm.db"
REMOTE_UPLOADS="/root/JinGui/backend/uploads"
TS=$(date +%Y%m%d-%H%M%S)
LOCAL_DIR="./backups"
LOCAL_DB="${LOCAL_DIR}/tcm-${TS}.db"
LOCAL_UPLOADS="${LOCAL_DIR}/uploads-${TS}"

mkdir -p "${LOCAL_DIR}"

echo "========================================"
echo "  拉取服务器数据库备份"
echo "  服务器: ${HOST}"
echo "  时间:    ${TS}"
echo "========================================"

# 1. 复制数据库到备份目录 → 打包 → 拉取
echo ""
echo "[1/3] 服务器端打包数据库..."
ssh "${HOST}" "sudo cp ${REMOTE_DB} /tmp/tcm-backup.db && sudo chmod 644 /tmp/tcm-backup.db && echo ok"

echo ""
echo "[2/3] 下载数据库..."
scp "${HOST}:/tmp/tcm-backup.db" "${LOCAL_DB}"
ssh "${HOST}" "sudo rm -f /tmp/tcm-backup.db"
echo "  已保存: ${LOCAL_DB}"

# 2. 拉取上传文件（如存在）
echo ""
echo "[3/3] 下载上传文件..."
if ssh "${HOST}" "test -d ${REMOTE_UPLOADS} && ls ${REMOTE_UPLOADS}/*.docx ${REMOTE_UPLOADS}/*.pdf 2>/dev/null | head -1" > /dev/null 2>&1; then
  mkdir -p "${LOCAL_UPLOADS}"
  scp -r "${HOST}:${REMOTE_UPLOADS}/*" "${LOCAL_UPLOADS}/" 2>/dev/null || echo "  (部分文件跳过)"
  echo "  已保存: ${LOCAL_UPLOADS}"
else
  echo "  (无上传文件)"
fi

# 3. 显示文件信息
echo ""
echo "========================================"
echo "  备份完成"
echo "========================================"
ls -lh "${LOCAL_DB}"
if [ -d "${LOCAL_UPLOADS}" ]; then
  echo ""
  echo "上传文件:"
  ls -lh "${LOCAL_UPLOADS}/" 2>/dev/null || true
fi

# 4. 清理旧备份（保留最近 30 份）
KEEP=30
OLD=$(ls -1t "${LOCAL_DIR}"/tcm-*.db 2>/dev/null | tail -n +$((KEEP+1)))
if [ -n "$OLD" ]; then
  echo ""
  echo "清理旧备份..."
  echo "$OLD" | while read f; do rm -f "$f" && echo "  删除: $(basename $f)"; done
fi
