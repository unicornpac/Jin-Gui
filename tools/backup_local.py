#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金匮系统 —— 本机数据库每日自动备份。

用 SQLite Online Backup API，允许服务运行中安全备份，不会复制到一半损坏。

产物：
    <backup-dir>/tcm-YYYYMMDD-HHmmss.db   每次一份
    <backup-dir>/tcm-latest.db            最新副本（恢复优先用它）
    <backup-dir>/backup.log               执行日志

用法：
    python backup_local.py
    python backup_local.py --data-dir D:\\projects\\Jin-Gui\\backend\\data --keep 90

退出码：0 成功；2 备份失败；3 校验失败
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

_LOG_FILE = None


def log(message, level="INFO"):
    line = "[%s] [%s] %s" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        level,
        message,
    )
    print(line)
    if _LOG_FILE:
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def make_backup(src, dst, attempts=3):
    """生成一致性快照，失败重试（服务写库时可能瞬时加锁）。"""
    last_err = None
    for i in range(1, attempts + 1):
        try:
            with sqlite3.connect(src, timeout=15) as s, sqlite3.connect(dst, timeout=15) as d:
                s.backup(d)
            return True
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log("attempt %d/%d failed: %s" % (i, attempts, exc), "WARN")
            time.sleep(2)
    log("backup failed: %s" % last_err, "ERROR")
    return False


def verify(db_path):
    con = sqlite3.connect(db_path)
    try:
        integrity = con.execute("pragma integrity_check").fetchone()[0]
        counts = {}
        for table in ("classic_texts", "medical_cases", "training_sessions"):
            try:
                counts[table] = con.execute("select count(*) from %s" % table).fetchone()[0]
            except sqlite3.Error:
                counts[table] = -1
        return integrity, counts
    finally:
        con.close()


def rotate(backup_dir, keep):
    files = sorted(
        [p for p in Path(backup_dir).glob("tcm-2*.db")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in files[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def main():
    global _LOG_FILE
    ap = argparse.ArgumentParser(description="金匮本机数据库备份")
    ap.add_argument("--data-dir", default=r"D:\projects\Jin-Gui\backend\data")
    ap.add_argument("--backup-dir", default=r"D:\projects\Jin-Gui\backups\local")
    ap.add_argument("--keep", type=int, default=90, help="保留天数（份数）")
    args = ap.parse_args()

    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = backup_dir / "backup.log"

    src = Path(args.data_dir) / "tcm.db"
    if not src.exists():
        log("source db not found: %s" % src, "ERROR")
        return 2

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / ("tcm-%s.db" % ts)
    latest = backup_dir / "tcm-latest.db"

    log("=========== backup start (source %.2f MB) ===========" % (src.stat().st_size / 1048576))

    if not make_backup(str(src), str(dst)):
        return 2

    integrity, counts = verify(str(dst))
    if integrity != "ok":
        log("integrity check failed: %s" % integrity, "ERROR")
        try:
            dst.unlink()
        except OSError:
            pass
        return 3
    log("integrity ok | texts=%d cases=%d sessions=%d"
        % (counts["classic_texts"], counts["medical_cases"], counts["training_sessions"]))

    with open(dst, "rb") as fsrc, open(latest, "wb") as fdst:
        while True:
            chunk = fsrc.read(1024 * 256)
            if not chunk:
                break
            fdst.write(chunk)

    log("saved: %s (%.2f MB)" % (dst, dst.stat().st_size / 1048576))

    removed = rotate(backup_dir, args.keep)
    if removed:
        log("rotated %d old backup(s), kept %d" % (removed, args.keep))

    log("=========== backup done ===========")
    return 0


if __name__ == "__main__":
    sys.exit(main())
