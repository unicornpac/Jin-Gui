#!/bin/bash
# ============================================================
# 金匮系统服务器端安全部署
# 执行：sudo bash /tmp/jingui-deploy.sh
#
# 生产数据库固定保存在 /var/lib/jingui，位于 Git 仓库之外。
# 每次同步代码前使用 SQLite Online Backup API 创建一致性备份。
# ============================================================
set -Eeuo pipefail

REPO_DIR="${JINGUI_REPO_DIR:-/root/JinGui}"
PERSIST_DATA_DIR="${JINGUI_DATA_DIR:-/var/lib/jingui}"
BACKUP_DIR="${JINGUI_BACKUP_DIR:-/var/backups/jingui}"
LEGACY_DB="${REPO_DIR}/backend/data/tcm.db"
PERSIST_DB="${PERSIST_DATA_DIR}/tcm.db"
SERVICE_DROPIN_DIR="/etc/systemd/system/jingui.service.d"
SERVICE_DROPIN="${SERVICE_DROPIN_DIR}/data-dir.conf"
RAW_BASE="https://raw.githubusercontent.com/unicornpac/Jin-Gui/main/backend"
RAW_REPO_BASE="https://raw.githubusercontent.com/unicornpac/Jin-Gui/main"
SERVICE_STOPPED_FOR_MIGRATION=false
MIGRATED_NEW_DB=false
DROPIN_INSTALLED=false

FILES=(
  "app/database.py"
  "app/dependencies.py"
  "app/main.py"
  "app/models.py"
  "app/schemas.py"
  "app/services/parser.py"
  "app/services/text_verifier.py"
  "app/services/import_validator.py"
  "app/services/agent_service.py"
  "app/services/ai_service.py"
  "app/services/treatment_safety.py"
  "app/services/matcher.py"
  "app/services/prompts_config.py"
  "app/services/safety.py"
  "app/services/western_data.py"
  "app/services/progress.py"
  "app/logger.py"
  "alembic.ini"
  "alembic/env.py"
  "alembic/script.py.mako"
  "alembic/versions/bb356c8cc735_initial.py"
  "app/routers/agent.py"
  "app/routers/documents.py"
  "app/routers/texts.py"
  "app/routers/cases.py"
  "app/routers/analysis.py"
  "app/routers/import_review.py"
  "app/routers/feedback.py"
  "seed_texts.py"
  "seed_cases.py"
  "requirements.txt"
  "static/jingui-motion.js"
  "static/jingui-theme.css"
  "static/index.html"
  "static/newcase.html"
  "static/showcase.html"
  "static/study.html"
  "static/user.html"
  "static/train.html"
)

ROOT_FILES=(
  "server_deploy.sh"
  "jingui.service"
)

sqlite_backup() {
  local source_db="$1"
  local target_db="$2"
  sudo env SOURCE_DB="${source_db}" TARGET_DB="${target_db}" python3 - <<'PY'
import os
import sqlite3

source = sqlite3.connect(os.environ["SOURCE_DB"])
target = sqlite3.connect(os.environ["TARGET_DB"])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY
}

recover_from_deploy_error() {
  if ${SERVICE_STOPPED_FOR_MIGRATION}; then
    if ${MIGRATED_NEW_DB} && ! ${DROPIN_INSTALLED}; then
      # drop-in 尚未启用时，旧库仍是权威数据；删除的只是刚生成的迁移副本。
      sudo rm -f -- "${PERSIST_DB}"
    fi
    sudo systemctl start jingui || true
  fi
}

trap recover_from_deploy_error ERR

