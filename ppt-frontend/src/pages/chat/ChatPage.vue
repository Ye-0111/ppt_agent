<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { message } from 'ant-design-vue'
import {
  SendOutlined,
  PlusOutlined,
  DeleteOutlined,
  RobotOutlined,
  UserOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  ToolOutlined,
  BulbOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons-vue'
import {
  chatStream,
  clearHistory,
  genSessionId,
  EventType,
} from '@/api/chatController'
import type { SSEEvent } from '@/api/chatController'

// ================================================================
// 类型
// ================================================================
interface ActivityItem {
  id: string
  kind: 'thinking' | 'tool' | 'plan-step'
  text?: string
  tool?: string
  args?: unknown
  result?: string
  done?: boolean
  status?: 'done' | 'error'
}
interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  activities: ActivityItem[]
  status: 'streaming' | 'done' | 'error'
  elapsed?: number
}

// ================================================================
// 状态
// ================================================================
const sessionId = ref(genSessionId())
const messages = ref<ChatMessage[]>([])
const input = ref('')
const sending = ref(false)
let abortCtrl: AbortController | null = null

const scrollRef = ref<HTMLElement | null>(null)

let seq = 0
const uid = () => `m${Date.now()}_${seq++}`

const shortSession = computed(() => sessionId.value.slice(0, 8))

const suggestions = [
  '你好，介绍一下你能做什么',
  '帮我做一份 3 页的 Python 入门 PPT',
  '列出工作区里的文件',
]

