"""结构化评分：把「LLM 自由打分」换成「按要点逐条对照」。

原来的评价只有一次模型调用，同一个学生重做同一份病案分数会浮动几十分，
学生也看不出分扣在哪里。这里把评分依据显式存进病案（``scoring_points``），
按学生原话逐条比对，给出可复现、可解释的明细。

要点结构::

    {
        "stage": "辨病",                 # 辨病 / 平脉 / 析证 / 定治
        "text": "辨为少阳枢机不利",       # 要点描述（展示给学生看）
        "weight": 20,                    # 权重（不要求和为 100，按实际总和归一）
        "keywords": ["少阳", "枢机"],     # 命中任一即算答对
        "min_level": "初级"              # 从哪一档难度开始计入
    }

``min_level`` 是「阶梯递进」语义：初级档只统计 min_level=初级 的要点，
中级追加「中级」，高级统计全部。初级学生因此不会被
「你要能说出方证的鉴别」这类高级要求扣分——这正是 P3 要解决的问题。

缺 ``keywords`` 的要点不做自动判定（``hit=None``），也不进入分母，
避免配置不全时把学生误判成没答对。

``messages`` 的 role 兼容 ``user`` / ``student`` 两种写法（训练会话两处都用过）。
"""

from typing import Any, Dict, Iterable, List, Optional

LEVEL_ORDER = {"初级": 1, "中级": 2, "高级": 3}
DEFAULT_LEVEL = "初级"
DEFAULT_MIN_LEVEL = "初级"


# ---------- 难度过滤 ----------

def normalize_level(level: Optional[str]) -> str:
    """把任意输入收敛到三档之一，未知值按初级处理。"""
    if isinstance(level, str) and level.strip() in LEVEL_ORDER:
        return level.strip()
    return DEFAULT_LEVEL


def _min_level(point: Dict[str, Any]) -> str:
    raw = point.get("min_level")
    if isinstance(raw, str) and raw.strip() in LEVEL_ORDER:
        return raw.strip()
    return DEFAULT_MIN_LEVEL


def select_points(points: Optional[Iterable], level: Optional[str]) -> List[dict]:
    """挑出当前难度应当计入的要点。"""
    current = LEVEL_ORDER[normalize_level(level)]
    selected = []
    for point in points or []:
        if not isinstance(point, dict):
            continue
        if LEVEL_ORDER[_min_level(point)] <= current:
            selected.append(point)
    return selected


def excluded_count(points: Optional[Iterable], level: Optional[str]) -> int:
    """统计因为难度不够而被排除的要点数量，用于向学生解释「还有没到考的部分」。"""
    total = len([p for p in (points or []) if isinstance(p, dict)])
    return total - len(select_points(points, level))


# ---------- 文本匹配 ----------

def student_text(messages: Optional[Iterable[dict]]) -> str:
    """拼接学生本人说过的话，患者/系统消息不参与评分。"""
    parts = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role not in ("user", "student"):
            continue
        content = message.get("content")
        if content:
            parts.append(str(content))
    return "\n".join(parts)


def _match_keywords(text: str, keywords: Optional[Iterable]) -> Optional[str]:
    if not text or not keywords:
        return None
    for keyword in keywords:
        if not keyword:
            continue
        token = str(keyword).strip()
        if token and token in text:
            return token
    return None


def _weight_of(point: Dict[str, Any]) -> float:
    try:
        value = float(point.get("weight", 0))
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


# ---------- 评分要点 ----------

def evaluate_points(
    points: Optional[Iterable],
    level: Optional[str],
    messages: Optional[Iterable[dict]],
) -> List[dict]:
    """逐条对照，返回每个要点的命中情况。"""
    text = student_text(messages)
    results = []
    for point in select_points(points, level):
        keywords = point.get("keywords") or []
        matched = _match_keywords(text, keywords)
        auto = bool(keywords)
        results.append({
            "stage": str(point.get("stage") or "其他"),
            "text": str(point.get("text") or ""),
            "weight": _weight_of(point),
            "min_level": _min_level(point),
            "auto": auto,
            "hit": (matched is not None) if auto else None,
            "evidence": matched,
            # strict = 只认字面，不接受语义复核。方剂名、是否做了鉴别这类
            # 事实，模型很容易「牵强附会」判成命中——实测学生一个方没开，
            # 复核却凭一句「调和营卫」把「方选柴胡桂枝汤」判成答对。
            "strict": bool(point.get("strict")),
        })
    return results


def _summarize_by_stage(point_results: List[dict]) -> Dict[str, dict]:
    stages: Dict[str, dict] = {}
    for item in point_results:
        bucket = stages.setdefault(
            item["stage"], {"total": 0.0, "max": 0.0, "hits": 0, "count": 0}
        )
        bucket["count"] += 1
        if item["hit"] is None:
            continue
        bucket["max"] += item["weight"]
        if item["hit"]:
            bucket["total"] += item["weight"]
            bucket["hits"] += 1
    return stages


