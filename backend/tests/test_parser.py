"""文档解析器回归测试 —— 运行期生成 DOCX，不依赖仓库外的样本文件。

原 `test_parser_regression.py` 依赖 `uploads/伤寒论原文398条整理.docx`，而该目录被
`.gitignore` 排除，导致 16 个用例在本地与 CI 全部 skip（回归保护实际不存在）。
这里改为在临时目录即时生成一份覆盖各类边界的样本，使解析器始终处于被验证状态。

覆盖点：章节标题识别与切换、句末条号提取、罗马数字版式清理、中文数字条号、
异体字归一化、重复条号质检、source_book 推断。
"""
import pytest
from docx import Document as DocxDocument

from app.services.import_validator import validate_import_batch
from app.services.parser import DocumentParser

# 混排《伤寒论》与《金匮要略》的典型排版：章标题、罗马数字、中文条号、异体字、重复条号
SAMPLE_PARAGRAPHS = [
    "伤寒论原文摘录",                                        # 前置无条号段落，应被章标题清空
    "辨太阳病脉证并治（上）",                                 # 章标题（含子篇“上”）
    "太阳之为病，脉浮，头项强痛而恶寒。（1）",
    "太阳病，发热汗出，恶风，脉缓者，名为中风。（2）",
    "Ⅰ太阳病，或已发热，或未发热，必恶寒体痛，呕逆。（3）",      # 行首罗马数字
    "太阳病，脉浮紧，发热恶寒，身疼痛，不汗出而烦躁者。（4）",
    "太阳病，发热而渴，不恶寒者，为温病。（5）",
    "此段故意复用条号，用于触发质检的重复检测。（4）",           # 重复条号
    "辨阳明病脉证并治",                                      # 章标题切换
    "阳明之为病，胃家实是也。（6）",
    "问曰：何缘得阳明病？答曰：太阳病发汗过多，胃中干燥，因转属阳明。（7）",
    "胸痹心痛短气病脉证治第九",                                # 金匮章标题
    "胸痹之病，喘息咳唾，胸背痛，短气，寸口脉沉而迟。（一）",       # 中文数字条号
    "栝楼薤白白酒汤方：栝楼实一枚，薤白半斤，白酒七升。（二）",
    "妇人杂病脉证並治第二十二",                                # 异体字“並”
    "妇人脏躁，喜悲伤欲哭，象如神灵所作，数欠伸。（一）",
]


@pytest.fixture(scope="module")
def parsed_texts(tmp_path_factory):
    """生成 DOCX 并返回解析出的条文列表"""
    work = tmp_path_factory.mktemp("parser")
    path = work / "tcm-classic-sample.docx"

    doc = DocxDocument()
    for line in SAMPLE_PARAGRAPHS:
        doc.add_paragraph(line)
    doc.save(path)

    parser = DocumentParser(str(work))
    raw = parser.parse(str(path))
    extracted = parser.extract_texts_and_cases(
        raw["content"], filename=path.name, paragraphs=raw["paragraphs"]
    )
    return extracted["texts"]


def _by_number(texts, num):
    return [t for t in texts if t.get("article_number") == num]


class TestArticleExtraction:
    """条号提取与正文清理"""

    def test_extracts_expected_article_count(self, parsed_texts):
        assert len(parsed_texts) >= 11

    def test_article_numbers_cover_sample_range(self, parsed_texts):
        numbers = {t["article_number"] for t in parsed_texts if t["article_number"] is not None}
        assert {1, 2, 3, 4, 5, 6, 7}.issubset(numbers)

    def test_roman_marker_removed_from_content(self, parsed_texts):
        third = _by_number(parsed_texts, 3)[0]
        assert "Ⅰ" not in third["content"]
        assert third["content"].startswith("太阳病")

    def test_trailing_article_number_removed(self, parsed_texts):
        first = _by_number(parsed_texts, 1)[0]
        assert "（1）" not in first["content"]
        assert "(1)" not in first["content"]
        assert first["content"].endswith("恶寒。")

    def test_raw_content_is_preserved_for_traceability(self, parsed_texts):
        third = _by_number(parsed_texts, 3)[0]
        assert third["raw_content"].strip() != third["content"]
        assert "Ⅰ" in third["raw_content"]


