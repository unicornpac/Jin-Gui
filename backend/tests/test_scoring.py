"""结构化要点评分 —— 难度过滤、关键词命中、语义复核、问诊完整度与评价接入。"""

import pytest

from app.models import TrainingSession

# ==================== 结构化评分（P3） ====================

_CASE_POINTS = [
    {"stage": "辨病", "text": "辨为少阳枢机不利", "weight": 20,
     "keywords": ["少阳"], "min_level": "初级"},
    {"stage": "平脉", "text": "脉弦主少阳", "weight": 15,
     "keywords": ["弦"], "min_level": "初级"},
    {"stage": "析证", "text": "往来寒热属枢机不利", "weight": 25,
     "keywords": ["枢机", "往来寒热"], "min_level": "中级"},
    {"stage": "定治", "text": "治以和解少阳", "weight": 20,
     "keywords": ["和解"], "min_level": "中级"},
    {"stage": "定治", "text": "方选柴胡桂枝汤", "weight": 20,
     "keywords": ["柴胡桂枝"], "min_level": "高级"},
]

_CASE_FACTS = [
    {"id": "chief", "label": "主诉", "must_ask": True, "keywords": ["怕冷", "发热"]},
    {"id": "sweat", "label": "出汗", "must_ask": True, "keywords": ["汗"]},
    {"id": "stool", "label": "大便", "must_ask": False, "keywords": ["大便"]},
]


