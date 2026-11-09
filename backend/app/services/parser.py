"""
文档解析服务
支持PDF、Word、TXT、Excel等格式的解析
自动识别中医经典条文格式并归类到条文库
"""
import os
import re
import hashlib
from typing import Dict, List, Tuple, Optional
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    import pandas as pd
except ImportError:
    pd = None

# 中医经典来源与章节关键词映射
SOURCE_BOOK_KEYWORDS = {
    "《伤寒论》": ["伤寒论", "伤寒"],
    "《金匮要略》": ["金匮", "金匮要略"],
    "《温病条辨》": ["温病", "温病条辨"],
    "《黄帝内经》": ["内经", "素问", "灵枢"],
}

# ── 罗马数字映射（Ⅰ-Ⅹ）──
_ROMAN_MAP = dict(zip("ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ", range(1, 11)))

# 句末条号模式：匹配末尾的 （数字）或（中文数字）
_SENTENCE_END_NUM_RE = re.compile(r'[（(](\d{1,3}|[一二三四五六七八九十百廿卅]+)[）)]\s*$')

# 中文数字 → 整数
_CN_NUM_MAP = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
    '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20,
    '廿': 20, '卅': 30, '百': 100,
}

# 金匮要略内部的子标题（非章节级别，仅作分组提示）
_JINGUI_SUBHEADERS = {'治未病', '诊法', '疾病分类', '治则', '证治', '方', '禁忌', '杂治'}
_JINGUI_SUBHEADER_PAT = re.compile(
    r'^(治未病|诊法|疾病分类[^\\n]{0,10}|治则|证治[^\\n]{0,10}|杂疗方|禽兽鱼虫|果实菜谷)$'
)

