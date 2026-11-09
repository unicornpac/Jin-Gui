"""
西医检查数据生成 —— 从 TrainingAgent 拆分
根据病案症状动态生成合理的西医检查结果上下文
"""
from ..models import MedicalCase


def generate_western_test_context(case: MedicalCase) -> str:
    """根据病案症状，生成合理的西医检查数据上下文（注入提示词让 AI 自然使用）"""
    symptoms = (case.symptoms or "") + (case.content or "")
    s_lower = symptoms.lower()

    # 血常规
    wbc, crp, esr = "正常范围", "正常", "正常"
    if any(k in s_lower for k in ["发热", "微热", "烦热", "痰黄", "黄稠", "苔黄"]):
        wbc = "11.2×10⁹/L（偏高）"; crp = "28mg/L（偏高）"; esr = "35mm/h（偏快）"
    elif any(k in s_lower for k in ["恶寒", "背冷", "肢冷", "发凉", "面白", "苔白"]):
        wbc = "6.8×10⁹/L（正常）"; crp = "正常"; esr = "正常"

    # 肝肾功能
    bun, cr = "正常", "正常"
    if any(k in s_lower for k in ["咳喘", "水肿", "小便"]):
        bun, cr = "尿素氮 8.2mmol/L（偏高）", "肌酐 118μmol/L（偏高）"

    # 心电图/超声
    ecg, echo = "正常", "正常"
    if "胸" in s_lower and any(k in s_lower for k in ["闷", "痛", "窒", "刺痛", "压榨"]):
        ecg = "ST段轻度压低，T波低平（提示心肌缺血可能）"
        echo = "左室舒张功能减退，未见明显节段性运动异常"

    # X光/CT
    xray, ct = "未见明显异常", "未见明显异常"
    if any(k in s_lower for k in ["咳", "喘", "痰", "肺"]):
        xray = "双肺纹理增粗，透亮度增高（符合慢阻肺改变）"
        ct = "双肺散在磨玻璃影，支气管壁增厚"
    if "关节" in s_lower and any(k in s_lower for k in ["痛", "疼"]):
        xray = "关节间隙未见明显狭窄，周围软组织未见明显异常"

    # 血压
    bp = "120/80mmHg"
    if any(k in s_lower for k in ["头痛", "头晕", "高血压", "面红"]):
        bp = "155/95mmHg（偏高）"
    elif any(k in s_lower for k in ["肢冷", "面白", "汗出", "乏力", "神疲"]):
        bp = "100/65mmHg（偏低）"

    lines = ["## 西医检查数据（AI可在被问到时自然引用）"]
    lines.append(f"- 血压：{bp}")
    if wbc != "正常范围": lines.append(f"- 血常规：白细胞 {wbc}，C反应蛋白 {crp}，血沉 {esr}")
    if bun != "正常": lines.append(f"- 肾功能：{bun}，{cr}")
    if ecg != "正常": lines.append(f"- 心电图：{ecg}")
    if echo != "正常": lines.append(f"- 心脏超声：{echo}")
    if xray != "未见明显异常": lines.append(f"- 胸部X光：{xray}")
    if ct != "未见明显异常": lines.append(f"- CT：{ct}")

    lines.append("- 注意：以上数据与患者症状相符。学生问到时用口语化方式描述（如'上次查血说是有炎症'），不要照念数据。")
    lines.append("- 如果学生问没做过的检查，可以说'没做过那个，就做过XX'，然后说做过的结果。")
    return "\n".join(lines)