db_counts() {
  local db_file="$1"
  sudo env DB_FILE="${db_file}" python3 - <<'PY'
import os
import sqlite3

conn = sqlite3.connect(os.environ["DB_FILE"])
try:
    values = []
    for table in (
        "training_sessions",
        "session_messages",
        "learning_history",
        "medical_cases",
        "classic_texts",
    ):
        try:
            values.append(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.OperationalError:
            values.append(0)
    print(*values)
finally:
    conn.close()
PY
}

echo "========================================"
echo "  金匮系统安全部署"
echo "  数据目录: ${PERSIST_DATA_DIR}"
echo "========================================"

# 1. 在同步 Git 前迁移并备份生产数据库
echo ""
echo "[1/5] 保护生产数据库..."
sudo install -d -m 0750 "${PERSIST_DATA_DIR}" "${BACKUP_DIR}"

if [ ! -f "${PERSIST_DB}" ] && [ -f "${LEGACY_DB}" ]; then
  if sudo systemctl is-active --quiet jingui; then
    echo "  首次迁移期间暂停服务，避免产生未复制的新记录"
    sudo systemctl stop jingui
    SERVICE_STOPPED_FOR_MIGRATION=true
  fi
  echo "  首次迁移: ${LEGACY_DB} -> ${PERSIST_DB}"
  sqlite_backup "${LEGACY_DB}" "${PERSIST_DB}"
  MIGRATED_NEW_DB=true
fi

BEFORE_COUNTS="0 0 0 0 0"
if [ -f "${PERSIST_DB}" ]; then
  TIMESTAMP="$(date +%Y%m%d-%H%M%S-%N)"
  BACKUP_DB="${BACKUP_DIR}/tcm-${TIMESTAMP}.db"
  sqlite_backup "${PERSIST_DB}" "${BACKUP_DB}"
  BEFORE_COUNTS="$(db_counts "${PERSIST_DB}")"
  echo "  已备份: ${BACKUP_DB}"
  echo "  部署前记录数（会话/消息/学习/病案/条文）: ${BEFORE_COUNTS}"
else
  echo "  未发现旧数据库，将在持久化目录创建新库"
fi

# 2. 同步代码。生产数据库在仓库外，不受 reset/clean 影响。
echo ""
echo "[2/5] 同步代码..."
SYNC_OK=false

if [ -d "${REPO_DIR}/.git" ]; then
  cd "${REPO_DIR}"
  if sudo git fetch origin main 2>/dev/null; then
    sudo git reset --hard origin/main
    sudo git clean -fd
    SYNC_OK=true
    echo "  Git 同步成功"
  fi
fi

if ! ${SYNC_OK}; then
  echo "  Git 不可用，改用 GitHub Raw 更新核心文件..."
  sudo mkdir -p "${REPO_DIR}/backend"
  for file in "${FILES[@]}"; do
    dest="${REPO_DIR}/backend/${file}"
    sudo mkdir -p "$(dirname "${dest}")"
    echo "    -> ${file}"
    sudo wget -q -O "${dest}" "${RAW_BASE}/${file}"
  done
  for file in "${ROOT_FILES[@]}"; do
    dest="${REPO_DIR}/${file}"
    echo "    -> ${file}"
    sudo wget -q -O "${dest}" "${RAW_REPO_BASE}/${file}"
  done
fi

# 3. 固定 systemd 的生产数据目录
echo ""
echo "[3/5] 配置持久化数据目录..."
sudo install -d -m 0755 "${SERVICE_DROPIN_DIR}"
printf '[Service]\nEnvironment=DATA_DIR=%s\n' "${PERSIST_DATA_DIR}" \
  | sudo tee "${SERVICE_DROPIN}" >/dev/null
DROPIN_INSTALLED=true
sudo systemctl daemon-reload

# 4. 只对持久化数据库执行轻量迁移
echo ""
echo "[4/5] 执行数据库迁移..."
cd "${REPO_DIR}/backend"
sudo env DATA_DIR="${PERSIST_DATA_DIR}" python3 -c "
from app.database import init_db; init_db()
from app.services.text_verifier import get_verifier
from app.database import SessionLocal
db = SessionLocal()
try:
    count = get_verifier().seed_chapter_meta(db)
    print(f'篇章元数据: {count} 条')
finally:
    db.close()
"

# 5. 重启并验证记录数没有减少
echo ""
echo "[5/5] 重启并验证..."
sudo systemctl restart jingui

AFTER_COUNTS="$(db_counts "${PERSIST_DB}")"
echo "  部署后记录数（会话/消息/学习/病案/条文）: ${AFTER_COUNTS}"

read -r before_sessions before_messages before_learning before_cases before_texts <<<"${BEFORE_COUNTS}"
read -r after_sessions after_messages after_learning after_cases after_texts <<<"${AFTER_COUNTS}"
if [ "${after_sessions}" -lt "${before_sessions}" ] \
  || [ "${after_messages}" -lt "${before_messages}" ] \
  || [ "${after_learning}" -lt "${before_learning}" ] \
  || [ "${after_cases}" -lt "${before_cases}" ] \
  || [ "${after_texts}" -lt "${before_texts}" ]; then
  echo "错误：部署后记录数减少，请立即使用 ${BACKUP_DIR} 中的备份恢复。" >&2
  exit 1
fi

HEALTH_OK=false
for attempt in $(seq 1 15); do
  if sudo systemctl is-active --quiet jingui \
    && curl -fsS --max-time 3 http://localhost:8000/health >/dev/null; then
    HEALTH_OK=true
    break
  fi
  echo "  等待服务启动（${attempt}/15）..."
  sleep 2
done

if ! ${HEALTH_OK}; then
  echo "错误：服务在等待 30 秒后仍未通过健康检查。" >&2
  echo "健康检查详情：" >&2
  curl -s --max-time 3 http://localhost:8000/health 2>&1 || true
  sudo systemctl status jingui --no-pager -l || true
  sudo journalctl -u jingui -n 50 --no-pager || true
  exit 1
fi

SERVICE_STOPPED_FOR_MIGRATION=false

echo ""
echo "========================================"
echo "  部署完成，生产数据库未被代码同步覆盖"
echo "  http://YOUR_SERVER_IP/study"
echo "========================================"
