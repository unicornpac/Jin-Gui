#!/bin/bash
# ============================================================
#  金匮系统 —— 服务器端一致性快照脚本
#
#  由本机 tools/sync_server_data.ps1 通过 ssh 调用：
#      bash /root/JinGui/tools/backup_now.sh /var/lib/jingui/tcm.db /tmp/jingui-snap.db
#
#  用 SQLite Online Backup API，允许服务在运行中安全备份，
#  不会出现"复制到一半被写入"导致的库损坏。
# ============================================================
set -euo pipefail

SRC="${1:-/var/lib/jingui/tcm.db}"
DST="${2:-/tmp/jingui-snap.db}"

if [ ! -f "$SRC" ]; then
    echo "source-db-not-found: $SRC" >&2
    exit 2
fi

python3 - "$SRC" "$DST" <<'PY'
import sqlite3
import sys

src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)
try:
    with dst:
        src.backup(dst)
finally:
    dst.close()
    src.close()

# 快照自身校验，避免把坏文件传回本机
con = sqlite3.connect(dst_path)
try:
    ok = con.execute("pragma integrity_check").fetchone()[0]
finally:
    con.close()
print("snapshot-ok integrity=%s" % ok)
PY

chmod 644 "$DST" 2>/dev/null || true
