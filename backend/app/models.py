"""
数据库模型定义
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class Category(Base):
    """分类表"""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, comment="分类名称")
    description = Column(Text, comment="分类描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    texts = relationship("ClassicText", back_populates="category")
    cases = relationship("MedicalCase", back_populates="category")


class ChapterMeta(Base):
    """篇章元数据表 —— 定义每本书的正确篇章结构和层级"""
    __tablename__ = "chapter_meta"

    id = Column(Integer, primary_key=True, index=True)
    book = Column(String(50), nullable=False, comment="书：《伤寒论》或《金匮要略》")
    chapter = Column(String(200), nullable=False, comment="篇章名")
    section = Column(String(100), comment="子篇（如太阳病 上/中/下）")
    order_index = Column(Integer, nullable=False, comment="篇章排序")
    article_count_expected = Column(Integer, comment="该篇章预期条文数（用于校验）")


class ClassicText(Base):
    """经典条文表 —— 支持书→篇章→条文 三级结构"""
    __tablename__ = "classic_texts"

    id = Column(Integer, primary_key=True, index=True)
    source_book = Column(String(200), nullable=False, comment="来源经典：《伤寒论》或《金匮要略》")
    chapter = Column(String(200), comment="篇章名（如 辨太阳病脉证并治）")
    section = Column(String(100), comment="子篇（如 上/中/下，仅太阳病需要）")
    article_number = Column(Integer, comment="条文编号（如 1, 2, 3...398）")
    order_index = Column(Integer, comment="篇章内排序序号")
    content = Column(Text, nullable=False, comment="规范正文（已清除排版符号、条号、冗余空白，供展示与检索）")
    keywords = Column(String(500), comment="关键词，逗号分隔")
    category_id = Column(Integer, ForeignKey("categories.id"), comment="分类ID")

    # ── 溯源字段 ──
    raw_content = Column(Text, comment="原始文本（含罗马数字、条号标记等，供追溯）")
    layout_marker = Column(String(10), comment="版式标记（如 Ⅰ/Ⅱ/Ⅲ，从展示正文中清除的符号）")
    source_file = Column(String(500), comment="来源文件名")
    source_hash = Column(String(64), comment="来源文件的 SHA-256 哈希")
    source_offset = Column(Integer, comment="在来源文件中的段落偏移量")
    source_edition = Column(String(200), comment="底本版本信息")
    import_batch_id = Column(String(36), comment="导入批次 ID（UUID）")

    # 互联网校验字段
    verified = Column(Boolean, default=False, comment="是否已通过互联网比对校验")
    verified_at = Column(DateTime(timezone=True), comment="校验时间")
    source_url = Column(String(500), comment="互联网参考来源URL")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    category = relationship("Category", back_populates="texts")
    related_cases = relationship("TextCaseRelation", back_populates="text")


class ImportBatch(Base):
    """导入批次表 —— 一次上传/导入产生一个批次"""
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(36), unique=True, nullable=False, comment="批次 UUID")
    source_file = Column(String(500), comment="来源文件名")
    source_hash = Column(String(64), comment="来源文件 SHA-256")
    source_edition = Column(String(200), comment="底本版本")
    total_articles = Column(Integer, default=0, comment="解析出的条文总数")
    unique_numbers = Column(Integer, default=0, comment="识别的唯一条号数")
    status = Column(String(20), default="pending", comment="状态：pending/needs_review/published/rejected")
    quality_report = Column(Text, comment="质检报告 JSON")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), comment="发布时间")


class ImportStaging(Base):
    """导入暂存表 —— 解析结果先存此处，人工确认后再发布到 classic_texts"""
    __tablename__ = "import_staging"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(36), ForeignKey("import_batches.batch_id"), nullable=False, comment="所属批次")
    source_book = Column(String(200), nullable=False)
    chapter = Column(String(200))
    section = Column(String(100))
    article_number = Column(Integer, comment="条号")
    order_index = Column(Integer, comment="篇章内排序")
    raw_content = Column(Text, comment="原始文本（含排版符号）")
    content = Column(Text, nullable=False, comment="规范正文（已清理）")
    layout_marker = Column(String(10), comment="版式标记")
    keywords = Column(String(500))
    source_file = Column(String(500))
    source_hash = Column(String(64))
    source_offset = Column(Integer, comment="段落偏移量")
    source_edition = Column(String(200))
    status = Column(String(20), default="needs_review", comment="状态：needs_review/approved/rejected")
    issue = Column(String(200), comment="质量问题标记（如 duplicate/missing_chapter/empty_content）")
    duplicate_of = Column(Integer, comment="重复号：指向同 batch 中相同 article_number 的另一条，或 classic_texts 中的已有记录")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    batch = relationship("ImportBatch", backref="staging_records", foreign_keys=[batch_id])


class MedicalCase(Base):
    """病案表"""
    __tablename__ = "medical_cases"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, comment="病案标题")
    content = Column(Text, nullable=False, comment="病案内容")
    symptoms = Column(Text, comment="症状描述")
    diagnosis = Column(String(200), comment="诊断")
    prescription = Column(String(500), comment="方剂")
    category_id = Column(Integer, ForeignKey("categories.id"), comment="分类ID")
    difficulty_level = Column(String(20), default="初级", comment="难度等级：初级/中级/高级")
    teaching_points = Column(Text, comment="教学要点（用于智能体引导）")
    correct_answer = Column(Text, comment="参考答案（辨病/平脉/析证/定治）")
    # 体格检查可得客观体征：{"pulse": {"text": "脉弦缓"}, "tongue": {...}}
    examinations = Column(JSON, comment="可检查的客观体征（脉/舌/腹/面/咽），供诊法直出使用")
    # 结构化教学数据（P3）：让评分从「LLM 自由打分」变成「按要点逐条对照」
    # key_facts: [{"id":"chief","label":"主诉","text":"...","must_ask":true,"min_level":"初级","keywords":[...]}]
    key_facts = Column(JSON, comment="问诊要点，用于完整度统计")
    # scoring_points: [{"stage":"辨病","text":"...","weight":20,"keywords":[...],"min_level":"初级"}]
    scoring_points = Column(JSON, comment="评分要点，按关键词逐条对照打分")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    category = relationship("Category", back_populates="cases")
    related_texts = relationship("TextCaseRelation", back_populates="case")


class TextCaseRelation(Base):
    """条文与病案关联表"""
    __tablename__ = "text_case_relations"

    id = Column(Integer, primary_key=True, index=True)
    text_id = Column(Integer, ForeignKey("classic_texts.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("medical_cases.id"), nullable=False)
    similarity_score = Column(String(50), comment="相似度评分")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    text = relationship("ClassicText", back_populates="related_cases")
    case = relationship("MedicalCase", back_populates="related_texts")


class Document(Base):
    """上传文档表"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(500), nullable=False, comment="文件名")
    file_type = Column(String(50), comment="文件类型：pdf, docx, txt等")
    file_path = Column(String(1000), comment="文件存储路径")
    file_size = Column(Integer, comment="文件大小（字节）")
    parsed_content = Column(Text, comment="解析后的内容")
    status = Column(String(50), default="pending", comment="状态：pending, processing, completed, failed")
    error_message = Column(Text, comment="解析失败原因（供管理员排查与重试）")
    upload_date = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), comment="处理完成时间")


