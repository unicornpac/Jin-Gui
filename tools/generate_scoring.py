"""为病案生成评分要点与问诊要点（参照病案 #12 的结构）。

输入：病案已有的 correct_answer（四段式）/ diagnosis / prescription / symptoms / 难度
输出：key_facts + scoring_points，写回 medical_cases 两列。

逐条调模型，状态落盘可续跑：
    python tools/generate_scoring.py --limit 3 --dry-run      # 试跑看质量
    python tools/generate_scoring.py --start 1 --write        # 全量写入
中断后重跑会自动跳过已完成的病案。
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import logging

# httpx/openai 的 DEBUG 日志会把进度淹没，只留警告
for _name in ("httpx", "httpcore", "openai", "urllib3"):
    logging.getLogger(_name).setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from tools.import_cases import build_client, extract_json  # noqa: E402

STATE_FILE = ROOT / ".codex_tmp" / "generate_scoring_state.json"
STAGES = ("辨病", "平脉", "析证", "定治")

PROMPT = """你是中医教学系统的数据整理助手。请为下面的病案生成评分要点与问诊要点。

病案：
标题：{title}
难度：{difficulty}
症状：{symptoms}
诊断：{diagnosis}
治法方剂：{prescription}
参考答案：
{correct_answer}

只输出 JSON，不要解释：
{{
  "key_facts": [
    {{"label": "病程长短", "must_ask": true, "keywords": ["多久", "几年", "多长时间"]}}
  ],
  "scoring_points": [
    {{"stage": "辨病", "text": "辨为眩晕（水饮上犯）", "weight": 25,
      "keywords": ["眩晕", "水饮"], "min_level": "初级", "strict": false}},
    {{"stage": "定治", "text": "方选苓桂术甘汤", "weight": 20,
      "keywords": ["苓桂术甘"], "min_level": "高级", "strict": true}}
  ]
}}

要求：
- key_facts 4-6 条：学生**开口问**才能拿到的信息（病程、诱因、主要症状、既往治疗、
  饮食二便、情志睡眠等）。**不要列舌象和脉象**——那些靠切诊取得。
  keywords 写学生原话里可能出现的 2-4 种说法；must_ask 只给真正必须问到的标 true，
  标 true 的不要超过一半。

- scoring_points **必须分三层**。min_level 逐条判定，**不要看这个病案本身是几难**，
  只看这条要点考的是什么能力：
  · 涉及「这是什么病」→ min_level 填「初级」（1-2 条）
  · 涉及「脉象说明什么 / 病机是什么 / 与什么证鉴别」→ 填「中级」（2-4 条）
  · 涉及「怎么治 / 用什么方 / 方义 / 前医之失 / 传变」→ 填「高级」（2-4 条）
  三层都必须有，缺一层就算不合格。
- **权重是每个阶段的总和**：辨病合计 25、平脉合计 15、析证合计 40、定治合计 20；
  同一阶段有多条时按重要性在该阶段内分配。
