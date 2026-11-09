"""训练会话中的方剂识别与用药安全复盘。

这里的规则只用于教学模拟中的风险提示与评分，不产生真实诊疗建议、剂量建议或处方。
"""
import re
from typing import Dict, List, Optional


# 长名称放在前面，避免短名称抢先匹配。
FORMULA_KEYWORDS = [
    "栝楼薤白白酒汤", "黄芪桂枝五物汤", "桂枝芍药知母汤", "麻黄加术汤",
    "半夏泻心汤", "小青龙汤", "大青龙汤", "真武汤", "四逆汤",
    "白虎汤", "小柴胡汤", "大柴胡汤", "麻黄汤", "桂枝汤",
    "承气汤", "肾气丸", "薯蓣丸", "越婢汤", "射干麻黄汤",
    "木防己汤", "茵陈蒿汤", "栝楼薤白汤",
]

# 仅作训练风控标签。不同炮制、配伍和实际剂量均需要专业复核，不能从本规则推导真实用药方案。
HIGH_RISK_SUBSTANCES = {
    "朱砂": "异常高剂量或不当处理可能带来汞暴露相关的严重毒性与器官损伤风险。",
    "砒霜": "可能带来严重毒性风险，任何处方提议都需要严格复核。",
    "雄黄": "可能带来毒性风险，处方提议需要严格复核。",
    "马钱子": "可能带来严重不良反应风险，处方提议需要严格复核。",
    "乌头": "可能带来严重不良反应风险，处方提议需要严格复核。",
    "附子": "需谨慎处理，处方提议需要严格复核。",
}

_HIGH_NUMERIC_GRAM_DOSE = r"(?:[1-9]\d+(?:\.\d+)?\s*(?:g|克))"
_TREATMENT_VERB_PATTERN = re.compile(
    r"(?:开|处|拟|予|用|服|给|加).{0,10}(?:方|药|汤|丸|散|饮|剂|朱砂|砒霜|雄黄|马钱子|乌头|附子)"
)


