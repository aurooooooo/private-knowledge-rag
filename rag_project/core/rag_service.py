import os
import tempfile
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
import json

class DocumentIngestionService:
    def __init__(self):
        # 1. 初始化 Embedding 模型 (运行在你的 4060 显卡上)
        # 选择 BAAI/bge-small-zh-v1.5：中文效果好，显存占用极小（不到 1GB），为后续大模型留出空间。
        LOCAL_MODEL_PATH = "D:/models/bge-small-zh-v1.5"
        self.embeddings = HuggingFaceEmbeddings(
            model_name=LOCAL_MODEL_PATH,
            model_kwargs={'device': 'cuda'},  # 强制使用 GPU
            encode_kwargs={'normalize_embeddings': True}
        )

        # 2. 初始化 Chroma 本地向量数据库
        self.persist_directory = "./chroma_db"
        self.vector_store = Chroma(
            collection_name="my_knowledge_base",
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory
        )

        # 3. 配置文本切分器
        # 为什么切分？大模型上下文有限，且整本书做向量化会丢失局部语义。
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,  # 每个文本块约 500 个字符
            chunk_overlap=50,  # 块与块之间重叠 50 个字符，防止把一句话从中间硬生生切断
            separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]
        )

    def process_and_store_pdf(self, file_content: bytes, filename: str) -> dict:
        """
        处理 PDF 二进制流并存入向量库
        """
        # 工程细节：处理网络上传的文件流，先写入临时文件，处理完立即销毁，避免撑爆磁盘
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name

        try:
            # 第一步：加载文档
            loader = PyPDFLoader(temp_path)
            documents = loader.load()

            # 第二步：文档切片
            chunks = self.text_splitter.split_documents(documents)

            # 为每个 chunk 添加来源元数据，方便日后溯源
            for chunk in chunks:
                chunk.metadata['source_file'] = filename

            # 第三步：向量化并存入 Chroma 数据库
            self.vector_store.add_documents(chunks)

            return {
                "status": "success",
                "filename": filename,
                "total_pages": len(documents),
                "chunks_created": len(chunks)
            }

        except Exception as e:
            # 实际工程中这里应该接入 logging 模块
            raise RuntimeError(f"处理 PDF 失败: {str(e)}")

        finally:
            # 清理临时文件
            if os.path.exists(temp_path):
                os.remove(temp_path)


from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain


class RAGQueryService:
    def __init__(self):
        # 1. 重新连接到刚才建立的本地 Chroma 数据库
        from langchain_huggingface import HuggingFaceEmbeddings
        # 保持与上传时完全一致的 Embedding 配置
        self.embeddings = HuggingFaceEmbeddings(
            model_name="D:/models/bge-small-zh-v1.5",
            model_kwargs={'device': 'cuda'},
            encode_kwargs={'normalize_embeddings': True}
        )
        self.vector_store = Chroma(
            collection_name="my_knowledge_base",
            embedding_function=self.embeddings,
            persist_directory="./chroma_db"
        )

        os.environ["NO_PROXY"] = "localhost,127.0.0.1"

        # 2. 初始化本地大语言模型 (通过 Ollama 调用)
        self.llm = ChatOllama(
            model="qwen2.5:7b",
            temperature=0.8,  # 温度调低，让模型回答更严谨，不要过度发散
            base_url="http://127.0.0.1:11434"
        )

        # 3. 构造系统提示词模板 (System Prompt) - 防幻觉的核心
        system_prompt = (
            "你是一个专业的知识库问答助手。"
            "请严格基于以下提供的上下文信息来回答用户的问题。"
            "如果你在上下文中找不到答案，请诚实地回答'根据已知信息无法回答该问题'，绝对不要编造内容。"
            "\n\n"
            "上下文信息：\n{context}"
        )
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])

        # 4. 构建检索问答链 (RAG Chain)
        # 将文档内容塞入 Prompt 的链
        self.question_answer_chain = create_stuff_documents_chain(self.llm, self.prompt_template)
        # 将检索器与问答链结合 (k=3 表示每次检索最相关的 3 个文档块)
        self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 3})
        self.rag_chain = create_retrieval_chain(self.retriever, self.question_answer_chain)

    def ask(self, query: str) -> dict:
        """
        处理用户提问，执行检索并生成回答
        """
        # 调用 RAG 链
        response = self.rag_chain.invoke({"input": query})

        # 工程规范：必须返回引用的来源，否则系统不可信
        sources = []
        for doc in response.get("context", []):
            sources.append({
                "content": doc.page_content,
                "file": doc.metadata.get("source_file", "Unknown")
            })

        return {
            "answer": response.get("answer"),
            "sources": sources
        }

    async def ask_stream(self, query: str):
        """
        处理用户提问，以 SSE 流式返回数据（打字机效果）
        """
        # 调用 RAG 链的异步流式方法
        async for chunk in self.rag_chain.astream({"input": query}):

            # 1. 拦截上下文：通常在第一个 chunk 返回
            if "context" in chunk:
                sources = [{
                    "content": doc.page_content,
                    "file": doc.metadata.get("source_file", "Unknown")
                } for doc in chunk["context"]]

                # 推送来源数据给前端
                source_data = json.dumps({"type": "sources", "data": sources}, ensure_ascii=False)
                yield f"data: {source_data}\n\n"

            # 2. 拦截模型生成的文本：这是被打碎的一个个字（Token）
            if "answer" in chunk:
                # 推送文字片段给前端
                text_data = json.dumps({"type": "text", "data": chunk["answer"]}, ensure_ascii=False)
                yield f"data: {text_data}\n\n"

        # 3. 结束标志：告诉前端回答完毕，可以关闭连接了
        yield "data: [DONE]\n\n"