<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <h2>RAG 知识库系统</h2>
        <button @click="createNewSession" class="new-chat-btn">
          <span>+</span> 新建对话
        </button>
      </div>
      
      <div class="session-list">
        <div 
          v-for="session in sessions" 
          :key="session.id"
          class="session-item"
          :class="{ active: currentSessionId === session.id }"
          @click="selectSession(session.id)"
        >
          <div class="session-title">💬 {{ session.title || '新对话' }}</div>
          <button @click.stop="deleteSession(session.id)" class="delete-session-btn" title="删除会话">
            ×
          </button>
        </div>
        <div v-if="sessions.length === 0" class="no-sessions">
          暂无历史对话
        </div>
      </div>
    </aside>

    <main class="main-content">
      <details class="knowledge-panel">
        <summary>📚 知识库文档管理 (点击展开/折叠)</summary>
        <div class="upload-controls">
          <input type="file" ref="fileInput" accept=".pdf" @change="handleFileChange" class="file-input" />
          <button @click="uploadFile" class="upload-btn" :disabled="!selectedFile || isUploading">
            {{ isUploading ? '上传解析中...' : '上传并向量化' }}
          </button>
          <span v-if="uploadStatus" class="upload-status" :class="{'error': uploadStatus.includes('❌')}">
            {{ uploadStatus }}
          </span>
        </div>
        <div class="document-list-container">
          <ul v-if="documents.length > 0" class="document-list">
            <li v-for="(doc, index) in documents" :key="index" class="document-item">
              <span class="doc-name">📄 {{ doc }}</span>
              <button @click="deleteDocument(doc)" class="delete-btn" :disabled="isDeleting === doc">删除</button>
            </li>
          </ul>
          <div v-else class="no-docs">暂无文档，请上传 PDF 构建知识库。</div>
        </div>
      </details>

      <div class="chat-section">
        <div class="chat-container" ref="scrollContainer">
          <div v-if="messages.length === 0" class="welcome-screen">
            <h3>我是你的私有知识库助手</h3>
            <p>请上传文档并在下方提问，或者选择左侧历史记录继续对话。</p>
          </div>

          <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
            <div class="message-content" v-html="renderMarkdown(message.content)"></div>
            <div v-if="message.role === 'assistant' && message.sources && message.sources.length > 0" class="message-sources">
              <h4>参考来源：</h4>
              <ul>
                <li v-for="(source, i) in message.sources" :key="i">📄 {{ source.file || source.file_name || '未知文档' }}</li>
              </ul>
            </div>
          </div>
          <div ref="chatEnd" class="chat-end"></div>
        </div>
        
        <div class="chat-input-area">
          <input 
            type="text" 
            v-model="query" 
            placeholder="请输入您的问题..."
            @keyup.enter="sendQuery"
            class="query-input"
            :disabled="isStreaming"
          />
          <button @click="sendQuery" class="send-btn" :disabled="!query.trim() || isStreaming">
            {{ isStreaming ? '检索思考中...' : '发送' }}
          </button>
        </div>
      </div>
    </main>
  </div>
</template>

<script>
import { ref, nextTick, reactive, onMounted } from 'vue'
import { marked } from 'marked'

