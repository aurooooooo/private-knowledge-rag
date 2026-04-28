from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from .database import Base


def generate_uuid():
    return str(uuid.uuid4())


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(100), nullable=False)  # 会话标题
    created_at = Column(DateTime, default=datetime.now)

    # 级联删除：删除会话时，里面的聊天记录也一起删掉
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user' 或 'assistant'
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)  # 存 AI 回答时的参考文档
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("ChatSession", back_populates="messages")