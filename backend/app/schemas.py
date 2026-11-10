"""
Pydantic数据模型（用于API请求和响应验证）
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


# ========== 经典条文 ==========
class ClassicTextBase(BaseModel):
    source_book: str = Field(..., description="来源经典：《伤寒论》或《金匮要略》")
    chapter: Optional[str] = Field(None, description="篇章名（如 辨太阳病脉证并治）")
    section: Optional[str] = Field(None, description="子篇（如 上/中/下）")
    article_number: Optional[int] = Field(None, description="条文编号（如 1, 2, 3...398）")
    order_index: Optional[int] = Field(None, description="篇章内排序")
    content: str = Field(..., description="条文内容")
    keywords: Optional[str] = Field(None, description="关键词，逗号分隔")


class ClassicTextCreate(ClassicTextBase):
    pass


class ClassicTextUpdate(BaseModel):
    source_book: Optional[str] = None
    chapter: Optional[str] = None
    section: Optional[str] = None
    article_number: Optional[int] = None
    order_index: Optional[int] = None
    content: Optional[str] = None
    keywords: Optional[str] = None


class ClassicTextResponse(ClassicTextBase):
    id: int
    verified: bool = False
    verified_at: Optional[datetime] = None
    source_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== 互联网校验 ==========
class TextVerifyRequest(BaseModel):
    """单条条文校验请求"""
    text_id: int = Field(..., description="要校验的条文ID")


class TextVerifyResponse(BaseModel):
    """校验结果"""
    text_id: int
    article_number: Optional[int] = None
    expected_article_number: Optional[int] = Field(None, description="互联网参考的条文编号")
    chapter_correct: bool = Field(False, description="章节归属是否正确")
    content_match: bool = Field(False, description="内容是否与权威来源一致")
    expected_chapter: Optional[str] = Field(None, description="互联网参考的篇章名")
    expected_section: Optional[str] = Field(None, description="互联网参考的子篇（上/中/下）")
    source_url: Optional[str] = Field(None, description="互联网参考来源")
    detail: Optional[str] = Field(None, description="详细比对说明")
    verified: bool = False
    fixed: bool = Field(False, description="是否执行了自动修复")


class TextVerifyBatchResponse(BaseModel):
    """批量校验结果"""
    total: int
    verified: int
    fixed: int
    details: List[TextVerifyResponse] = []


# ========== 病案 ==========
class MedicalCaseBase(BaseModel):
    title: str = Field(..., description="病案标题")
    content: str = Field(..., description="病案内容")
    symptoms: Optional[str] = Field(None, description="症状描述")
    diagnosis: Optional[str] = Field(None, description="诊断")
    prescription: Optional[str] = Field(None, description="方剂")
    difficulty_level: Optional[str] = Field("初级", description="难度等级：初级/中级/高级")
    teaching_points: Optional[str] = Field(None, description="教学要点")
    correct_answer: Optional[str] = Field(None, description="参考答案")
    examinations: Optional[dict] = Field(
        None, description="可检查的客观体征（脉/舌/腹/面/咽），训练中由诊法直出返回"
    )
    key_facts: Optional[List[dict]] = Field(
        None, description="问诊要点，用于统计学生是否问到了必问项"
    )
    scoring_points: Optional[List[dict]] = Field(
        None, description="评分要点，按关键词逐条对照打分，支持 min_level 按难度过滤"
    )


class MedicalCaseCreate(MedicalCaseBase):
    pass


class MedicalCaseUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    prescription: Optional[str] = None
    difficulty_level: Optional[str] = None
    teaching_points: Optional[str] = None
    correct_answer: Optional[str] = None
    examinations: Optional[dict] = None
    key_facts: Optional[List[dict]] = None
    scoring_points: Optional[List[dict]] = None


class MedicalCaseResponse(MedicalCaseBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MedicalCasePublicResponse(BaseModel):
    """公开病案视图 —— 不含诊断、方剂、教学要点与参考答案，仅供学生端使用。

    训练系统的核心约束是学生看不到标准答案，因此公开接口一律使用本模型；
    需要完整字段的调用方必须走 /api/cases/admin/（管理员认证）。
    """
    id: int
    title: str
    content: str
    symptoms: Optional[str] = None
    difficulty_level: Optional[str] = Field("初级", description="难度等级：初级/中级/高级")

    class Config:
        from_attributes = True


# ========== 文档 ==========
class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    upload_date: datetime
    processed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== 分析 ==========
class AnalysisQuery(BaseModel):
    text: str = Field(..., description="输入的条文内容")
    model: Optional[str] = Field(None, description="可选，指定模型（如 deepseek-chat、deepseek-v3）")


class AnalysisResponse(BaseModel):
    text_id: Optional[int] = None
    text_content: str
    matched_cases: List[MedicalCaseResponse] = []
    analysis_result: str = Field(..., description="分析结果")


# ========== 批量操作 ==========
class BatchDeleteIds(BaseModel):
    ids: List[int] = Field(..., description="要删除的ID列表")


# ========== 通用响应 ==========
class MessageResponse(BaseModel):
    message: str
    success: bool = True


# ========== 智能体训练 ==========
class SessionStartRequest(BaseModel):
    """开始训练会话请求"""
    difficulty_level: str = Field("初级", description="难度等级：初级/中级/高级")
    student_id: Optional[str] = Field(
        "anonymous", max_length=32, description="学生标识（学号或昵称，留空视为匿名）"
    )
    case_id: Optional[int] = Field(None, description="指定病案ID（留空则自动选取）")


class SessionStartResponse(BaseModel):
    """开始训练会话响应"""
    session_id: int
    difficulty_level: str
    case_title: str
    agent_message: str = Field(..., description="智能体的开场引导消息")
    session_token: str = Field(
        ...,
        description="会话归属令牌。后续 /message 与 /evaluate 必须通过 X-Session-Token 请求头回传",
    )
    guidance: Optional[dict] = Field(None, description="开始后的第一步提示")


class SessionMessageRequest(BaseModel):
    """学生发送消息请求"""
    content: str = Field(..., description="学生输入的内容")


class SessionMessageResponse(BaseModel):
    """智能体回复消息响应"""
    agent_message: str = Field(..., description="智能体的回复内容")
    message_type: Optional[str] = Field(
        None, description="消息类型：question/hint/correction/praise/evaluation；体征直出等消息为 null"
    )
    session_status: str = Field("active", description="会话状态：active/completed")
    progress: Optional[dict] = Field(None, description="当前进度（辨病/平脉/析证/定治）")


class SessionDetailResponse(BaseModel):
    """会话详情响应"""
    id: int
    student_id: str
    difficulty_level: str
    status: str
    case_title: Optional[str] = None
    decision_path: Optional[str] = None
    score: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    messages: List[dict] = []

    class Config:
        from_attributes = True


class SessionEvaluateResponse(BaseModel):
    """会话评价响应"""
    session_id: int
    score: str = Field(..., description="综合评价")
    evaluation: str = Field(..., description="详细评价报告")
    decision_path: str = Field(..., description="辨治路径追溯（辨病→平脉→析证→定治）")
    case_title: Optional[str] = Field(None, description="病案标题（训练结束后揭晓）")
    case_correct_answer: Optional[str] = Field(None, description="参考答案（训练结束后揭晓）")
    related_texts: Optional[List[dict]] = Field(None, description="相关经典条文（含出处和原文）")
    safety_feedback: Optional[dict] = Field(None, description="训练用药安全复盘（非真实诊疗建议）")
    scoring: Optional[dict] = Field(
        None,
        description="结构化要点得分：逐条命中情况、分阶段小计、问诊完整度；病案未配要点时为 null",
    )


class PublicStatsResponse(BaseModel):
    """公开首页使用的聚合统计，不包含学生或会话明细。"""
    text_count: int
    case_count: int
    session_count: int
    average_score: Optional[float] = None


# ========== 用户反馈 ==========
class FeedbackCreate(BaseModel):
    """提交反馈请求"""
    # 公开接口，类别用枚举收口，避免任意字符串入库后被管理端渲染
    category: Literal["功能建议", "bug反馈", "使用体验", "其他"] = Field(
        ..., description="反馈类别：功能建议/bug反馈/使用体验/其他"
    )
    content: str = Field(..., min_length=5, max_length=2000, description="反馈内容（5-2000字）")
    contact: Optional[str] = Field(None, description="联系方式（可选）")
    session_id: Optional[int] = Field(None, description="关联的训练会话ID（可选）")


class FeedbackUpdate(BaseModel):
    """管理员更新反馈状态"""
    status: Optional[str] = Field(None, description="状态：pending/resolved/closed")
    admin_note: Optional[str] = Field(None, description="管理员备注")


class FeedbackResponse(BaseModel):
    """反馈列表响应"""
    id: int
    session_id: Optional[int] = None
    category: str
    content: str
    contact: Optional[str] = None
    status: str
    admin_note: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    session_difficulty: Optional[str] = Field(None, description="关联会话难度（如有）")

    class Config:
        from_attributes = True
