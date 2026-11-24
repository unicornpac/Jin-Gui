"""从 Excel 批量导入医案（LLM 解析成结构化字段）。

数据来源：桌面《金匮_病案题.xlsx》，Sheet1 每行一条医案原文，
形如「荀××，女，40岁。七八年来……舌苔薄白，脉弦缓。综合脉证，思之：……处方：……」。

解析后写入 medical_cases，字段与现有病案一致。
逐条调用模型，结果落盘可续跑：中断后用 --start 从断点继续。

用法：
    # 试点 5 条，只看输出不写库
    python tools/import_cases.py --limit 5 --dry-run

    # 从第 6 条开始，写库
    python tools/import_cases.py --start 6 --write

    # 只重新解析某个区间（覆盖已有结果）
    python tools/import_cases.py --start 100 --limit 20 --write --force

状态文件：.codex_tmp/case_import_state.json（记录已处理行号与结果）
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / ".codex_tmp" / "case_import_state.json"
DEFAULT_XLSX = r"C:\Users\言行\Desktop\金匮_病案题.xlsx"

PROMPT = """你是中医经典教学系统的数据整理助手。下面是一条医案原文，请解析成结构化字段。

原文：
{text}

只输出 JSON，不要解释、不要代码块标记：
{{
  "title": "病名——证型，如「湿病——桂枝附子汤证」，不要带难度前缀",
  "difficulty_level": "初级或中级或高级",
  "content": "客观病历部分：患者信息、病史、症状、舌脉、化验检查",
  "symptoms": "症状与舌脉，用顿号分隔",
  "diagnosis": "辨证结论，病名加证型",
  "prescription": "治法与方剂，保留药物组成（可简写）",
  "correct_answer": "按【辨病】【平脉】【析证】【定治】四段整理的教学参考答案",
  "teaching_points": "2-4 条辨证要点，用「；」连成一行"
}}

字段要求：
- content 只保留客观病历：删掉医生的分析推理、辨证过程、「处方：」及其后的内容；
  西医检查（体温、血象、反射等）可以保留。
- content 必须包含原文给出的**舌象和脉象**（symptoms 里也会列出，两处都要有）。
- symptoms 必须包含舌象和脉象（原文有的都要）。
- difficulty_level 按**病情本身的复杂程度**判定，与出自哪本书无关：
  · 初级：单一证型、病机直接、一个主方就能解决，症状典型易辨
  · 中级：有兼证，或需要与 1-2 个相近证鉴别，或需加减
  · 高级：病机复杂、多脏腑同病、需要合方，或有误治/变证/复诊转方