class LearningHistory(Base):
    """学习记录表"""
    __tablename__ = "learning_history"

    id = Column(Integer, primary_key=True, index=True)
    user_query = Column(Text, nullable=False, comment="用户查询的条文")
    text_id = Column(Integer, ForeignKey("classic_texts.id"), comment="关联的条文ID")
    case_id = Column(Integer, ForeignKey("medical_cases.id"), comment="关联的病案ID")
    analysis_result = Column(Text, comment="AI分析结果")
    query_time = Column(DateTime(timezone=True), server_default=func.now())


class TrainingSession(Base):
    """训练会话表 —— 智能体三阶梯多轮交互"""
    __tablename__ = "training_sessions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(100), default="anonymous", comment="学生标识（可扩展为学号）")
    difficulty_level = Column(String(20), nullable=False, comment="难度等级：初级/中级/高级")
    case_id = Column(Integer, ForeignKey("medical_cases.id"), comment="关联的病案ID")
    status = Column(String(20), default="active", comment="会话状态：active/completed/abandoned")
    decision_path = Column(Text, comment="学生辨治路径摘要（辨病→平脉→析证→定治）")
    # 已完成过的体格检查项，用于「不重复检查」判定
    examinations_done = Column(JSON, default=list, comment="已获取的检查项 key 列表")
    score = Column(String(50), comment="综合评价分数/等级")
    # 评价结果落库：重复打开「已评价」的会话时直接回放，不必再花一次模型调用
    evaluation = Column(Text, comment="评价报告原文（JSON 文本）")
    scoring = Column(JSON, comment="结构化要点得分明细")
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), comment="结束时间")

    # 关系
    case = relationship("MedicalCase")
    messages = relationship("SessionMessage", back_populates="session", order_by="SessionMessage.created_at")


class SessionMessage(Base):
    """会话消息表"""
    __tablename__ = "session_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("training_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False, comment="角色：student / agent / system")
    content = Column(Text, nullable=False, comment="消息内容")
    message_type = Column(String(30), comment="消息类型：question/hint/correction/praise/evaluation/other")
    key_decision = Column(Text, comment="关键决策点记录（如辨病完成、析证完成等）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    session = relationship("TrainingSession", back_populates="messages")


class Feedback(Base):
    """用户反馈表"""
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("training_sessions.id"), comment="关联的训练会话ID（可选）")
    category = Column(String(30), nullable=False, comment="反馈类别：功能建议/bug反馈/使用体验/其他")
    content = Column(Text, nullable=False, comment="反馈内容")
    contact = Column(String(200), comment="联系方式（可选）")
    status = Column(String(20), default="pending", comment="状态：pending/resolved/closed")
    admin_note = Column(Text, comment="管理员备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), comment="处理时间")

    # 关系
    session = relationship("TrainingSession")