def _finalize(scoring: dict, point_results: List[dict]) -> dict:
    """按当前命中情况重算总分。规则判定与语义复核后都要走这里。"""
    scored = [item for item in point_results if item["hit"] is not None]
    total = sum(item["weight"] for item in scored if item["hit"])
    maximum = sum(item["weight"] for item in scored)
    ratio = (total / maximum) if maximum > 0 else 0.0
    scoring["points"] = point_results
    scoring["by_stage"] = _summarize_by_stage(point_results)
    scoring["gradable"] = maximum > 0
    scoring["total"] = round(total, 1)
    scoring["max"] = round(maximum, 1)
    scoring["ratio"] = round(ratio, 4)
    scoring["percent"] = round(ratio * 100, 1) if maximum > 0 else None
    return scoring


# ---------- 问诊完整度 ----------

def _fact_keywords(fact: Dict[str, Any]) -> List[str]:
    """问诊要点的匹配词：显式 keywords 优先，否则退化为标签本身。"""
    keywords = [str(k) for k in (fact.get("keywords") or []) if k]
    if keywords:
        return keywords
    label = fact.get("label")
    return [str(label)] if label else []


def patient_text(messages: Optional[Iterable[dict]]) -> str:
    """患者说过的话，用来判断某些信息是不是患者自己主动交代的。"""
    parts = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role in ("user", "student"):
            continue
        content = message.get("content")
        if content:
            parts.append(str(content))
    return "\n".join(parts)


def evaluate_key_facts(
    key_facts: Optional[Iterable],
    level: Optional[str],
    messages: Optional[Iterable[dict]],
) -> Optional[dict]:
    """统计关键信息是否已经到手。

    **不说「漏问」除非真的漏**：患者开场白往往已经把病程、季节、口苦、心烦
    一次说完，学生根本不需要再问一遍。所以这里分三档：
    - ``asked``    学生主动问到的
    - ``revealed`` 患者自己交代的（开场白或回答里已经说了）
    - ``missing``  双方都没提到，才是真正需要补的

    这是辅助指标，不参与主分——没问到不等于答错。
    """
    facts = select_points(key_facts, level)
    if not facts:
        return None
    student = student_text(messages)
    patient = patient_text(messages)
    must = [f for f in facts if f.get("must_ask", True)]
    asked, revealed, missing = [], [], []
    for fact in must:
        label = str(fact.get("label") or fact.get("id") or "未命名")
        keywords = _fact_keywords(fact)
        if _match_keywords(student, keywords):
            asked.append(label)
        elif _match_keywords(patient, keywords):
            revealed.append(label)
        else:
            missing.append(label)
    total = len(must)
    covered = len(asked) + len(revealed)
    return {
        "asked": len(asked),
        "revealed": len(revealed),
        "total": total,
        "ratio": (covered / total) if total else 0.0,
        "missing": missing,
    }


# ---------- 汇总 ----------

def evaluate_scoring(
    medical_case: Any,
    level: Optional[str],
    messages: Optional[Iterable[dict]],
) -> Optional[dict]:
    """计算一份会话的结构化得分；病案没配要点时返回 None（调用方沿用旧评分）。"""
    points = getattr(medical_case, "scoring_points", None) or []
    facts = getattr(medical_case, "key_facts", None) or []
    if not points and not facts:
        return None

    point_results = evaluate_points(points, level, messages)
    scoring = {
        "level": normalize_level(level),
        "excluded": excluded_count(points, level),
        "key_facts": evaluate_key_facts(facts, level, messages),
        "semantic_review": None,
    }
    return _finalize(scoring, point_results)


# ---------- 语义复核 ----------
# 关键词匹配有个绕不过去的短板：学生说「嘴巴又干又苦」，规则认不出这就是「口苦」；
# 患者开场白明明交代过季节规律，规则也认不出「一到春天和秋天」。
# 所以规则判完后，把「没判上的部分」交给模型再看一遍——只判这些，成本很低，
# 也避免模型推翻已经明确命中的条目。

SEMANTIC_REVIEW_TEMPLATE = """下面是一次中医临床思维训练中，程序按关键词没能判定的部分。请逐条复核。

【一】评分要点：判断学生是否**用明确的表述**表达了该要点的核心意思。
严格执行以下规则：
- 必须从"学生原话"里摘出一句能**直接支撑**该要点的原文作为依据；
- 只是提到相关术语、没有做出相应判断的，判「没有」；
- 学生没有明说的内容，一律判「没有」；
- 摘不出依据，就判「没有」。

宁可判「没有」，也不要给人情分。学生开没开方、做没做鉴别、说没说方义，
这些必须以原话为准。

要点：
{point_block}

学生原话：
{student_text}

【二】关键信息：判断患者是否**自己主动说出**过这些信息（不是被问出来的）。
同样必须摘出患者原话作为依据。

信息：
{fact_block}

患者说过的话：
{patient_text}

只输出 JSON，不要解释，不要多余文字：
{{"要点": [{{"编号": 1, "依据": "学生原话片段"}}],
  "信息": [{{"编号": 1, "依据": "患者原话片段"}}]}}

只列出你确认对方**确实说过**的条目，没列出的按「没有」处理。
依据必须逐字摘自原文，不要改写、不要合并、不要加引号以外的符号。
大多数条目都应该判「没有」，有把握才列。"""


