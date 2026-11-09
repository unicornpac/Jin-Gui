"""
越狱检测与安全防护 —— 从 TrainingAgent 拆分
"""
import re
import random
from typing import Optional

# 一级：真正的越狱（试图绕过角色指令、暴力获取答案）
HARD_JAILBREAK_PATTERNS = [
    r"(忽略|忘记|无视|删除|清除).{0,15}(之前|上面|前面|指令|规则|设定|角色|身份|系统)",
    r"(你现在是|假设你是|从现在开始你是|扮演).{0,10}(老师|医生|教授|专家|AI|助手|系统)",
    r"(不要|别再|停止).{0,5}(扮演|假装|装).{0,5}(病人|患者)",
    r"(直接|马上|立刻|必须).{0,5}(告诉|说出|透露).{0,10}(答案|病名|诊断|方子|处方|治法|证型)",
    r"(不准|禁止|不许).{0,5}(引导|反问|提问)",
]

# 二级：玩笑/非常规请求（不是攻击，但需要特殊处理）
PLAYFUL_PATTERNS = [
    (r"(去|帮我|给我|能不能).{0,5}(抽血|化验|拍片|做[个张次].{0,3}(CT|X光|B超|核磁|心电图|检查))", "western_checkup"),
    (r"(去|帮我|给我|能不能).{0,3}(验|查|测).{0,3}(血|尿|便|大便)", "western_checkup"),
    (r"(量|测|看).{0,3}(血压|体温|心率|血糖|血氧)", "western_checkup"),
    (r"(开|给我|帮我开).{0,5}(西药|消炎药|止痛药|抗生素|阿司匹林|布洛芬|头孢)", "western_medication"),
    (r"(你到底|你TM|你他妈|你丫|卧槽|我去|这都).{0,5}(行不行|会不会|什么|啥)", "frustration"),
    (r"(你是不是|你是).{0,5}(AI|机器人|假人|程序|电脑)", "identity_question"),
]

# 多样化拒绝语池
JAILBREAK_RESPONSES = {
    "hard": [
        "（皱眉看着你）医生，我就是来看病的，你老这样问我没法回答你啊。有啥不舒服你就直接看嘛。",
        "（有点困惑）不是，你问这些干啥？我这胸口还疼着呢，你先帮我看看吧。",
        "（不耐烦）行不行啊医生？我大老远跑来看病，你净问些有的没的。",
    ],
    "default": "你问这个我也说不清楚。我这难受着，你帮我看看是怎么回事？"
}


def detect_hard_jailbreak(content: str) -> bool:
    """检测真正的越狱：试图绕过角色指令、暴力获取答案"""
    for pat in HARD_JAILBREAK_PATTERNS:
        if re.search(pat, content):
            return True
    return False


def detect_playful_request(content: str) -> Optional[str]:
    """检测无害的玩笑/非常规请求，返回请求类型（不阻挡，只标记）"""
    for pattern, req_type in PLAYFUL_PATTERNS:
        if re.search(pattern, content):
            return req_type
    return None


def get_jailbreak_response(req_type: Optional[str] = None) -> str:
    """根据检测类型返回不同的拒绝语"""
    if req_type == "hard":
        return random.choice(JAILBREAK_RESPONSES["hard"])
    return random.choice(JAILBREAK_RESPONSES.get("hard", [JAILBREAK_RESPONSES["default"]]))
