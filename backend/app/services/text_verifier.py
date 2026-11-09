"""
互联网条文校验服务 —— 调用 LLM 对比数据库中的条文与权威来源
"""
import json, re, os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

_backend_dir = Path(__file__).resolve().parent.parent.parent

from ..models import ClassicText, ChapterMeta
from ..logger import get_logger

logger = get_logger(__name__)


# ========== 已知的《伤寒论》和《金匮要略》篇章结构 ==========

SHANGHAN_CHAPTERS = [
    ("辨太阳病脉证并治（上）", "辨太阳病脉证并治", "上", 1),
    ("辨太阳病脉证并治（中）", "辨太阳病脉证并治", "中", 2),
    ("辨太阳病脉证并治（下）", "辨太阳病脉证并治", "下", 3),
    ("辨阳明病脉证并治", "辨阳明病脉证并治", None, 4),
    ("辨少阳病脉证并治", "辨少阳病脉证并治", None, 5),
    ("辨太阴病脉证并治", "辨太阴病脉证并治", None, 6),
    ("辨少阴病脉证并治", "辨少阴病脉证并治", None, 7),
    ("辨厥阴病脉证并治", "辨厥阴病脉证并治", None, 8),
    ("辨霍乱病脉证并治", "辨霍乱病脉证并治", None, 9),
    ("辨阴阳易差后劳复病脉证并治", "辨阴阳易差后劳复病脉证并治", None, 10),
]

# 伤寒论各章预期条文数（参考宋本）
SHANGHAN_EXPECTED = {
    "辨太阳病脉证并治（上）": 30,
    "辨太阳病脉证并治（中）": 97,
    "辨太阳病脉证并治（下）": 51,
    "辨阳明病脉证并治": 84,
    "辨少阳病脉证并治": 10,
    "辨太阴病脉证并治": 8,
    "辨少阴病脉证并治": 45,
    "辨厥阴病脉证并治": 56,
    "辨霍乱病脉证并治": 10,
    "辨阴阳易差后劳复病脉证并治": 7,
}

JINGUI_CHAPTERS = [
    ("脏腑经络先后病脉证第一", 1),
    ("痉湿暍病脉证治第二", 2),
    ("百合狐惑阴阳毒病脉证治第三", 3),
    ("疟病脉证并治第四", 4),
    ("中风历节病脉证并治第五", 5),
    ("血痹虚劳病脉证并治第六", 6),
    ("肺痿肺痈咳嗽上气病脉证治第七", 7),
    ("奔豚气病脉证治第八", 8),
    ("胸痹心痛短气病脉证治第九", 9),
    ("腹满寒疝宿食病脉证治第十", 10),
    ("五脏风寒积聚病脉证并治第十一", 11),
    ("痰饮咳嗽病脉证并治第十二", 12),
    ("消渴小便不利淋病脉证并治第十三", 13),
    ("水气病脉证并治第十四", 14),
    ("黄疸病脉证并治第十五", 15),
    ("惊悸吐衄下血胸满瘀血病脉证治第十六", 16),
    ("呕吐哕下利病脉证治第十七", 17),
    ("疮痈肠痈浸淫病脉证并治第十八", 18),
    ("趺蹶手指臂肿转筋阴狐疝蛔虫病脉证治第十九", 19),
    ("妇人妊娠病脉证并治第二十", 20),
    ("妇人产后病脉证治第二十一", 21),
    ("妇人杂病脉证并治第二十二", 22),
    ("杂疗方第二十三", 23),
    ("禽兽鱼虫禁忌并治第二十四", 24),
    ("果实菜谷禁忌并治第二十五", 25),
]


