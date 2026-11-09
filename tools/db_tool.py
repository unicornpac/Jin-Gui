#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite 辅助工具：一致性备份与完整性校验。

被 tools/*.ps1 调用，避免在 PowerShell 里拼 python -c 带来的引号问题。

用法：
    python db_tool.py backup <源库> <目标库>
    python db_tool.py check  <库文件>
"""

import sqlite3
import sys


def do_backup(src_path: str, dst_path: str) -> int:
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    print("backup-ok")
    return 0


def do_check(db_path: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        integrity = con.execute("pragma integrity_check").fetchone()[0]
        try:
            texts = con.execute("select count(*) from classic_texts").fetchone()[0]
        except sqlite3.Error:
            texts = -1
        try:
            cases = con.execute("select count(*) from medical_cases").fetchone()[0]
        except sqlite3.Error:
            cases = -1
        try:
            sessions = con.execute("select count(*) from training_sessions").fetchone()[0]
        except sqlite3.Error:
            sessions = -1
        print("%s texts=%d cases=%d sessions=%d" % (integrity, texts, cases, sessions))
    finally:
        con.close()
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: db_tool.py backup <src> <dst> | check <db>")
        return 2
    cmd = sys.argv[1]
    if cmd == "backup":
        if len(sys.argv) < 4:
            print("usage: db_tool.py backup <src> <dst>")
            return 2
        return do_backup(sys.argv[2], sys.argv[3])
    if cmd == "check":
        return do_check(sys.argv[2])
    print("unknown command: " + cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
