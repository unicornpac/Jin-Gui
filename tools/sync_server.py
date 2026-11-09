#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金匮系统 —— 从生产服务器同步数据到本机（可挂 Windows 计划任务）。

流程：
    1. ssh 探测连通性（要求 SSH 密钥免密）
    2. 服务器上用 SQLite Online Backup 生成一致性快照（tools/backup_now.sh）
    3. scp 拉回本机，校验 integrity_check
    4. 上传目录打包拉回（可选）
    5. 按「近期逐份 + 每日一份」轮转

只要这个任务在跑，服务器哪天到期被回收，本机都有最新数据。

用法：
    python sync_server.py
    python sync_server.py --server root@1.2.3.4
    python sync_server.py --skip-uploads

退出码：0 成功；1 连接失败；2 传输失败；3 校验失败
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

LOG_FILE = None


def log(message, level="INFO"):
    line = "[%s] [%s] %s" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        level,
        message,
    )
    print(line)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def run(cmd, timeout=900):
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except FileNotFoundError:
        return 127, "command not found: %s" % cmd[0]


def ssh_base(server, connect_timeout):
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=%d" % connect_timeout,
        "-o", "StrictHostKeyChecking=accept-new",
        server,
    ]


def verify_db(path):
    try:
        con = sqlite3.connect(path)
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
    except Exception as exc:  # noqa: BLE001
        return "error: %s" % exc, {}


