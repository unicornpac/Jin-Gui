"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine, event
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


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection, connection_record):
    """每条新连接生效的 SQLite 参数。

    默认的 rollback journal 模式下，一个写事务会阻塞所有读；多人同时训练、
    管理员同时翻看会话列表时，很容易撞上 "database is locked"。
    - WAL：读写互不阻塞，写与写仍串行但等待时间大幅缩短
    - busy_timeout：抢不到写锁时等待 5 秒再报错，而不是立刻失败
    - synchronous=NORMAL：WAL 下的常规取舍，牺牲极端断电时的最后一笔事务
    内存库会静默忽略这些设置，测试不受影响。
    """
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite 参数设置失败（沿用默认值）: %s", exc)

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
