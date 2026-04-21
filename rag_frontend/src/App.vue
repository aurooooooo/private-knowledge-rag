<template>
  <div class="app">
    <h1>RAG 知识库系统</h1>
    
    <div class="upload-section">
      <h2>上传PDF文档</h2>
      <input 
        type="file" 
        ref="fileInput" 
        accept=".pdf" 
        @change="handleFileChange"
        class="file-input"
      />
      <button @click="uploadFile" class="upload-btn" :disabled="!selectedFile || isUploading">
        {{ isUploading ? '上传中...' : '上传文件' }}
      </button>
      <div v-if="uploadStatus" class="upload-status">
        {{ uploadStatus }}
      </div>
    </div>
    
    <div class="chat-section">
      <h2>AI智能问答</h2>
      <div class="chat-container" ref="scrollContainer">
        <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
          <div class="message-content" v-html="renderMarkdown(message.content)"></div>
          
          <div v-if="message.role === 'assistant' && message.sources && message.sources.length > 0" class="message-sources">
            <h4>参考来源：</h4>
            <ul>
              <li v-for="(source, i) in message.sources" :key="i">
                📄 {{ source.file }}
              </li>
            </ul>
          </div>
        </div>
        <div ref="chatEnd" class="chat-end"></div>
      </div>
      
      <div class="chat-input">
        <input 
          type="text" 
          v-model="query" 
          placeholder="请输入您的问题..."
          @keyup.enter="sendQuery"
          class="query-input"
          :disabled="isStreaming"
        />
        <button @click="sendQuery" class="send-btn" :disabled="!query.trim() || isStreaming">
          {{ isStreaming ? '正在思考...' : '发送' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, nextTick, reactive } from 'vue'
import { marked } from 'marked'

export default {
  name: 'App',
  setup() {
    const fileInput = ref(null)
    const selectedFile = ref(null)
    const uploadStatus = ref('')
    const isUploading = ref(false)
    const query = ref('')
    const messages = reactive([]) // 使用 reactive 保持数组响应式
    const isStreaming = ref(false)
    const chatEnd = ref(null)
    const scrollContainer = ref(null)

    const handleFileChange = (e) => {
      selectedFile.value = e.target.files[0]
    }

    const uploadFile = async () => {
      if (!selectedFile.value) return
      isUploading.value = true
      uploadStatus.value = '上传中...'

      const formData = new FormData()
      formData.append('file', selectedFile.value)

      try {
        const response = await fetch('http://127.0.0.1:8000/api/v1/knowledge/upload', {
          method: 'POST',
          body: formData
        })
        const data = await response.json()
        if (response.ok) {
          uploadStatus.value = `✅ 上传成功！生成了 ${data.chunks_created} 个知识片段。`
          fileInput.value.value = ''
          selectedFile.value = null
        } else {
          uploadStatus.value = '❌ 上传失败: ' + (data.detail || '未知错误')
        }
      } catch (error) {
        uploadStatus.value = '❌ 连接服务器失败'
      } finally {
        isUploading.value = false
      }
    }

    const sendQuery = async () => {
      if (!query.value.trim() || isStreaming.value) return

      const userQuery = query.value.trim()
      messages.push({ role: 'user', content: userQuery })
      query.value = ''
      
      isStreaming.value = true
      
      // 创建助手的初始响应对象
      const assistantMessage = reactive({
        role: 'assistant',
        content: '',
        sources: []
      })
      messages.push(assistantMessage)

      await nextTick()
      scrollToBottom()

      try {
        const response = await fetch('http://127.0.0.1:8000/api/v1/knowledge/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: userQuery })
        })

        if (!response.ok) throw new Error('服务器响应异常')

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = '' // 核心：缓冲区，处理被切断的 JSON 片段

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          // 将新读到的字节流解码并累加到缓冲区
          buffer += decoder.decode(value, { stream: true })

          // 按行切割缓冲区内容
          const lines = buffer.split('\n')
          
          // 重要：最后一行可能是不完整的，留在缓冲区等下一次填充
          buffer = lines.pop()

          for (const line of lines) {
            const trimmedLine = line.trim()
            if (!trimmedLine || !trimmedLine.startsWith('data: ')) continue

            const dataStr = trimmedLine.replace('data: ', '')
            
            if (dataStr === '[DONE]') {
              isStreaming.value = false
              continue
            }

            try {
              const parsed = JSON.parse(dataStr)
              if (parsed.type === 'text') {
                // 逐字累加，触发 Vue 响应式更新
                assistantMessage.content += parsed.data
              } else if (parsed.type === 'sources') {
                assistantMessage.sources = parsed.data
              }
              // 每次内容更新后，平滑滚动到底部
              scrollToBottom()
            } catch (e) {
              // 如果 JSON 依然解析失败，说明这一行还没收全，把它加回缓冲区
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
      nextTick(() => {
        if (chatEnd.value) {
          chatEnd.value.scrollIntoView({ behavior: 'smooth' })
        }
      })
    }

    const renderMarkdown = (text) => {
      return marked.parse(text || '')
    }

    return {
      fileInput, selectedFile, uploadStatus, isUploading,
      query, messages, isStreaming, chatEnd, scrollContainer,
      handleFileChange, uploadFile, sendQuery, renderMarkdown
    }
  }
}
</script>

<style scoped>
.app {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
  font-family: Arial, sans-serif;
}

h1 {
  text-align: center;
  color: #333;
  margin-bottom: 30px;
}

.upload-section {
  background-color: #f5f5f5;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 30px;
}

.upload-section h2 {
  color: #333;
  margin-bottom: 15px;
}

.file-input {
  margin-right: 10px;
  margin-bottom: 10px;
}

.upload-btn {
  background-color: #4CAF50;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 4px;
  cursor: pointer;
}

.upload-btn:disabled {
  background-color: #cccccc;
  cursor: not-allowed;
}

.upload-status {
  margin-top: 10px;
  padding: 10px;
  background-color: #e8f5e8;
  border-radius: 4px;
  color: #2e7d32;
}

.chat-section {
  background-color: #f5f5f5;
  padding: 20px;
  border-radius: 8px;
}

.chat-section h2 {
  color: #333;
  margin-bottom: 15px;
}

.chat-container {
  max-height: 400px;
  overflow-y: auto;
  background-color: white;
  border-radius: 4px;
  padding: 10px;
  margin-bottom: 15px;
}

.message {
  margin-bottom: 15px;
  padding: 10px;
  border-radius: 8px;
}

.message.user {
  background-color: #e3f2fd;
  align-self: flex-end;
  margin-left: 50px;
}

.message.assistant {
  background-color: #f1f1f1;
  margin-right: 50px;
}

.message-content {
  line-height: 1.5;
}

.message-sources {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #ddd;
  font-size: 12px;
  color: #666;
}

.message-sources h4 {
  margin: 0 0 5px 0;
}

.message-sources ul {
  margin: 0;
  padding-left: 20px;
}

.chat-input {
  display: flex;
}

.query-input {
  flex: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px 0 0 4px;
  font-size: 14px;
}

.send-btn {
  background-color: #2196F3;
  color: white;
  border: none;
  padding: 0 20px;
  border-radius: 0 4px 4px 0;
  cursor: pointer;
}

.send-btn:disabled {
  background-color: #cccccc;
  cursor: not-allowed;
}

.chat-end {
  height: 1px;
}
.message-content :deep(p) {
  margin: 0 0 10px 0;
}
.app { max-width: 800px; margin: 0 auto; padding: 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
.upload-section, .chat-section { background: #fff; border: 1px solid #eee; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.05); }
.chat-container { height: 500px; overflow-y: auto; padding: 15px; border: 1px solid #eee; margin-bottom: 15px; display: flex; flex-direction: column; }
.message { max-width: 85%; margin-bottom: 20px; padding: 12px 16px; border-radius: 12px; position: relative; }
.message.user { align-self: flex-end; background-color: #007bff; color: white; border-bottom-right-radius: 2px; }
.message.assistant { align-self: flex-start; background-color: #f8f9fa; border: 1px solid #e9ecef; border-bottom-left-radius: 2px; }
.message-sources { margin-top: 10px; font-size: 0.85em; border-top: 1px dashed #ccc; padding-top: 8px; }
.chat-input { display: flex; gap: 10px; }
.query-input { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; outline: none; }
.send-btn { padding: 0 24px; background: #007bff; color: white; border: none; border-radius: 8px; cursor: pointer; transition: background 0.3s; }
.send-btn:disabled { background: #ccc; }
</style>