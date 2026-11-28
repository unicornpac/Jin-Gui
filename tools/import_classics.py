"""把《金匮要略》各篇 docx 解析成条文并写入 classic_texts。

源目录形如 `01 脏腑经络先后病脉证第一.docx`，每篇一篇。
复用项目已有的解析器与切分算法（按句末「（N）」收束），再清掉方剂段落，
只留条文正文——与库中已有的前三篇格式保持一致。

用法：
    python tools/import_classics.py --dry-run        # 只看统计
    python tools/import_classics.py --write          # 写入
已存在的篇章会自动跳过，可重复执行。
"""
import argparse
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.parser import DocumentParser, _split_by_sentence_end_number  # noqa: E402

SOURCE_BOOK = "《金匮要略》"
MIN_LEN = 8

# 源文件名里的异体字要归一到通行写法，否则按标准篇名检索不到。
# zhconv 的简体表不覆盖 CJK 扩展 B 区，只能显式列出。
CHAPTER_FIXES = {
    "\U00027312": "惑",   # 百合狐𧌒 → 百合狐惑
}


def clean_article(text: str) -> str:
    """去掉小节标题、方名行、方药组成与煎服法，只留条文正文。"""
    lines = [x.strip() for x in (text or "").split("\n") if x.strip()]
    if not lines:
        return ""
    if any("【附方】" in line for line in lines[:2]):
        return ""                                   # 附方不算正经条文
    kept = []
    for index, s in enumerate(lines):
        if index == 0 and len(s) < 15 and not re.search(r"[。！？；]", s):
            continue                                # 首行短标题
        if re.match(r"^[一二三四五六七八九十]+、", s) and len(s) < 15:
            continue                                # 小节标题
        if s.endswith("方") and len(s) <= 14:
            continue                                # 方名
        if s.startswith(("上", "右")) and len(s) <= 160:
            continue                                # 煎服法
        if sum(s.count(c) for c in "分兩两枚升銖") >= 2:
            continue                                # 方药组成
        if len(s) < 70 and "（" in s and not s.endswith("。"):
            continue                                # 炮制说明式药味行
        if len(s) < 60 and not s.endswith(("。", "！", "？")) and "主之" not in s:
            continue                                # 短句且无结论，多半是药味
        kept.append(s)
    return "\n".join(kept).strip()


def chapter_from_filename(name: str) -> str:
    stem = re.sub(r"^\d+\s+", "", Path(name).stem).strip()
    for bad, good in CHAPTER_FIXES.items():
        stem = stem.replace(bad, good)
    return stem


def main() -> int:
    parser = argparse.ArgumentParser(description="导入金匮条文")
    parser.add_argument("--dir", default=r"D:\文档表格\金匮条文库")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files = sorted(Path(args.dir).glob("*.docx"))
    if not files:
        print(f"目录里没有 docx：{args.dir}")
        return 1

    from app.database import SessionLocal
    from app.models import ClassicText

    db = SessionLocal()
    existing = {r.chapter for r in db.query(ClassicText.chapter).all()}

    doc_parser = DocumentParser(upload_dir=str(ROOT / ".codex_tmp" / "upload_probe"))
    batch_id = uuid.uuid4().hex[:12]

    total_kept = total_dropped = 0
    imported_chapters = []

    for path in files:
        chapter = chapter_from_filename(path.name)
        if chapter in existing:
            print(f"跳过（已存在）{chapter}")
            continue

        result = doc_parser.parse(str(path))
        articles = _split_by_sentence_end_number(result.get("paragraphs") or [])
        kept = []
        for art in articles:
            body = clean_article(art.get("content") or "")
            if len(body) >= MIN_LEN:
                kept.append((art, body))
        dropped = len(articles) - len(kept)
        total_kept += len(kept)
        total_dropped += dropped
        imported_chapters.append(chapter)
        print(f"{path.name}: 切 {len(articles)} 条 → 保留 {len(kept)}，丢弃 {dropped}（方剂/附方）")

        if args.write:
            for order, (art, body) in enumerate(kept, start=1):
                db.add(ClassicText(
                    source_book=SOURCE_BOOK,
                    chapter=chapter,
                    content=body,
                    raw_content=art.get("raw_content") or body,
                    article_number=art.get("article_number"),
                    order_index=order,
                    verified=False,
                    layout_marker=art.get("layout_marker"),
                    source_file=path.name,
                    source_hash=result.get("sha256"),
                    source_offset=art.get("source_offset"),
                    import_batch_id=batch_id,
                ))

    if args.write:
        db.commit()

    print(f"\n篇数 {len(imported_chapters)}，条文 {total_kept} 条，丢弃 {total_dropped} 段")
    if args.write:
        total = db.query(ClassicText).count()
        print(f"库中条文总数: {total}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
