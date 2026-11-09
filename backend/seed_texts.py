"""
条文导入脚本 —— 支持《伤寒论》398条和《金匮要略》

用法：
  python seed_texts.py              # 增量导入到暂存区（不覆盖正式库）
  python seed_texts.py --clean      # 清空后全量重导到正式库
  python seed_texts.py --validate   # 仅解析+质检，不写库
"""
import sys, os, glob, re, argparse, json, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, init_db
from app.models import ClassicText, ChapterMeta, ImportBatch, ImportStaging
from app.services.parser import DocumentParser
from app.services.text_verifier import get_verifier, SHANGHAN_CHAPTERS, JINGUI_CHAPTERS
from app.services.import_validator import validate_import_batch, format_report_text

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def extract_keywords(content: str) -> str:
    """从条文内容中提取关键词"""
    keywords = []
    formulas = [
        "桂枝汤", "麻黄汤", "小青龙", "大青龙", "真武汤", "四逆汤",
        "白虎汤", "承气汤", "小柴胡", "大柴胡", "半夏泻心",
        "肾气丸", "薯蓣丸", "栝楼薤白", "越婢汤", "木防己",
        "茵陈蒿汤", "栀子豉汤", "理中汤", "吴茱萸汤", "当归四逆",
        "白头翁汤", "桃花汤", "桔梗汤", "猪苓汤", "五苓散",
    ]
    for f in formulas:
        if f in content:
            keywords.append(f)
    return ",".join(keywords[:5]) if keywords else ""


def seed(clean: bool = False, validate_only: bool = False):
    db = SessionLocal()
    try:
        # 初始化篇章元数据
        verifier = get_verifier()
        verifier.seed_chapter_meta(db)

        if clean:
            db.query(ClassicText).delete()
            db.query(ImportBatch).delete()
            db.query(ImportStaging).delete()
            db.commit()
            print("[clean] 已清空旧数据")

        # ───── 找到所有要处理的文档 ─────
        shanghan_files = glob.glob(os.path.join(UPLOAD_DIR, "*伤寒论*"))
        jingui_files = glob.glob(os.path.join(UPLOAD_DIR, "*金匮*"))

        if not shanghan_files and not jingui_files:
            all_docs = glob.glob(os.path.join(UPLOAD_DIR, "*.docx")) + glob.glob(os.path.join(UPLOAD_DIR, "*.doc"))
            if all_docs:
                print(f"[WARN] 未找到《伤寒论》或《金匮要略》文件，尝试处理 {len(all_docs)} 个文档...")
                for f in all_docs:
                    process_document_file(db, f, validate_only)
            else:
                print("[ERR] uploads 目录下无可处理的文档！请上传 Word 文件。")
            return

        for filepath in shanghan_files:
            process_document_file(db, filepath, validate_only)
        for filepath in jingui_files:
            process_document_file(db, filepath, validate_only)

        # ───── 输出最终统计 ─────
        total = db.query(ClassicText).count()
        staging_total = db.query(ImportStaging).count()
        print(f"\n{'='*50}")
        print(f"[stats] 正式条文总数: {total}")
        print(f"[stats] 暂存区条数: {staging_total}")

        from sqlalchemy import func as sqlfunc
        books = db.query(ClassicText.source_book, sqlfunc.count(ClassicText.id)).group_by(ClassicText.source_book).all()
        for book, cnt in books:
            print(f"  {book}: {cnt}条")

        print("\n[dist] 篇章分布：")
        chapters = db.query(
            ClassicText.source_book, ClassicText.chapter,
            sqlfunc.count(ClassicText.id)
        ).group_by(ClassicText.source_book, ClassicText.chapter).order_by(
            ClassicText.source_book, ClassicText.chapter
        ).all()
        for book, ch, cnt in chapters:
            print(f"  {book} | {ch}: {cnt}条")

        unassigned = db.query(ClassicText).filter(
            (ClassicText.chapter == None) | (ClassicText.chapter == "")
        ).count()
        if unassigned > 0:
            print(f"\n[WARN] 无章节归属: {unassigned}条")

    finally:
        db.close()


def process_document_file(db, filepath: str, validate_only: bool = False):
    """处理单个文档：解析 → 质检 → 暂存 → (可选)直接发布"""
    fname = os.path.basename(filepath)
    print(f"\n[file] 处理: {fname}")

    parser = DocumentParser(UPLOAD_DIR)
    result = parser.parse(filepath)
    content = result.get("content", "")
    paragraphs = result.get("paragraphs")
    source_hash = result.get("sha256", "")
    print(f"   解析: {len(content)} 字符")

    extracted = parser.extract_texts_and_cases(
        content, filename=fname, paragraphs=paragraphs,
    )
    texts = extracted.get("texts", [])
    print(f"   提取: {len(texts)} 条条文")

    if not texts:
        print("   [WARN] 未提取到条文")
        return

    # ── 质量闸门 ──
    source_book = texts[0].get("source_book", "《伤寒论》") if texts else "《伤寒论》"
    quality_report = validate_import_batch(texts, expected_book=source_book)
    print(f"\n   质检报告:")
    for line in format_report_text(quality_report).split('\n'):
        print(f"     {line}")

    if validate_only:
        return

    # ── 创建导入批次 ──
    batch_id = uuid.uuid4().hex[:12]
    batch = ImportBatch(
        batch_id=batch_id,
        source_file=fname,
        source_hash=source_hash,
        source_edition=None,
        total_articles=len(texts),
        unique_numbers=quality_report["actual_unique"],
        status="needs_review",
        quality_report=json.dumps(quality_report, ensure_ascii=False),
    )
    db.add(batch)
    db.commit()

    # ── 写入暂存区 ──
    duplicates = quality_report.get("duplicates", {})
    num_first_seen = set()
    staged_count = 0
    for art in texts:
        num = art.get("article_number")
        status_value = "needs_review"
        issue = None

        if num in duplicates:
            if num in num_first_seen:
                issue = f"duplicate: 条号 {num} 重复出现，需人工裁决"
            else:
                num_first_seen.add(num)

        stg = ImportStaging(
            batch_id=batch_id,
            source_book=art.get("source_book", source_book),
            chapter=art.get("chapter"),
            section=art.get("section"),
            article_number=num,
            order_index=num,
            raw_content=art.get("raw_content", ""),
            content=art.get("content", ""),
            layout_marker=art.get("layout_marker"),
            source_file=fname,
            source_hash=source_hash,
            source_offset=art.get("source_offset"),
            source_edition=None,
            status=status_value,
            issue=issue,
        )
        db.add(stg)
        staged_count += 1

    db.commit()
    print(f"   [OK] 暂存: {staged_count}条, 批次: {batch_id}")


if __name__ == "__main__":
    parser_arg = argparse.ArgumentParser(description="导入中医经典条文")
    parser_arg.add_argument("--clean", action="store_true", help="清空数据库后重新导入到正式库")
    parser_arg.add_argument("--validate", action="store_true", help="仅解析+质检，不写库")
    args = parser_arg.parse_args()

    init_db()  # 确保表存在
    seed(clean=args.clean, validate_only=args.validate)