// ================================================================
// 工具
// ================================================================
const scrollToBottom = async () => {
  await nextTick()
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

const formatJson = (v: unknown) => {
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

// ================================================================
// 事件处理
// ================================================================
const onEvent = (ev: SSEEvent) => {
  const cur = messages.value[messages.value.length - 1]
  if (!cur || cur.role !== 'assistant') return

  switch (ev.type) {
    case EventType.TextDelta:
      cur.text += ev.content
      break
    case EventType.AgentThinking:
      cur.activities.push({ id: uid(), kind: 'thinking', text: ev.message, done: false })
      break
    case EventType.ToolCall:
      cur.activities.push({
        id: uid(),
        kind: 'tool',
        tool: ev.tool,
        args: ev.args,
        done: false,
      })
      break
    case EventType.ToolResult: {
      // 反向匹配最后一条同名且未完成的工具活动
      for (let i = cur.activities.length - 1; i >= 0; i--) {
        const a = cur.activities[i]
        if (a.kind === 'tool' && a.tool === ev.tool && !a.done) {
          a.result = ev.result
          a.done = true
          break
        }
      }
      break
    }
    case EventType.PlanStepStart:
      cur.activities.push({ id: uid(), kind: 'plan-step', text: ev.description, done: false })
      break
    case EventType.PlanStepEnd: {
      for (let i = cur.activities.length - 1; i >= 0; i--) {
        const a = cur.activities[i]
        if (a.kind === 'plan-step' && !a.done) {
          a.done = true
          a.status = ev.status
          break
        }
      }
      break
    }
    case EventType.Error:
      cur.status = 'error'
      message.error(ev.message)
      break
    case EventType.Done:
      cur.status = 'done'
      cur.elapsed = ev.elapsed_seconds
      break
    default:
      // TASK_CLASSIFIED / PLAN_CREATED 当前流不产生，忽略
      break
  }
  scrollToBottom()
}

// ================================================================
// 发送 / 停止 / 会话
// ================================================================
const send = async (overrideText?: string) => {
  const text = (overrideText ?? input.value).trim()
  if (!text || sending.value) return

  input.value = ''
  messages.value.push({ id: uid(), role: 'user', text, activities: [], status: 'done' })
  messages.value.push({
    id: uid(),
    role: 'assistant',
    text: '',
    activities: [],
    status: 'streaming',
  })
  sending.value = true
  abortCtrl = new AbortController()
  await scrollToBottom()

  try {
    await chatStream({
      message: text,
      sessionId: sessionId.value,
      signal: abortCtrl.signal,
      onEvent,
    })
    // 正常结束后若仍是 streaming（未收到 DONE），兜底置 done
    const cur = messages.value[messages.value.length - 1]
    if (cur && cur.role === 'assistant' && cur.status === 'streaming') {
      cur.status = 'done'
    }
  } catch (e) {
    const err = e as Error
    const cur = messages.value[messages.value.length - 1]
    if (err.name === 'AbortError') {
      if (cur && cur.role === 'assistant' && cur.status === 'streaming') {
        cur.status = 'done'
        if (!cur.text) cur.text = '（已停止）'
      }
    } else {
      if (cur && cur.role === 'assistant') cur.status = 'error'
      message.error(err.message || '发送失败')
    }
  } finally {
    sending.value = false
    abortCtrl = null
    scrollToBottom()
  }
}

const stop = () => {
  abortCtrl?.abort()
}

const newConversation = () => {
  if (sending.value) stop()
  sessionId.value = genSessionId()
  messages.value = []
}

const clearCurrentHistory = async () => {
  try {
    const res = await clearHistory(sessionId.value)
    if (res.data.code === 0) {
      message.success('历史记录已清除')
      messages.value = []
    } else {
      message.error('清除失败：' + res.data.message)
    }
  } catch (e) {
    message.error('清除失败：' + (e as Error).message)
  }
}

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div id="chatPage">
    <div class="chat-shell">
      <!-- 顶栏 -->
      <header class="chat-header">
        <div class="chat-title">
          <RobotOutlined class="title-icon" />
          <span>AI 对话</span>
        </div>
        <div class="chat-actions">
          <span class="session-tag" title="当前会话 ID">会话：{{ shortSession }}</span>
          <a-button size="small" @click="newConversation">
            <template #icon><PlusOutlined /></template>
            新对话
          </a-button>
          <a-button size="small" @click="clearCurrentHistory">
            <template #icon><DeleteOutlined /></template>
            清空历史
          </a-button>
        </div>
      </header>

      <!-- 消息流 -->
      <div ref="scrollRef" class="chat-body">
        <!-- 空状态 -->
        <div v-if="!messages.length" class="empty-state">
          <div class="empty-icon"><RobotOutlined /></div>
          <h3>和 AI 开始对话</h3>
          <p>支持流式回复，可实时查看思考过程与工具调用</p>
          <div class="suggestions">
            <button
              v-for="s in suggestions"
              :key="s"
              class="suggestion-chip"
              @click="send(s)"
            >
              {{ s }}
            </button>
          </div>
        </div>

        <div
          v-for="msg in messages"
          :key="msg.id"
          :class="['msg-row', msg.role]"
        >
          <div :class="['avatar', msg.role]">
            <UserOutlined v-if="msg.role === 'user'" />
            <RobotOutlined v-else />
          </div>

          <div :class="['bubble', msg.role]">
            <!-- 活动区（仅助手） -->
            <div
              v-if="msg.role === 'assistant' && msg.activities.length"
              class="activities"
            >
              <div v-for="a in msg.activities" :key="a.id" class="activity">
                <!-- 思考状态 -->
                <div v-if="a.kind === 'thinking'" class="act-thinking">
                  <LoadingOutlined v-if="msg.status === 'streaming'" class="spin" />
                  <BulbOutlined v-else />
                  <span>{{ a.text }}</span>
                </div>

                <!-- 工具调用 -->
                <div v-else-if="a.kind === 'tool'" class="act-tool" :class="{ done: a.done }">
                  <div class="act-tool-head">
                    <ToolOutlined class="tool-ico" />
                    <span class="tool-name">{{ a.tool }}</span>
                    <span class="tool-status">
                      <template v-if="!a.done"><LoadingOutlined class="spin" /> 执行中</template>
                      <template v-else><CheckCircleOutlined class="ok" /> 完成</template>
                    </span>
                  </div>
                  <details v-if="a.args != null" class="tool-block">
                    <summary>参数</summary>
                    <pre>{{ formatJson(a.args) }}</pre>
                  </details>
                  <details v-if="a.result" class="tool-block" open>
                    <summary>结果</summary>
                    <pre>{{ a.result }}</pre>
                  </details>
                </div>

                <!-- 计划步骤（预留） -->
                <div
                  v-else-if="a.kind === 'plan-step'"
                  class="act-plan"
                  :class="a.status"
                >
                  <CheckCircleOutlined v-if="a.done && a.status === 'done'" class="ok" />
                  <ExclamationCircleOutlined v-else-if="a.status === 'error'" class="err" />
                  <LoadingOutlined v-else class="spin" />
                  <span>{{ a.text }}</span>
                </div>
              </div>
            </div>

            <!-- 正文 -->
            <div v-if="msg.text || msg.role === 'user'" class="msg-text">
              {{ msg.text }}<span
                v-if="msg.role === 'assistant' && msg.status === 'streaming'"
                class="caret"
                >▍</span
              >
            </div>

            <!-- 错误 / 耗时 -->
            <div v-if="msg.role === 'assistant' && msg.status === 'error'" class="err-tag">
              <ExclamationCircleOutlined /> 回复出错，请重试
            </div>
            <div v-if="msg.role === 'assistant' && msg.elapsed != null" class="elapsed">
              耗时 {{ msg.elapsed }}s
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <footer class="chat-input">
        <a-textarea
          v-model:value="input"
          :auto-size="{ minRows: 1, maxRows: 6 }"
          placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
          @keydown="onKeydown"
          class="input-area"
        />
        <a-button
          v-if="!sending"
          type="primary"
          :disabled="!input.trim()"
          @click="send()"
          class="send-btn"
        >
          <template #icon><SendOutlined /></template>
          发送
        </a-button>
        <a-button v-else danger @click="stop" class="send-btn">
          <span class="stop-square"></span>
          停止
        </a-button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
#chatPage {
  height: calc(100vh - 134px); /* header(64) + footer(70) */
  padding: 20px;
  background: var(--color-background-secondary);
}

.chat-shell {
  max-width: 920px;
  height: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-2xl);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

/* —— 顶栏 —— */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-background);
}
.chat-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}
.title-icon {
  color: var(--color-primary);
  font-size: 20px;
}
.chat-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.session-tag {
  font-size: 12px;
  color: var(--color-text-muted);
  background: var(--color-background-tertiary);
  padding: 4px 10px;
  border-radius: var(--radius-full);
  font-family: monospace;
  margin-right: 4px;
}

