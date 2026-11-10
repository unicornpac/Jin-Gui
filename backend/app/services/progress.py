"""
进度分析与决策辅助 —— 从 TrainingAgent 拆分
所有函数均为纯函数，不依赖 TrainingAgent 实例状态
"""
from typing import List, Optional

# ==================== 阶段判定用的词表 ====================
# 四个阶段的完成条件（2026-11 起）：
#   辨病 —— 说出病名或证型方向
#   平脉 —— 完成切诊取得脉象（脉象「含义」归析证）
#   析证 —— 解释病机，且至少给出一组鉴别
#   定治 —— 同时给出治法与方剂

DISEASE_KEYWORDS = [
    "湿病", "暍病", "疟病", "百合病", "胸痹", "痰饮", "水气", "黄疸",
    "虚劳", "肺痿", "肺痈", "咳嗽上气", "奔豚气", "腹满", "寒疝",
    "血痹", "风水", "支饮", "溢饮", "悬饮",
    "太阳病", "阳明病", "少阳病", "太阴病", "少阴病", "厥阴病",
    # 学生会说「少阳枢机不利」而不是「少阳病」，故补六经简称
    "太阳", "阳明", "少阳", "太阴", "少阴", "厥阴",
]

# 病机：用于判定「析证」
PATHOGENESIS_KEYWORDS = [
    "枢机", "气郁", "肝郁", "卫气", "营卫", "痰浊", "痰热", "瘀血", "血瘀",
    "阳虚", "阴虚", "气虚", "血虚", "湿热", "寒湿", "寒饮", "伏肺", "脾虚",
    "表虚", "里实", "上焦", "中焦", "下焦", "病机", "邪在", "正虚", "闭阻",
    "不宣", "失和", "内停", "上乘", "外越",
]

# 鉴别：析证要求至少一组鉴别
DIFFERENTIAL_KEYWORDS = [
    "鉴别", "区别于", "不同于", "而非", "需要与", "容易混淆", "不可误作",
    "并非", "当与", "须与",
]

# 治法：定治要求「治法 + 方剂」
TREATMENT_METHOD_KEYWORDS = [
    "治法", "和解", "调和", "解表", "散寒", "温肺", "化饮", "清热", "利湿",
    "活血", "化瘀", "健脾", "温阳", "滋阴", "补气", "养血", "通阳", "散结",
    "豁痰", "回阳", "救逆", "祛风", "除湿", "宣肺", "降逆", "和胃",
]

FORMULA_KEYWORDS = [
    "小柴胡", "柴胡桂枝", "桂枝汤", "麻黄汤", "小青龙", "大青龙", "真武汤",
    "四逆汤", "白虎汤", "承气汤", "栝楼薤白", "茵陈蒿", "越婢", "肾气丸",
    "薯蓣丸", "射干麻黄", "木防己", "黄芪桂枝五物", "桂枝附子", "理中丸",
]


def classify_response(response: str) -> str:
    """根据 AI 回复内容分类消息类型"""
    if not response:
        return "question"
    r = response[:100]
    if any(k in r for k in ["评价", "总结", "评分", "成绩", "训练结束"]):
        return "evaluation"
    if any(k in r for k in ["正确", "很好", "不错", "非常棒", "答对了"]):
        return "praise"
    if any(k in r for k in ["提示", "再想想", "注意", "考虑一下"]):
        return "hint"
    return "question"


def extract_decision_point(student: str, agent: str, progress: dict) -> Optional[str]:
    """从学生消息中提取关键决策点（辨病/脉象/方剂）"""
    for kw in ["湿病", "暍病", "疟病", "百合病", "胸痹", "痰饮", "水气", "黄疸", "虚劳", "血痹", "风水", "支饮",
               "太阳病", "阳明病", "少阳病", "太阴病", "少阴病", "厥阴病"]:
        if kw in student:
            return f"辨病：{kw}"
    for kw in ["脉浮", "脉沉", "脉数", "脉迟", "脉滑", "脉涩", "脉弦", "脉细", "脉洪", "脉微", "脉紧"]:
        if kw in student:
            return f"脉象：{kw}"
    for kw in ["桂枝汤", "麻黄汤", "小青龙", "大青龙", "真武汤", "四逆汤", "白虎汤", "承气汤",
               "小柴胡", "大柴胡", "半夏泻心", "肾气丸", "薯蓣丸", "栝楼薤白", "越婢汤", "木防己"]:
        if kw in student:
            return f"方剂：{kw}"
    return None


STAGE_KEYS = ("辨病", "平脉", "析证", "定治")
SESSION_TURN_LIMIT = 50


def should_end_session(history: List[dict], progress: dict, level: str) -> bool:
    """判断是否应自动结束会话。

    结束条件（满足其一）：
    1. 四个思辨阶段全部完成 —— 学生已走完路径，不必再等到轮数上限；
    2. 交互轮数达到上限。

    `level` 预留给"按难度设置不同上限"，当前各档统一使用 SESSION_TURN_LIMIT。
    """
    if progress and all(progress.get(stage) for stage in STAGE_KEYS):
        return True
    return len(history) >= SESSION_TURN_LIMIT


def build_progress_hint(progress: dict) -> str:
    """根据后端识别的实际进度，生成患者行为指令"""
    hints = []
    if progress.get('辨病'):
        hints.append('- 辨病阶段已完成：医生已准确识别病证。你虽听不懂中医术语，但能感到他说中了你的感觉。语气自然放松，流露信任。可主动补充"哦对了我还有个事忘了说"类型的细节。用日常语言确认身体感受（"对对，就这感觉""嗯差不多"），绝不说"你诊断对了"。')
    if progress.get('平脉'):
        hints.append('- 平脉阶段已完成：医生连你的脉象都说对了。你更信任他了——语气放松，怀疑感减少，更愿意透露兼症和生活细节。')
    if progress.get('析证'):
        hints.append('- 析证阶段已完成：医生分析得很透彻。你表现出"终于有人懂我"的释然感，态度完全配合，有问必答。')
    if progress.get('定治'):
        hints.append('- 定治阶段已完成：你完全信任医生。可以说"行那我听你的""要多久好转？"之类的话，自然进入收尾。')
    if not hints:
        return ''
    return '## 当前进度行为指令（医生已达到的进度，据此调整你的态度）\n' + '\n'.join(hints)
