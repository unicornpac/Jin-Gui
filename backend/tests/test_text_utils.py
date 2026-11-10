"""文本处理与回复分类 —— 清理、消息类型判定、决策点提取、经典范围识别。

都是纯函数，不依赖数据库或网络。"""

import pytest

from app.models import MedicalCase
from app.services.ai_service import clean_analysis_output

# ==================== 文本清理 ====================

class TestCleanText:
    """Markdown 符号清理"""

    @pytest.mark.parametrize("raw,expected", [
        ("# 诊断结果", "诊断结果"),
        ("## 辨证分析", "辨证分析"),
        ("### 治疗方案", "治疗方案"),
        ("**这是一个粗体**", "这是一个粗体"),
        ("*这是一个斜体*", "这是一个斜体"),
        ("使用`麻黄汤`治疗", "使用麻黄汤治疗"),
        ("前面\n---\n后面", "前面\n\n后面"),
        ("## **重要**：`脉浮`\n---\n辨证", "重要：脉浮\n\n辨证"),
        ("- 第一条", "第一条"),
        ("— 第二条", "第二条"),
        ("第一段\n\n\n\n第二段", "第一段\n\n第二段"),
    ])
    def test_cleans_markdown(self, agent, raw, expected):
        assert agent._clean_text(raw) == expected

    def test_edge_inputs(self, agent):
        assert agent._clean_text("") == ""
        assert agent._clean_text(None) == ""
        text = "这是一个普通的回复，没有任何 markdown 符号。"
        assert agent._clean_text(text) == text


class TestCleanAnalysisOutput:
    """条文分析的纯文本收敛"""

    def test_removes_markdown_and_long_dashes(self):
        raw = "## **核心含义：**\n* 病机——症状相互影响。\n---\n`辨证要点`：注意寒热。"
        result = clean_analysis_output(raw)

        assert result == "核心含义：\n病机，症状相互影响。\n\n辨证要点：注意寒热。"
        assert "*" not in result
        assert "——" not in result
        assert "---" not in result

    def test_keeps_plain_chinese_paragraphs(self):
        raw = "核心含义：说明病机。\n\n\n临床应用：结合症状判断。"
        assert clean_analysis_output(raw) == "核心含义：说明病机。\n\n临床应用：结合症状判断。"


# ==================== 回复分类与决策提取 ====================

class TestClassifyResponse:
    """回复类型分类"""

    @pytest.mark.parametrize("response,expected_type", [
        ("评价一下你的表现", "evaluation"),
        ("总结本次训练", "evaluation"),
        ("综合评分 85 分", "evaluation"),
        ("训练结束，以下是你的成绩", "evaluation"),
        ("正确！你答对了", "praise"),
        ("很好，思路很清晰", "praise"),
        ("不错，继续推进", "praise"),
        ("非常棒", "praise"),
        ("提示：再想想脉象的特点", "hint"),
        ("注意一下舌苔的颜色", "hint"),
        ("考虑一下是否有表证", "hint"),
    ])
    def test_classifies_correctly(self, agent, response, expected_type):
        assert agent._classify_response(response) == expected_type

    def test_defaults_to_question(self, agent):
        assert agent._classify_response("你哪里不舒服啊") == "question"
        assert agent._classify_response("胸口疼了三天了") == "question"
        assert agent._classify_response("") == "question"


class TestExtractDecisionPoint:
    """关键决策点提取"""

    def test_extracts_disease_pulse_and_formula(self, agent):
        extract = agent._extract_decision_point
        assert extract("这是湿病", "", {}) == "辨病：湿病"
        assert extract("我觉得是胸痹", "", {}) == "辨病：胸痹"
        assert extract("太阳病", "", {}) == "辨病：太阳病"
        assert extract("应该是阳明病", "", {}) == "辨病：阳明病"
        assert extract("脉浮", "", {}) == "脉象：脉浮"
        assert extract("脉弦", "", {}) == "脉象：脉弦"
        assert extract("脉沉", "", {}) == "脉象：脉沉"
        assert extract("用桂枝汤", "", {}) == "方剂：桂枝汤"
        assert extract("麻黄汤加减", "", {}) == "方剂：麻黄汤"
        assert extract("小柴胡汤", "", {}) == "方剂：小柴胡"

    def test_priority_and_no_match(self, agent):
        # 三类同时出现时病名优先
        assert "辨病" in agent._extract_decision_point("这是湿病，脉浮", "", {})
        assert agent._extract_decision_point("你好", "", {}) is None
        assert agent._extract_decision_point("哪里不舒服", "", {}) is None


class TestDetectClassicContext:
    """经典范围自动识别"""

    def test_detects_classic_scope(self, agent):
        assert "金匮要略" in agent._detect_classic_context(
            MedicalCase(title="湿病", content="关节痛", diagnosis="湿病"))
        assert "伤寒论" in agent._detect_classic_context(
            MedicalCase(title="感冒", content="太阳病", diagnosis="太阳病"))
        assert "两者本为一体" in agent._detect_classic_context(
            MedicalCase(title="杂病", content="金匮胸痹，涉及太阳病", diagnosis=""))


class TestBuildPlayfulContext:
    """玩笑请求上下文构建"""

    def test_builds_context_by_type(self, agent, sample_case_advanced, sample_case_beginner):
        ctx = agent._build_playful_context("western_checkup", sample_case_advanced)
        assert "西医检查" in ctx
        assert "特殊指令" in ctx
        assert "不满" in agent._build_playful_context("frustration", sample_case_beginner)
        assert "AI" in agent._build_playful_context("identity_question", sample_case_beginner)
        # 未知类型不编造上下文
        assert agent._build_playful_context("unknown_type", sample_case_beginner) == ""


class TestGenerateWesternTestContext:
    """西医检查数据生成"""

    def test_generates_by_case_signals(self, agent, sample_case_advanced,
                                       sample_case_beginner, sample_case_intermediate):
        ctx = agent._generate_western_test_context(sample_case_advanced)
        assert "血压" in ctx
        assert "血常规" in ctx
        assert "血常规" in agent._generate_western_test_context(sample_case_beginner)
        assert "心电图" in agent._generate_western_test_context(sample_case_intermediate)