class TestChapterAttribution:
    """章标题识别与章节归属"""

    def test_taiyang_section(self, parsed_texts):
        first = _by_number(parsed_texts, 1)[0]
        assert first["chapter"] == "辨太阳病脉证并治"
        assert first["section"] == "上"

    def test_yangming_chapter_switch(self, parsed_texts):
        sixth = _by_number(parsed_texts, 6)[0]
        assert sixth["chapter"] == "辨阳明病脉证并治"
        assert sixth["section"] is None

    def test_jingui_chapter_header(self, parsed_texts):
        chest = [t for t in parsed_texts if "胸痹" in (t.get("chapter") or "")]
        assert chest, "金匮章标题未被识别"
        assert chest[0]["chapter"].endswith("第九")


class TestChineseNumerals:
    """中文数字条号"""

    def test_chinese_number_becomes_integer(self, parsed_texts):
        chest = [t for t in parsed_texts if t["article_number"] == 1 and "胸痹" in (t.get("chapter") or "")]
        assert chest, "（一）未被解析为条号 1"
        assert "（一）" not in chest[0]["content"]

    def test_second_chest_article(self, parsed_texts):
        chest = [t for t in parsed_texts if t["article_number"] == 2 and "胸痹" in (t.get("chapter") or "")]
        assert chest, "（二）未被解析为条号 2"


class TestVariantCharacters:
    """异体字归一化（並 → 并）"""

    def test_variant_heading_is_recognised(self, parsed_texts):
        womens = [t for t in parsed_texts if "妇人杂病" in (t.get("chapter") or "")]
        assert womens, "含异体字“並”的章标题未被识别"
        assert "並" not in womens[0]["chapter"]
        assert womens[0]["chapter"].startswith("妇人杂病脉证并治")


class TestQualityGate:
    """导入质量闸门的重复检测"""

    def test_duplicate_article_number_is_reported(self, parsed_texts):
        report = validate_import_batch(parsed_texts, expected_book="《金匮要略》")
        assert 4 in report["duplicates"], "重复条号 4 未被质检捕获"
        assert report["passed"] is False

    def test_empty_content_is_reported(self):
        report = validate_import_batch(
            [{"article_number": 1, "content": "", "chapter": "甲"}],
            expected_book="《金匮要略》",
        )
        assert report["passed"] is False
        assert report["empty_content"] == [1]

    def test_no_valid_article_number_is_reported(self):
        report = validate_import_batch([{"article_number": None, "content": "正文"}])
        assert report["passed"] is False
        assert "未识别到任何有效条号" in report["issues"][0]


class TestSourceBookDetection:
    """source_book 推断"""

    def test_explicit_title_wins(self):
        parser = DocumentParser()
        assert parser._detect_source_book("《伤寒论》原文", "xx.docx") == "《伤寒论》"

    def test_jingui_chapter_pattern(self):
        parser = DocumentParser()
        content = "胸痹心痛短气病脉证治第九\n胸痹之病……"
        assert parser._detect_source_book(content, "sample.docx") == "《金匮要略》"

    def test_no_signal_returns_empty(self):
        parser = DocumentParser()
        assert parser._detect_source_book("随便一段与经典无关的文字", "plain.docx") == ""


class TestLengthThreshold:
    """短文档回退路径"""

    def test_too_few_paragraphs_falls_back_without_crash(self):
        parser = DocumentParser()
        result = parser.extract_texts_and_cases("太阳病，脉浮。（1）", filename="short.txt",
                                               paragraphs=[("太阳病，脉浮。（1）", 0)])
        assert isinstance(result["texts"], list)
