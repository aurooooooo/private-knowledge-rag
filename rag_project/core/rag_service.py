import os
import tempfile
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings, SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from sqlalchemy.orm import Session
from .models import ChatMessage
import json
import httpx

class DocumentIngestionService:
    def __init__(self):
        # 1. 初始化 Embedding 模型 (运行在你的 4060 显卡上)
        # 选择 BAAI/bge-small-zh-v1.5：中文效果好，显存占用极小（不到 1GB），为后续大模型留出空间。
        # LOCAL_MODEL_PATH = "D:/models/bge-small-zh-v1.5"
        # self.embeddings = HuggingFaceEmbeddings(
        #     model_name=LOCAL_MODEL_PATH,
        #     model_kwargs={'device': 'cuda'},  # 强制使用 GPU
        #     encode_kwargs={'normalize_embeddings': True}
        # )
        Settings.embed_model = HuggingFaceEmbedding(
            model_name="D:/models/bge-small-zh-v1.5",
            device="cuda"
        )

        # 2. 初始化 Chroma 本地向量数据库
        # self.persist_directory = "./chroma_db"
        # self.vector_store = Chroma(
        #     collection_name="my_knowledge_base",
        #     embedding_function=self.embeddings,
        #     persist_directory=self.persist_directory
        # )
        db = chromadb.PersistentClient(path="./chroma_db")
        chroma_collection = db.get_or_create_collection("llama_index_kb")
        self.vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

        # 3. 配置文本切分器
        # 为什么切分？大模型上下文有限，且整本书做向量化会丢失局部语义。
        # self.text_splitter = RecursiveCharacterTextSplitter(
        #     chunk_size=500,  # 每个文本块约 500 个字符
        #     chunk_overlap=50,  # 块与块之间重叠 50 个字符，防止把一句话从中间硬生生切断
        #     separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]
        # )
        self.node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)

    def process_and_store_pdf(self, file_content: bytes, filename: str) -> dict:
        """
        处理 PDF 二进制流，解析为 LlamaIndex Nodes 并存入向量库
        """
        # 1. 临时文件落盘 (资源隔离规范：避免大文件打爆内存)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name

        try:
            # 2. 调用 LlamaIndex 的原生阅读器
            # 默认情况下，它会将 PDF 的每一页解析为一个独立的 Document 对象
            reader = SimpleDirectoryReader(input_files=[temp_path])
            documents = reader.load_data()

            # 3. 强制注入核心元数据
            # 极其重要：这是你刚才写的“文档删除”功能（依靠 source_file）能够生效的前提！
            for doc in documents:
                doc.metadata["source_file"] = filename
                # 如果未来你需要做“按分类检索”，可以继续往这里塞：
                # doc.metadata["category"] = "backend_architecture"

            # 4. 获取存储上下文，绑定我们在 __init__ 中初始化的 Chroma 数据库
            storage_context = StorageContext.from_defaults(vector_store=self.vector_store)

            # 5. 【核心转化】：构建索引引擎
            # 这一步内部发生了很多事：
            # Document -> 交给 transformations(句子切分器) -> 变成互相连接的 Nodes
            # -> 调用 Embedding 模型计算向量 -> 连同 Node 数据一并存入 Chroma
            index = VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context,
                transformations=[self.node_parser],
                show_progress=True  # 如果在控制台运行，会显示一个极客风格的进度条
            )

            return {
                "status": "success",
                "filename": filename,
                "total_pages": len(documents),
                "message": f"成功将 {len(documents)} 页文档转化为知识图谱节点。"
            }

        except Exception as e:
            raise RuntimeError(f"LlamaIndex 处理 PDF 失败: {str(e)}")

        finally:
            # 6. 强制清理临时文件 (类似 SpringBoot 里的 finally 块释放连接)
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 在 DocumentIngestionService 类中添加以下两个方法：

    def list_documents(self) -> list:
        """
        获取向量库中所有已上传的文档列表 (适配 LlamaIndex + Chroma)
        """
        try:
            # 绕过 LlamaIndex，直接访问底层的 Chroma collection 获取元数据
            result = self.vector_store._collection.get(include=['metadatas'])
            metadatas = result.get('metadatas', [])

            filenames = set()
            for meta in metadatas:
                if meta and 'source_file' in meta:
                    filenames.add(meta['source_file'])

            return list(filenames)
        except Exception as e:
            print(f"获取文档列表失败: {e}")
            return []

    def delete_document(self, filename: str) -> dict:
        """
        根据文件名，删除所有关联节点
        """
        try:
            self.vector_store._collection.delete(
                where={"source_file": filename}
            )
            return {"status": "success"}
        except Exception as e:
            raise RuntimeError(f"删除文档失败: {str(e)}")


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

        # 1. 构建一个耐扛的异步 HTTP 客户端
        # - 放大超时时间到 120 秒，给 CPU 重排留足时间
        # - 启用连接池，防止高频调用时端口耗尽
        custom_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        load_dotenv()
        model_name = os.getenv("LLM_MODEL_NAME", "MiniMax-M2")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "致命错误：没有找到 OPENAI_API_KEY！")
        # 2. 初始化大语言模型
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0.1,
            max_tokens=2048,
            timeout=60.0,
            extra_body={"reasoning_split": True}
        )

        # 3. 构造系统提示词模板 (System Prompt) - 兼顾严谨与逻辑推断
        system_prompt = (
            "你是一个专业的知识库问答助手。"
            "请严格基于以下提供的上下文信息来回答用户的问题。\n"
            "【规则】：\n"
            "1. 你可以根据上下文中的信息进行合理的逻辑推断（例如：前端代理指向的 localhost 端口，通常就是后端本地运行的端口）。\n"
            "2. 如果通过上下文及其合理推断依然无法得到答案，请明确回答'根据已知信息无法回答该问题'。\n"
            "3. 绝对不要引入任何你的通用知识库中不存在于上下文的信息。\n"
            "\n\n"
            "上下文信息：\n{context}"
        )
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])

        # 1. 实例化现有的向量检索器 (初筛，扩大召回数量 k=15)
        base_retriever = self.vector_store.as_retriever(search_kwargs={"k": 15})

        # 2. 从本地路径加载 BGE 系列专用的轻量级 Rerank 模型
        # BAAI/bge-reranker-base 体积小，精度高，非常适合工程落地
        LOCAL_RERANK_PATH = "D:/models/bge-reranker-base"
        rerank_model = HuggingFaceCrossEncoder(
            model_name=LOCAL_RERANK_PATH,
            model_kwargs={'device': 'cpu'}  # 继续利用 4060 的算力
        )

        # 3. 创建重排压缩器，设定最终只保留得分最高的前 3 篇文档
        compressor = CrossEncoderReranker(model=rerank_model, top_n=3)

        # 4. 【核心重构】使用 ContextualCompressionRetriever 将两者串联
        # 它会自动执行：向量检索捞 15 条 -> 送给 Reranker 打分 -> 砍掉 12 条 -> 输出最精锐的 3 条
        self.compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=base_retriever
        )

        # 4. 构建检索问答链 (RAG Chain)
        # 将文档内容塞入 Prompt 的链
        self.question_answer_chain = create_stuff_documents_chain(self.llm, self.prompt_template)
        # 将检索器与问答链结合 (k=3 表示每次检索最相关的 3 个文档块)
        # self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 3})
        # self.rag_chain = create_retrieval_chain(self.retriever, self.question_answer_chain)

        self.rag_chain = create_retrieval_chain(self.compression_retriever, self.question_answer_chain)

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

    async def ask_stream(self, query: str, db: Session, session_id: str):
        """
        处理流式对话，并自动将问答存入数据库
        """
        # 1. 查询该 session_id 下的历史记录，拼装给大模型
        history_records = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at).all()

        # 将 ORM 对象转为普通列表给大模型重写引擎用
        history = [{"role": msg.role, "content": msg.content} for msg in history_records]

        # 2. 保存用户的新问题到数据库
        user_msg = ChatMessage(session_id=session_id, role="user", content=query)
        db.add(user_msg)
        db.commit()

        # 3. 拦截查询重写
        actual_query = await self._rewrite_query(query, history)

        # 4. 准备变量，用来“偷录” AI 的完整回答和参考来源
        full_assistant_response = ""
        full_sources = []

        # 5. 调用 RAG 链 (注意这里如果用的是 LlamaIndex，代码稍微有点不同，如果是上一版的 LangChain 则用这个)
        async for chunk in self.rag_chain.astream({"input": actual_query}):
            if "context" in chunk:
                full_sources = [{
                    "content": doc.page_content,
                    "file": doc.metadata.get("source_file", "Unknown")
                } for doc in chunk["context"]]
                yield f"data: {json.dumps({'type': 'sources', 'data': full_sources}, ensure_ascii=False)}\n\n"

            if "answer" in chunk:
                # 累加 AI 回答的每一个字
                full_assistant_response += chunk["answer"]
                yield f"data: {json.dumps({'type': 'text', 'data': chunk['answer']}, ensure_ascii=False)}\n\n"

        # 6. 【流式结束拦截】当循环完毕，把完整的 AI 回答存入数据库！
        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=full_assistant_response,
            sources=full_sources
        )
        db.add(assistant_msg)
        db.commit()

        yield "data: [DONE]\n\n"

    async def _rewrite_query(self, query: str, history: list) -> str:
        """
        利用大模型，结合历史记录，将用户的简写问题重写为完整的独立提问。
        """
        # 1. 如果没有历史记录，直接返回原问题，节省算力
        if not history:
            return query

        # 2. 截取最近的 4 到 6 条对话记录（保留太多容易超出上下文且变慢）
        recent_history = history[-6:]
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_history])

        # 3. 构造重写专用的 Prompt（极其关键：限制大模型只重写，不回答）
        prompt_template = """你是一个底层系统组件，专门负责“查询重写（Query Rewrite）”。你绝对不能尝试回答用户的问题！
        你的唯一任务是：根据【对话历史】，判断用户的【最新提问】是否省略了主语或上下文。如果是，请将其补全为一个独立、语义完整的“问句”。

        【核心规则】：
        1. 提取历史记录中的具体名词，替换最新提问中的代词（如“它”、“这个”）。
        2. 输出必须仍然是一个提问，绝对不能是陈述句或答案！
        3. 【极其重要】：如果【最新提问】是一个完整独立的全新话题（例如闲聊、新的指令），没有使用代词，也没有暗指历史话题，请**直接原样输出原句**，绝对不要强行把历史名词塞进去！
        4. 只能输出重写后的句子，不能有任何多余的废话。

        --- 示例开始 ---
        【历史】
        user: 后端有哪些接口？
        assistant: 有用户注册和用户登录接口。
        【最新提问】
        那它的参数是什么？
        【独立提问】
        用户登录接口的参数是什么？

        【历史】
        user: 用户注册接口怎么调用？
        assistant: 需要发送 POST 请求。
        【最新提问】
        你能帮我写一段Python代码吗？
        【独立提问】
        你能帮我写一段Python代码吗？

        【历史】
        user: 你好
        assistant: 你好！有什么可以帮您？
        【最新提问】
        你好
        【独立提问】
        你好
        --- 示例结束 ---

        【对话历史】
        {history}

        【最新提问】
        {query}

        独立提问："""

        prompt = PromptTemplate.from_template(prompt_template)

        # 4. 构建一条极其轻量的处理链：Prompt -> LLM -> 提取纯文本
        rewrite_chain = prompt | self.llm | StrOutputParser()

        # 5. 调用模型生成重写后的问题
        rewritten_query = await rewrite_chain.ainvoke({"history": history_str, "query": query})

        # 打印日志，方便你在终端观察“重写魔法”
        # print(f"\n历史记录: {history_str}")
        print(f"[重写引擎] 原始问题: {query}")
        print(f"[重写引擎] 独立提问: {rewritten_query}\n")

        return rewritten_query.strip()