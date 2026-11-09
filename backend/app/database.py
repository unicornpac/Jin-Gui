"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .logger import get_logger

logger = get_logger(__name__)
import os

# 数据库文件路径
# DATA_DIR 环境变量用于云平台持久磁盘挂载（如 Render），未设置时使用本地 data/ 目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# 导出供其他模块使用
__all__ = ['BASE_DIR', 'DATA_DIR', 'engine', 'SessionLocal', 'Base', 'get_db', 'init_db']

DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'tcm.db')}"

# 创建数据库引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite需要这个参数
    echo=False  # 设置为True可以看到SQL语句
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基础模型类
Base = declarative_base()


def get_db():
    """
    获取数据库会话
    用于依赖注入
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库 — 通过 Alembic 执行所有迁移（新建表 + 增量变更）"""
    from alembic.config import Config
    from alembic import command

    alembic_ini = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic.ini")
    alembic_cfg = Config(alembic_ini)
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
