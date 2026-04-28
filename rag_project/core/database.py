from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite 数据库文件路径
SQLALCHEMY_DATABASE_URL = "sqlite:///./chat_history.db"

# connect_args={"check_same_thread": False} 是 FastAPI 操作 SQLite 必加的配置
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 依赖注入函数：每次请求来时获取数据库连接，请求结束自动关闭
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()