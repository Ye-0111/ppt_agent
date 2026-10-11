import request from '@/request'
import { streamPostSSE } from '@/utils/sse'
import type { SSEEvent } from './chatController'

/**
 * PPT 模板 API
 *
 * 后端 test/ 的模板 router（前缀 /ppt/template）：上传 / 列表 / 详情 / 删除 + 选择模板创作。
 * - 上传：multipart/form-data，file 必须是 .pptx 且含 {{占位符}}，否则抛 PARAMS_ERROR(40000)。
 * - 列表：POST 分页，body {current,pageSize,scope?:'mine'|'public'|'all'}，返回 records/total。
 * - 创作是独立 SSE 路径 /ppt/template/create（区别于 /ppt/create），AI 只填占位符、不重新排版。
 * - 用模板创作要求是模板 owner：公开模板他人可见但不能用来创作（非 owner 抛 NOT_FOUND_ERROR 40400）。
 * 全部接口仅需登录（TOKEN cookie），非管理员专属。
 */

/**
 * 上传模板（multipart）。axios 对 FormData 会自动加带 boundary 的 Content-Type，
 * 切勿手动设 Content-Type，否则丢 boundary 导致后端解析失败。
 */
export async function uploadTemplate(file: File, name: string, isPublic: boolean) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('name', name)
  formData.append('is_public', String(isPublic))
  return request.post<API.BaseResponse<API.TemplateRecord>>(
    '/ppt/template/upload',
    formData,
  )
}

/** 分页查询模板列表（POST，分页参数走 body 驼峰；scope 默认 all = 自己 + 公开） */
export async function listTemplates(body: API.TemplateListRequest) {
  return request.post<API.BaseResponse<API.TemplatePageVO>>('/ppt/template/list', {
    current: body.current ?? 1,
    pageSize: body.pageSize ?? 10,
    ...(body.scope ? { scope: body.scope } : {}),
  })
}

/** 模板详情（仅自己上传或公开可见，否则 code!==0） */
export async function getTemplateDetail(id: number) {
  return request.get<API.BaseResponse<API.TemplateRecord>>(`/ppt/template/detail/${id}`)
}

/** 删除模板（仅 owner；后端同时尽力删除物理文件） */
export async function deleteTemplate(id: number) {
  return request.post<API.BaseResponse<null>>('/ppt/template/delete', { id })
}

export interface CreatePptByTemplateOptions {
  /** 模板 ID（必须是当前用户自己上传的模板） */
  templateId: number
  /** 创作主题/需求，AI 据此为模板占位符生成内容 */
  message: string
  /** 风格（可选，后端当前仅预留） */
  style?: string
  signal?: AbortSignal
  /** 每解析出一条 SSE 事件回调一次 */
  onEvent: (event: SSEEvent) => void
}

/**
 * 选模板创作（SSE 流，独立路径 /ppt/template/create）。
 *
 * 事件序列：TASK_CLASSIFIED(mode=template) → AGENT_THINKING(role=content) →
 * TEXT_DELTA(多个，拼成占位符 JSON) → TOOL_CALL(render_ppt_template) →
 * TOOL_RESULT(substituted/missing) → DONE / ERROR。
 * DONE 附带 pptId / filename / remaining_quota，产物复用 downloadPpt(filename) 下载。
 * 开流前配额不足(40104) / 非 owner(40400) 抛 ApiError；中断抛 AbortError（见 utils/sse）。
 */
export async function createPptByTemplateStream(opts: CreatePptByTemplateOptions): Promise<void> {
  const body: Record<string, unknown> = {
    templateId: opts.templateId,
    message: opts.message,
  }
  if (opts.style) body.style = opts.style
  return streamPostSSE('/ppt/template/create', {
    body,
    signal: opts.signal,
    onEvent: opts.onEvent,
  })
}
