import { API_BASE_URL } from '@/config/env'

/**
 * fetch POST SSE 公共工具
 *
 * 后端 test/ 的 SSE 端点（/chat/stream、/ppt/create）返回 text/event-stream，
 * 每条 `data: {...}\n\n`。但配额不足/未登录等业务异常会在开流前抛出，
 * 后端全局处理器返回 HTTP 200 + JSON `{code,data,message}`（非 event-stream）。
 * 此时按 BaseResponse 解析，code!==0 抛 ApiError，调用方可据 code 区分处理
 * （如 40104 配额不足、40100 未登录、40101 无权限）。
 */

/** 携带后端业务错误码的错误 */
export class ApiError extends Error {
  code: number
  constructor(code: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

export interface StreamSSEOptions {
  body: Record<string, unknown>
  signal?: AbortSignal
  /** 每解析出一条 SSE 事件回调一次 */
  onEvent: (payload: any) => void
}

/** 以 POST 发起 SSE 流式请求，逐事件回调 */
export async function streamPostSSE(path: string, opts: StreamSSEOptions): Promise<void> {
  const { body, signal, onEvent } = opts
  const url = `${API_BASE_URL}${path}`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      credentials: 'include',
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    const err = e as Error
    if (err.name === 'AbortError') throw e
    throw new Error(`无法连接到服务：${err.message}`)
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const text = await response.text()
      if (text) detail = text
    } catch {
      /* 忽略 */
    }
    throw new Error(`服务返回错误：${detail}`)
  }

  const contentType = response.headers.get('content-type') || ''

  // 非 event-stream：开流前的业务异常（配额不足/未登录等）返回 JSON
  if (!contentType.includes('text/event-stream')) {
    let payload: { code?: number; message?: string } | null = null
    try {
      payload = await response.json()
    } catch {
      throw new Error('响应格式异常')
    }
    const code = payload?.code ?? -1
    if (code !== 0) {
      throw new ApiError(code, payload?.message || '请求失败')
    }
    return
  }

  const stream = response.body
  if (!stream) throw new Error('当前环境不支持流式响应')

  const reader = stream.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatch = (rawEvent: string) => {
    // 一个事件可能含多行 data:，按 SSE 规范换行拼接；忽略 event:/id:/retry: 与注释行
    const dataLines: string[] = []
    for (const line of rawEvent.split('\n')) {
      const trimmed = line.replace(/^\r/, '')
      if (/^data:/.test(trimmed)) {
        dataLines.push(trimmed.slice(5).replace(/^ /, ''))
      }
    }
    if (!dataLines.length) return
    const payloadStr = dataLines.join('\n')
    try {
      onEvent(JSON.parse(payloadStr))
    } catch (e) {
      console.warn('[SSE] 解析事件失败:', payloadStr, e)
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // 事件之间以空行分隔；逐个切出完整事件，尾部不完整的留在 buffer
      let sep: number
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        if (rawEvent.trim()) dispatch(rawEvent)
      }
    }
    // flush 解码器残留 + 未以 \n\n 结尾的最后一段
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
  } catch (e) {
    const err = e as Error
    if (err.name === 'AbortError') throw e
    throw new Error(`读取流式响应失败：${err.message}`)
  }
}
