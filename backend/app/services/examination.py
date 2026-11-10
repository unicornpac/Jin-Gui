"""诊法直出：把「号脉 / 看舌 / 按腹」这类检查从患者对话里分离出来。

脉象、舌象是**客观体征**，应当由系统按病案数据直接返回，而不是让患者模型即兴发挥。
好处有三：
1. 体征准确、措辞统一，不会漏给或含糊；
2. 检查不消耗 LLM 调用，响应从数十秒降到毫秒；
3. 教学上正确——切诊取得的是体征，不是让病人「说一下脉象」。
"""
import re
from typing import Dict, Optional

# 分句边界：动作词与「脉/舌」之间不跨越标点
_SEG = r"[^，。？！,。.?!；;]"

# 讨论语境：出现「主 / 说明 / 表示…」说明学生在解读体征，而不是要求检查
_DISCUSS = re.compile(
    rf"(?:脉象|脉|舌象|舌|舌苔|苔){_SEG}{{0,6}}"
    r"(?:主|说明|表示|反映|提示|属于|意味着|见于)"
    rf"|(?:主|说明|表示|反映|提示|意味着){_SEG}{{0,6}}(?:脉|舌)"
)

# 检查项 -> (识别正则, 患者配合动作)
# 规则要点：
# 1. 只认「动作 + 脉/舌」，不把「脉象」这类名词当触发词，
#    否则「脉象主肝脾郁」会被误当成要求号脉；
# 2. 没有动作词但明确询问体征的句子（脉怎么样 / 舌头伸出来 / 舌苔如何）也算检查请求。
EXAMINATIONS: Dict[str, tuple] = {
    "pulse": (
        rf"(?:号|摸|切|把|搭|按|诊|看|瞧|观){_SEG}{{0,8}}脉"
        rf"|脉(?:象)?{_SEG}{{0,4}}(?:怎么样|如何|什么情况|呢)",
        "患者伸出手腕，你搭上寸口",
    ),
    "tongue": (
        rf"(?:看|瞧|观|伸|望|查|吐){_SEG}{{0,8}}(?:舌|苔)"
        rf"|(?:舌|苔){_SEG}{{0,4}}(?:伸出来|怎么样|如何|什么情况)"
        rf"|(?:张|抬|伸){_SEG}{{0,4}}(?:嘴|口)",
        "患者伸出舌头",
    ),
    "abdomen": (
        rf"(?:按|摸|压|叩){_SEG}{{0,6}}(?:腹|肚子|脘)",
        "患者躺下，露出腹部",
    ),
    "face": (
        rf"(?:看|观|望){_SEG}{{0,4}}(?:面色|脸色|气色)",
        "你端详患者的面色",
    ),
    "throat": (
        rf"(?:看|查|望){_SEG}{{0,4}}(?:咽|嗓子|咽喉)",
        "患者张开嘴",
    ),
}


def detect_examination(text: str) -> Optional[str]:
    """识别学生这一句话是否在要求做体格检查，返回检查项 key。

    先排除「讨论体征」的句子：学生说「脉象主肝脾郁」是在解读脉象，
    属于析证范畴，不应触发一次切诊。
    """
    text = (text or "").strip()
    if not text:
        return None
    if _DISCUSS.search(text):
        return None
    for key, (pattern, _) in EXAMINATIONS.items():
        if re.search(pattern, text):
            return key
    return None


def examination_label(key: str) -> str:
    return {
        "pulse": "脉象",
        "tongue": "舌象",
        "abdomen": "腹诊",
        "face": "面色",
        "throat": "咽部",
    }.get(key, key)


def build_reply(key: str, exam: dict) -> str:
    """把病案里的体征渲染成一条患者消息：动作 + 客观结果。"""
    action = EXAMINATIONS.get(key, (None, "你做了检查"))[1]
    text = (exam.get("text") or "").strip()
    detail = (exam.get("detail") or "").strip()
    body = f"（{action}）{text}" if text else f"（{action}）未见异常"
    if detail:
        body += f"，{detail}"
    return body


def build_repeat_reply(key: str, exam: dict) -> str:
    """重复检查时的提示：给出已有结果并说明无需重复。"""
    text = (exam.get("text") or "").strip()
    return f"（{examination_label(key)}已获取：{text}，无需重复检查）"


def absent_reply(key: str) -> str:
    """病案未记录该项检查。"""
    return f"（本例未记录{examination_label(key)}结果）"