# 罗马数字开头的版式标记
_LAYOUT_MARKER_RE = re.compile(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s*')

# 章节标题模式
_CHAPTER_PATTERNS = [
    re.compile(r'辨(太阳|阳明|少阳|太阴|少阴|厥阴)病脉证并治[（(]?([上下中])?[)）]?'),
    re.compile(r'辨(霍乱|阴阳易差后劳复)病脉证并治'),
]

# 金匮要略章节
_JINGUI_CHAPTER_RE = re.compile(
    r'([脏腑经络先后痉湿暍百合狐惑阴阳毒疟中风历节血痹虚劳肺痿肺痈咳嗽上气奔豚气'
    r'胸痹心痛短气腹满寒疝宿食五脏风寒积聚痰饮咳嗽消渴小便不利淋水气黄疸惊悸吐衄下血'
    r'胸满瘀血呕吐哕下利疮痈肠痈浸淫趺蹶手指臂肿转筋阴狐疝蛔虫妇人妊娠妇人产后妇人杂'
    r'杂疗禽兽鱼虫禁忌果实菜谷禁忌]+'
    r'(?:病脉证[并治]*|病脉证治|方|禁忌并治|禁忌)'
    r'[第]?[一二三四五六七八九十百廿卅]+)'
)


def _strip_layout_marker(text: str) -> Tuple[str, Optional[str]]:
    """从段落开头移除罗马数字版式标记，返回 (清理后文本, 标记)"""
    m = _LAYOUT_MARKER_RE.match(text)
    if m:
        marker = m.group().strip()
        cleaned = text[m.end():].strip()
        return cleaned, marker
    return text, None


def _extract_sentence_end_number(text: str) -> Optional[int]:
    """从句末提取条号 （N）或（中文数字），返回整数条号或 None"""
    m = _SENTENCE_END_NUM_RE.search(text.rstrip())
    if m:
        val = m.group(1)
        if val.isdigit():
            return int(val)
        # 中文数字
        if val in _CN_NUM_MAP:
            return _CN_NUM_MAP[val]
        # 复合中文数字如 "二十一" → 21, "十三" → 13
        total = 0
        for ch in val:
            if ch == '十':
                total = 10 if total == 0 else total * 10
            elif ch == '百':
                total = 100 if total == 0 else total * 100
            elif ch in _CN_NUM_MAP:
                total += _CN_NUM_MAP[ch]
        return total if total > 0 else None
    return None


def _is_chapter_header(text: str) -> bool:
    """判断是否为章节标题行"""
    text = _normalize_chapter(text.strip())
    for pat in _CHAPTER_PATTERNS:
        if pat.match(text):
            return True
    # 金匮要略章节
    if _JINGUI_CHAPTER_RE.match(text):
        return True
    return False


# 异体字归一化映射：文档中的生僻/繁异体 → chapter_meta 标准字符
_VARIANT_MAP = str.maketrans({
    '\U00027492': '\u60d1',  # 𧌒 → 惑
    '\u865b': '\u865a',      # 虛 → 虚
    '\u4e26': '\u5e76',       # 並 → 并
})


def _normalize_chapter(text: str) -> str:
    """归一化章节名中的异体字"""
    return text.translate(_VARIANT_MAP)


def _parse_chapter(text: str) -> Tuple[str, Optional[str]]:
    """解析章节标题，返回 (chapter_name, section)"""
    text = _normalize_chapter(text.strip())
    for pat in _CHAPTER_PATTERNS:
        m = pat.match(text)
        if m:
            jing = m.group(1)
            sub = m.group(2) if m.lastindex >= 2 else None
            return f"辨{jing}病脉证并治", sub
    jm = _JINGUI_CHAPTER_RE.match(text)
    if jm:
        return jm.group(0).rstrip("。，,. "), None
    return text, None


def _clean_display_content(raw: str) -> str:
    """
    清理展示用正文：
    1. 移除每行开头的罗马数字版式标记（支持多段合并的条文）
    2. 移除末尾的 （数字） 条号
    3. 规范化空白
    """
    # 先分行处理，每行单独剥离罗马数字
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned_lines = []
    for line in lines:
        stripped, _ = _strip_layout_marker(line.strip())
        # 移除末尾条号
        stripped = _SENTENCE_END_NUM_RE.sub('', stripped).strip()
        if stripped:
            cleaned_lines.append(stripped)
    s = "\n".join(cleaned_lines)
    # 规范化空白
    s = re.sub(r'[ \t]+', ' ', s)
    s = s.strip()
    return s


def _split_by_sentence_end_number(
    paragraphs: List[Tuple[str, int]]
) -> List[dict]:
    """
    句末条号收束切分 —— 核心切分算法。
    
    输入: [(段落文本, 段落偏移量), ...]
    
    算法:
    1. 维护缓冲区，累积同一条号的多个段落
    2. 遇到句末 （N） 时提取条号
    3. 连续段落相同条号 → 合并为一条（多段条文）
    4. 不同条号 → 结束前一条，开始新条
    
    返回: [{
        "article_number": int,
        "raw_content": str,        # 原始文本（含罗马数字、条号标记）
        "content": str,            # 规范正文（已清理）
        "layout_marker": str,      # 版式标记
        "chapter": str,            # 所属章节
        "section": str,            # 子篇（上/中/下）
        "source_offset": int,      # 起始段落偏移量
    }, ...]
    """
    articles = []
    buffer = {}  # 当前累积的条文

    def _finish_article():
        nonlocal buffer
        if buffer and buffer.get("article_number") is not None:
            # 合并 raw_content 和 content
            buffer["raw_content"] = "\n".join(buffer["raw_parts"])
            buffer["content"] = _clean_display_content(buffer["raw_content"])
            articles.append({
                "article_number": buffer["article_number"],
                "raw_content": buffer["raw_content"],
                "content": buffer["content"],
                "layout_marker": (buffer.get("markers") or [None])[0],
                "chapter": buffer.get("chapter"),
                "section": buffer.get("section"),
                "source_offset": buffer["source_offset"],
            })
        buffer = {}

    current_chapter = None
    current_section = None
    pending = []  # 无条号的导引段落，归属到下一条

    def _article_complete(buf):
        """缓冲区中的条文是否已完整（最后一段带条号）"""
        if not buf or not buf.get("raw_parts"):
            return False
        last = buf["raw_parts"][-1]
        return _extract_sentence_end_number(last) is not None

    for para_text, para_offset in paragraphs:
        text = para_text.strip()
        if not text:
            continue

        # ── 章节标题 → 更新上下文 ──
        if _is_chapter_header(text):
            _finish_article()
            pending.clear()
            current_chapter, current_section = _parse_chapter(text)
            continue

        # ── 标题行 / 元数据 → 跳过 ──
        if "原文" in text and "条" in text and "整理" in text:
            continue
        stripped, _ = _strip_layout_marker(text)
        if len(stripped) < 4 and all(ch in "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ \t" for ch in text):
            continue
        if _JINGUI_SUBHEADER_PAT.match(text):
            continue

        # ── 提取句末条号 ──
        article_num = _extract_sentence_end_number(text)

        if article_num is not None:
            # 与缓冲区相同条号 → 合并（多段条文）
            if buffer and buffer.get("article_number") == article_num:
                buffer["raw_parts"].append(text)
                _, m2 = _strip_layout_marker(text)
                if m2:
                    buffer.setdefault("markers", []).append(m2)
                continue

            # 不同条号 → 结束前一条
            _finish_article()

            # 开始新条：如果 pending 中有导引段落，prepend
            parts = pending + [text] if pending else [text]
            pending.clear()
            _, marker = _strip_layout_marker(text)
            buffer = {
                "article_number": article_num,
                "raw_parts": parts,
                "markers": [marker] if marker else [],
                "chapter": current_chapter,
                "section": current_section,
                "source_offset": para_offset,
            }
        else:
            # 无条号文本
            if buffer:
                if _article_complete(buffer):
                    # 当前条文已完整，新段落是下一条的导引
                    pending.append(text)
                else:
                    # 当前条文未完整（没有末尾条号），视为续文
                    buffer["raw_parts"].append(text)
            else:
                # 无缓冲区，累积到 pending
                pending.append(text)

    # 处理最后一条
    _finish_article()

    # 如果还有 pending 文本没有归属，作为独立未编号条目
    if pending:
        articles.append({
            "article_number": None,
            "raw_content": "\n".join(pending),
            "content": _clean_display_content("\n".join(pending)),
            "layout_marker": None,
            "chapter": current_chapter,
            "section": current_section,
            "source_offset": -1,
        })

    return articles


# ─────────────────────────────────────────────
# DocumentParser 类
# ─────────────────────────────────────────────


class DocumentParser:
    """文档解析器"""

    def __init__(self, upload_dir: str = None):
        self.upload_dir = upload_dir or "uploads"
        os.makedirs(self.upload_dir, exist_ok=True)

    def parse(self, file_path: str, file_type: str = None) -> Dict[str, any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        if not file_type:
            file_type = self._detect_file_type(file_path)

        if file_type == "application/pdf" or file_path.lower().endswith('.pdf'):
            return self._parse_pdf(file_path)
        elif file_type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          "application/msword"] or file_path.lower().endswith(('.docx', '.doc')):
            return self._parse_word(file_path)
        elif file_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          "application/vnd.ms-excel"] or file_path.lower().endswith(('.xlsx', '.xls')):
            return self._parse_excel(file_path)
        elif file_type == "text/plain" or file_path.lower().endswith('.txt'):
            return self._parse_txt(file_path)
        else:
            return self._parse_txt(file_path)

    def _detect_file_type(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        type_map = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.txt': 'text/plain'
        }
        return type_map.get(ext, 'text/plain')

    def _compute_sha256(self, file_path: str) -> str:
        """计算文件 SHA-256"""
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()

    def _parse_pdf(self, file_path: str) -> Dict[str, any]:
        if pdfplumber is None:
            raise ImportError("pdfplumber未安装，请运行: pip install pdfplumber")
        text_content = ""
        pages_count = 0
        try:
            with pdfplumber.open(file_path) as pdf:
                pages_count = len(pdf.pages)
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content += page_text + "\n"
        except Exception as e:
            raise Exception(f"PDF解析失败: {str(e)}")
        paragraphs = [(line.strip(), i) for i, line in enumerate(text_content.split('\n')) if line.strip()]
        return {
            "content": text_content.strip(),
            "paragraphs": paragraphs,
            "paragraph_count": len(paragraphs),
            "pages": pages_count,
            "file_type": "pdf",
            "sha256": self._compute_sha256(file_path),
        }

    def _parse_word(self, file_path: str) -> Dict[str, any]:
        if DocxDocument is None:
            raise ImportError("python-docx未安装，请运行: pip install python-docx")
        try:
            doc = DocxDocument(file_path)
            paragraphs_with_text = []
            all_text_lines = []
            for i, para in enumerate(doc.paragraphs):
                text = para.text.strip()
                if text:
                    paragraphs_with_text.append((text, i))
                    all_text_lines.append(text)
        except Exception as e:
            raise Exception(f"Word解析失败: {str(e)}")

        return {
            "content": "\n".join(all_text_lines).strip(),
            "paragraphs": paragraphs_with_text,
            "paragraph_count": len(paragraphs_with_text),
            "file_type": "word",
            "sha256": self._compute_sha256(file_path),
        }

    def _parse_excel(self, file_path: str) -> Dict[str, any]:
        if pd is None:
            raise ImportError("pandas未安装，请运行: pip install pandas openpyxl")
        all_text = []
        sheets_count = 0
        try:
            excel_file = pd.ExcelFile(file_path)
            sheets_count = len(excel_file.sheet_names)
            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
                df = df.dropna(how='all').fillna('')
                first_row = [str(v).lower() for v in df.iloc[0]] if len(df) > 0 else []
                content_col = None
                for i, c in enumerate(first_row):
                    if any(k in c for k in ['内容', '条文', '正文', 'text', 'content']):
                        content_col = i
                        break
                if content_col is None and len(df.columns) >= 2:
                    content_col = 1
                elif content_col is None:
                    content_col = 0
                start_row = 1 if any(k in ' '.join(first_row) for k in ['编号', '条', '内容', '来源']) else 0
                rows = []
                for idx in range(start_row, len(df)):
                    row = df.iloc[idx]
                    vals = [str(v).strip() for v in row if str(v).strip()]
                    if not vals:
                        continue
                    cell = vals[content_col] if content_col < len(vals) else (vals[-1] if vals else "")
                    if cell and len(cell) > 15:
                        rows.append(cell)
                sheet_text = f"\n=== 工作表: {sheet_name} ===\n" + "\n\n".join(rows)
                all_text.append(sheet_text)
            text_content = "\n\n".join(all_text).strip()
        except Exception as e:
            raise Exception(f"Excel解析失败: {str(e)}")
        paragraphs = [(line.strip(), i) for i, line in enumerate(text_content.split('\n')) if line.strip()]
        return {
            "content": text_content,
            "paragraphs": paragraphs,
            "paragraph_count": len(paragraphs),
            "sheets": sheets_count,
            "file_type": "excel",
            "sha256": self._compute_sha256(file_path),
        }

    def _parse_txt(self, file_path: str) -> Dict[str, any]:
        try:
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
            text_content = None
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        text_content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            if text_content is None:
                raise Exception("无法使用常见编码读取文件")
        except Exception as e:
            raise Exception(f"TXT解析失败: {str(e)}")
        paragraphs = [(line.strip(), i) for i, line in enumerate(text_content.split('\n')) if line.strip()]
        return {
            "content": text_content,
            "paragraphs": paragraphs,
            "paragraph_count": len(paragraphs),
            "file_type": "txt",
            "sha256": self._compute_sha256(file_path),
        }

    def _detect_source_book(self, content: str, filename: str = "") -> str:
        combined = (content[:3000] + " " + filename).lower()
        # 1. 文件名优先：金匮章节特征（如"XX病脉证并治第X"）→ 金匮
        if re.search(r'病脉证[并治]*[第]?[一二三四五六七八九十百廿卅]+', filename):
            return "《金匮要略》"
        # 2. 内容扫描金匮药专属关键词（"金匮"字面不会在伤寒论正文中出现）
        if any(kw in combined for kw in ["金匮", "金匮要略"]):
            return "《金匮要略》"
        # 3. 内容开头包含金匮章节标题（如"XX病脉证并治第X"）→ 金匮
        if re.search(r'病脉证[并治]*[第]?[一二三四五六七八九十百廿卅]+', content[:5000]):
            return "《金匮要略》"
        # 4. 伤寒论章节标题（辨太阳/阳明等病脉证并治）→ 伤寒
        if re.search(r'辨(太阳|阳明|少阳|太阴|少阴|厥阴|霍乱)病脉证并治', content[:5000]):
            return "《伤寒论》"
        # 5. 文件名不含金匮特征，内容出现"伤寒论"→ 伤寒论
        if any(kw in combined for kw in ["伤寒论"]):
            return "《伤寒论》"
        # 6. 无法判断时，返回空让调用方通过其他方式推断
        return ""

    # ── 新版提取入口 ──

    def extract_texts_and_cases(
        self, content: str, filename: str = "",
        paragraphs: List[Tuple[str, int]] = None,
    ) -> Dict[str, any]:
        """
        从解析的文本中提取条文和病案。

        优先使用 paragraphs（段落列表）进行句末条号收束切分；
        若无 paragraphs（如 PDF 纯文本），回退到旧版兼容模式。

        返回: {
            "texts": [{
                "article_number": int,
                "raw_content": str,
                "content": str,
                "layout_marker": str,
                "source_book": str,
                "chapter": str,
                "section": str,
                "source_offset": int,
            }, ...],
            "cases": [...]
        }
        """
        source_book = self._detect_source_book(content, filename)

        # ── 优先：句末条号收束切分（需要段落信息）──
        if paragraphs and len(paragraphs) > 5:
            articles = _split_by_sentence_end_number(paragraphs)
            if len(articles) >= 3:
                texts_raw = []
                for art in articles:
                    if not art.get("content") or len(art["content"]) < 5:
                        continue
                    texts_raw.append({
                        "article_number": art["article_number"],
                        "raw_content": art["raw_content"],
                        "content": art["content"],
                        "layout_marker": art.get("layout_marker"),
                        "source_book": source_book,
                        "chapter": art.get("chapter"),
                        "section": art.get("section"),
                        "source_offset": art.get("source_offset"),
                    })
                return {"texts": texts_raw, "cases": []}

        # ── 回退：兼容无段落信息的纯文本 ──
        return self._extract_legacy(content, filename, source_book)

    def _extract_legacy(self, content: str, filename: str, source_book: str) -> Dict[str, any]:
        """旧版兼容提取（用于无段落信息的纯文本/PDF）"""
        texts_raw = []
        seen_texts = set()

        # 找所有句末 （数字/中文数字） 的位置，按位置切割
        nums_positions = []
        for m in re.finditer(r'[（(](\d{1,3}|[一二三四五六七八九十百廿卅]+)[）)]', content):
            num_str = m.group(1)
            num = int(num_str) if num_str.isdigit() else (_CN_NUM_MAP.get(num_str) or 0)
            nums_positions.append((m.end(), num))

        if len(nums_positions) < 5:
            return self._extract_fallback(content, source_book)

        prev_end = 0
        for end_pos, num in nums_positions:
            segment = content[prev_end:end_pos].strip()
            prev_end = end_pos
            if len(segment) < 15:
                continue
            cleaned = _clean_display_content(segment)
            if cleaned and cleaned not in seen_texts:
                seen_texts.add(cleaned)
                texts_raw.append({
                    "article_number": num,
                    "raw_content": segment,
                    "content": cleaned,
                    "layout_marker": None,
                    "source_book": source_book,
                    "chapter": None,
                    "section": None,
                    "source_offset": None,
                })

        return {"texts": texts_raw, "cases": []}

    def _extract_fallback(self, content: str, source_book: str) -> Dict[str, any]:
        """最终的兜底策略"""
        texts_raw = []
        seen = set()
        # 按六经病开头切
        for sep in ['太阳病', '阳明病', '少阳病', '太阴病', '少阴病', '厥阴病']:
            parts = content.split(sep)
            for p in parts[1:]:
                rest = p.strip()
                for ns in ['太阳病', '阳明病', '少阳病', '太阴病', '少阴病', '厥阴病', '伤寒']:
                    if ns in rest[1:]:
                        rest = rest[:rest.index(ns)]
                t = (sep + rest).strip()
                if 25 < len(t) < 1500 and t not in seen:
                    seen.add(t)
                    texts_raw.append({
                        "article_number": None,
                        "raw_content": t,
                        "content": t,
                        "layout_marker": None,
                        "source_book": source_book,
                        "chapter": None,
                        "section": None,
                        "source_offset": None,
                    })
        return {"texts": texts_raw, "cases": []}
