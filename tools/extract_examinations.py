"""从病案文本里提取舌象与脉象，写入 examinations。

训练时学生号脉、看舌，系统直接返回这里的客观体征——病案没配的话，
学生只会看到「本例未记录」，等于系统缺数据却让学生扣分。

提取来源：symptoms + content（原文里「苔白腻、脉沉弦细」这类描述）。
已有 examinations 的病案不覆盖。

用法：
    python tools/extract_examinations.py --dry-run
    python tools/extract_examinations.py --write
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "backend" / "data" / "tcm.db"

# 「脉」后面到标点为止，最多 10 字；「舌」同上，「苔」通常跟在舌象后
PULSE_RE = re.compile(r"脉[^，。；、,;.\s]{1,10}")
TONGUE_RE = re.compile(r"舌[^，。；、,;.\s]{1,10}|苔[^，。；、,;.\s]{1,8}")


def extract(text: str) -> dict:
    pulse = PULSE_RE.findall(text)
    tongue = TONGUE_RE.findall(text)
    result = {}
    if pulse:
        # 取第一个脉象描述
        result["pulse"] = {"text": pulse[0]}
    if tongue:
        # symptoms 与 content 常各写一遍，会出现「舌淡红苔白腻 / 舌淡红 / 苔白腻」，
        # 去掉被其他片段包含的短片段，只留最完整的那条
        uniq = list(dict.fromkeys(tongue))
        uniq = [x for x in uniq if not any(x != y and x in y for y in uniq)]
        result["tongue"] = {"text": "，".join(uniq)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="提取舌脉体征")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select id, title, symptoms, content, examinations from medical_cases order by id"
    ).fetchall()

    updated = skipped = empty = 0
    samples = []
    for row in rows:
        if row["examinations"]:
            skipped += 1
            continue
        text = (row["symptoms"] or "") + " " + (row["content"] or "")
        found = extract(text)
        if not found:
            empty += 1
            continue
        if len(samples) < 6:
            samples.append((row["id"], row["title"][:26], found))
        if args.write:
            conn.execute(
                "update medical_cases set examinations = ? where id = ?",
                (json.dumps(found, ensure_ascii=False), row["id"]),
            )
        updated += 1

    if args.write:
        conn.commit()
    conn.close()

    print(f"共 {len(rows)} 条：已存在 {skipped}，可提取 {updated}，无舌脉 {empty}")
    for cid, title, found in samples:
        print(f"  #{cid} {title}")
        for k, v in found.items():
            print(f"      {k}: {v['text']}")
    if args.dry_run:
        print("\n（dry-run，未写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
