from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from core.rag_service import DocumentIngestionService, RAGQueryService
from fastapi.responses import StreamingResponse

app = FastAPI(title="RAG 知识库微服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ingestion_service = DocumentIngestionService()
# 实例化查询服务
query_service = RAGQueryService()


# 定义请求体的数据结构
class ChatRequest(BaseModel):
    query: str

@app.post("/api/v1/knowledge/chat")
async def chat_with_knowledge_base(request: ChatRequest):
    """
    基于本地知识库进行问答
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    try:
        # 调用核心问答逻辑
        result = query_service.ask(request.query)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/knowledge/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    接收前端上传的 PDF 文件，转换为向量并持久化
    """
    # 校验文件类型 (防御性编程)
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="目前仅支持 PDF 格式的文件")

    try:
        # 读取文件流
        content = await file.read()

        # 调用核心逻辑层
        result = ingestion_service.process_and_store_pdf(content, file.filename)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/knowledge/chat/stream")
async def chat_with_knowledge_base_stream(request: ChatRequest):
    """
    SSE 流式问答接口（供 Vue 前端打字机效果使用）
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 返回 StreamingResponse，必须明确指定 media_type 为 text/event-stream
    return StreamingResponse(
        query_service.ask_stream(request.query),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    import uvicorn

    # 启动服务，开启热更新
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)