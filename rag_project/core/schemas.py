from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime


# 请求流式问答的 DTO
class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None  # 如果是新会话，前端可以不传


# 响应/返回的 DTO
class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources: Optional[Any] = None
    created_at: datetime

    class Config:
        from_attributes = True  # 允许直接读取 SQLAlchemy 的模型


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime

    class Config:
        orm_mode = True