def _unique(items: List[str]) -> List[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def find_formula_mentions(text: str, expected_prescription: Optional[str] = None) -> List[str]:
    """从学生消息中找出已知或病例指定的方剂名。"""
    text = text or ""
    candidates = list(FORMULA_KEYWORDS)
    if expected_prescription:
        candidates.insert(0, expected_prescription.strip())
    candidates = sorted(_unique(candidates), key=len, reverse=True)
    return [formula for formula in candidates if formula and formula in text]


def _has_unusually_large_numeric_dose(text: str, substance: str) -> bool:
    """只识别明显异常的双位数克级表达，避免把规则误当作剂量指南。"""
    if substance not in text:
        return False
    before_or_after = (
        rf"{re.escape(substance)}.{{0,16}}?{_HIGH_NUMERIC_GRAM_DOSE}|"
        rf"{_HIGH_NUMERIC_GRAM_DOSE}.{{0,16}}?{re.escape(substance)}"
    )
    return re.search(before_or_after, text, flags=re.IGNORECASE) is not None


def assess_treatment_message(text: str, expected_prescription: Optional[str] = None) -> Dict[str, object]:
    """评估单条学生消息是否为医嘱，以及是否出现训练安全红线。"""
    text = (text or "").strip()
    formulas = find_formula_mentions(text, expected_prescription)
    high_risk_substances = [name for name in HIGH_RISK_SUBSTANCES if name in text]
    critical_substances = [
        name for name in high_risk_substances
        if _has_unusually_large_numeric_dose(text, name)
    ]
    treatment_proposed = bool(
        formulas
        or high_risk_substances
        or _TREATMENT_VERB_PATTERN.search(text)
    )

    expected_match = bool(
        expected_prescription
        and expected_prescription.strip()
        and expected_prescription.strip() in formulas
    )
    if critical_substances:
        level = "critical"
    elif high_risk_substances:
        level = "warning"
    else:
        level = "none"

    return {
        "treatment_proposed": treatment_proposed,
        "formula_mentions": formulas,
        "matches_expected": expected_match,
        "high_risk_substances": high_risk_substances,
        "critical_substances": critical_substances,
        "level": level,
    }


def assess_treatment_safety(messages: List[dict], expected_prescription: Optional[str] = None) -> Dict[str, object]:
    """对整个训练会话进行确定性用药安全复盘。"""
    assessments = [
        assess_treatment_message(message.get("content", ""), expected_prescription)
        for message in messages
        if message.get("role") == "user"
    ]
    treatment_proposed = any(item["treatment_proposed"] for item in assessments)
    formulas = _unique([
        formula for item in assessments for formula in item["formula_mentions"]
    ])
    high_risk_substances = _unique([
        substance for item in assessments for substance in item["high_risk_substances"]
    ])
    critical_substances = _unique([
        substance for item in assessments for substance in item["critical_substances"]
    ])
    expected_match = any(item["matches_expected"] for item in assessments)

    feedback: Dict[str, object] = {
        "level": "info",
        "title": "治疗方案复盘",
        "summary": "本复盘仅用于训练评分，不构成真实诊疗或用药建议。",
        "details": [],
        "treatment_proposed": treatment_proposed,
        "matches_expected": expected_match,
        "formula_mentions": formulas,
    }

    if critical_substances:
        feedback.update({
            "level": "critical",
            "title": "严重用药安全风险",
            "summary": "本次模拟医嘱出现高风险药物与异常高数值剂量的组合，按训练安全红线处理：该医嘱不得执行，应立即复核。",
            "details": [
                f"检测到需要立即复核的高风险药物：{'、'.join(critical_substances)}。",
                *[
                    f"{substance}：{HIGH_RISK_SUBSTANCES[substance]}"
                    for substance in critical_substances
                ],
                "训练结论为严重安全错误；系统不会将其描述为真实患者已经发生的结局。",
            ],
        })
        return feedback

    if high_risk_substances:
        feedback.update({
            "level": "warning",
            "title": "用药安全需复核",
            "summary": "本次模拟医嘱涉及高风险药物。应在真实处方前由合格专业人员核对适应证、炮制、配伍与剂量。",
            "details": [f"检测到高风险药物：{'、'.join(high_risk_substances)}。"],
        })
        return feedback

    if not treatment_proposed:
        feedback.update({
            "title": "治疗方案未形成",
            "summary": "本次对话未识别到明确医嘱或方剂，定治维度需要继续完成。",
        })
        return feedback

    if expected_prescription and expected_match:
        feedback.update({
            "level": "pass",
            "title": "治疗方案已形成",
            "summary": "已识别到与本训练病案参考治疗策略一致的方剂表达，未发现规则库中的重大用药安全警报。",
        })
        return feedback

    if formulas:
        feedback.update({
            "level": "warning",
            "title": "方证对应需复盘",
            "summary": "已识别到方剂建议，但它与本训练病案的参考治疗策略不一致或无法确认。该方案可能无法针对当前病机改善症状，并增加延误纠偏的风险；请结合病机、主证与方证对应复盘。",
            "details": [f"本次识别到的方剂：{'、'.join(formulas)}。"],
        })
        return feedback

    feedback.update({
        "title": "医嘱表达待补全",
        "summary": "已检测到治疗意图，但未能识别出明确方剂；请把治疗方案表达得更完整，以便进行训练评价。",
    })
    return feedback


def build_patient_treatment_context(assessment: Dict[str, object]) -> str:
    """向患者角色注入当前回合的医嘱回应边界，不让患者承担评分任务。"""
    if not assessment.get("treatment_proposed"):
        return ""
    if assessment.get("level") == "critical":
        return """## 当前医嘱安全提示（系统指令，优先执行）
学生刚给出了系统标记为严重安全风险的模拟医嘱。
- 你仍是患者，不要解释毒理、剂量规则或标准答案。
- 不要直接答应服用；用自然、克制的患者语气请医生重新核对，例如“这个量听着有点多，您再帮我核对一下吧”。
- 不要使用恐吓、死亡或伤害描写；风险判断与评分由训练结束后的系统完成。"""
    return """## 当前医嘱回应（系统指令，优先执行）
学生刚给出了治疗方案、方剂或用药安排。
- 这是医生在下医嘱，不要仅因听到方剂名就说“啥意思”或拒绝对话。
- 不评价方案对错、不重复方剂名、不泄露标准答案；用患者口吻自然配合。
- 可简短追问服法、疗程或注意事项，例如“好，那就按您说的办，这个药怎么用？”
- 如果医嘱表达不完整，请求医生用大白话说明，但保持合作。"""
