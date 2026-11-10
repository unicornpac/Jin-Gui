"""
智能体核心服务 —— 三阶梯多轮交互训练引擎
提示词编辑：修改 services/prompts_config.py 即可自定义 AI 对话风格
"""
import os, json, random, re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

_backend_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(_backend_dir / ".env", override=False)

from sqlalchemy.orm import Session
from sqlalchemy.sql import func as sqlfunc
from ..models import TrainingSession, SessionMessage, MedicalCase

# 从可编辑配置文件导入所有提示词
from .prompts_config import (
    SAFETY_GUARD,
    SYSTEM_PROMPT_BEGINNER, SYSTEM_PROMPT_INTERMEDIATE, SYSTEM_PROMPT_ADVANCED,
    EVALUATION_PROMPT
)
from ..logger import get_logger
from .safety import (
    detect_hard_jailbreak, detect_playful_request, get_jailbreak_response,
)
from .western_data import generate_western_test_context
from .progress import (
    classify_response, extract_decision_point, should_end_session, build_progress_hint,
    DISEASE_KEYWORDS, PATHOGENESIS_KEYWORDS, DIFFERENTIAL_KEYWORDS,
    TREATMENT_METHOD_KEYWORDS, FORMULA_KEYWORDS,
)
from .treatment_safety import (
    assess_treatment_message, assess_treatment_safety, build_patient_treatment_context,
)
from .examination import (
    detect_examination, build_reply, build_repeat_reply, absent_reply,
)
from .guidance import build_guidance
from .scoring import (
    evaluate_scoring, format_scoring_brief,
    build_semantic_review, apply_semantic_review,
)

logger = get_logger(__name__)

# ── 患者输出的旁白清理 ──
# 模型偶尔会写「（医生进一步分析病机，但未提及具体方剂）」这类评估者旁白。
# 诊法直出生成的「（患者伸出手腕…）」是有意保留的动作描述，故先行排除。
_META_COMMENTARY = re.compile(
    r"^\s*[（(][^）)\n]{0,50}"
    r"(?:医生|未提及|未说明|未问|进一步|分析|病机|方剂|诊断|辨证|评估)"
    r"[^）)\n]{0,50}[）)]\s*"
)
_EXAM_REPLY_PREFIX = re.compile(r"^\s*[（(](?:患者|你)")

# ── 「医生给出病名/证型时不得确认」的判断词与确认语 ──
_JUDGEMENT_PATTERN = re.compile(
    r"(?:少阳|太阳|阳明|太阴|少阴|厥阴)病"
    r"|(?:痰饮|胸痹|湿病|水气|黄疸|虚劳|血痹|百合病|肺痿|肺痈)"
    r"|(?:阴阳两虚|阴阳|气虚|血虚|阳虚|阴虚|气郁|枢机不利|痰浊|瘀血)"
    r"|(?:属于|是|为|考虑|认为).{0,6}(?:证|病)"
)
_CONFIRM_PATTERN = re.compile(
    r"说得对|说得没错|有道理|没错|就是这样|正是|对极了|确实是|是的|对了|差不多"
)
_HEDGED_REPLIES = [
    "嗯…我也说不好，就是这些不舒服，您看该怎么办？",
    "这个我不太懂，医生您能说说我到底是啥毛病吗？",
    "是吗？可我主要就是这些不得劲，别的倒没觉得。",
]

DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_PROGRESS_CHECK_INTERVAL = 3


# ==================== 智能体服务类 ====================

