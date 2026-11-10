"""分阶段训练引导。

按训练层级与当前进度，告诉学生「下一步该做什么」。提示只描述任务，不揭示答案。

层级差异：
- 初级（辨病与主证识别）：问诊 → 辨病 → 结束
- 中级（平脉与析证）：问诊 → 切诊 → 平脉 → 析证 → 结束
- 高级（定治与整体决策）：问诊 → 切诊 → 平脉 → 析证 → 定治 → 结束
"""
from typing import Dict, List, Optional

STAGE_LABEL = {
    "ask": "问诊",
    "examine": "切诊",
    "pulse": "平脉",
    "patho": "析证",
    "treat": "定治",
    "done": "已完成",
}


def _pack(stage: str, text: str) -> Dict[str, str]:
    return {"stage": stage, "label": STAGE_LABEL[stage], "text": text}


def build_guidance(
    level: str,
    progress: Dict[str, object],
    examinations_done: Optional[List[str]] = None,
    student_turns: int = 0,
) -> Dict[str, str]:
    """返回本回合的下一步提示。

    Args:
        level: 训练层级（初级/中级/高级）
        progress: 当前进度字典（辨病/平脉/析证/定治）
        examinations_done: 已完成的检查项 key 列表
        student_turns: 学生已发言轮数
    """
    done_exams = set(examinations_done or [])
    has_exam = bool(done_exams)
    turns = int(student_turns or 0)

    # ---------- 初级：只练辨病与主证 ----------
    if level == "初级":
        if progress.get("辨病"):
            return _pack("done", "辨病已完成，可以结束训练查看评价")
        if turns < 2:
            return _pack("ask", "继续问诊：了解起病、诱因和主要症状")
        return _pack("ask", "信息已较充分，请给出你的辨病结论：属何病、何证")

    # ---------- 中级 / 高级 ----------
    if not has_exam:
        if turns < 2:
            return _pack("ask", "继续问诊：了解起病、诱因与主要症状，随后进行切诊")
        return _pack(
            "examine",
            "请进行切诊：可以说「我号一下脉」「看看舌头」，获取脉象与舌象",
        )
    if not progress.get("析证"):
        return _pack(
            "patho",
            "脉象已取得。请说明这个脉象主什么，并结合兼症分析病机，"
            "再与相近的证做一组鉴别",
        )

    if level == "高级":
        if not progress.get("定治"):
            return _pack("treat", "请给出治法与方药，并说明选方（或合方）的理由")
        return _pack("done", "四阶段已完成，可以结束训练查看评价")

    return _pack("done", "平脉与析证已完成，可以结束训练")


def stage_changed(previous: Optional[str], current: str) -> bool:
    """阶段发生推进时，值得在聊天流里插一条提示。"""
    return bool(previous) and previous != current and current != "ask"
