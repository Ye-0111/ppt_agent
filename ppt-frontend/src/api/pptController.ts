import request from '@/request'
import { streamPostSSE } from '@/utils/sse'
import type { SSEEvent } from './chatController'

/**
 * PPT 创作 SSE API
 *
 * 后端 test/ 的 `POST /ppt/create`：需登录（TOKEN cookie），配额门控在开流前同步执行，
 * 不足直接返回 JSON（code 40104，非 event-stream）。事件与对话接口同源
 * （AGENT_THINKING / TEXT_DELTA / TOOL_CALL / TOOL_RESULT / ERROR / DONE），
 * DONE 附带 remaining_quota 表示扣减后剩余配额。
 */

export interface PptCreateStreamOptions {
  /** 创作主题/需求 */
  message: string
  /** 风格：business/creative/academic/minimalist，不传走后端默认 */
  style?: string
  /** 会话 ID（不传后端按用户隔离） */
  sessionId: string
  signal?: AbortSignal
  /** 每解析出一条 SSE 事件回调一次 */
  onEvent: (event: SSEEvent) => void
}

/** 流式创建 PPT。中断抛 AbortError；配额不足/未登录抛 ApiError（见 utils/sse） */
export async function createPptStream(opts: PptCreateStreamOptions): Promise<void> {
  const body: Record<string, unknown> = {
    message: opts.message,
    sessionId: opts.sessionId,
  }
  if (opts.style) body.style = opts.style
  return streamPostSSE('/ppt/create', {
    body,
    signal: opts.signal,
    onEvent: opts.onEvent,
  })
}

/**
 * 大纲审阅后续跑（第二段 SSE，扣配额）。
 *
 * 后端 test/ 的 `POST /ppt/create/resume`：需登录，body {message(原主题), outline(编辑后),
 * threadId?, style?}（无 sessionId，后端自取 u{uid}）。outline 经 normalize_outline 规范化后
 * 注入 state.outline 跑 create_pipeline（跳过 outline 节点）。事件与第一段同源，
 * DONE 附带 remaining_quota。normalize 结果为空时开流前抛 PARAMS_ERROR(40000)「大纲内容非法或为空」。
 */
export interface PptResumeStreamOptions {
  /** 第一段 /ppt/create 的原始主题（必须原样回传） */
  message: string
  /** 编辑后的大纲页面数组（{title, layout_hint, purpose}） */
  outline: unknown[]
  /** 第一段 OUTLINE_REVIEW 返回的 thread_id（可选，A' 方案仅作 draft 标识/日志） */
  threadId?: string
  /** 风格：与第一段保持一致 */
  style?: string
  signal?: AbortSignal
  /** 每解析出一条 SSE 事件回调一次 */
  onEvent: (event: SSEEvent) => void
}

/** 提交编辑后的大纲并续跑生成。中断抛 AbortError；配额不足/未登录/大纲非法抛 ApiError（见 utils/sse） */
export async function resumePptStream(opts: PptResumeStreamOptions): Promise<void> {
  const body: Record<string, unknown> = {
    message: opts.message,
    outline: opts.outline,
  }
  if (opts.threadId) body.threadId = opts.threadId
  if (opts.style) body.style = opts.style
  return streamPostSSE('/ppt/create/resume', {
    body,
    signal: opts.signal,
    onEvent: opts.onEvent,
  })
}

/**
 * 下载已生成的 PPTX。responseType=blob，浏览器内触发保存。
 * 共享 axios 拦截器只判 data.code===40100，blob 的 data 是 Blob、无 code，安全。
 */
export async function downloadPpt(filename: string): Promise<void> {
  const resp = await request.get(`/ppt/download/${encodeURIComponent(filename)}`, {
    responseType: 'blob',
  })
  const blob = new Blob([resp.data], {
    type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * 分页查询当前用户的 PPT 任务列表。
 *
 * 后端 test/ 的 `POST /ppt/list`（注意是 POST，分页参数走 body 驼峰）：
 * 需登录，按当前用户隔离，固定 id DESC。返回 BaseResponse<PptPageVO>。
 * status 不传则返回全部（SUCCESS/IN_PROGRESS/FAILED）。
 * 注意：records[].topic 已被后端截断到 80 字符，完整主题走 getPptDetail。
 */
export async function listPpts(body: API.PptListRequest) {
  return request.post<API.BaseResponse<API.PptPageVO>>('/ppt/list', {
    current: body.current ?? 1,
    pageSize: body.pageSize ?? 10,
    ...(body.status ? { status: body.status } : {}),
  })
}

/**
 * 获取 PPT 任务详情（含完整 topic、outline/research JSON、errorMessage）。
 *
 * 后端 test/ 的 `GET /ppt/detail/{pptId}`：需登录；任务不存在或不属于当前用户
 * 返回 code!==0「任务不存在或无权访问」。
 */
export async function getPptDetail(pptId: number) {
  return request.get<API.BaseResponse<API.PptDetail>>(`/ppt/detail/${pptId}`)
}

/**
 * 获取 PPT 任务的智能体执行日志（各 specialist 耗时/状态/输入输出摘要）。
 *
 * 后端 test/ 的 `GET /ppt/agent-log/{pptId}`：需登录 + 归属校验（参照 /ppt/detail）。
 * 返回 BaseResponse<AgentExecutionStatsVO>：总耗时、各 specialist 耗时、整体状态、日志列表。
 * 无日志时 overallStatus='NOT_FOUND'、logs=[]。字段驼峰（VO alias 序列化，与登录接口同构）。
 */
export async function getAgentLog(pptId: number) {
  return request.get<API.BaseResponse<API.AgentExecutionStats>>(`/ppt/agent-log/${pptId}`)
}

/**
 * 断点继续生成（SSE 流）。
 *
 * 后端 test/ 的 `POST /ppt/resume`：需登录，body {pptId(必), message?}。
 * 仅 status==='IN_PROGRESS' 的任务可续跑，否则开流前抛 ApiError
 * （如「任务状态为 SUCCESS/FAILED，不可续跑」/「无可续跑的进度，请重新创建」）。
 * 事件与 /ppt/create 同源（默认开关下不推 OUTLINE_REVIEW），DONE 附带
 * {pptId, filename?, remaining_quota?}。message 不传则沿用任务原 topic。
 *
 * 命名说明：区别于 resumePptStream（POST /ppt/create/resume，大纲审阅后继续）。
 */
export interface ResumePptBreakpointOptions {
  /** 要续跑的任务 ID */
  pptId: number
  /** 可选：覆盖主题（不改就不传，后端沿用原 topic） */
  message?: string
  signal?: AbortSignal
  /** 每解析出一条 SSE 事件回调一次 */
  onEvent: (event: SSEEvent) => void
}

/** 断点续跑。中断抛 AbortError；配额/未登录/状态非法抛 ApiError（见 utils/sse） */
export async function resumePptBreakpoint(opts: ResumePptBreakpointOptions): Promise<void> {
  const body: Record<string, unknown> = { pptId: opts.pptId }
  if (opts.message) body.message = opts.message
  return streamPostSSE('/ppt/resume', {
    body,
    signal: opts.signal,
    onEvent: opts.onEvent,
  })
}