class TextVerifier:
    """条文校验器：用 LLM 比对数据库条文与已知权威结构"""

    def __init__(self):
        self._setup_client()

    def _setup_client(self):
        import os
        self.api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or None
        self.model = os.getenv("AI_MODEL", "deepseek-chat").strip()
        self.client = None
        if self.api_key:
            try:
                from .llm_client import build_openai_client
                # trust_env=False：内网端点不能被系统代理劫持（见 llm_client 模块说明）
                self.client = build_openai_client(api_key=self.api_key, base_url=self.base_url)
            except ImportError:
                pass

    # ---------- 篇章种子 ----------

    def seed_chapter_meta(self, db: Session):
        """将《伤寒论》和《金匮要略》的正确篇章结构写入 chapter_meta 表"""
        existing = db.query(ChapterMeta).count()
        if existing > 0:
            return existing  # 已初始化

        items = []
        for full_name, chapter, section, order in SHANGHAN_CHAPTERS:
            items.append(ChapterMeta(
                book="《伤寒论》", chapter=chapter, section=section,
                order_index=order,
                article_count_expected=SHANGHAN_EXPECTED.get(full_name)
            ))
        for full_name, order in JINGUI_CHAPTERS:
            items.append(ChapterMeta(
                book="《金匮要略》", chapter=full_name, section=None,
                order_index=order, article_count_expected=None
            ))
        db.add_all(items)
        db.commit()
        return len(items)

    # ---------- 逐条分类修正 ----------

    def classify_text(self, text: ClassicText) -> dict:
        """
        单条条文智能分类：用 LLM 根据内容判断它属于哪个篇章、
        编号应该是多少。
        """
        if not self.client:
            return {}

        canonical = []
        for full_name, ch, sec, _ in SHANGHAN_CHAPTERS:
            canonical.append(f"- {full_name}")
        for full_name, _ in JINGUI_CHAPTERS[:10]:
            canonical.append(f"- {full_name}")

        prompt = f"""你是中医经典校勘专家。请分析以下条文，判断它应该属于《伤寒论》还是《金匮要略》，以及具体篇章和编号。

已知篇章结构：
{chr(10).join(canonical)}

【待分类条文】
{text.content[:800]}

当前数据库记录：book={text.source_book}, chapter={text.chapter}, article_number={text.article_number}

请输出JSON（只输出JSON）：
{{"book":"《伤寒论》或《金匮要略》","chapter":"完整篇章名","section":"上/中/下 或 null","article_number":编号,"confidence":"高/中/低","reason":"简短理由"}}"""

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是中医经典校勘专家。只输出JSON。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500, temperature=0.1
            )
            content = resp.choices[0].message.content
            m = re.search(r'\{[\s\S]*\}', content)
            if m:
                return json.loads(m.group())
        except Exception as e:
            logger.warning("classify_text error: %s", e)
        return {}

    def verify_single(self, db: Session, text_id: int) -> dict:
        """
        单条校验：比对当前分类 vs LLM 判断的正确分类
        返回校验报告
        """
        text = db.query(ClassicText).filter(ClassicText.id == text_id).first()
        if not text:
            return {"error": f"条文 {text_id} 不存在"}

        result = self.classify_text(text)
        if not result:
            return {
                "text_id": text_id,
                "article_number": text.article_number,
                "chapter_correct": None,
                "content_match": None,
                "expected_chapter": None,
                "source_url": None,
                "detail": "LLM 调用失败，无法校验",
                "verified": False,
            }

        chapter_correct = (result.get("chapter") == text.chapter)
        if text.section and result.get("section"):
            chapter_correct = chapter_correct and (result.get("section") == text.section)

        return {
            "text_id": text_id,
            "article_number": text.article_number,
            "expected_article_number": result.get("article_number"),
            "chapter_correct": chapter_correct,
            "content_match": result.get("confidence") == "高",
            "expected_chapter": result.get("chapter"),
            "expected_section": result.get("section"),
            "source_url": None,
            "detail": result.get("reason", ""),
            "verified": chapter_correct,
        }

    def verify_and_fix_single(self, db: Session, text_id: int) -> dict:
        """校验并自动修复：如果分类不对，直接更新数据库"""
        report = self.verify_single(db, text_id)
        if report.get("error"):
            return report

        text = db.query(ClassicText).filter(ClassicText.id == text_id).first()
        if not text:
            return report

        fixed = False
        if report.get("expected_chapter") and not report["chapter_correct"]:
            text.chapter = report["expected_chapter"]
            if report.get("expected_section"):
                text.section = report["expected_section"]
            fixed = True

        if report.get("expected_article_number") and report["expected_article_number"] != text.article_number:
            text.article_number = report["expected_article_number"]
            fixed = True

        if fixed:
            text.verified = True
            text.verified_at = datetime.now()
            db.commit()

        report["fixed"] = fixed
        return report

    def verify_batch(self, db: Session, text_ids: List[int] = None, fix: bool = False) -> dict:
        """批量校验"""
        if text_ids:
            texts = db.query(ClassicText).filter(ClassicText.id.in_(text_ids)).all()
        else:
            texts = db.query(ClassicText).filter(ClassicText.verified == False).limit(50).all()

        details = []
        verified_count = 0
        fixed_count = 0

        for text in texts:
            if fix:
                r = self.verify_and_fix_single(db, text.id)
            else:
                r = self.verify_single(db, text.id)
            details.append(r)
            if r.get("verified"):
                verified_count += 1
            if r.get("fixed"):
                fixed_count += 1

        return {
            "total": len(texts),
            "verified": verified_count,
            "fixed": fixed_count,
            "details": details,
        }

    def validate_chapter_distribution(self, db: Session) -> dict:
        """
        验收：按篇章统计条文分布，与预期对比
        """
        from sqlalchemy import func as sqlfunc

        # 实际分布
        actual = {}
        rows = db.query(
            ClassicText.source_book, ClassicText.chapter,
            sqlfunc.count(ClassicText.id)
        ).group_by(ClassicText.source_book, ClassicText.chapter).all()
        for book, ch, cnt in rows:
            actual[f"{book}|{ch}"] = cnt

        # 预期分布
        expected = {}
        for full_name, chapter, section, order in SHANGHAN_CHAPTERS:
            key = f"《伤寒论》|{chapter}"
            expected[key] = SHANGHAN_EXPECTED.get(full_name, "?")

        return {
            "actual": {k: v for k, v in sorted(actual.items())},
            "expected": {k: v for k, v in sorted(expected.items())},
            "issues": [
                f"{k}: 实际{actual.get(k, 0)}条, 预期{expected.get(k, '?')}条"
                for k in expected
                if actual.get(k, 0) != expected.get(k, "?")
            ]
        }


_verifier = None


def get_verifier() -> TextVerifier:
    global _verifier
    if _verifier is None:
        _verifier = TextVerifier()
    return _verifier