def rotate(files, keep):
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for old in files[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def main():
    global LOG_FILE
    ap = argparse.ArgumentParser(description="从生产服务器同步数据到本机")
    ap.add_argument("--server", default="root@YOUR_SERVER_IP", help="SSH 地址，如 root@1.2.3.4")
    ap.add_argument("--remote-data-dir", default="/var/lib/jingui")
    ap.add_argument("--remote-uploads", default="/root/JinGui/backend/uploads")
    ap.add_argument("--remote-script", default="/root/JinGui/tools/backup_now.sh")
    ap.add_argument("--backup-root", default=r"D:\projects\Jin-Gui\backups\server")
    ap.add_argument("--keep-recent", type=int, default=14)
    ap.add_argument("--keep-daily", type=int, default=180)
    ap.add_argument("--skip-uploads", action="store_true")
    ap.add_argument("--connect-timeout", type=int, default=15)
    args = ap.parse_args()

    root = Path(args.backup_root)
    recent = root / "recent"
    daily = root / "daily"
    recent.mkdir(parents=True, exist_ok=True)
    daily.mkdir(parents=True, exist_ok=True)
    LOG_FILE = root / "sync.log"

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log("=========== sync start ===========")
    log("server=%s data=%s" % (args.server, args.remote_data_dir))

    # 0. 依赖检查
    for tool in ("ssh", "scp"):
        if not shutil.which(tool):
            log("missing command: %s (install Windows OpenSSH Client)" % tool, "ERROR")
            return 1

    # 1. 连通性
    code, out = run(ssh_base(args.server, args.connect_timeout) + ["echo __ok__"], timeout=60)
    if code != 0 or "__ok__" not in out:
        log("ssh connect failed (code=%d): %s" % (code, out.strip()[:200]), "ERROR")
        log("check: key auth (ssh-keygen / ssh-copy-id) and server reachability", "ERROR")
        return 1
    log("ssh ok")

    # 2. 服务器端一致性快照
    remote_snap = "/tmp/jingui-snap-%s.db" % ts
    code, out = run(
        ssh_base(args.server, args.connect_timeout)
        + ["bash '%s' '%s/tcm.db' '%s'" % (args.remote_script, args.remote_data_dir, remote_snap)],
        timeout=300,
    )
    if code != 0 or "snapshot-ok" not in out:
        log("backup_now.sh unavailable/failed, fallback to raw cp: %s" % out.strip()[:200], "WARN")
        code, out = run(
            ssh_base(args.server, args.connect_timeout)
            + ["cp '%s/tcm.db' '%s'" % (args.remote_data_dir, remote_snap)],
            timeout=300,
        )
        if code != 0:
            log("remote snapshot failed: %s" % out.strip()[:200], "ERROR")
            return 2
    log("snapshot ready: %s" % remote_snap)

    # 3. 下载
    local_db = recent / ("tcm-%s.db" % ts)
    code, out = run(["scp", "-q",
                     "-o", "BatchMode=yes",
                     "-o", "ConnectTimeout=%d" % args.connect_timeout,
                     "%s:%s" % (args.server, remote_snap), str(local_db)], timeout=900)
    if code != 0 or not local_db.exists():
        log("scp database failed: %s" % out.strip()[:200], "ERROR")
        return 2
    log("database downloaded: %.2f MB" % (local_db.stat().st_size / 1048576))

    # 4. 校验
    integrity, counts = verify_db(str(local_db))
    if integrity != "ok":
        log("integrity check failed: %s" % integrity, "ERROR")
        return 3
    log("integrity ok | texts=%d cases=%d sessions=%d"
        % (counts.get("classic_texts", -1), counts.get("medical_cases", -1), counts.get("training_sessions", -1)))

    # 5. 上传文件
    if not args.skip_uploads:
        try:
            code, out = run(
                ssh_base(args.server, args.connect_timeout)
                + ["test -d '%s' && echo yes || echo no" % args.remote_uploads],
                timeout=120,
            )
            if "yes" in out:
                remote_tgz = "/tmp/jingui-uploads-%s.tgz" % ts
                run(ssh_base(args.server, args.connect_timeout)
                    + ["tar czf '%s' -C '%s' . 2>/dev/null || true" % (remote_tgz, args.remote_uploads)],
                    timeout=1800)
                local_tgz = recent / ("uploads-%s.tgz" % ts)
                code, out = run(["scp", "-q", "-o", "BatchMode=yes",
                                 "%s:%s" % (args.server, remote_tgz), str(local_tgz)], timeout=1800)
                run(ssh_base(args.server, args.connect_timeout) + ["rm -f '%s'" % remote_tgz], timeout=120)
                if local_tgz.exists() and local_tgz.stat().st_size > 0:
                    target = recent / ("uploads-%s" % ts)
                    target.mkdir(parents=True, exist_ok=True)
                    try:
                        with tarfile.open(local_tgz, "r:gz") as tf:
                            tf.extractall(target)
                        log("uploads synced: %d files"
                            % len([p for p in target.rglob("*") if p.is_file()]))
                    finally:
                        local_tgz.unlink(missing_ok=True)
                else:
                    log("no uploads to sync", "WARN")
            else:
                log("remote uploads dir not found, skipped", "WARN")
        except Exception as exc:  # noqa: BLE001
            log("uploads sync failed (non fatal): %s" % exc, "WARN")

    # 6. 清理服务器临时快照
    run(ssh_base(args.server, args.connect_timeout) + ["rm -f '%s'" % remote_snap], timeout=120)

    # 7. 每日归档
    day_tag = datetime.now().strftime("%Y%m%d")
    daily_db = daily / ("tcm-%s.db" % day_tag)
    if not daily_db.exists():
        shutil.copy2(local_db, daily_db)
        log("daily archive created: %s" % daily_db)

    # 8. 轮转
    removed = rotate(list(recent.glob("tcm-*.db")), args.keep_recent)
    if removed:
        log("rotated %d recent db, kept %d" % (removed, args.keep_recent))
    up_dirs = [p for p in recent.glob("uploads-*") if p.is_dir()]
    up_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in up_dirs[args.keep_recent:]:
        shutil.rmtree(old, ignore_errors=True)
    removed = rotate(list(daily.glob("tcm-*.db")), args.keep_daily)
    if removed:
        log("rotated %d daily archive, kept %d" % (removed, args.keep_daily))

    log("=========== sync done (ok) ===========")
    log("latest: %s" % local_db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