def _fake_case(**overrides):
    from types import SimpleNamespace
    data = {
        "scoring_points": _CASE_POINTS,
        "key_facts": _CASE_FACTS,
        "prescription": "柴胡桂枝汤",
        "title": "反复感冒",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestScoringLevelFilter:
    """层级过滤：初级学生不该被高级要点扣分。"""

    def test_points_selected_by_level(self):
        from app.services.scoring import select_points, excluded_count
        # 初级只计 min_level=初级 的两条；中级追两条；高级再追一条
        assert len(select_points(_CASE_POINTS, "初级")) == 2
        assert len(select_points(_CASE_POINTS, "中级")) == 4
        assert len(select_points(_CASE_POINTS, "高级")) == 5
        # 未知档位一律按初级处理
        assert len(select_points(_CASE_POINTS, None)) == 2
        assert len(select_points(_CASE_POINTS, "专家")) == 2
        assert excluded_count(_CASE_POINTS, "初级") == 3
        assert excluded_count(_CASE_POINTS, "高级") == 0

    def test_beginner_keeps_only_beginner_texts(self):
        from app.services.scoring import select_points
        picked = [p["text"] for p in select_points(_CASE_POINTS, "初级")]
        assert picked == ["辨为少阳枢机不利", "脉弦主少阳"]


class TestScoringEvaluate:
    """逐条对照打分。"""

    def test_beginner_score_normalized_within_own_pool(self):
        """同样只说对「少阳」，初级按 35 分满分算，不会被高级要点稀释。"""
        from app.services.scoring import evaluate_scoring
        messages = [{"role": "user", "content": "考虑少阳枢机不利"}]
        result = evaluate_scoring(_fake_case(), "初级", messages)
        assert result["max"] == 35
        assert result["total"] == 20
        assert result["percent"] == pytest.approx(57.1, abs=0.1)

    def test_advanced_same_answer_scores_lower(self):
        from app.services.scoring import evaluate_scoring
        messages = [{"role": "user", "content": "考虑少阳枢机不利"}]
        result = evaluate_scoring(_fake_case(), "高级", messages)
        assert result["max"] == 100
        # 「少阳」命中辨病 20 分，「枢机」命中级析证 25 分，其余未答
        assert result["percent"] == pytest.approx(45.0, abs=0.1)

    def test_full_answer_scores_full_marks(self):
        from app.services.scoring import evaluate_scoring
        messages = [{"role": "user", "content":
                     "辨少阳枢机不利，脉弦，病机属枢机不利、往来寒热，治以和解，方用柴胡桂枝汤"}]
        result = evaluate_scoring(_fake_case(), "高级", messages)
        assert result["percent"] == 100.0

    def test_patient_lines_do_not_count(self):
        """患者自己说的不算学生答对。"""
        from app.services.scoring import evaluate_scoring
        messages = [{"role": "assistant", "content": "大夫，我这少阳枢机不利吧"}]
        result = evaluate_scoring(_fake_case(), "初级", messages)
        assert result["total"] == 0

    def test_points_without_keywords_are_not_graded(self):
        """没写关键词的要点不判定、也不进分母，避免配置不全时误扣分。"""
        from app.services.scoring import evaluate_scoring
        case = _fake_case(scoring_points=[
            {"stage": "辨病", "text": "无关键词要点", "weight": 30, "min_level": "初级"},
            {"stage": "辨病", "text": "有关键词", "weight": 10,
             "keywords": ["少阳"], "min_level": "初级"},
        ])
        result = evaluate_scoring(case, "初级", [{"role": "user", "content": "少阳"}])
        assert result["max"] == 10          # 无关键词的要点不进分母
        assert result["percent"] == 100.0
        assert result["points"][0]["hit"] is None

        # 一条都判不了时标成不可判定，调用方不会用 0 分覆盖原评分
        ungradable = evaluate_scoring(
            _fake_case(scoring_points=[{"stage": "辨病", "text": "没关键词", "weight": 30}],
                       key_facts=[]),
            "初级", [{"role": "user", "content": "少阳"}],
        )
        assert ungradable["gradable"] is False
        assert ungradable["percent"] is None

    def test_no_config_returns_none(self):
        from app.services.scoring import evaluate_scoring
        case = _fake_case(scoring_points=[], key_facts=[])
        assert evaluate_scoring(case, "初级", [{"role": "user", "content": "少阳"}]) is None

    def test_by_stage_summary(self):
        from app.services.scoring import evaluate_scoring
        messages = [{"role": "user", "content": "少阳，脉弦"}]
        result = evaluate_scoring(_fake_case(), "初级", messages)
        assert result["by_stage"]["辨病"]["total"] == 20
        assert result["by_stage"]["平脉"]["total"] == 15

    def test_key_facts_track_asked_and_missing(self):
        from app.services.scoring import evaluate_scoring
        asked = evaluate_scoring(
            _fake_case(), "初级", [{"role": "user", "content": "你怕冷发热吗？出汗多不多？"}]
        )["key_facts"]
        assert asked["asked"] == 2
        assert asked["total"] == 2
        assert asked["missing"] == []

        partial = evaluate_scoring(
            _fake_case(), "初级", [{"role": "user", "content": "你怕冷吗"}]
        )["key_facts"]
        assert partial["missing"] == ["出汗"]

    def test_brief_summarises_score_and_gaps(self):
        from app.services.scoring import evaluate_scoring, format_scoring_brief
        brief = format_scoring_brief(
            evaluate_scoring(_fake_case(), "初级", [{"role": "user", "content": "少阳"}])
        )
        assert "57" in brief
        assert "未覆盖" in brief
        # 没有可判定内容时不产生空摘要
        assert format_scoring_brief(None) == ""
        assert format_scoring_brief({"gradable": False}) == ""


class TestSemanticReview:
    """语义复核：只把规则没判上的部分交给模型。"""

    def _review(self):
        from app.services.scoring import evaluate_scoring, build_semantic_review
        messages = [{"role": "user", "content": "考虑少阳"}]
        scoring = evaluate_scoring(_fake_case(), "初级", messages)
        return scoring, build_semantic_review(scoring, messages)

    def test_only_unmatched_points_are_reviewed(self):
        from app.services.scoring import evaluate_scoring, build_semantic_review
        messages = [
            {"role": "user", "content": "考虑少阳"},
            {"role": "user", "content": "腰不酸"},
        ]
        scoring = evaluate_scoring(_fake_case(), "初级", messages)
        review = build_semantic_review(scoring, messages)
        # 「少阳」已命中辨病，送审的只剩「脉弦」一条
        assert len(review["missed_points"]) == 1
        assert all(item["hit"] is False for item in review["missed_points"])

    def test_prompt_contains_student_words(self):
        _, review = self._review()
        assert "考虑少阳" in review["prompt"]
        assert "脉弦主少阳" in review["prompt"]

    def test_evidence_must_be_traceable(self):
        """模型给的依据必须能在原话里找到，否则不采纳。

        没有这道闸，模型会把「没判上」的要点全判命中——实测直接给了满分。
        """
        from app.services.scoring import apply_semantic_review
        scoring, review = self._review()
        before = scoring["total"]

        adopted = apply_semantic_review(review, {"要点": [
            {"编号": 1, "依据": "考虑少阳"},          # 原话里有，采纳
        ]})
        assert adopted["total"] > before
        assert adopted["semantic_review"]["adopted_points"] == 1

        _, review2 = self._review()
        rejected = apply_semantic_review(review2, {"要点": [
            {"编号": 1, "依据": "脉弦主少阳肝胆气郁"},  # 原话里没有，驳回
        ]})
        assert rejected["total"] == before
        assert rejected["semantic_review"]["rejected_points"] == 1

    def test_apply_marks_revealed_facts(self):
        from app.services.scoring import (
            evaluate_scoring, build_semantic_review, apply_semantic_review,
        )
        messages = [
            {"role": "user", "content": "考虑少阳"},
            {"role": "assistant", "content": "最近老觉得身上发冷"},
        ]
        scoring = evaluate_scoring(_fake_case(), "初级", messages)
        review = build_semantic_review(scoring, messages)
        assert review["missing_facts"] == ["主诉", "出汗"]
        updated = apply_semantic_review(review, {"信息": [
            {"编号": 1, "已说": True, "依据": "身上发冷"},
        ]})
        assert updated["key_facts"]["revealed"] == 1
        assert updated["key_facts"]["missing"] == ["出汗"]

    def test_bad_verdict_is_ignored(self):
        from app.services.scoring import apply_semantic_review
        scoring, review = self._review()
        before = scoring["total"]
        for bad in (None, "不是字典", {"要点": [{"编号": "x"}]}, {}, {"要点": "全对"}):
            assert apply_semantic_review(review, bad)["total"] == before

    def test_no_review_when_nothing_to_check(self):
        from app.services.scoring import evaluate_scoring, build_semantic_review
        # 没有评分数据
        assert build_semantic_review(None, []) is None
        # 全部要点都已命中，没有可送审的内容
        case = _fake_case(scoring_points=[
            {"stage": "辨病", "text": "少阳", "weight": 10,
             "keywords": ["少阳"], "min_level": "初级"},
        ], key_facts=[])
        messages = [{"role": "user", "content": "少阳"}]
        scoring = evaluate_scoring(case, "初级", messages)
        assert build_semantic_review(scoring, messages) is None

    def test_lenient_parse(self):
        """模型输出的 JSON 偶尔会坏掉，不能因此让整次复核白跑。"""
        from app.services.agent_service import TrainingAgent
        broken = ('{"要点": [{"编号": 1, "依据": "考虑少阳"}], '
                  '"信息": [{"编号": 2, "依据": "我怕冷"}]')   # 缺最外层右括号
        parsed = TrainingAgent._parse_semantic_verdict(broken)
        assert parsed is not None
        assert parsed["要点"][0]["依据"] == "考虑少阳"
        assert parsed["信息"][0]["编号"] == 2
        assert TrainingAgent._parse_semantic_verdict("模型没按要求输出") is None


class TestKeyFactsRevealed:
    """患者开场白已经说过的信息，不该算学生「漏问」。"""

    def test_three_states(self):
        from app.services.scoring import evaluate_key_facts
        # 患者开场白全说了 → 全算「已交代」，不报漏问
        revealed = evaluate_key_facts(_CASE_FACTS, "初级", [
            {"role": "assistant", "content": "我怕冷，也不太出汗"},
            {"role": "user", "content": "嗯，你说说"},
        ])
        assert revealed["revealed"] == 2
        assert revealed["missing"] == []
        assert revealed["ratio"] == 1.0

        # 学生问到的与患者交代的分别计数
        mixed = evaluate_key_facts(_CASE_FACTS, "初级", [
            {"role": "assistant", "content": "我有点怕冷"},
            {"role": "user", "content": "出汗多吗"},
        ])
        assert mixed["asked"] == 1
        assert mixed["revealed"] == 1
        assert mixed["missing"] == []

        # 双方都没提，才是真的缺
        missing = evaluate_key_facts(_CASE_FACTS, "初级", [
            {"role": "assistant", "content": "我有点怕冷"},
            {"role": "user", "content": "什么时候开始的"},
        ])
        assert missing["missing"] == ["出汗"]


class TestEvaluateSessionWithScoring:
    """评价接入：配了要点就按要点给分，没配就沿用模型分。"""

    def _prepare(self, db_session, agent, case, level, student_lines):
        from app.models import SessionMessage
        session = TrainingSession(
            student_id="test_scoring", difficulty_level=level,
            case_id=case.id, status="active",
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)
        for line in student_lines:
            db_session.add(SessionMessage(
                session_id=session.id, role="student", content=line))
        db_session.commit()
        agent.client = None          # 不触发真实模型调用
        return session

    def test_score_comes_from_scoring_points(self, db_session, agent,
                                             sample_case_advanced):
        sample_case_advanced.scoring_points = _CASE_POINTS
        sample_case_advanced.key_facts = _CASE_FACTS
        db_session.commit()
        session = self._prepare(db_session, agent, sample_case_advanced,
                                "初级", ["考虑少阳枢机不利"])
        result = agent.evaluate_session(db_session, session.id)
        assert result["scoring"]["gradable"] is True
        assert result["score"] == "57.1"
        db_session.refresh(session)
        assert session.scoring["percent"] == pytest.approx(57.1, abs=0.1)
        assert session.evaluation             # 评价原文已落库

    def test_level_changes_same_answer_score(self, db_session, agent,
                                             sample_case_advanced):
        sample_case_advanced.scoring_points = _CASE_POINTS
        db_session.commit()
        beginner = self._prepare(db_session, agent, sample_case_advanced,
                                 "初级", ["考虑少阳枢机不利"])
        r1 = agent.evaluate_session(db_session, beginner.id)

        advanced = self._prepare(db_session, agent, sample_case_advanced,
                                 "高级", ["考虑少阳枢机不利"])
        r2 = agent.evaluate_session(db_session, advanced.id)
        assert float(r1["score"]) > float(r2["score"])

    def test_no_config_keeps_legacy_behaviour(self, db_session, agent,
                                              sample_case_beginner):
        session = self._prepare(db_session, agent, sample_case_beginner,
                                "初级", ["我看看"])
        result = agent.evaluate_session(db_session, session.id)
        assert result["scoring"] is None
        assert result["score"] == "未评分"    # 无模型、无要点时的占位，未被覆盖