- 每条给 2-4 个关键词，覆盖同义说法（如「口苦」「嘴里发苦」）。
- strict：凡涉及**方名**或**是否做了鉴别**的要点填 true，其余 false。
- 关键词要具体，不要用「有病」「不适」这类泛词；每条至少 2 个字。
- 所有条目的 min_level 一律填「{difficulty}」。
- JSON 字符串内部不能换行，多个说法用「；」分隔。"""


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


# 学生几乎不会用来提问的空泛说法，留着只会让命中率虚高
GENERIC_KEYWORDS = {"哪里不舒服", "什么症状", "有病", "不适", "难受", "怎么回事",
                    "怎么办", "情况", "症状", "问题"}


def clean_keywords(words, upper=6):
    if not isinstance(words, list):
        return []
    result = []
    for w in words:
        text = str(w).strip()
        if text in GENERIC_KEYWORDS:
            continue
        if 2 <= len(text) <= 12 and text not in result:
            result.append(text)
    return result[:upper]


def cap_must_ask(facts):
    """must_ask 全 true 会让完整度分母虚高，限制在一半左右。"""
    if not facts:
        return facts
    limit = max(2, (len(facts) + 1) // 2)
    for index, fact in enumerate(facts):
        fact["must_ask"] = index < limit
    return facts


STAGE_TARGET = {"辨病": 25.0, "平脉": 15.0, "析证": 40.0, "定治": 20.0}
STAGE_LEVEL = {"辨病": "初级", "平脉": "中级", "析证": "中级", "定治": "高级"}


def normalize_weights(points):
    """把各阶段权重缩放到目标总和（模型常把「每阶段 40」理解成「每条 40」）。"""
    by_stage = {}
    for p in points:
        by_stage.setdefault(p["stage"], []).append(p)
    for stage, items in by_stage.items():
        target = STAGE_TARGET.get(stage, 20.0)
        total = sum(i["weight"] for i in items) or float(len(items))
        for item in items:
            item["weight"] = round(item["weight"] / total * target, 1)
    return points


def normalize(payload, difficulty):
    """校验并补齐，返回 (记录, 错误)。"""
    if not isinstance(payload, dict):
        return None, "输出不是 JSON 对象"

    facts = []
    for item in payload.get("key_facts") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        kws = clean_keywords(item.get("keywords"))
        if len(label) < 2 or not kws:
            continue
        facts.append({
            "label": label,
            "must_ask": bool(item.get("must_ask", True)),
            "min_level": difficulty,
            "keywords": kws,
        })

    points = []
    for item in payload.get("scoring_points") or []:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip()
        text = str(item.get("text") or "").strip()
        try:
            weight = float(item.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        kws = clean_keywords(item.get("keywords"))
        if stage not in STAGES or len(text) < 4 or weight <= 0 or not kws:
            continue
        # 不靠模型判断层级：按阶段硬映射，正好对应三阶梯
        # 辨病=初级（只考"这是什么病"）、平脉/析证=中级（解释为什么）、定治=高级（怎么治）
        level = STAGE_LEVEL.get(stage, "中级")
        points.append({
            "stage": stage,
            "text": text,
            "weight": weight,
            "keywords": kws,
            "min_level": level,
            "strict": bool(item.get("strict", False)),
        })

    if len(facts) < 3:
        return None, f"key_facts 仅 {len(facts)} 条"
    if len(points) < 3:
        return None, f"scoring_points 仅 {len(points)} 条"
    stages = {p["stage"] for p in points}
    if len(stages) < 3:
        return None, f"只覆盖 {len(stages)} 个阶段"
    return {"key_facts": cap_must_ask(facts),
            "scoring_points": normalize_weights(points)}, None


def generate(client, model, case) -> tuple:
    prompt = PROMPT.format(
        title=case["title"], difficulty=case["difficulty_level"],
        symptoms=case["symptoms"] or "（未提供）",
        diagnosis=case["diagnosis"] or "（未提供）",
        prescription=case["prescription"] or "（未提供）",
        correct_answer=case["correct_answer"] or "（未提供）",
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=2500,
    )
    return extract_json(resp.choices[0].message.content or "")


def write_to_db(records):
    from app.database import SessionLocal
    from app.models import MedicalCase

    db = SessionLocal()
    updated = 0
    try:
        for rec in records:
            case = db.query(MedicalCase).filter(MedicalCase.id == rec["id"]).first()
            if not case:
                continue
            case.key_facts = rec["key_facts"]
            case.scoring_points = rec["scoring_points"]
            updated += 1
        db.commit()
    finally:
        db.close()
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="生成病案评分要点")
    parser.add_argument("--start", type=int, default=1, help="从第几个病案开始（按 id 升序）")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--flush-every", type=int, default=10)
    parser.add_argument("--include-existing", action="store_true",
                        help="连已经配过要点的病案也重跑")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=False)

    from app.database import SessionLocal
    from app.models import MedicalCase

    db = SessionLocal()
    query = db.query(MedicalCase)
    if not args.include_existing:
        # 已经配好要点的（如 #12）不动
        query = query.filter(MedicalCase.scoring_points.is_(None))
    rows = query.order_by(MedicalCase.id).all()
    cases = [{
        "id": c.id, "title": c.title, "difficulty_level": c.difficulty_level,
        "symptoms": c.symptoms, "diagnosis": c.diagnosis,
        "prescription": c.prescription, "correct_answer": c.correct_answer,
    } for c in rows]
    db.close()

    selected = cases[args.start - 1:]
    if args.limit:
        selected = selected[:args.limit]
    print(f"待处理 {len(selected)} 条（库中共 {len(cases)}）\n")

    state = load_state()
    done = set(state.get("done", []))
    client = build_client()
    model = os.getenv("AI_MODEL", "example-model")

    pending = []
    ok_count = fail_count = 0
    for item in selected:
        cid = item["id"]
        if cid in done and not args.force:
            continue
        record, error = None, None
        for attempt in range(3):
            started = time.time()
            try:
                payload = generate(client, model, item)
                record, error = normalize(payload, item["difficulty_level"])
            except Exception as exc:
                record, error = None, f"调用失败：{exc}"
            if record:
                break
            time.sleep(2)
        elapsed = time.time() - started

        if not record:
            state.setdefault("failed", []).append({"id": cid, "error": error})
            save_state(state)
            fail_count += 1
            print(f"#{cid} 失败：{error}")
            continue

        record["id"] = cid
        record["title"] = item["title"]
        pending.append(record)
        done.add(cid)
        state["done"] = sorted(done)
        state["records"] = [r for r in state.get("records", []) if r.get("id") != cid]
        state["records"].append(record)
        save_state(state)
        ok_count += 1
        print(f"#{cid} {item['title'][:30]}  "
              f"要点 {len(record['key_facts'])} / {len(record['scoring_points'])}  ({elapsed:.1f}s)")

        if args.write and len(pending) >= args.flush_every:
            write_to_db(pending)
            print(f"  ↳ 已写入 {len(pending)} 条")
            pending = []

    if args.dry_run:
        out = ROOT / ".codex_tmp" / "scoring_preview.json"
        out.write_text(json.dumps(pending or state.get("records", [])[-len(selected):],
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n预览: {out}")

    if args.write and pending:
        write_to_db(pending)
        print(f"  ↳ 已写入 {len(pending)} 条")

    print(f"\n成功 {ok_count}，失败 {fail_count}，累计完成 {len(state.get('done', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
