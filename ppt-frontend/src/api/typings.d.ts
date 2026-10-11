/**
 * API 类型定义
 */
declare namespace API {
  /** 统一响应 */
  interface BaseResponse<T = any> {
    code: number
    data: T
    message: string
  }

  /** 登录用户信息 */
  interface LoginUserVO {
    id?: number
    username?: string
    nickname?: string
    userRole?: string
    createTime?: string
    pptQuota?: number
    token?: string
  }

  /** 用户配额记录（管理员分页查询） */
  interface QuotaRecord {
    id: number
    username: string
    nickname?: string
    userRole: string
    pptQuota: number
    createTime?: string
  }

  /** 配额分页结果 */
  interface QuotaPageVO {
    records: QuotaRecord[]
    total: number
    current: number
    pageSize: number
  }

  /** 登录请求 */
  interface UserLoginRequest {
    username: string
    password: string
  }

  /** 注册请求 */
  interface UserRegisterRequest {
    username: string
    password: string
    checkPassword: string
  }

  /** 大纲页面布局提示（对齐后端 normalize_outline 白名单） */
  type OutlineLayoutHint = 'title-slide' | 'content' | 'two-column'

  /** 大纲单页（对齐后端 state.outline：[{title, layout_hint, purpose}]） */
  interface OutlinePage {
    title: string
    layout_hint: OutlineLayoutHint
    purpose?: string
  }

  /** PPT 任务状态（对齐后端 sys_ppt.status） */
  type PptRecordStatus = 'SUCCESS' | 'IN_PROGRESS' | 'FAILED'

  /** PPT 生成阶段（对齐后端 sys_ppt.stage 流转） */
  type PptRecordStage =
    | 'CREATED'
    | 'OUTLINE_DONE'
    | 'RESEARCH_DONE'
    | 'CONTENT_DONE'
    | 'BEAUTIFY_DONE'

  /** PPT 列表行（POST /ppt/list 返回，topic 已被后端截断 >80 字符） */
  interface PptRecord {
    id: number
    filename: string | null
    topic: string
    style: string
    status: PptRecordStatus
    stage: PptRecordStage
    createTime: string
    updateTime: string
  }

  /** PPT 分页结果 */
  interface PptPageVO {
    records: PptRecord[]
    total: number
    current: number
    pageSize: number
  }

  /** PPT 列表查询请求（POST /ppt/list body，驼峰） */
  interface PptListRequest {
    current?: number
    pageSize?: number
    status?: PptRecordStatus
  }

  /** PPT 任务详情（GET /ppt/detail/{id}，topic 完整；outline/research 为 JSON 字符串） */
  interface PptDetail {
    id: number
    userId: number
    filename: string | null
    topic: string
    style: string
    status: PptRecordStatus
    stage: PptRecordStage
    outline: string | null
    research: string | null
    sessionId: string
    createTime: string
    updateTime: string
    errorMessage: string | null
  }

  /** 模板可见范围（对齐后端 TemplateListRequest.scope） */
  type TemplateScope = 'mine' | 'public' | 'all'

  /** PPT 模板记录（上传/列表/详情返回；variables 已反序列化为数组，isPublic 已转 bool） */
  interface TemplateRecord {
    id: number
    userId: number
    name: string
    filename: string
    /** 占位符名数组（后端 variables JSON 已反序列化） */
    variables?: string[]
    slideCount?: number
    isPublic: boolean
    createTime: string
    updateTime: string
  }

  /** 模板分页结果 */
  interface TemplatePageVO {
    records: TemplateRecord[]
    total: number
    current: number
    pageSize: number
  }

  /** 模板列表查询请求（POST /ppt/template/list body，驼峰） */
  interface TemplateListRequest {
    current?: number
    pageSize?: number
    scope?: TemplateScope
  }

  /** 智能体单次执行状态（对齐后端 sys_agent_log.status） */
  type AgentLogStatus = 'RUNNING' | 'SUCCESS' | 'FAILED'

  /** 任务执行整体状态（对齐后端 AgentExecutionStatsVO.overallStatus；NOT_FOUND=无日志） */
  type AgentLogOverallStatus = 'SUCCESS' | 'FAILED' | 'RUNNING' | 'NOT_FOUND'

  /** 单条 specialist 执行日志（GET /ppt/agent-log/{id} 返回；inputData/outputData 为 JSON 字符串） */
  interface AgentLog {
    id: number
    taskId: string
    agentName: string
    startTime: string
    endTime: string | null
    durationMs: number | null
    status: AgentLogStatus
    errorMessage: string | null
    prompt: string | null
    inputData: string | null
    outputData: string | null
    createTime: string
    updateTime: string
  }

  /** 任务执行统计（按 taskId 聚合所有 specialist 执行） */
  interface AgentExecutionStats {
    taskId: string
    totalDurationMs: number
    agentCount: number
    agentDurations: Record<string, number>
    overallStatus: AgentLogOverallStatus
    logs: AgentLog[]
  }
}