def build_semantic_review(
    scoring: Optional[dict],
    messages: Optional[Iterable[dict]],
) -> Optional[dict]:
    """把规则没判定的部分打包成一次语义复核请求；没有可复核项时返回 None。"""
    if not scoring:
        return None
    # strict 要点不送审：方剂、鉴别这类事实只认字面
    missed = [
        item for item in scoring.get("points", [])
        if item["hit"] is False and not item.get("strict")
    ]
    facts = scoring.get("key_facts") or {}
    missing_facts = list(facts.get("missing") or [])
    if not missed and not missing_facts:
        return None

    point_block = "\n".join(
        f"{index}. （{item['stage']}）{item['text']}"
        for index, item in enumerate(missed, start=1)
    ) or "（无）"
    fact_block = "\n".join(
        f"{index}. {label}" for index, label in enumerate(missing_facts, start=1)
    ) or "（无）"
    said_by_student = student_text(messages)
    said_by_patient = patient_text(messages)

    prompt = SEMANTIC_REVIEW_TEMPLATE.format(
        point_block=point_block,
        student_text=said_by_student or "（学生没有发言）",
        fact_block=fact_block,
        patient_text=said_by_patient or "（患者没有发言）",
    )
    return {
        "prompt": prompt,
        "missed_points": missed,        # 引用原列表，应用时原地修改
        "missing_facts": missing_facts,
        "scoring": scoring,
        "student_text": said_by_student,
        "patient_text": said_by_patient,
    }


def _evidence_supported(evidence: Any, source: str) -> bool:
    """模型给出的依据必须真的能在原文里找到，否则不采纳。

    没有这道闸，模型会顺手把「没判上」的要点全判成「表达了」——
    实测中 11 条全被判命中，直接给了满分。
    """
    if not evidence or not source:
        return False
    text = str(evidence).strip().strip("「」\"'“”")
    if len(text) < 2:
        return False
    return text in source


def _collect_verdicts(raw: Any, upper: int) -> List[tuple]:
    """解析模型返回的条目数组：编号合法即入选，依据是否可信另行校验。"""
    if not isinstance(raw, list):
        return []
    accepted = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("编号"))
        except (TypeError, ValueError):
            continue
        if not (1 <= index <= upper):
            continue
        accepted.append((index - 1, str(item.get("依据") or "")))
    return accepted


def apply_semantic_review(request: dict, verdict: Optional[dict]) -> dict:
    """把模型的复核结果并回评分。证据对不上原文的一律不采纳。"""
    scoring = request["scoring"]
    if not isinstance(verdict, dict):
        return scoring

    student = request.get("student_text") or ""
    patient = request.get("patient_text") or ""
    missed = request["missed_points"]
    missing_facts = request["missing_facts"]
    adopted_points, rejected_points = 0, 0

    for index, evidence in _collect_verdicts(verdict.get("要点"), len(missed)):
        if _evidence_supported(evidence, student):
            missed[index]["hit"] = True
            missed[index]["evidence"] = "语义判定"
            adopted_points += 1
        else:
            rejected_points += 1

    adopted_facts, rejected_facts = 0, 0
    facts = scoring.get("key_facts") or {}
    for index, evidence in _collect_verdicts(verdict.get("信息"), len(missing_facts)):
        label = missing_facts[index]
        if not _evidence_supported(evidence, patient):
            rejected_facts += 1
            continue
        if label in facts.get("missing", []):
            facts["missing"].remove(label)
            facts["revealed"] = facts.get("revealed", 0) + 1
            total = facts.get("total") or 1
            facts["ratio"] = round(
                (facts.get("asked", 0) + facts["revealed"]) / total, 4
            )
            adopted_facts += 1

    scoring["semantic_review"] = {
        "checked_points": len(missed),
        "checked_facts": len(missing_facts),
        "adopted_points": adopted_points,
        "rejected_points": rejected_points,
        "adopted_facts": adopted_facts,
        "rejected_facts": rejected_facts,
    }
    return _finalize(scoring, scoring["points"])


def format_scoring_brief(scoring: Optional[dict]) -> str:
    """把要点得分压成一句话，写进评价报告的「要点得分」。"""
    if not scoring or not scoring.get("gradable"):
        return ""
    head = f"{scoring['percent']:.0f} 分（{scoring['total']:g}/{scoring['max']:g}）"
    missed = [item["text"] for item in scoring.get("points", []) if item["hit"] is False]
    if missed:
        head += "；未覆盖：" + "、".join(missed[:3])
        if len(missed) > 3:
            head += f" 等 {len(missed)} 项"
    facts = scoring.get("key_facts") or {}
    if facts.get("missing"):
        head += "；仍缺：" + "、".join(facts["missing"][:4])
    return head