/* —— 消息流 —— */
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
  scroll-behavior: smooth;
}
.chat-body::-webkit-scrollbar {
  width: 8px;
}
.chat-body::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: var(--radius-full);
}

.msg-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  align-items: flex-start;
}
.msg-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.avatar.user {
  background: var(--gradient-primary);
  color: #fff;
}
.avatar.assistant {
  background: rgba(79, 70, 229, 0.1);
  color: var(--color-primary);
}

.bubble {
  max-width: 78%;
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}
.bubble.user {
  background: var(--gradient-primary);
  color: #fff;
  border-top-right-radius: var(--radius-sm);
}
.bubble.assistant {
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-top-left-radius: var(--radius-sm);
}

.msg-text {
  white-space: pre-wrap;
}
.caret {
  display: inline-block;
  margin-left: 1px;
  color: var(--color-primary);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to {
    visibility: hidden;
  }
}

/* —— 活动区 —— */
.activities {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}
.activity {
  font-size: 13px;
}
.act-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
  background: var(--color-background);
  padding: 6px 10px;
  border-radius: var(--radius-md);
  border: 1px dashed var(--color-border);
}
.act-thinking .spin {
  color: var(--color-primary);
}

.act-tool {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.act-tool.done {
  border-color: rgba(34, 197, 94, 0.4);
}
.act-tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-background-tertiary);
}
.tool-ico {
  color: var(--color-info);
}
.tool-name {
  font-weight: 600;
  color: var(--color-text);
  font-family: monospace;
}
.tool-status {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.tool-status .ok {
  color: var(--color-success);
}
.tool-block {
  padding: 0 12px;
  font-size: 12px;
}
.tool-block summary {
  cursor: pointer;
  padding: 6px 0;
  color: var(--color-text-secondary);
  user-select: none;
}
.tool-block pre {
  margin: 0 0 8px;
  padding: 8px 10px;
  background: var(--color-background-tertiary);
  border-radius: var(--radius-sm);
  overflow-x: auto;
  max-height: 240px;
  overflow-y: auto;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  white-space: pre-wrap;
  color: var(--color-text-secondary);
}

.act-plan {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
}
.act-plan .ok {
  color: var(--color-success);
}
.act-plan.error .err {
  color: var(--color-error);
}

/* —— 错误 / 耗时 —— */
.err-tag {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-error);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.elapsed {
  margin-top: 6px;
  font-size: 11px;
  color: var(--color-text-muted);
}

/* —— 空状态 —— */
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--color-text-secondary);
}
.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-2xl);
  background: rgba(79, 70, 229, 0.1);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  margin-bottom: 16px;
}
.empty-state h3 {
  margin: 0 0 6px;
  font-size: 18px;
  color: var(--color-text);
}
.empty-state p {
  margin: 0 0 20px;
  font-size: 14px;
}
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
  max-width: 480px;
}
.suggestion-chip {
  padding: 8px 14px;
  border: 1px solid var(--color-border);
  background: var(--color-background);
  border-radius: var(--radius-full);
  font-size: 13px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.suggestion-chip:hover {
  border-color: var(--color-primary-light);
  color: var(--color-primary-dark);
  background: rgba(79, 70, 229, 0.05);
}

/* —— 输入区 —— */
.chat-input {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--color-border);
  background: var(--color-background);
}
.input-area {
  flex: 1;
  border-radius: var(--radius-lg) !important;
}
.send-btn {
  height: 40px;
  border-radius: var(--radius-lg);
  font-weight: 600;
}
.stop-square {
  display: inline-block;
  width: 10px;
  height: 10px;
  background: currentColor;
  border-radius: 2px;
  margin-right: 2px;
}

@media (max-width: 768px) {
  #chatPage {
    padding: 10px;
    height: calc(100vh - 134px);
  }
  .bubble {
    max-width: 88%;
  }
  .session-tag {
    display: none;
  }
}
</style>