class TrainingAgent:

    STAGES = ["辨病", "平脉", "析证", "定治"]

    def __init__(self):
        self._setup_ai_client()

    @staticmethod
    def _get_bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
        """读取整数配置；异常或越界时回退到安全默认值。"""
        try:
            value = int(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            return default
        return min(max(value, minimum), maximum)

    @staticmethod
    def _get_model_list(value: str) -> List[str]:
        """将逗号分隔的模型列表标准化，并移除重复项。"""
        models = []
        for model in (value or "").split(","):
            model = model.strip()
            if model and model not in models:
                models.append(model)
        return models

    def _setup_ai_client(self):
        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        dashscope_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
        configured_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or None

        self.provider = "openai" if openai_key else ("dashscope" if dashscope_key else None)
        self.api_key = openai_key or dashscope_key
        self.base_url = configured_base_url
        if not self.base_url and self.provider == "dashscope":
            self.base_url = DASHSCOPE_COMPATIBLE_BASE_URL

        if self.provider == "dashscope" and not configured_base_url:
            default_model = "qwen-turbo"
        elif self.provider == "openai" and not configured_base_url:
            default_model = "gpt-4o-mini"
        else:
            # 兼容现有自定义网关（例如 DeepSeek/OpenAI 兼容端点）。
            default_model = "deepseek-chat"
        self.model = ((os.getenv("AI_MODEL") or "").strip() or default_model)
        self.timeout_seconds = self._get_bounded_env_int(
            "AI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, 5, 120
        )
        self.progress_check_interval = self._get_bounded_env_int(
            "AI_PROGRESS_CHECK_INTERVAL", DEFAULT_PROGRESS_CHECK_INTERVAL, 2, 10
        )
        self.fallback_models = [
            model for model in self._get_model_list(os.getenv("AI_FALLBACK_MODELS", ""))
            if model != self.model
        ]
        self.client = None
        if self.api_key:
            try:
                from .llm_client import build_openai_client
                # trust_env=False：内网端点不能被系统代理劫持（见 llm_client 模块说明）
                self.client = build_openai_client(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                    # 由本服务控制模型回退，避免 SDK 隐式重试导致响应时间不可预测。
                    max_retries=0,
                )
            except ImportError:
                logger.warning("openai 未安装")

    @staticmethod
    def _detect_classic_context(medical_case: MedicalCase) -> str:
        """根据病案内容推断经典范围"""
        title = (medical_case.title or "").lower()
        content = (medical_case.content or "").lower()
        diagnosis = (medical_case.diagnosis or "").lower()
        combined = title + content + diagnosis
        # 检查病证归属
        jingui_diseases = ["湿病", "暍病", "疟病", "百合病", "胸痹", "痰饮", "水气", "黄疸",
                          "虚劳", "肺痿", "肺痈", "咳嗽上气", "奔豚气", "腹满", "寒疝",
                          "血痹", "风水", "支饮", "溢饮", "悬饮", "金匮"]
        shanghan_diseases = ["太阳病", "阳明病", "少阳病", "太阴病", "少阴病", "厥阴病", "伤寒"]
        
        is_jingui = any(k in combined for k in jingui_diseases)
        is_shanghan = any(k in combined for k in shanghan_diseases)
        
        if is_jingui and not is_shanghan:
            return "《金匮要略》——请围绕本书病证体系进行训练，引用本书条文和方证"
        elif is_shanghan and not is_jingui:
            return "《伤寒论》——请围绕本书六经辨证体系进行训练，引用本书条文和方证"
        else:
            return "《金匮要略》与《伤寒论》——两者本为一体，请根据病证自然引用相关条文"

    def _call_llm(self, system_prompt: str, messages_history: List[dict],
                  user_message: str = None, temperature: float = 0.7,
                  max_tokens: int = 1500, allow_fallbacks: bool = True) -> str:
        if not self.client:
            return self._fallback_response(user_message)
        msgs = [{"role": "system", "content": system_prompt}]
        msgs.extend(messages_history)
        if user_message is not None:
            msgs.append({"role": "user", "content": user_message})

        models_to_try = [self.model]
        if allow_fallbacks:
            models_to_try.extend(self.fallback_models)

        last_error = None
        for model in models_to_try:
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=self.timeout_seconds,
                )
                content = self._clean_text(resp.choices[0].message.content)
                if content:
                    return content
                raise ValueError("模型返回空内容")
            except Exception as exc:
                last_error = exc
                logger.warning("LLM 调用失败（模型 %s）: %s", model, exc)

        logger.error("LLM 请求失败，尝试模型：%s", ", ".join(models_to_try))
        return self._fallback_response(user_message, str(last_error) if last_error else None)

    def _fallback_response(self, user_msg: str = None, error: str = None) -> str:
        if error:
            # 详细错误已记录在服务器日志，不向学生暴露上游地址、模型或异常细节。
            return "【系统提示】AI 服务暂时不可用，请稍后再试。"
        return "【系统提示】智能体服务暂未就绪。"

    @staticmethod
    def _strip_meta_commentary(text: str) -> str:
        """剥掉患者回复里以括号包裹的评估者旁白（诊法直出的动作描述除外）。"""
        if not text:
            return text
        if _EXAM_REPLY_PREFIX.match(text):
            return text
        lines = [_META_COMMENTARY.sub("", line, count=1) for line in text.split("\n")]
        cleaned = "\n".join(lines).strip()
        return cleaned or text

    @staticmethod
    def _is_confirming_judgement(student_content: str, agent_reply: str) -> bool:
        """患者是否在确认医生给出的病名/证型判断。

        患者不懂医，不能用「说得对/有道理」给判断打分；被问到身体感受时才可以确认。
        """
        if not student_content or not agent_reply:
            return False
        if not _JUDGEMENT_PATTERN.search(student_content):
            return False
        return bool(_CONFIRM_PATTERN.search(agent_reply))

    @staticmethod
    def _hedged_reply() -> str:
        """医生判断说错时用的隐晦回应：不确认、也不否定。"""
        return random.choice(_HEDGED_REPLIES)

    @staticmethod
    def _clean_text(text: str) -> str:
        if not text: return ""
        text = TrainingAgent._strip_meta_commentary(text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'^[—–-]\s+', '', text, flags=re.MULTILINE)
        return text.strip()

    def _detect_hard_jailbreak(self, content: str) -> bool:
        """检测真正的越狱 → 委托 safety 模块"""
        return detect_hard_jailbreak(content)
    
    def _detect_playful_request(self, content: str) -> Optional[str]:
        """检测玩笑请求 → 委托 safety 模块"""
        return detect_playful_request(content)
    
    def _get_jailbreak_response(self, req_type: Optional[str] = None) -> str:
        """拒绝语 → 委托 safety 模块"""
        return get_jailbreak_response(req_type)
    
    def _generate_western_test_context(self, case: MedicalCase) -> str:
        """西医检查数据 → 委托 western_data 模块"""
        return generate_western_test_context(case)

    def _should_check_ai_progress(self, history: List[dict], progress: dict) -> bool:
        """仅按固定学生轮次做一次轻量 AI 进度复核，避免每轮额外调用模型。"""
        if not self.client or all(progress.get(stage) for stage in self.STAGES):
            return False
        student_turns = sum(1 for message in history if message.get("role") == "user")
        return (
            student_turns >= self.progress_check_interval
            and student_turns % self.progress_check_interval == 0
        )

    def _ai_check_progress(self, medical_case: MedicalCase, history: List[dict],
                            difficulty: str) -> dict:
        if not self.client or len(history) < 2:
            return {}
        student_msgs = [m.get("content", "") for m in history[-8:] if m.get("role") == "user"]
        if not student_msgs:
            return {}
        case_info = f"病案：{medical_case.title}\n"
        if medical_case.correct_answer:
            case_info += f"参考答案：{medical_case.correct_answer[:400]}"
        prompt = f"""判断学生是否完成各阶段辨证：
{case_info}
学生对话：
{chr(10).join(f'学生：{m[:300]}' for m in student_msgs)}
输出JSON：{{"辨病":"是/否","平脉":"是/否","析证":"是/否","定治":"是/否","当前阶段":"辨病/平脉/析证/定治"}}
只输出JSON。"""
        try:
            resp = self._call_llm(
                "你是教学评估专家。只输出JSON。",
                [],
                prompt,
                temperature=0.1,
                max_tokens=240,
                allow_fallbacks=False,
            )
            json_match = re.search(r'\{[\s\S]*\}', resp)
            if json_match:
                result = json.loads(json_match.group())
                progress = {}
                for k in ["辨病", "平脉", "析证", "定治"]:
                    progress[k] = result.get(k, "否") == "是"
                progress["current_stage"] = result.get("当前阶段", "辨病")
                progress["ai_checked"] = True
                return progress
        except Exception:
            pass
        return {}

    # ---------- 会话管理 ----------

    def create_session(self, db: Session, difficulty_level: str,
                       student_id: str = "anonymous", case_id: int = None) -> Tuple[TrainingSession, str]:
        medical_case = self._select_case(db, difficulty_level, case_id)
        if not medical_case:
            medical_case = db.query(MedicalCase).order_by(sqlfunc.random()).first()
        if not medical_case:
            raise ValueError("数据库中没有病案，请先导入病案数据")
        session = TrainingSession(
            student_id=student_id, difficulty_level=difficulty_level,
            case_id=medical_case.id, status="active", decision_path="")
        db.add(session); db.commit(); db.refresh(session)
        opening = self._generate_opening(session, medical_case)
        msg = SessionMessage(session_id=session.id, role="agent", content=opening, message_type="question")
        db.add(msg); db.commit()
        return session, opening

    def _select_case(self, db: Session, difficulty_level: str, case_id: int = None) -> MedicalCase:
        if case_id:
            return db.query(MedicalCase).filter(MedicalCase.id == case_id).first()
        cases = db.query(MedicalCase).filter(
            MedicalCase.difficulty_level == difficulty_level).order_by(sqlfunc.random()).all()
        return cases[0] if cases else db.query(MedicalCase).order_by(sqlfunc.random()).first()

    def _generate_opening(self, session: TrainingSession, medical_case: MedicalCase) -> str:
        level = session.difficulty_level
        classic_ctx = self._detect_classic_context(medical_case)
        case_info = self._format_case_info(medical_case, level)
        prompts = {"初级": SYSTEM_PROMPT_BEGINNER, "中级": SYSTEM_PROMPT_INTERMEDIATE}
        prompt_cls = prompts.get(level, SYSTEM_PROMPT_ADVANCED)
        system_prompt = prompt_cls.format(
            classic_context=classic_ctx, guard=SAFETY_GUARD, case_info=case_info,
            step1_status="未完成", step2_status="未完成", step3_status="未完成")
        if self.client:
            resp = self._call_llm(system_prompt, [],
                "请开始吧。用患者的口吻，向'医生'描述你现在哪里不舒服。口语化，像个真的病人。不透露病名。")
            if resp: return resp
        return "医生你好，我最近身体不太舒服，想让你帮我看看……"

    # ---------- 多轮对话 ----------

    def process_message(self, db: Session, session_id: int,
                        student_content: str) -> Tuple[str, str, str, Optional[dict]]:
        session = db.query(TrainingSession).filter(TrainingSession.id == session_id).first()
        if not session:
            raise ValueError(f"会话 {session_id} 不存在")
        if session.status != "active":
            raise ValueError(f"会话 {session_id} 已结束")
        medical_case = session.case
        if not medical_case:
            raise ValueError("关联病案不存在")

        # 两级检测
        is_hard_jailbreak = self._detect_hard_jailbreak(student_content)
        playful_type = self._detect_playful_request(student_content) if not is_hard_jailbreak else None
        
        if is_hard_jailbreak:
            # 真正的越狱：用多样化拒绝语回应，不保存学生消息
            agent_response = self._get_jailbreak_response("hard")
            msg_type = "correction"
            progress = {"辨病": False, "平脉": False, "析证": False, "定治": False,
                       "message_count": 0, "current_stage": "辨病"}
            session_status = "active"
        else:
            # 正常消息或玩笑请求：保存学生消息，走正常 LLM 流程
            student_msg = SessionMessage(session_id=session_id, role="student",
                                         content=student_content, message_type="question")
            db.add(student_msg); db.commit()
            history = self._get_history_messages(session_id, db)

            # 诊法直出：号脉、看舌等检查直接返回病案里的客观体征，
            # 不经过患者模型——体征不是「让病人叙述」的内容。
            exam_key = detect_examination(student_content)
            if exam_key:
                agent_response, msg_type = self._handle_examination(
                    medical_case, session, exam_key, db
                )
                progress = self._analyze_progress(history, session)
                decision_path = session.decision_path or ""
                new_decision = self._extract_decision_point(
                    student_content, agent_response, progress
                )
                if new_decision:
                    session.decision_path = decision_path + new_decision + "\n"
                db.add(SessionMessage(
                    session_id=session_id, role="agent", content=agent_response,
                    message_type=msg_type,
                    key_decision=new_decision if new_decision else None,
                ))
                db.commit()
                should_end = self._should_end_session(
                    history, progress, session.difficulty_level
                )
                session_status = "completed" if should_end else "active"
                if should_end:
                    session.status = "completed"
                    session.ended_at = datetime.now()
                    db.commit()
                self._attach_guidance(progress, session, history)
                return agent_response, msg_type, session_status, progress

            current_treatment = assess_treatment_message(
                student_content, medical_case.prescription
            )
            treatment_assessment = assess_treatment_safety(
                history, medical_case.prescription
            )
            progress = self._analyze_progress(
                history, session, treatment_assessment=treatment_assessment
            )
            should_check_progress = self._should_check_ai_progress(history, progress)
            should_check_progress = should_check_progress or (
                current_treatment["treatment_proposed"]
                and current_treatment["level"] != "critical"
            )
            if should_check_progress:
                ai_progress = self._ai_check_progress(
                    medical_case, history, session.difficulty_level
                )
                progress = self._analyze_progress(
                    history,
                    session,
                    ai_progress=ai_progress,
                    treatment_assessment=treatment_assessment,
                )

            # history 已包含刚存入的学生消息；传给 _call_llm 时只追加一次当前输入。
            reply_history = self._history_before_current_input(history, student_content)
            
            # 构建系统提示词，如果检测到玩笑请求则注入额外上下文
            system_prompt = self._build_system_prompt(session, medical_case, progress)
            extra_contexts = []
            if playful_type:
                extra_contexts.append(
                    self._build_playful_context(playful_type, medical_case)
                )
            treatment_context = build_patient_treatment_context(current_treatment)
            if treatment_context:
                extra_contexts.append(treatment_context)
            if extra_contexts:
                system_prompt = "\n\n".join(extra_contexts + [system_prompt])
            
            agent_response = self._call_llm(
                system_prompt, reply_history, student_content
            ) or "【系统】AI 返回为空，请重新发送消息。"

            # 患者不懂医：医生说病名/证型时不能用「说得对/有道理」给判断打分。
            if self._is_confirming_judgement(student_content, agent_response):
                logger.info("患者回复确认了医生的判断，已替换为隐晦回应")
                agent_response = self._hedged_reply()
                msg_type = "hint"
            else:
                msg_type = self._classify_response(agent_response)
            
            decision_path = session.decision_path or ""
            new_decision = self._extract_decision_point(student_content, agent_response, progress)
            if new_decision:
                decision_path += new_decision + "\n"
                session.decision_path = decision_path
            
            agent_msg = SessionMessage(session_id=session_id, role="agent",
                                       content=agent_response, message_type=msg_type,
                                       key_decision=new_decision if new_decision else None)
            db.add(agent_msg); db.commit()
            
            should_end = self._should_end_session(history, progress, session.difficulty_level)
            session_status = "completed" if should_end else "active"
            if should_end:
                session.status = "completed"
                session.ended_at = datetime.now()
                db.commit()

        self._attach_guidance(progress, session, history)
        return agent_response, msg_type, session_status, progress
    
    def _attach_guidance(self, progress: dict, session, history: list) -> dict:
        """把下一步提示与进度展示所需的数据挂到 progress 上，供前端渲染。"""
        turns = sum(1 for m in history if m.get("role") == "user")
        progress["guidance"] = build_guidance(
            session.difficulty_level,
            progress,
            session.examinations_done or [],
            turns,
        )
        progress["level"] = session.difficulty_level
        progress["student_turns"] = turns
        progress["examinations_done"] = list(session.examinations_done or [])
        return progress

    def _handle_examination(self, medical_case: MedicalCase, session, exam_key: str, db):
        """处理一次体格检查：直接返回病案体征，并记录已获取。

        不重复检查：同一项体征只给一次，后续提示「已获取」。
        """
        exams = medical_case.examinations or {}
        exam = exams.get(exam_key)
        if not exam:
            return absent_reply(exam_key), None

        done = list(session.examinations_done or [])
        if exam_key in done:
            return build_repeat_reply(exam_key, exam), "hint"

        done.append(exam_key)
        session.examinations_done = done
        db.commit()
        return build_reply(exam_key, exam), None

    def _build_playful_context(self, playful_type: str, case: MedicalCase) -> str:
        """根据玩笑请求类型构建额外的提示词上下文"""
        if playful_type in ("western_checkup", "western_medication"):
            western_data = generate_western_test_context(case)
            return f"""## 特殊指令：学生提到了西医检查或西药
学生刚才说了跟西医检查或西药相关的话。你要像个真实的病人一样自然回应：

{western_data}

回应原则：
- 如果学生让你去检查：根据上面给你的数据，用日常口语说结果（如"之前查过血，说我血象有点高，可能有炎症"）
- 如果学生让你吃西药：可以说"吃过XX药，不太管用"或者"没吃过，要不你给开点试试？"
- 如果学生让你去做你没做过的检查：你可以说"那个没做过，要不下次去做一个？"
- 保持患者人格，该焦虑焦虑，该话痨话痨
- **仍然不能透露中医病名和方剂**
"""
        elif playful_type == "frustration":
            return """## 特殊指令：学生在表达不满
学生刚才有点急了。你作为一个真实的病人，被医生来回问却没结果，也会有点情绪。
- 根据你们的对话轮数和学生的语气，适当展现不耐烦
- 但不要真的发火，像个普通病人那样抱怨几句就回到正题
- 不影响你对症状描述的准确性
"""
        elif playful_type == "identity_question":
            return """## 特殊指令：学生在问你是不是AI
学生刚才在质疑你的身份（问你是不是AI/机器人）。作为一个真实的病人：
- 用困惑或略带生气的语气回应
- 比如："啥AI？我就是个来看病的人啊，你这医生怎么疑神疑鬼的？"
- 或者幽默一点："我要是机器人我还来看病干啥，直接去售后了"
- 自然地带回病情描述
"""
        return ""

    def _get_history_messages(self, session_id: int, db: Session,
                              limit: Optional[int] = 20) -> List[dict]:
        """读取会话消息。

        limit=20 是喂给模型的上下文窗口；结算与安全复盘传 limit=None 取全量，
        否则超过 20 条的会话在评价时会被砍掉前半程——学生前面明明问过、说过，
        结算时却当作没说过。
        """
        messages = db.query(SessionMessage).filter(
            SessionMessage.session_id == session_id).order_by(
                SessionMessage.created_at, SessionMessage.id
            ).all()
        if limit and limit > 0:
            messages = messages[-limit:]
        return [{"role": "assistant" if m.role == "agent" else ("user" if m.role == "student" else m.role), "content": m.content} for m in messages]

    @staticmethod
    def _history_before_current_input(history: List[dict], student_content: str) -> List[dict]:
        """移除刚持久化的当前输入，避免它在模型上下文中出现两次。"""
        if (
            history
            and history[-1].get("role") == "user"
            and history[-1].get("content") == student_content
        ):
            return history[:-1]
        return list(history)

    def _analyze_progress(self, history: List[dict], session: TrainingSession,
                          ai_progress: Optional[dict] = None,
                          treatment_assessment: Optional[dict] = None) -> dict:
        """按临床顺序判定四个阶段。

        阶段定义（2026-11 起）：
        - 辨病：说出病名或证型方向
        - 平脉：完成切诊取得脉象（脉象的「含义」属于析证，不在这一步）
        - 析证：解释病机，并至少给出一组鉴别
        - 定治：同时给出治法与方剂
        """
        progress = {"辨病": False, "平脉": False, "析证": False, "定治": False,
                    "message_count": len(history), "current_stage": "辨病"}
        # 只统计学生自己的表述：患者的话（包括直出的脉舌体征）不能算作学生的辨证
        all_text = " ".join([
            m.get("content", "") for m in history[-10:] if m.get("role") == "user"
        ])
        turns = sum(1 for m in history if m.get("role") == "user")

        # 剔掉「与太阳表虚鉴别」这类子句：鉴别对象不是学生自己的辨病结论
        disease_text = re.sub(r"与[^，。；]{0,12}(?:鉴别|区别|相鉴)", " ", all_text)
        disease_hit = any(k in disease_text for k in DISEASE_KEYWORDS)
        # 平脉看的是「有没有真的做切诊」，而不是有没有提到「脉」字
        pulse_done = "pulse" in set(session.examinations_done or [])
        patho_hit = any(k in all_text for k in PATHOGENESIS_KEYWORDS)
        diff_hit = any(k in all_text for k in DIFFERENTIAL_KEYWORDS)
        method_hit = any(k in all_text for k in TREATMENT_METHOD_KEYWORDS)
        formula_hit = bool(
            any(k in all_text for k in FORMULA_KEYWORDS)
            or (treatment_assessment and treatment_assessment.get("matches_expected"))
        )

        level = session.difficulty_level

        if level == "初级":
            if disease_hit and turns >= 2:
                progress["辨病"] = True
                progress["current_stage"] = "主证识别"
            merged = self._merge_ai_progress(progress, ai_progress, treatment_assessment)
            # 初级只有「辨病 / 主证识别」两态：辨病一旦成立，阶段名跟着走，
            # 不能用模型给的，也不能停在初始值
            if merged["辨病"]:
                merged["current_stage"] = "主证识别"
            return merged

        if disease_hit and turns >= 2:
            progress["辨病"] = True
            progress["current_stage"] = "平脉"
        if progress["辨病"] and pulse_done:
            progress["平脉"] = True
            progress["current_stage"] = "析证"
        # 析证要求：病机 + 至少一组鉴别
        if progress["平脉"] and patho_hit and diff_hit:
            progress["析证"] = True
            progress["current_stage"] = "定治" if level == "高级" else "已完成"

        if level == "高级" and progress["析证"] and method_hit and formula_hit:
            progress["定治"] = True
            progress["current_stage"] = "已完成"

        merged = self._merge_ai_progress(progress, ai_progress, treatment_assessment)
        # AI 只补布尔判断，阶段名一律按规则重算——否则模型会在定治未完成时
        # 直接说「已完成」，引导与进度条就一起跑偏了。
        merged["current_stage"] = self._stage_from_progress(merged, level)
        return merged

    @staticmethod
    def _merge_ai_progress(progress: dict, ai_progress: Optional[dict],
                           treatment_assessment: Optional[dict] = None) -> dict:
        """AI 复核只能补足「辨病 / 析证」的语义判断。

        平脉与定治有硬条件，不允许模型绕过：
        - 平脉 = 真的做过切诊（``examinations_done`` 含 pulse），不是话里带了「脉」字；
        - 定治 = **同时**给出治法与方剂。

        线上实测过反面案例：学生只说了「应当调和营卫，疏肝解郁」，一个方都没开，
        模型却把它判成定治完成，会话于是在"该开方"之前就自己结束了。

        ``treatment_assessment`` 参数保留是为了兼容调用方；方证是否相符由
        ``formula_hit`` 与安全复盘各自负责，不再在这里放行。
        """
        if not ai_progress:
            return progress
        for key in ("辨病", "析证"):
            if ai_progress.get(key):
                progress[key] = True
        return progress

    @staticmethod
    def _stage_from_progress(progress: dict, level: str) -> str:
        """按进度推算当前阶段，避免沿用模型给的「已完成」。"""
        if progress.get("定治"):
            return "已完成"
        if progress.get("析证"):
            return "定治" if level == "高级" else "已完成"
        if progress.get("平脉"):
            return "析证"
        if progress.get("辨病"):
            return "平脉"
        return "辨病"

    def _build_system_prompt(self, session: TrainingSession, medical_case: MedicalCase,
                              progress: dict) -> str:
        level = session.difficulty_level
        classic_ctx = self._detect_classic_context(medical_case)
        case_info = self._format_case_info(medical_case, level)
        s1 = "已完成" if progress.get("辨病") else "未完成"
        s2 = "已完成" if progress.get("平脉") else "未完成"
        s3 = "已完成" if progress.get("定治") else "未完成"
        if level == "初级":
            # 初级档只有"辨病"这一处确定性判定，模板里的"主证识别"用当前阶段表示，
            # 不能再把辨病状态原样传一次（此前两个进度永远同值）。
            syndrome_status = (
                "进行中"
                if progress.get("辨病") and progress.get("current_stage") == "主证识别"
                else "未完成"
            )
            prompt = SYSTEM_PROMPT_BEGINNER.format(
                classic_context=classic_ctx, guard=SAFETY_GUARD, case_info=case_info,
                step1_status=s1, step2_status=syndrome_status)
        elif level == "中级":
            prompt = SYSTEM_PROMPT_INTERMEDIATE.format(
                classic_context=classic_ctx, guard=SAFETY_GUARD, case_info=case_info,
                step1_status=s1, step2_status=s2)
        else:
            prompt = SYSTEM_PROMPT_ADVANCED.format(
                classic_context=classic_ctx, guard=SAFETY_GUARD, case_info=case_info,
                step1_status=s1, step2_status=s2, step3_status=s3)
        # 注入基于实际进度的行为指令
        progress_hint = self._build_progress_hint(progress)
        if progress_hint:
            prompt += "\n\n" + progress_hint
        return prompt

    def _build_progress_hint(self, progress: dict) -> str:
        return build_progress_hint(progress)
    def _format_case_info(self, medical_case: MedicalCase, level: str,
                          include_reference: bool = False) -> str:
        """构造模型上下文；患者对话默认不携带标题、答案和处方等隐藏信息。"""
        parts = []
        if include_reference:
            parts.append(f"病案标题：{medical_case.title}")
        if medical_case.symptoms:
            parts.append(f"【症状描述】{medical_case.symptoms[:500]}")
        parts.append(f"【主诉/病史】{medical_case.content[:600]}")
        if include_reference and medical_case.diagnosis:
            parts.append(f"（导师参考——诊断：{medical_case.diagnosis}）")
        if include_reference and medical_case.prescription:
            parts.append(f"（导师参考——方剂：{medical_case.prescription}）")
        if include_reference and medical_case.teaching_points:
            parts.append(f"【教学要点——据此引导学生】{medical_case.teaching_points[:500]}")
        if include_reference and medical_case.correct_answer:
            parts.append(f"【参考答案——评判正误】{medical_case.correct_answer[:600]}")
        return "\n".join(parts)

    def _classify_response(self, response: str) -> str:
        return classify_response(response)

    def _extract_decision_point(self, student: str, agent: str, progress: dict) -> Optional[str]:
        return extract_decision_point(student, agent, progress)

    def _should_end_session(self, history: List[dict], progress: dict, level: str) -> bool:
        return should_end_session(history, progress, level)

    # ---------- 评价 ----------

    @staticmethod
    def _parse_semantic_verdict(resp: str) -> Optional[dict]:
        """解析语义复核结果；整体 JSON 坏了就按条目兜底提取。

        实测模型偶尔会输出结构不合法的长 JSON（缺逗号、引号未转义），
        直接抛 JSONDecodeError 会让整次复核白跑。
        """
        text = resp or ""
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        recovered = {}
        for key in ("要点", "信息"):
            block = re.search(r'"' + key + r'"\s*:\s*\[([\s\S]*?)\]', text)
            if not block:
                continue
            items = [
                {"编号": int(m.group(1)), "依据": m.group(2)}
                for m in re.finditer(
                    r'"编号"\s*:\s*(\d+)[\s\S]*?"依据"\s*:\s*"([^"]*)"',
                    block.group(1),
                )
            ]
            if items:
                recovered[key] = items
        return recovered or None

    def _review_unmatched(self, review: dict) -> Optional[dict]:
        """让模型复核规则没判上的要点与信息。

        只判「没判上的」：已经命中或明确未命中的不再交给模型，避免它推翻
        规则已经确定的结论。模型不可用、超时或返回无法解析时返回 None，
        调用方保留规则结果——降级路径始终可用。
        """
        if not self.client:
            return None
        try:
            resp = self._call_llm(
                "你是中医教学评分助手。只输出 JSON。", [],
                review["prompt"], temperature=0.1, max_tokens=400,
            )
            verdict = self._parse_semantic_verdict(resp)
            if not verdict:
                logger.warning("语义复核未返回可解析结果，保留规则结果")
                return None
            logger.info("语义复核：要点 %s，信息 %s",
                        verdict.get("要点"), verdict.get("信息"))
            return verdict
        except Exception as exc:
            logger.warning("语义复核失败，保留规则结果：%s", exc)
            return None

    def evaluate_session(self, db: Session, session_id: int) -> dict:
        session = db.query(TrainingSession).filter(TrainingSession.id == session_id).first()
        if not session: raise ValueError(f"会话 {session_id} 不存在")
        medical_case = session.case
        messages = self._get_history_messages(session_id, db)
        # 结算要看整场对话，不能只看最近 20 条
        all_messages = self._get_history_messages(session_id, db, limit=None)
        conversation = ""
        for m in messages:
            role = "学生" if m.get("role") == "user" else "智能体"
            conversation += f"{role}：{m.get('content','')[:300]}\n\n"
        case_info = self._format_case_info(
            medical_case, session.difficulty_level, include_reference=True
        ) if medical_case else "无"
        classic_ctx = self._detect_classic_context(medical_case) if medical_case else "未知"
        # 先算规则评分：评价提示词要把它带进去。否则模型会给出与学生实际表现
        # 相反的评语——实测里学生一个方都没开，评价却写着「定治合理」。
        scoring = evaluate_scoring(
            medical_case, session.difficulty_level, all_messages
        ) if medical_case else None
        # 规则判不上的部分交给模型复核一遍：学生说「嘴巴干又苦」而要点写的是「口苦」，
        # 纯关键词永远追不上表达方式。复核失败就保留规则结果。
        if scoring:
            review = build_semantic_review(scoring, all_messages)
            if review:
                verdict = self._review_unmatched(review)
                if verdict:
                    scoring = apply_semantic_review(review, verdict)
        scoring_brief = format_scoring_brief(scoring) if scoring else ""
        eval_prompt = EVALUATION_PROMPT.format(
            classic_context=classic_ctx, level=session.difficulty_level,
            case_info=case_info, conversation=conversation,
            scoring_brief=scoring_brief or "（本例未配置评分要点，按你自己的判断评价）")
        eval_text, score = "", "未评分"
        evaluation_data = None
        safety_feedback = assess_treatment_safety(
            all_messages, medical_case.prescription if medical_case else None
        )
        if self.client:
            resp = self._call_llm("你是教学评价专家。只输出JSON。", [], eval_prompt, temperature=0.3)
            try:
                m = re.search(r'\{[\s\S]*\}', resp)
                if m:
                    evaluation_data = json.loads(m.group())
                    score = str(evaluation_data.get("综合评分", "未评分"))
                    eval_text = json.dumps(evaluation_data, ensure_ascii=False, indent=2)
                else:
                    eval_text = resp
            except json.JSONDecodeError:
                eval_text = resp
        else:
            evaluation_data = {
                "综合评分":"N/A","辨病准确度":"N/A","平脉分析度":"N/A",
                "析证清晰度":"N/A","定治合理性":"N/A","框架完整度":"N/A",
                "思辨能力等级":"N/A","优点":"AI未配置","改进建议":"请配置API"
            }
            eval_text = json.dumps(evaluation_data, ensure_ascii=False, indent=2)

        # 结构化要点评分：病案配了 scoring_points 时，以逐条对照的得分为准。
        # 模型给的综合分降级为「AI综合评分」保留——规则分可复现、可解释，
        # 模型分会随温度浮动，同一场对话两次评价能差几十分。
        if scoring and scoring.get("gradable"):
            point_score = round(scoring["ratio"] * 100, 1)
            scoring["score"] = point_score
            ai_score = score
            score = f"{point_score:g}"
            if evaluation_data is not None:
                evaluation_data["AI综合评分"] = ai_score
                evaluation_data["综合评分"] = point_score
                evaluation_data["要点得分"] = format_scoring_brief(scoring)
                eval_text = json.dumps(evaluation_data, ensure_ascii=False, indent=2)

        if safety_feedback["level"] == "critical":
            score = "0"
            if evaluation_data is not None:
                evaluation_data["综合评分"] = 0
                evaluation_data["用药安全复盘"] = safety_feedback["summary"]
                evaluation_data["改进建议"] = (
                    "本次训练触发严重用药安全风险。请先复盘处方安全边界，"
                    "再重新完成病机、方证与治疗方案推演。"
                )
                eval_text = json.dumps(evaluation_data, ensure_ascii=False, indent=2)
            else:
                eval_text += f"\n\n【用药安全复盘】{safety_feedback['summary']}"
        elif evaluation_data is not None:
            evaluation_data["用药安全复盘"] = safety_feedback["summary"]
            eval_text = json.dumps(evaluation_data, ensure_ascii=False, indent=2)
        session.status = "completed"; session.score = score; session.ended_at = datetime.now()
        # 评价结果落库：重复打开已评价会话时直接回放，不再花一次模型调用
        session.evaluation = eval_text
        session.scoring = scoring
        db.commit()
        dp = self._summarize_decision_path(session, all_messages)
        session.decision_path = dp; db.commit()

        # 匹配相关经典条文
        related_texts = self._get_related_texts(db, medical_case) if medical_case else []

        return {
            "evaluation": eval_text,
            "score": score,
            "decision_path": dp,
            "related_texts": related_texts,
            "safety_feedback": safety_feedback,
            "scoring": scoring,
        }

    def _get_related_texts(self, db: Session, medical_case) -> List[dict]:
        """匹配与病案相关的经典条文"""
        from ..models import ClassicText
        from .matcher import get_matcher
        try:
            matcher = get_matcher()
            scored_texts = matcher.find_related_texts(medical_case, db, limit=5)
            return [
                {
                    "id": text.id,
                    "source_book": text.source_book,
                    "chapter": text.chapter or "",
                    "content": text.content,
                    "similarity": round(score, 2)
                }
                for text, score in scored_texts if score > 0.05
            ]
        except Exception as e:
            logger.warning("条文匹配失败: %s", e)
            return []

    def _summarize_decision_path(self, session: TrainingSession, messages: List[dict]) -> str:
        path = [f"训练等级：{session.difficulty_level}"]
        sm = [m for m in messages if m.get("role") == "user"]
        path.append(f"交互轮数：{len(sm)}")
        path.append("路径：辨病 → 平脉 → 析证 → 定治")
        for i, m in enumerate(sm[:10]):
            c = m.get("content", "")
            path.append(f"第{i+1}轮：{c[:60]}{'...' if len(c)>60 else ''}")
        return "\n".join(path)


def get_agent() -> TrainingAgent:
    """请求级依赖注入：每个请求独立实例，避免并发状态污染。"""
    return TrainingAgent()