export default {
  name: 'App',
  setup() {
    // 基础状态
    const API_BASE = 'http://127.0.0.1:8000/api/v1'
    
    // --- 会话管理状态 ---
    const sessions = ref([])
    const currentSessionId = ref(null)
    const messages = reactive([])
    
    // --- 知识库状态 ---
    const fileInput = ref(null)
    const selectedFile = ref(null)
    const uploadStatus = ref('')
    const isUploading = ref(false)
    const documents = ref([])
    const isDeleting = ref(null)

    // --- 聊天状态 ---
    const query = ref('')
    const isStreaming = ref(false)
    const chatEnd = ref(null)

    // 初始化：拉取会话列表和文档列表
    onMounted(() => {
      fetchSessions()
      fetchDocuments()
    })

    // ========== 会话管理逻辑 ==========
    const fetchSessions = async () => {
      try {
        const res = await fetch(`${API_BASE}/sessions`)
        if (res.ok) {
          sessions.value = await res.json()
        }
      } catch (e) { console.error("获取会话列表失败") }
    }

    const createNewSession = async () => {
      try {
        const res = await fetch(`${API_BASE}/sessions`, { method: 'POST' })
        if (res.ok) {
          const newSession = await res.json()
          currentSessionId.value = newSession.id
          messages.splice(0, messages.length) // 清空当前屏幕
          await fetchSessions()
        }
      } catch (e) { console.error("创建会话失败") }
    }

    const selectSession = async (id) => {
      if (currentSessionId.value === id) return
      currentSessionId.value = id
      
      try {
        // 拉取对应会话的历史消息
        const res = await fetch(`${API_BASE}/sessions/${id}/messages`)
        if (res.ok) {
          const historyMsg = await res.json()
          // 清空并重新填入
          messages.splice(0, messages.length, ...historyMsg)
          scrollToBottom()
        }
      } catch (e) { console.error("获取消息记录失败") }
    }

    const deleteSession = async (id) => {
      if (!confirm('确定删除该对话及其所有历史记录吗？')) return
      try {
        const res = await fetch(`${API_BASE}/sessions/${id}`, { method: 'DELETE' })
        if (res.ok) {
          if (currentSessionId.value === id) {
            currentSessionId.value = null
            messages.splice(0, messages.length)
          }
          await fetchSessions()
        }
      } catch (e) { console.error("删除会话失败") }
    }

    // ========== 知识库管理逻辑 ==========
    const fetchDocuments = async () => {
      try {
        const res = await fetch(`${API_BASE}/knowledge/documents`)
        if (res.ok) {
          const data = await res.json()
          documents.value = data.documents
        }
      } catch (e) { console.error('获取文档列表失败') }
    }

    const handleFileChange = (e) => { selectedFile.value = e.target.files[0] }

    const uploadFile = async () => {
      if (!selectedFile.value) return
      isUploading.value = true
      uploadStatus.value = '上传并向量化中...'
      const formData = new FormData()
      formData.append('file', selectedFile.value)

      try {
        const res = await fetch(`${API_BASE}/knowledge/upload`, { method: 'POST', body: formData })
        if (res.ok) {
          uploadStatus.value = `✅ 上传成功！`
          fileInput.value.value = ''
          selectedFile.value = null
          await fetchDocuments()
        } else {
          uploadStatus.value = '❌ 上传失败'
        }
      } catch (e) { uploadStatus.value = '❌ 连接服务器失败' } 
      finally { isUploading.value = false }
    }

    const deleteDocument = async (filename) => {
      if (!confirm(`确定删除 "${filename}" 吗？`)) return
      isDeleting.value = filename
      try {
        const res = await fetch(`${API_BASE}/knowledge/documents/${encodeURIComponent(filename)}`, { method: 'DELETE' })
        if (res.ok) {
          uploadStatus.value = `✅ 文件已删除`
          await fetchDocuments()
        }
      } catch (e) { uploadStatus.value = '❌ 删除失败' } 
      finally { isDeleting.value = null }
    }

    // ========== 问答核心逻辑 ==========
    const sendQuery = async () => {
      if (!query.value.trim() || isStreaming.value) return

      // 核心拦截：如果没有选中会话，先自动建一个
      if (!currentSessionId.value) {
        await createNewSession()
      }

      const userQuery = query.value.trim()
      messages.push({ role: 'user', content: userQuery })
      query.value = ''
      isStreaming.value = true
      
      const assistantMessage = reactive({ role: 'assistant', content: '', sources: [] })
      messages.push(assistantMessage)
      scrollToBottom()

      try {
        // 新版请求体：带上 session_id
        const reqBody = { query: userQuery, session_id: currentSessionId.value }
        
        const response = await fetch(`${API_BASE}/knowledge/chat/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reqBody)
        })

        if (!response.ok) throw new Error('服务器响应异常')

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = '' 

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop()

          for (const line of lines) {
            const trimmedLine = line.trim()
            if (!trimmedLine || !trimmedLine.startsWith('data: ')) continue

            const dataStr = trimmedLine.replace('data: ', '')
            if (dataStr === '[DONE]') {
              isStreaming.value = false
              await fetchSessions() // 对话结束后刷新左侧栏（可能更新了标题）
              continue
            }

            try {
              const parsed = JSON.parse(dataStr)
              if (parsed.type === 'text') {
                assistantMessage.content += parsed.data
              } else if (parsed.type === 'sources') {
                assistantMessage.sources = parsed.data
              }
              scrollToBottom()
            } catch (e) {
              buffer = line + '\n' + buffer
            }
          }
        }
      } catch (error) {
        assistantMessage.content = '❌ 系统错误: ' + error.message
      } finally {
        isStreaming.value = false
      }
    }

    const scrollToBottom = () => {
      nextTick(() => { if (chatEnd.value) chatEnd.value.scrollIntoView({ behavior: 'smooth' }) })
    }

    const renderMarkdown = (text) => marked.parse(text || '')

    return {
      sessions, currentSessionId, fetchSessions, createNewSession, selectSession, deleteSession,
      fileInput, selectedFile, uploadStatus, isUploading, documents, isDeleting, handleFileChange, uploadFile, deleteDocument,
      query, messages, isStreaming, chatEnd, sendQuery, renderMarkdown
    }
  }
}
</script>

<style scoped>
*{
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

/* 双栏布局核心样式 */
.app-layout {
  display: flex;
  height: 100vh;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background-color: #f3f4f6;
  margin: -8px; /* 清除 body 默认 margin */
}

/* 左侧栏 */
.sidebar {
  width: 260px;
  background-color: #202123;
  color: #fff;
  display: flex;
  flex-direction: column;
  padding: 10px;
  box-shadow: 2px 0 5px rgba(0,0,0,0.1);
}
.sidebar-header h2 { font-size: 16px; margin: 10px 0 20px 10px; color: #ececf1; }
.new-chat-btn {
  background-color: transparent;
  border: 1px solid #565869;
  color: white;
  padding: 12px;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  transition: background 0.3s;
  display: flex;
  align-items: center;
  gap: 10px;
}
.new-chat-btn:hover { background-color: #2a2b32; }

.session-list { margin-top: 20px; overflow-y: auto; flex: 1; }
.session-item {
  padding: 12px 10px;
  margin-bottom: 5px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #ececf1;
  font-size: 14px;
}
.session-item:hover { background-color: #2a2b32; }
.session-item.active { background-color: #343541; }
.session-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
.delete-session-btn { background: transparent; border: none; color: #8e8ea0; cursor: pointer; font-size: 18px; }
.delete-session-btn:hover { color: #ff4d4f; }
.no-sessions { text-align: center; color: #8e8ea0; font-size: 12px; margin-top: 20px; }

/* 右侧主区 */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 20px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

/* 知识库面板 */
.knowledge-panel { background: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.knowledge-panel summary { font-weight: 600; cursor: pointer; color: #333; outline: none; }
.upload-controls { display: flex; align-items: center; margin-top: 15px; gap: 10px;}
.file-input { flex: 1; border: 1px solid #ddd; padding: 8px; border-radius: 6px; }
.upload-btn { background: #10a37f; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; }
.upload-btn:disabled { background: #ccc; }
.document-list-container { margin-top: 15px; border-top: 1px dashed #eee; padding-top: 10px; }
.document-list { list-style: none; padding: 0; margin: 0; max-height: 150px; overflow-y: auto; }
.document-item { display: flex; justify-content: space-between; align-items: center; padding: 8px; background: #f9f9f9; margin-bottom: 5px; border-radius: 4px; font-size: 13px;}
.delete-btn { background: #ff4d4f; color: white; border: none; padding: 4px 8px; border-radius: 4px; cursor: pointer; }

/* 聊天区 */
.chat-section { flex: 1; display: flex; flex-direction: column; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
.chat-container { flex: 1; overflow-y: auto; padding: 20px; }
.welcome-screen { text-align: center; color: #666; margin-top: 100px; }
.message { max-width: 85%; margin-bottom: 20px; padding: 15px; border-radius: 8px; font-size: 15px; line-height: 1.6; }
.message.user { align-self: flex-end; background-color: #10a37f; color: white; margin-left: auto; border-bottom-right-radius: 2px; }
.message.assistant { background-color: #f7f7f8; border: 1px solid #e5e5e5; border-bottom-left-radius: 2px; color: #374151; }
.message-sources { margin-top: 15px; padding-top: 10px; border-top: 1px dashed #ccc; font-size: 12px; color: #666; }
.message-content :deep(p) { margin: 0 0 10px 0; }
.message-content :deep(pre) { background: #282c34; color: #abb2bf; padding: 10px; border-radius: 4px; overflow-x: auto; }
.chat-input-area { padding: 20px; border-top: 1px solid #eee; display: flex; gap: 10px; background: white; }
.query-input { flex: 1; padding: 12px 15px; border: 1px solid #e5e5e5; border-radius: 8px; outline: none; font-size: 15px; box-shadow: 0 0 5px rgba(0,0,0,0.02) inset; }
.query-input:focus { border-color: #10a37f; }
.send-btn { background: #10a37f; color: white; border: none; padding: 0 25px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: background 0.3s; }
.send-btn:disabled { background: #ececf1; color: #8e8ea0; cursor: not-allowed; }
</style>