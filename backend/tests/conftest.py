"""pytest 公共夹具与全局隔离。

测试环境的三条约定（改动前请先读）：

1. **不碰真实数据**：`DATA_DIR` 指向进程级临时目录，因此数据库与上传目录都落在临时区，
   不会污染仓库内的 `backend/data/tcm.db` 和 `backend/uploads/`。
2. **不发真实请求**：AI 相关环境变量默认置空，任何用例都不会调用外部模型接口；
   需要验证"已配置"分支时，在用例内用 `monkeypatch.setenv` 临时打开。
3. **不依赖本机配置**：管理员密码与会话令牌密钥使用测试专用值。

在此之上，`test_parser.py` 会即时生成 DOCX，避免依赖仓库外的大文件。
"""
import os
import tempfile

os.environ.setdefault("ADMIN_PASSWORD", "jingui2026")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="jingui-tests-"))
for _key in (
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "DASHSCOPE_API_KEY",
    "BAIDU_API_KEY",
    "BAIDU_SECRET_KEY",
    "AI_MODEL",
):
    os.environ.setdefault(_key, "")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.models import MedicalCase, TrainingSession, SessionMessage
from app.services.agent_service import TrainingAgent


# ==================== 数据库夹具 ====================

@pytest.fixture(scope="function")
def engine():
    """每个测试函数独立的 SQLite 内存引擎"""
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=e)
    yield e
    Base.metadata.drop_all(bind=e)


@pytest.fixture(scope="function")
def db_session(engine):
    """每个测试函数独立的数据库会话（自动回滚）"""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ==================== FastAPI TestClient 夹具 ====================

@pytest.fixture(scope="function")
def client(engine, monkeypatch):
    """FastAPI 测试客户端：DB 依赖替换为内存引擎，跳过启动期迁移与后台解析。"""
    from app.main import app
    from app.database import get_db as original_get_db

    Session = sessionmaker(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[original_get_db] = override_get_db

    # 启动期迁移只针对持久库，测试用内存库，跳过以节省每次 CASE 的开销
    monkeypatch.setattr("app.main.init_db", lambda: None, raising=False)
    # 上传后的后台解析会走独立 Session，测试中打桩，避免触碰任何真实库
    monkeypatch.setattr(
        "app.routers.documents.process_document", lambda *a, **k: None, raising=False
    )

    Base.metadata.create_all(bind=engine)

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ==================== 样本数据夹具 ====================

@pytest.fixture(scope="function")
def sample_case_beginner(db_session):
    """初级难度样本病案：湿病（麻黄加术汤证）"""
    case = MedicalCase(
        title="湿病——麻黄加术汤证",
        content="患者张某，男，45岁。3天前淋雨后出现全身关节疼痛、沉重，恶寒发热，无汗。",
        symptoms="身痛重着、恶寒发热、无汗、舌苔白腻",
        diagnosis="湿病（表湿证）",
        prescription="麻黄加术汤",
        difficulty_level="初级",
        teaching_points="辨病关键：身痛重着+恶寒发热=表湿。与太阳伤寒鉴别：彼无'重着'感。",
        correct_answer="辨病：湿病。平脉：N/A。析证：表湿证，湿邪在表，卫阳被遏。定治：麻黄加术汤，发汗解表祛湿。",
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case


@pytest.fixture(scope="function")
def sample_case_intermediate(db_session):
    """中级难度样本病案：胸痹（栝楼薤白白酒汤证）"""
    case = MedicalCase(
        title="胸痹——栝楼薤白白酒汤证",
        content="患者李某，女，58岁。胸闷痛反复发作2月余，每次持续数分钟，放射至左肩背，气短，动则加剧。",
        symptoms="胸痛彻背、喘息短气、舌淡苔白、脉沉迟",
        diagnosis="胸痹（上焦阳虚）",
        prescription="栝楼薤白白酒汤",
        difficulty_level="中级",
        teaching_points="辨病关键：胸痛彻背+脉沉迟=胸痹。鉴别：与心痛（真心痛）鉴别，彼痛更剧烈且危重。",
        correct_answer="辨病：胸痹。平脉：脉沉迟（阳虚阴凝）。析证：上焦阳虚，阴寒上乘，胸阳不展。定治：栝楼薤白白酒汤，通阳散结、豁痰下气。",
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case


@pytest.fixture(scope="function")
def sample_case_advanced(db_session):
    """高级难度样本病案：黄疸（茵陈蒿汤证）"""
    case = MedicalCase(
        title="黄疸——茵陈蒿汤证",
        content="患者王某，男，42岁。发热、身目黄染3天，小便黄赤如浓茶，大便干结。自述近日饮食油腻，饮酒较多。",
        symptoms="身目黄染、发热、小便黄赤、大便秘结、舌红苔黄腻、脉弦数",
        diagnosis="黄疸（阳黄——湿热蕴结）",
        prescription="茵陈蒿汤",
        difficulty_level="高级",
        teaching_points="辨病关键：身目黄染+小便黄赤=黄疸。需与萎黄鉴别（彼不伴小便黄）。析证注意湿热偏重。",
        correct_answer="辨病：黄疸。平脉：脉弦数（湿热内盛）。析证：湿热蕴结中焦，熏蒸肝胆，胆汁外溢。定治：茵陈蒿汤，清热利湿退黄。",
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case


# ==================== Agent 夹具 ====================

@pytest.fixture(scope="function")
def agent():
    """无真实 AI 客户端的 agent 实例（纯单元测试）"""
    return TrainingAgent()


# ==================== 通用小工具 ====================

@pytest.fixture(scope="function")
def active_session(db_session, sample_case_beginner):
    """一条已开始、含开场白的训练会话"""
    session = TrainingSession(
        student_id="test_student",
        difficulty_level="初级",
        case_id=sample_case_beginner.id,
        status="active",
    )
    db_session.add(session)
    db_session.commit()
    db_session.add(
        SessionMessage(
            session_id=session.id,
            role="agent",
            content="医生你好，我最近不太舒服。",
            message_type="question",
        )
    )
    db_session.commit()
    db_session.refresh(session)
    return session
