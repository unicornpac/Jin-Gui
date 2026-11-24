"""为病案生成条文关联：规则粗筛候选 → LLM 精选 → 写入 text_case_relations。

背景：条文库是繁体、病案是简体，且病案用的是西医/现代病名，纯字面匹配不可靠。
先用 matcher 取 top-15 候选（已做繁简归一与病名加权），再让模型判断哪些真正相关。

用法：
    python tools/build_relations.py --limit 3 --dry-run
    python tools/build_relations.py --write
状态落盘 .codex_tmp/relations_state.json，可续跑。
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

for _name in ("httpx", "httpcore", "openai", "urllib3"):
    logging.getLogger(_name).setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from tools.import_cases import build_client, extract_json  # noqa: E402

STATE_FILE = ROOT / ".codex_tmp" / "relations_state.json"
CANDIDATES = 20

PROMPT = """下面是一个中医病案，以及从《伤寒论》《金匮要略》里初筛出的候选条文。
请挑出与该病案**直接相关**的条文：
能说明本病案的病名、病机、证型，或与该病案所用方剂对应的原文。

只挑真正对得上的，宁少勿多（1-4 条）；不相关的一条都不要选。

病案：
标题：{title}
诊断：{diagnosis}
治法方剂：{prescription}
辨证要点：{answer}

候选条文：
{candidates}

只输出 JSON，不要解释：
{{"选中": [1, 3], "理由": ["第1条…", "第3条…"]}}"""


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"done": [], "results": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成条文-病案关联")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=False)

    from app.database import SessionLocal
    from app.models import MedicalCase, ClassicText, TextCaseRelation
    from app.services.matcher import get_matcher

    db = SessionLocal()
    matcher = get_matcher()
    texts = db.query(ClassicText).all()
    cases = db.query(MedicalCase).order_by(MedicalCase.id).all()
    print(f"病案 {len(cases)}，条文 {len(texts)}")

    state = load_state()
    done = set(state.get("done", []))
    client = build_client()
    model = os.getenv("AI_MODEL", "example-model")

    selected = cases[args.start - 1:]
    if args.limit:
        selected = selected[:args.limit]

    results = []
    for case in selected:
        if case.id in done and not args.force:
            continue
        scored = sorted(
            ((t, matcher._calculate_similarity(t, case)) for t in texts),
            key=lambda x: -x[1],
        )[:CANDIDATES]
        scored = [(t, s) for t, s in scored if s > 0]
        if not scored:
            print(f"#{case.id} 无候选，跳过")
            continue

        lines = "\n".join(
            f"{i}. [{t.chapter or ''}] {(t.content or '')[:180]}"
            for i, (t, _) in enumerate(scored, start=1)
        )
        prompt = PROMPT.format(
            title=case.title, diagnosis=case.diagnosis or "（无）",
            prescription=case.prescription or "（无）",
            answer=(case.correct_answer or "")[:260],
            candidates=lines,
        )
        started = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=800,
            )
            verdict = extract_json(resp.choices[0].message.content or "") or {}
        except Exception as exc:
            print(f"#{case.id} 调用失败：{exc}")
            continue

        picks = []
        for idx in verdict.get("选中") or []:
            try:
                n = int(idx)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= len(scored):
                text, score = scored[n - 1]
                picks.append({"text_id": text.id, "score": round(score, 3),
                              "chapter": text.chapter})
        results.append({"case_id": case.id, "title": case.title, "picks": picks,
                        "reasons": verdict.get("理由") or []})
        done.add(case.id)
        state["done"] = sorted(done)
        state["results"] = [r for r in state.get("results", []) if r.get("case_id") != case.id]
        state["results"].append(results[-1])
        save_state(state)
        print(f"#{case.id} {case.title[:26]}  选中 {len(picks)} 条  ({time.time()-started:.0f}s)")

    if args.write and results:
        existing = {(r.text_id, r.case_id) for r in db.query(TextCaseRelation).all()}
        added = 0
        for item in results:
            for pick in item["picks"]:
                key = (pick["text_id"], item["case_id"])
                if key in existing:
                    continue
                db.add(TextCaseRelation(text_id=pick["text_id"], case_id=item["case_id"],
                                        similarity_score=str(pick["score"])))
                added += 1
        db.commit()
        print(f"写入关联 {added} 条")

    if args.dry_run:
        out = ROOT / ".codex_tmp" / "relations_preview.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"预览: {out}")

    print(f"\n完成 {len(results)} 条，累计 {len(state.get('done', []))}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
