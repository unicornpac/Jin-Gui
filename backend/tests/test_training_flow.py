"""训练流程 —— 四阶段进度判定、诊法直出、阶段引导，以及 AI 复核的边界约束。"""

from unittest.mock import MagicMock, patch

import pytest

from app.models import MedicalCase, TrainingSession

# ==================== 进度分析 ====================

@pytest.fixture
def beginner_session(db_session, sample_case_beginner):
    s = TrainingSession(
        student_id="test_student", difficulty_level="初级",
        case_id=sample_case_beginner.id, status="active",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


@pytest.fixture
def intermediate_session(db_session, sample_case_intermediate):
    s = TrainingSession(
        student_id="test_student", difficulty_level="中级",
        case_id=sample_case_intermediate.id, status="active",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


@pytest.fixture
def advanced_session(db_session, sample_case_advanced):
    s = TrainingSession(
        student_id="test_student", difficulty_level="高级",
        case_id=sample_case_advanced.id, status="active",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


class TestAnalyzeProgress:
    """三档难度的阶段判定"""

    def test_beginner_initial_and_min_messages(self, agent, beginner_session):
        with patch.object(agent, "_ai_check_progress", return_value={}):
            empty = agent._analyze_progress([{"role": "user", "content": "你好"}], beginner_session)
            single = agent._analyze_progress(
                [{"role": "user", "content": "这是湿病"}], beginner_session
            )
        assert empty["辨病"] is False and empty["current_stage"] == "辨病"
        assert single["辨病"] is False, "少于 2 条消息不应判定辨病完成"

    def test_beginner_disease_hit(self, agent, beginner_session):
        beginner_session.examinations_done = ["pulse"]   # 初级也要先切诊
        history = [
            {"role": "user", "content": "你哪里不舒服"},
            {"role": "user", "content": "这像是湿病"},
        ]
        with patch.object(agent, "_ai_check_progress", return_value={}):
            progress = agent._analyze_progress(history, beginner_session)

        assert progress["辨病"] is True
        assert progress["current_stage"] == "主证识别"

    def test_intermediate_flow_requires_examination(self, agent, intermediate_session):
        base = [
            {"role": "user", "content": "你哪里不舒服"},
            {"role": "user", "content": "这是胸痹吧"},
        ]
        p0 = agent._analyze_progress(base, intermediate_session)
        assert p0["辨病"] is False, "没切诊之前不能判定辨病"

        intermediate_session.examinations_done = ["pulse"]
        p1 = agent._analyze_progress(base, intermediate_session)
        assert p1["辨病"] is True
        assert p1["平脉"] is False, "只号了脉、没说脉象含义，不能算平脉完成"

        # 说出脉象含义（命中该案平脉要点）→ 平脉完成
        history = base + [{"role": "user", "content": "脉沉迟，主阳虚阴凝"}]
        p2 = agent._analyze_progress(history, intermediate_session)
        assert p2["平脉"] is True
        assert p2["析证"] is False, "只提脉象、没有病机与鉴别，不算析证"

        # 说出病机并给出一组鉴别 → 析证完成
        full = history + [{
            "role": "user",
            "content": "上焦阳虚、痰浊闭阻，需与心痛鉴别",
        }]
        p3 = agent._analyze_progress(full, intermediate_session)
        assert p3["析证"] is True

    def test_advanced_full_pipeline(self, agent, advanced_session):
        advanced_session.examinations_done = ["pulse"]
        history = [
            {"role": "user", "content": "这是黄疸"},
            {"role": "user", "content": "脉弦数，主湿热内盛"},
            {"role": "user", "content": "湿热蕴结中焦，与萎黄鉴别"},
            {"role": "user", "content": "治当清热利湿，用茵陈蒿汤"},
        ]
        progress = agent._analyze_progress(history, advanced_session)

        assert progress["辨病"] is True
        assert progress["平脉"] is True
        assert progress["析证"] is True
        assert progress["定治"] is True
        assert progress["current_stage"] == "已完成"

    def test_formula_without_method_does_not_complete_treatment(self, agent, advanced_session):
        """定治要求「治法 + 方剂」；只说方名不算形成方案。"""
        advanced_session.examinations_done = ["pulse"]
        history = [
            {"role": "user", "content": "这是黄疸"},
            {"role": "user", "content": "脉弦数，主湿热内盛"},
            {"role": "user", "content": "湿热蕴结中焦，与萎黄鉴别"},
            {"role": "user", "content": "用桂枝汤"},
        ]
        progress = agent._analyze_progress(history, advanced_session)

        assert progress["析证"] is True
        assert progress["定治"] is False, "缺少治法，不应判定定治完成"

    def test_ai_progress_merges_as_or(self, agent, beginner_session):
        history = [
            {"role": "user", "content": "你好"},
            {"role": "user", "content": "你觉得怎么样"},
        ]
        progress = agent._analyze_progress(
            history,
            beginner_session,
            ai_progress={"辨病": True, "平脉": False, "current_stage": "主证识别"},
        )

        assert progress["辨病"] is True
        assert progress["current_stage"] == "主证识别"


class TestShouldEndSession:
    """会话自动结束边界"""

    @pytest.mark.parametrize("level,rounds,expected", [
        ("初级", 14, False), ("初级", 15, True),
        ("中级", 29, False), ("中级", 30, True),
        ("高级", 49, False), ("高级", 50, True),
    ])
    def test_round_threshold(self, agent, level, rounds, expected):
        """各难度轮数上限不同：初级 15、中级 30、高级 50。"""
        assert agent._should_end_session(rounds, {}, level) is expected

    def test_stage_completion_depends_on_level(self, agent):
        """初级答出辨病就该收尾，中级还要求平脉与析证，高级要走满四阶段。"""
        assert agent._should_end_session(0, {"辨病": True}, "初级") is True

        assert agent._should_end_session(0, {"辨病": True}, "中级") is False
        assert agent._should_end_session(
            0, {"辨病": True, "平脉": True, "析证": True}, "中级") is True

        assert agent._should_end_session(
            0, {"辨病": True, "平脉": True, "析证": True}, "高级") is False
        assert agent._should_end_session(
            0, {"辨病": True, "平脉": True, "析证": True, "定治": True}, "高级") is True



class TestStageGating:
    """中高级分关卡：每关独立计数，满 3 次公布答案并强制过关。"""

    def test_three_wrongs_reveal_answer_and_pass(self, agent, db_session, intermediate_session):
        intermediate_session.examinations_done = ["pulse"]
        db_session.commit()
        # 先问一句（判定要求至少两轮发言），再连错三次
        agent.process_message(db_session, intermediate_session.id, "还有什么不舒服")
        for word in ("痹病", "黄疸", "虚劳"):
            _, _, _, progress = agent.process_message(
                db_session, intermediate_session.id, f"我认为是{word}")
        assert progress.get("辨病") is True, "错满 3 次应公布答案并过关"
        assert progress.get("stage_revealed") == "辨病"
        row = db_session.query(type(intermediate_session)).filter(
            type(intermediate_session).id == intermediate_session.id).first()
        assert "辨病" in (row.revealed_stages or [])

    def test_stage_passes_are_persisted(self, agent, db_session, intermediate_session):
        intermediate_session.examinations_done = ["pulse"]
        db_session.commit()
        agent.process_message(db_session, intermediate_session.id, "我认为是胸痹")
        agent.process_message(db_session, intermediate_session.id, "脉沉迟，主阳虚阴凝")
        row = db_session.query(type(intermediate_session)).filter(
            type(intermediate_session).id == intermediate_session.id).first()
        assert "辨病" in (row.verified_stages or [])
        assert "平脉" in (row.verified_stages or []), "后面再说别的，平脉不能退回未完成"

# ==================== 诊法直出 ====================

class TestExaminationDirect:
    """号脉、看舌等检查直接返回体征，不经过患者模型，也不重复给结果。"""

    @pytest.fixture
    def case_with_exams(self, db_session, sample_case_beginner):
        sample_case_beginner.examinations = {
            "pulse": {"text": "脉弦缓"},
            "tongue": {"text": "舌苔薄白"},
        }
        db_session.commit()
        return sample_case_beginner

    @pytest.fixture
    def active(self, db_session, case_with_exams):
        session = TrainingSession(
            student_id="examinee",
            difficulty_level="初级",
            case_id=case_with_exams.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)
        return session

    def test_pulse_returns_examination_without_llm(self, agent, db_session, active):
        agent._call_llm = MagicMock(side_effect=AssertionError("诊法不应调用 LLM"))

        reply, msg_type, status, progress = agent.process_message(
            db_session, active.id, "让我摸摸脉"
        )

        assert "脉弦缓" in reply
        assert "患者伸出手腕" in reply
        assert status == "active"
        assert msg_type is None, "体征消息不应带提示标签"

    def test_tongue_returns_examination(self, agent, db_session, active):
        reply, _, _, _ = agent.process_message(db_session, active.id, "伸出舌头看看")
        assert "舌苔薄白" in reply
        assert "患者伸出舌头" in reply

    def test_repeat_examination_is_refused(self, agent, db_session, active):
        agent.process_message(db_session, active.id, "号脉")
        reply, msg_type, _, _ = agent.process_message(db_session, active.id, "再号一次脉")

        assert "已获取" in reply
        assert "无需重复" in reply
        assert msg_type == "hint", "重复检查应提示而非纠错"

    def test_missing_examination_reports_not_recorded(self, agent, db_session, active):
        """病案没这项记录时，不能只说「未记录」把学生卡住，要给下一步。"""
        reply, _, _, _ = agent.process_message(db_session, active.id, "按按肚子")
        assert "没有提供" in reply and "问诊" in reply

    def test_examination_does_not_count_as_student_diagnosis(self, agent, db_session, active):
        """学生只是要求号脉，并未说出脉象含义，平脉不应被打勾。"""
        _, _, _, progress = agent.process_message(db_session, active.id, "让我摸摸脉")
        assert progress["平脉"] is False

    def test_examination_is_recorded_on_session(self, agent, db_session, active):
        agent.process_message(db_session, active.id, "号脉")
        db_session.refresh(active)
        assert active.examinations_done == ["pulse"]

# ==================== 分阶段引导 ====================

class TestGuidance:
    """引导提示：按层级与进度给出下一步任务，且不泄露答案。"""

    IDLE = {"辨病": False, "平脉": False, "析证": False, "定治": False}

    def test_beginner_starts_with_ask(self):
        from app.services.guidance import build_guidance
        g = build_guidance("初级", dict(self.IDLE), [], 0)
        assert g["stage"] == "ask"
        assert "问诊" in g["text"]

    def test_beginner_done_after_diagnosis(self):
        from app.services.guidance import build_guidance
        g = build_guidance("初级", {**self.IDLE, "辨病": True}, [], 3)
        assert g["stage"] == "done"

    def test_intermediate_asks_before_examination(self):
        from app.services.guidance import build_guidance
        assert build_guidance("中级", dict(self.IDLE), [], 0)["stage"] == "ask"
        assert build_guidance("中级", dict(self.IDLE), [], 1)["stage"] == "ask"

    def test_intermediate_requires_examination(self):
        from app.services.guidance import build_guidance
        g = build_guidance("中级", dict(self.IDLE), [], 2)
        assert g["stage"] == "examine"
        assert "切诊" in g["text"]

    def test_examination_asks_for_pulse_meaning(self):
        """取脉之后还要求说明脉象含义，平脉才算过。"""
        from app.services.guidance import build_guidance
        g = build_guidance("中级", {**self.IDLE, "辨病": True}, ["pulse"], 3)
        assert g["stage"] == "pulse"
        assert "脉象" in g["text"]

    def test_after_pulse_goes_to_patho(self):
        """平脉过了才提示病机与鉴别。"""
        from app.services.guidance import build_guidance
        g = build_guidance("中级", {**self.IDLE, "辨病": True, "平脉": True}, ["pulse"], 4)
        assert g["stage"] == "patho"
        assert "鉴别" in g["text"]

    def test_advanced_requires_treatment(self):
        from app.services.guidance import build_guidance
        progress = {"辨病": True, "平脉": True, "析证": True, "定治": False}
        g = build_guidance("高级", progress, ["pulse", "tongue"], 6)
        assert g["stage"] == "treat"
        assert "治法" in g["text"]

    def test_advanced_done(self):
        from app.services.guidance import build_guidance
        progress = {"辨病": True, "平脉": True, "析证": True, "定治": True}
        assert build_guidance("高级", progress, ["pulse"], 8)["stage"] == "done"

    def test_guidance_never_leaks_answer(self):
        from app.services.guidance import build_guidance
        for level in ("初级", "中级", "高级"):
            for turns in (0, 2, 5):
                text = build_guidance(level, dict(self.IDLE), [], turns)["text"]
                assert "少阳" not in text and "柴胡" not in text

class TestProgressMergeGuard:
    """AI 复核不得绕过平脉与定治的硬条件。

    线上实测：学生只说「应当调和营卫，疏肝解郁」、一个方都没开，
    模型却把定治判成完成，会话在「该开方」之前就自己结束了。
    """

    def test_ai_cannot_complete_treatment(self):
        from app.services.agent_service import TrainingAgent
        base = {"辨病": True, "平脉": True, "析证": True, "定治": False}
        merged = TrainingAgent._merge_ai_progress(
            dict(base),
            {"辨病": True, "平脉": True, "析证": True, "定治": True,
             "current_stage": "已完成"},
        )
        assert merged["定治"] is False

    def test_ai_cannot_complete_pulse(self):
        from app.services.agent_service import TrainingAgent
        base = {"辨病": True, "平脉": False, "析证": False, "定治": False}
        merged = TrainingAgent._merge_ai_progress(dict(base), {"平脉": True})
        assert merged["平脉"] is False

    def test_ai_can_still_supplement_diagnosis_and_pathogenesis(self):
        from app.services.agent_service import TrainingAgent
        base = {"辨病": False, "平脉": True, "析证": False, "定治": False}
        merged = TrainingAgent._merge_ai_progress(
            dict(base), {"辨病": True, "析证": True})
        assert merged["辨病"] is True
        assert merged["析证"] is True

    def test_stage_is_recomputed_from_rules(self):
        from app.services.agent_service import TrainingAgent
        assert TrainingAgent._stage_from_progress(
            {"辨病": True, "平脉": True, "析证": True, "定治": False}, "高级") == "定治"
        assert TrainingAgent._stage_from_progress(
            {"辨病": True, "平脉": True, "析证": True, "定治": False}, "中级") == "已完成"
        assert TrainingAgent._stage_from_progress(
            {"辨病": True, "平脉": True, "析证": True, "定治": True}, "高级") == "已完成"


class TestStatementFilter:
    """进度判定只看陈述句：问句和否定句不是「做出判断」。"""

    def test_drops_questions(self):
        from app.services.progress import statement_text
        assert statement_text("你是不是少阳病？") == ""
        assert statement_text("少阳病？") == ""
        assert statement_text("你怕冷吗") == ""
        assert statement_text("有没有出汗呢") == ""

    def test_drops_negations(self):
        from app.services.progress import statement_text
        assert statement_text("不像少阳病。") == ""
        assert statement_text("排除太阳病") == ""

    def test_keeps_affirmative_part_of_mixed_sentence(self):
        from app.services.progress import statement_text
        # 否定分句丢掉，肯定分句留下
        assert statement_text("不像少阳，应该是太阳病") == "应该是太阳病"
        kept = statement_text("脉弦缓，是少阳枢机不利。要不要用小柴胡？")
        assert "少阳枢机不利" in kept
        assert "小柴胡" not in kept

    def test_keeps_plain_statement(self):
        from app.services.progress import statement_text
        text = "脉弦，病机是枢机不利，当和解少阳，方用柴胡桂枝汤"
        assert statement_text(text) == text

    def test_empty_input(self):
        from app.services.progress import statement_text
        assert statement_text("") == ""
        assert statement_text(None) == ""


class TestStageReviewGuard:
    """阶段首次点亮时让模型确认；否决则撤销，判不了则采信规则。"""

    @staticmethod
    def _progress(**overrides):
        base = {"辨病": False, "平脉": True, "析证": False, "定治": False,
                "current_stage": "析证"}
        base.update(overrides)
        return base

    @staticmethod
    def _session(verified=None):
        from types import SimpleNamespace
        return SimpleNamespace(verified_stages=list(verified or []))

    def test_parse_verdict(self):
        from app.services.agent_service import TrainingAgent
        assert TrainingAgent._parse_stage_verdict('{"判断": true}') is True
        assert TrainingAgent._parse_stage_verdict('{"判断": false}') is False
        assert TrainingAgent._parse_stage_verdict('{"判断": "是"}') is True
        assert TrainingAgent._parse_stage_verdict('{"判断": "否"}') is False
        assert TrainingAgent._parse_stage_verdict("没有 JSON") is None

    def test_false_verdict_reverts_and_cascades(self, agent):
        from unittest.mock import MagicMock
        agent.client = object()          # 非 None 才会进入复核
        agent._verify_stage = MagicMock(return_value=False)
        session = self._session()
        progress = self._progress(辨病=True, 析证=True, 定治=True)
        result = agent._verify_new_stages(session, progress, [], "高级")
        assert result["辨病"] is False
        assert result["析证"] is False
        assert result["定治"] is False    # 前面被撤销，后面级联退回
        assert session.verified_stages == []   # 否决不记录，学生补充后重判

    def test_true_verdict_records_stage(self, agent):
        from unittest.mock import MagicMock
        agent.client = object()
        agent._verify_stage = MagicMock(return_value=True)
        session = self._session()
        result = agent._verify_new_stages(session, self._progress(辨病=True), [], "高级")
        assert result["辨病"] is True
        assert "辨病" in session.verified_stages

    def test_unknown_verdict_keeps_rule_result(self, agent):
        from unittest.mock import MagicMock
        agent.client = object()
        agent._verify_stage = MagicMock(return_value=None)
        session = self._session()
        result = agent._verify_new_stages(session, self._progress(辨病=True), [], "高级")
        assert result["辨病"] is True     # fail-open

    def test_skips_already_verified(self, agent):
        from unittest.mock import MagicMock
        agent.client = object()
        agent._verify_stage = MagicMock(return_value=False)
        session = self._session(["辨病"])
        agent._verify_new_stages(session, self._progress(辨病=True), [], "高级")
        agent._verify_stage.assert_not_called()

    def test_no_client_skips_review(self, agent):
        from unittest.mock import MagicMock
        agent.client = None
        agent._verify_stage = MagicMock(return_value=False)
        session = self._session()
        result = agent._verify_new_stages(session, self._progress(辨病=True), [], "高级")
        assert result["辨病"] is True
        agent._verify_stage.assert_not_called()
