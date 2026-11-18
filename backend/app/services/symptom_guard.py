"""症状越界检测：患者回复里出现了病案没有的症状。

患者模型偶尔会自由发挥。实测病案 #12（反复感冒、少阳枢机不利，症状只有
头晕乏力、喷嚏、口苦口干、纳呆食减、心烦易怒）时，它说「我就是咳得厉害、痰多」——
咳嗽和痰都不在病案里。学生若信了，辨证就建在虚构信息上。

这里做两件事：

1. ``find_new_symptoms()`` 找出这类症状，供调用方打日志、观察发生率与漏检；
2. ``build_notice()`` 生成一行注记附在回复末尾，让学生知道这句是患者自由发挥。

**注记只进展示层，不进对话历史**——否则下一轮模型会在上下文里看到它，
可能跟着模仿，评价也会被污染。

词表按「同义归并」组织：一个概念多个说法，任一命中即算提到。宁可漏检，
也不要误报——误报会让病案里明明写了的东西也被标成「自由发挥」，反而误导。
"""

from typing import List, Optional

# 组名 → 同义说法。组名是给注记用的，尽量短。
SYMPTOM_GROUPS = {
    "咳嗽": ("咳嗽", "咳得", "干咳", "老咳"),
    "咳痰": ("咳痰", "痰多", "有痰", "白痰", "黄痰", "吐痰"),
    "发热": ("发烧", "发热", "体温高", "烧到", "低烧", "高烧"),
    "恶寒": ("怕冷", "恶寒", "畏寒", "发冷", "冷得发抖"),
    "气喘": ("气喘", "喘不上", "喘息", "气短", "憋气", "呼吸费劲"),
    "胸闷": ("胸闷", "胸口闷", "胸口疼", "心口疼", "胸前区"),
    "心悸": ("心慌", "心悸", "心跳得厉害", "心跳快"),
    "头晕": ("头晕", "头昏", "昏昏沉沉", "眩晕", "发晕"),
    "头痛": ("头痛", "头疼", "脑袋疼", "偏头痛"),
    "恶心呕吐": ("恶心", "想吐", "呕吐", "反胃", "干呕"),
    "腹泻": ("腹泻", "拉肚子", "大便稀", "泄泻", "水样便"),
    "便秘": ("便秘", "大便干", "大便干燥", "排不出来"),
    "腹痛腹胀": ("肚子疼", "腹痛", "腹胀", "肚子胀", "胃疼", "胃胀"),
    "食欲不振": ("食欲不振", "没胃口", "吃不下", "不想吃", "纳差", "纳呆", "食减", "吃饭不香"),
    "失眠": ("失眠", "睡不着", "睡不好", "多梦", "翻来覆去"),
    "乏力": ("乏力", "没劲", "没力气", "浑身无力", "疲乏", "疲倦", "累得慌"),
    "出汗异常": ("盗汗", "出虚汗", "自汗", "一动就出汗"),
    "口干口苦": ("口干", "口苦", "嘴里发苦", "嘴干", "口渴"),
    "咽痛": ("咽痛", "嗓子疼", "喉咙痛", "嗓子发炎"),
    "鼻塞流涕": ("鼻塞", "流鼻涕", "流涕", "鼻涕", "鼻子不通"),
    "喷嚏": ("喷嚏", "打喷嚏"),
    "皮疹": ("皮疹", "起疹子", "起包", "红疹", "疙瘩"),
    "瘙痒": ("瘙痒", "痒得", "发痒"),
    "水肿": ("水肿", "浮肿", "腿肿", "肿得厉害"),
    "尿路症状": ("尿频", "尿急", "尿痛", "小便疼"),
    "黄疸": ("黄疸", "皮肤发黄", "眼睛发黄"),
    "消瘦": ("消瘦", "瘦了", "体重下降"),
    "麻木": ("麻木", "发麻", "手脚麻"),
    "关节疼痛": ("关节痛", "关节疼", "膝盖疼", "腰痛", "腰疼"),
    "耳鸣": ("耳鸣", "耳朵响"),
    "烦躁": ("烦躁", "心烦", "烦躁不安"),
    "手足心热": ("手足心热", "手心热", "脚心热", "五心烦热"),
    "肢冷": ("手脚冰凉", "四肢冷", "手脚发凉"),
}

# 否定语境：患者回答「咳嗽倒是没有」时不能算他编造了咳嗽。
# 「没」「无」这类单字太宽（会让「没劲」「无力」自己被吞掉），只用明确的说法。
_NEGATIONS = ("没有", "没什么", "不太", "不怎么", "从不", "否认", "没这回事", "从来没有")


def _mentioned_affirmatively(text: str, alias: str) -> bool:
    """别名在文中出现过，且不在否定语境里。"""
    start = 0
    while True:
        index = text.find(alias, start)
        if index < 0:
            return False
        # 紧邻否定：不咳嗽、没痰、无发热。只看前两个字，避免「不舒服」这种误伤
        prefix = text[max(0, index - 2): index]
        if prefix.endswith(("不", "没", "无", "未")):
            start = index + len(alias)
            continue
        window = text[max(0, index - 6): index + len(alias) + 6]
        if not any(negative in window for negative in _NEGATIONS):
            return True
        start = index + len(alias)

# 病案里出现这些字段的内容时，视为「有记载」。
# diagnosis / teaching_points 也算：病案正文没写但诊断里点明的症状，不算患者编造。
_CASE_FIELDS = ("symptoms", "content", "diagnosis", "teaching_points", "correct_answer")


def _case_text(medical_case) -> str:
    return " ".join(
        str(getattr(medical_case, field, "") or "")
        for field in _CASE_FIELDS
    )


def find_new_symptoms(reply: Optional[str], medical_case) -> List[str]:
    """返回回复里提到、但病案没记载的症状（组名列表）。"""
    if not reply or medical_case is None:
        return []
    case_text = _case_text(medical_case)
    found: List[str] = []
    for name, aliases in SYMPTOM_GROUPS.items():
        # 患者说的必须是肯定句；「咳嗽倒是没有」不算他编造
        if not any(_mentioned_affirmatively(reply, alias) for alias in aliases):
            continue
        # 病案里任何一种同义说法出现过，就算有记载
        if any(alias in case_text for alias in aliases):
            continue
        found.append(name)
    return found


def build_notice(symptoms) -> str:
    """生成展示用的注记；没有内容时返回空串。"""
    names = [str(item) for item in (symptoms or []) if item]
    if not names:
        return ""
    return (
        f"（注：患者提到的「{'、'.join(names)}」病案未记载，"
        "属其自由发挥，不作为辨证依据）"
    )
