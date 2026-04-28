from fastapi import UploadFile, File, FastAPI, Depends, HTTPException
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse
from core.database import engine, Base, get_db
from core.models import ChatSession, ChatMessage
from core.schemas import ChatRequest, SessionResponse, MessageResponse
from core.rag_service import DocumentIngestionService, RAGQueryService

# 初始化数据库表
Base.metadata.create_all(bind=engine)

app = FastAPI(title="RAG 知识库微服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 实例化服务
ingestion_service = DocumentIngestionService()
query_service = RAGQueryService()

# ==================== 知识库管理接口 ====================

@app.post("/api/v1/knowledge/upload")
async def upload_document(file: UploadFile = File(...)):
    """接收前端上传的 PDF 文件，转换为向量并持久化"""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="目前仅支持 PDF 格式的文件")
    try:
        content = await file.read()
        return ingestion_service.process_and_store_pdf(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/knowledge/documents")
async def get_documents():
    """获取已上传文档列表"""
    try:
        filenames = ingestion_service.list_documents()
        return {"documents": filenames}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/knowledge/documents/{filename}")
async def delete_document(filename: str):
    """删除指定文档"""
    try:
        return ingestion_service.delete_document(filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 会话与对话记录接口 ====================

@app.post("/api/v1/sessions", response_model=SessionResponse)
async def create_session(db: Session = Depends(get_db)):
    """新建一个聊天会话"""
    new_session = ChatSession(title="新对话")
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return new_session

@app.get("/api/v1/sessions", response_model=list[SessionResponse])
async def get_sessions(db: Session = Depends(get_db)):
    """获取左侧会话列表（按时间倒序）"""
    return db.query(ChatSession).order_by(ChatSession.created_at.desc()).all()

@app.get("/api/v1/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_session_messages(session_id: str, db: Session = Depends(get_db)):
    """获取某个会话的聊天历史"""
    # 这里的 ChatMessage 现在 100% 指向 core.models 里的数据库模型了！
    return db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at).all()

@app.delete("/api/v1/sessions/{session_id}")
async def delete_session(session_id: str, db: Session = Depends(get_db)):
    """删除废弃会话"""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(session)
    db.commit()
    return {"status": "success"}


# ==================== 核心 RAG 问答接口 ====================

@app.post("/api/v1/knowledge/chat/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """流式对话入口，接入 SQLite 历史记忆"""
    session_id = request.session_id

    # 如果前端没传 session_id (即第一次对话)，帮他建一个
    if not session_id:
        new_session = ChatSession(title=request.query[:10] + "...")
        db.add(new_session)
        db.commit()
        session_id = new_session.id
    else:
        # 如果传了，且是第一次发消息，顺便把标题更新一下
        msg_count = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).count()
        if msg_count == 0:
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session:
                session.title = request.query[:10] + "..."
                db.commit()

    return StreamingResponse(
        query_service.ask_stream(request.query, db, session_id),
        media_type="text/event-stream"
    )


if __name__ == "__main__":
    import uvicorn
    # 启动服务，开启热更新
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)