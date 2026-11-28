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
    "correct": "纠正",
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

    # ---------- 初级：问诊 → 舌脉 → 辨病 ----------
    if level == "初级":
        if progress.get("辨病"):
            return _pack("done", "辨病已完成，可以结束训练查看评价")
        if progress.get("辨病错误"):
            left = max(0, 3 - int(progress.get("wrong_diagnosis_count") or 0))
            tail = f"（已错 {3 - left} 次，再错 {left} 次将结束本次训练）" if left else "（已达上限）"
            return _pack("correct", f"这个判断与本病案不符，可以再结合舌脉与问诊信息考虑{tail}")
        if progress.get("辨病模糊"):
            return _pack(
                "correct",
                f"「{progress['辨病模糊']}」是笼统的病类，不是中医诊断。"
                "请给出具体病名，例如胸痹、痹病、脏躁、黄疸",
            )
        if turns < 2:
            return _pack("ask", "继续问诊：了解起病、诱因和主要症状")
        if not has_exam:
            return _pack(
                "examine",
                "请进行切诊——可以说「我号一下脉」「看看舌头」，舌脉也是辨证依据",
            )
        return _pack(
            "ask",
            "请根据问诊与舌脉结果写出中医诊断（只需病名，不必辨证型、不用开方）",
        )

    # ---------- 中级 / 高级 ----------
    if not has_exam:
        if turns < 2:
            return _pack("ask", "继续问诊：了解起病、诱因与主要症状，随后进行切诊")
        return _pack(
            "examine",
            "请进行切诊：可以说「我号一下脉」「看看舌头」，获取脉象与舌象",
        )
    if progress.get("stage_revealed"):
        stage = progress["stage_revealed"]
        nxt = {"辨病": "说说脉象说明什么", "平脉": "说说病机，并与相近的证做一组鉴别",
               "析证": "给出治法与方药", "定治": "本次训练已完成"}.get(stage, "继续")
        return _pack("ask", f"「{stage}」已给出答案（该关不计分）。{nxt}")
    if progress.get("stage_incomplete") == "析证":
        return _pack("patho", "病机说到了，还差一组与相近证的鉴别")
    if progress.get("stage_wrong"):
        stage = progress["stage_wrong"]
        counts = (progress.get("stage_wrong_counts") or {}).get(stage, 1)
        return _pack("correct", f"{stage}这一关还没对上（本关已错 {counts} 次，满 3 次会公布答案）")
    if progress.get("辨病错误"):
        return _pack("correct", "这个判断与本病案不符，可以再结合舌脉与问诊信息考虑")
    if not progress.get("平脉"):
        return _pack(
            "pulse",
            "脉象已取得。请说明这个脉象主什么（例如「脉弦主饮邪内停」）",
        )
    if not progress.get("析证"):
        return _pack(
            "patho",
            "脉象说清楚了。请分析病机，再与相近的证做一组鉴别",
        )

    if level == "高级":
        if not progress.get("定治"):
            return _pack("treat", "请给出治法与方药，并说明选方（或合方）的理由")
        return _pack("done", "四阶段已完成，可以结束训练查看评价")

    return _pack("done", "平脉与析证已完成，可以结束训练")


def stage_changed(previous: Optional[str], current: str) -> bool:
    """阶段发生推进时，值得在聊天流里插一条提示。"""
    return bool(previous) and previous != current and current != "ask"
