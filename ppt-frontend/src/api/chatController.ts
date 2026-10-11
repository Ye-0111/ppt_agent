import request from '@/request'
import { streamPostSSE } from '@/utils/sse'

/**
 * SSE 流式对话 API
 *
 * 后端 test/ 的 `POST /chat/stream` 返回 SSE，每条形如：
 *   data: {"type": <事件类型>, ...}\n\n
 *
 * 事件类型对齐后端 app/schemas/events.py。其中 AGENT_THINKING / TEXT_DELTA /
 * TOOL_CALL / TOOL_RESULT / ERROR / DONE 是当前 langchain_agent.run_stream 实际下发的；
 * 模板创作流（POST /ppt/template/create，见 templateController）开头会额外推
 * TASK_CLASSIFIED (mode='template')，其 TOOL_RESULT 载荷为 substituted/missing 而非 result。
 * PLAN_* 当前流不产生，仅作兼容预留。
 * DONE 在 PPT 创建接口下会额外附带 remaining_quota（见 pptController）。
 */

// ================================================================
// 事件类型常量（对齐后端 events.py 大写下划线风格）
// ================================================================
export const EventType = {
  AgentThinking: 'AGENT_THINKING',
  TaskClassified: 'TASK_CLASSIFIED',
  PlanCreated: 'PLAN_CREATED',
  PlanStepStart: 'PLAN_STEP_START',
  PlanStepEnd: 'PLAN_STEP_END',
  ToolCall: 'TOOL_CALL',
  ToolResult: 'TOOL_RESULT',
  TextDelta: 'TEXT_DELTA',
  Error: 'ERROR',
  Done: 'DONE',
  // —— 多智能体增强事件（前端可忽略，向前兼容）——
  AgentSwitch: 'AGENT_SWITCH',
  // —— 大纲人工审阅：大纲已生成并暂停，等待用户编辑 ——
  OutlineReview: 'OUTLINE_REVIEW',
} as const

// ================================================================
// 事件载荷类型（判别联合，以 type 字段区分）
// ================================================================
export type SSEEvent =
  | {
      type: typeof EventType.AgentThinking
      message: string
      /** 多智能体角色；模板创作流为 'content' */
      role?: string
    }
  | { type: typeof EventType.TextDelta; content: string }
  | { type: typeof EventType.ToolCall; tool: string; args: Record<string, unknown> }
  | {
      type: typeof EventType.ToolResult
      tool: string
      /** 普通创作：工具结果文本 */
      result?: string
      /** 模板创作 render_ppt_template：已替换占位符个数 */
      substituted?: number
      /** 模板创作：未替换（缺值）的占位符 */
      missing?: string[]
    }
  | { type: typeof EventType.Error; message: string }
  | {
      type: typeof EventType.Done
      session_id: string
      elapsed_seconds: number
      remaining_quota?: number
      /** 生成成功的 PPTX 文件名（供下载，仅创作类流程附带） */
      filename?: string
      /** 模板创作 DONE 附带的任务 ID */
      pptId?: number
    }
  // —— 大纲人工审阅（OUTLINE_REVIEW_ENABLED 开启时由第一段 SSE 推送）——
  // outline 为 JSON 字符串（state.outline），解析后为 API.OutlinePage[]
  | { type: typeof EventType.OutlineReview; outline: string; thread_id: string }
  | { type: typeof EventType.AgentSwitch; agent: string }
  // —— 任务分类：模板创作流开头会推（mode='template' + 模板信息）；普通流当前不产生 ——
  | {
      type: typeof EventType.TaskClassified
      /** 普通流：simple/complex */
      classification?: 'simple' | 'complex'
      /** 模板创作：固定 'template' */
      mode?: string
      templateId?: number
      templateName?: string
      slideCount?: number
      placeholders?: string[]
    }
  | { type: typeof EventType.PlanCreated; steps: unknown[]; total: number }
  | {
      type: typeof EventType.PlanStepStart
      step: number
      total: number
      description: string
    }
  | {
      type: typeof EventType.PlanStepEnd
      step: number
      status: 'done' | 'error'
      error?: string
    }

// ================================================================
// 流式请求
// ================================================================
export interface ChatStreamOptions {
  message: string
  sessionId: string
  signal?: AbortSignal
  /** 每解析出一条 SSE 事件回调一次 */
  onEvent: (event: SSEEvent) => void
}

/**
 * 发起流式对话。底层走 utils/sse 的 fetch + ReadableStream。
 *
 * 中断：signal abort 后抛 name === 'AbortError'；业务异常（如未登录）抛 ApiError（见 utils/sse）。
 */
export async function chatStream(opts: ChatStreamOptions): Promise<void> {
  return streamPostSSE('/chat/stream', {
    body: { message: opts.message, session_id: opts.sessionId },
    signal: opts.signal,
    onEvent: opts.onEvent,
  })
}

/** 清除指定会话的历史记录 */
export async function clearHistory(sessionId: string) {
  return request.post('/chat/clear', { session_id: sessionId })
}

/** 生成会话 ID（优先 crypto.randomUUID，回退时间戳+随机串） */
export function genSessionId(): string {
  const c = globalThis.crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}