- 原文没有的信息填 null，不要编造。
- JSON 字符串内部**不能出现换行符**：多条要点用「；」分隔，不要分行。
- 八个字段**一个都不能少**，correct_answer 尤其不能省略。"""


def load_cases(path: str):
    from openpyxl import load_workbook

    ws = load_workbook(path, data_only=True)["Sheet1"]
    cases = []
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        text = (row[0] or "").strip() if isinstance(row[0], str) else ""
        if text and text != "病案":
            cases.append((row_no, text))
    return cases


def build_client():
    import httpx
    from openai import OpenAI

    return OpenAI(
        base_url=os.getenv("OPENAI_BASE_URL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        http_client=httpx.Client(trust_env=False, timeout=180.0),
    )


def extract_json(raw: str):
    """从模型输出里取出 JSON 对象；容忍 ```json 包裹。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    body = match.group()
    # 模型常在字符串里直接换行（如多条 teaching_points），标准 JSON 不允许。
    # strict=False 允许字符串内的控制字符，能直接吃下这种输出。
    for candidate in (body, re.sub(r"\r?\n(?!\s*[\"\]\},])", " ", body)):
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
    return None


def parse_case(client, model: str, text: str):
    """调用模型解析一条；返回 (记录, 原始输出)。"""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": PROMPT.format(text=text)}],
        temperature=0.2,
        max_tokens=3000,
    )
    raw = resp.choices[0].message.content or ""
    return extract_json(raw), raw


def normalize(record: dict, source_row: int):
    """补齐字段、拼标题前缀、做基本校验。返回 (记录, 错误说明)。"""
    if not isinstance(record, dict):
        return None, "模型输出不是 JSON 对象"
    title = (record.get("title") or "").strip()
    content = (record.get("content") or "").strip()
    level = (record.get("difficulty_level") or "").strip()
    if not title:
        return None, "缺少 title"
    if not content:
        return None, "缺少 content"
    if not (record.get("correct_answer") or "").strip():
        # 多半是输出被截断，重试一次通常就好
        return None, "缺少 correct_answer（可能被截断）"
    if level not in ("初级", "中级", "高级"):
        level = "中级"
    record["difficulty_level"] = level
    record["title"] = f"【{level}】{title}"
    record["content"] = content
    for field in ("symptoms", "diagnosis", "prescription", "teaching_points", "correct_answer"):
        value = record.get(field)
        record[field] = value.strip() if isinstance(value, str) and value.strip() else None
    record["_source_row"] = source_row
    return record, None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"done": [], "failed": [], "records": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def write_to_db(records):
    """写库。返回 (新增条数, 跳过条数)。"""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.database import SessionLocal
    from app.models import MedicalCase

    db = SessionLocal()
    added = skipped = 0
    try:
        existing = {c.title for c in db.query(MedicalCase).all()}
        for item in records:
            if item["title"] in existing:
                skipped += 1
                continue
            db.add(MedicalCase(
                title=item["title"],
                content=item["content"],
                symptoms=item.get("symptoms"),
                diagnosis=item.get("diagnosis"),
                prescription=item.get("prescription"),
                difficulty_level=item["difficulty_level"],
                teaching_points=item.get("teaching_points"),
                correct_answer=item.get("correct_answer"),
            ))
            added += 1
        db.commit()
    finally:
        db.close()
    return added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Excel 医案批量导入")
    parser.add_argument("--file", default=DEFAULT_XLSX)
    parser.add_argument("--start", type=int, default=1, help="从第几条开始（1-based，不含表头）")
    parser.add_argument("--limit", type=int, default=0, help="处理多少条，0 表示到末尾")
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    parser.add_argument("--write", action="store_true", help="解析后写入数据库")
    parser.add_argument("--force", action="store_true", help="重跑已处理过的行")
    parser.add_argument("--flush-every", type=int, default=20,
                        help="每处理多少条写一次库（默认 20）")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=False)

    cases = load_cases(args.file)
    print(f"读取到 {len(cases)} 条医案")
    selected = cases[args.start - 1:]
    if args.limit:
        selected = selected[:args.limit]
    print(f"本次处理 {len(selected)} 条（第 {args.start} 条起）\n")

    state = load_state()
    done = set(state.get("done", []))
    client = build_client()
    model = os.getenv("AI_MODEL", "example-model")

    results = []
    added_total = skipped_total = 0
    for index, (row_no, text) in enumerate(selected, start=args.start):
        if row_no in done and not args.force:
            print(f"[{index}] 第 {row_no} 行 已处理，跳过")
            continue
        record = None
        error = None
        for attempt in range(3):
            started = time.time()
            try:
                parsed, raw = parse_case(client, model, text)
                record, error = normalize(parsed, row_no)
            except Exception as exc:
                record, error, raw = None, f"调用失败：{exc}", ""
            if record:
                break
            print(f"  第 {attempt + 1} 次失败：{error}")
            time.sleep(2)
        elapsed = time.time() - started

        if not record:
            state.setdefault("failed", []).append({"row": row_no, "error": error})
            save_state(state)
            print(f"[{index}] 第 {row_no} 行 失败：{error}")
            continue

        results.append(record)
        if row_no not in done:
            done.add(row_no)
        state["done"] = sorted(done)
        state["records"] = [r for r in state.get("records", []) if r.get("_source_row") != row_no]
        state["records"].append(record)
        save_state(state)

        print(f"[{index}] 第 {row_no} 行 {record['title']}  "
              f"({record['difficulty_level']}, {elapsed:.1f}s)")

        # 分批落库：中断时已经写进去的不会丢
        if args.write and len(results) >= args.flush_every:
            added, skipped = write_to_db(results)
            added_total += added
            skipped_total += skipped
            print(f"  ↳ 本批入库 {added} 条（同名跳过 {skipped}），累计 {added_total}")
            results = []

    if args.dry_run:
        out = ROOT / ".codex_tmp" / "case_import_preview.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n预览已写入 {out}")
        return 0

    if args.write and results:
        added, skipped = write_to_db(results)
        added_total += added
        skipped_total += skipped

    if args.write:
        print(f"\n入库合计：新增 {added_total} 条，同名跳过 {skipped_total} 条")
    print(f"累计已完成 {len(state.get('done', []))} 条，失败 {len(state.get('failed', []))} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
