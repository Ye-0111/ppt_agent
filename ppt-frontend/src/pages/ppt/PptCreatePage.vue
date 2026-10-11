<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  RocketOutlined,
  BulbOutlined,
  ToolOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CheckCircleFilled,
  ExclamationCircleOutlined,
  RedoOutlined,
  DownloadOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons-vue'
import {
  createPptStream,
  resumePptStream,
  resumePptBreakpoint,
  getPptDetail,
  downloadPpt,
} from '@/api/pptController'
import {
  createPptByTemplateStream,
  listTemplates,
  getTemplateDetail,
} from '@/api/templateController'
import OutlineReviewStage from './components/OutlineReviewStage.vue'
import { EventType, genSessionId } from '@/api/chatController'
import type { SSEEvent } from '@/api/chatController'
import { ApiError } from '@/utils/sse'
import { useLoginUserStore } from '@/stores/loginUser'
import dayjs from 'dayjs'

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

// ================================================================
// 状态
// ================================================================
const router = useRouter()
const route = useRoute()
const loginUserStore = useLoginUserStore()

type Phase = 'INPUT' | 'CREATING' | 'REVIEW' | 'COMPLETED' | 'RESUME'
const phase = ref<Phase>('INPUT')

const topic = ref('')
const style = ref('') // 空 = 默认
const activities = ref<ActivityItem[]>([])
const assistantText = ref('')
const remainingQuota = ref(loginUserStore.loginUser.pptQuota ?? 0)
// 大纲人工审阅（REVIEW 阶段）
const outlinePages = ref<API.OutlinePage[]>([])
const outlineThreadId = ref('')
const pendingMessage = ref('') // 第二段需原样回传第一段的主题
const pendingStyle = ref('')
// 生成产物文件名（DONE 携带，供下载）
const resultFilename = ref('')
const resuming = ref(false) // 续跑按钮 loading
// 断点恢复（RESUME 阶段）：从 /ppt/list 跳 ?resume=<pptId> 进入
const resumeTask = ref<{
  id: number
  topic: string
  style: string
  stage: API.PptRecordStage
  updateTime: string
} | null>(null)
const resumeDetailLoading = ref(false)
// 选择模板创作（与 ?resume 互斥）：selectedTemplate 非 null → startCreate 走模板创作流
const selectedTemplate = ref<{ id: number; name: string } | null>(null)
const selectedTemplateId = ref<number | undefined>(undefined)
const myTemplates = ref<API.TemplateRecord[]>([])
const templateLoading = ref(false)
let abortCtrl: AbortController | null = null
let sessionId = genSessionId()
// ERROR 事件标志：流式出错后防止「未收到 DONE 也结束」的兜底误判为完成（create/resume 共用）
let streamError = false
let seq = 0
const uid = () => `a${Date.now()}_${seq++}`

const bodyRef = ref<HTMLElement | null>(null)

const styleOptions = [
  { value: '', label: '默认' },
  { value: 'business', label: '商务' },
  { value: 'creative', label: '创意' },
  { value: 'academic', label: '学术' },
  { value: 'minimalist', label: '简约' },
]

// 阶段/风格中文映射（列表页与恢复卡共用语义）
const STAGE_LABELS: Record<API.PptRecordStage, string> = {
  CREATED: '已创建',
  OUTLINE_DONE: '大纲完成',
  RESEARCH_DONE: '素材已收集',
  CONTENT_DONE: '内容已生成',
  BEAUTIFY_DONE: '美化完成',
}
const STYLE_LABELS: Record<string, string> = {
  '': '默认',
  business: '商务',
  creative: '创意',
  academic: '学术',
  minimalist: '简约',
}

const hotTopics = [
  '2026 年 AI 技术发展趋势',
  '公司年度工作总结',
  '新产品发布演示',
  'Python 入门教程（3 页）',
  '季度业绩分析报告',
]

const canCreate = computed(() => topic.value.trim().length > 0 && remainingQuota.value > 0)

// ================================================================
// 工具
// ================================================================
const scrollToBottom = () => {
  nextTick(() => {
    if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
  })
}

const formatJson = (v: unknown) => {
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

const formatTime = (t?: string) => {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm')
}

// OUTLINE_REVIEW.outline 是 JSON 字符串（state.outline），解析为页面数组；防御非数组/解析失败
const parseOutlinePages = (raw: unknown): API.OutlinePage[] => {
  let data = raw
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw)
    } catch {
      return []
    }
  }
  if (!Array.isArray(data)) return []
  return data.filter((p) => p && typeof p === 'object') as API.OutlinePage[]
}

// ================================================================
// SSE 事件处理
// ================================================================
const onEvent = (ev: SSEEvent) => {
  switch (ev.type) {
    case EventType.TextDelta:
      assistantText.value += ev.content
      break
    case EventType.AgentThinking:
      activities.value.push({ id: uid(), kind: 'thinking', text: ev.message, done: false })
      break
    case EventType.ToolCall:
      activities.value.push({
        id: uid(),
        kind: 'tool',
        tool: ev.tool,
        args: ev.args,
        done: false,
      })
      break
    case EventType.ToolResult: {
      for (let i = activities.value.length - 1; i >= 0; i--) {
        const a = activities.value[i]
        if (a.kind === 'tool' && a.tool === ev.tool && !a.done) {
          a.result = ev.result
          a.done = true
          break
        }
      }
      break
    }
    case EventType.PlanStepStart:
      activities.value.push({ id: uid(), kind: 'plan-step', text: ev.description, done: false })
      break
    case EventType.PlanStepEnd: {
      for (let i = activities.value.length - 1; i >= 0; i--) {
        const a = activities.value[i]
        if (a.kind === 'plan-step' && !a.done) {
          a.done = true
          a.status = ev.status
          break
        }
      }
      break
    }
    case EventType.OutlineReview: {
      // 第一段大纲生成完成并暂停：解析大纲、记住原主题/风格，切到大纲编辑器
      const pages = parseOutlinePages(ev.outline)
      if (!pages.length) {
        message.error('大纲解析失败，请重试')
        phase.value = 'INPUT'
        break
      }
      outlinePages.value = pages
      outlineThreadId.value = ev.thread_id ?? ''
      pendingMessage.value = topic.value
      pendingStyle.value = style.value
      phase.value = 'REVIEW'
      break
    }
    case EventType.TaskClassified:
      // 模板创作流开头：展示已选模板信息（普通创作流当前不产生此事件）
      if (ev.mode === 'template') {
        activities.value.push({
          id: uid(),
          kind: 'thinking',
          text: `已选定模板：${ev.templateName ?? ''}${ev.slideCount ? `（${ev.slideCount} 页）` : ''}`,
          done: true,
        })
      }
      break
    case EventType.Error:
      streamError = true
      message.error(ev.message || '生成出错')
      break
    case EventType.Done:
      if (ev.remaining_quota != null) remainingQuota.value = ev.remaining_quota
      if (ev.filename) resultFilename.value = ev.filename
      // 第一段（大纲审阅）末尾的 DONE：此时 phase 已切到 REVIEW，不应判完成；
      // 第二段（续跑）的 DONE：phase 为 CREATING，正常完成。
      // 开关关闭时的存量单段流：无 OUTLINE_REVIEW，phase 仍 CREATING → 正常完成（向后兼容）。
      if (phase.value !== 'REVIEW') phase.value = 'COMPLETED'
      break
    default:
      break
  }
  scrollToBottom()
}

// ================================================================
// 操作
// ================================================================

const onDownload = async () => {
  if (!resultFilename.value) return
  try {
    await downloadPpt(resultFilename.value)
  } catch (e) {
    const err = e as Error & { code?: number }
    message.error(err.message || '下载失败')
  }
}

const startCreate = async () => {
  const text = topic.value.trim()
  if (!text) {
    message.warning('请输入 PPT 主题')
    return
  }
  if (remainingQuota.value <= 0) {
    message.warning('PPT 配额不足')
    return
  }

  activities.value = []
  assistantText.value = ''
  phase.value = 'CREATING'
  streamError = false
  abortCtrl = new AbortController()
  scrollToBottom()

  try {
    if (selectedTemplate.value) {
      // 选择模板：走独立 SSE 路径 /ppt/template/create（AI 仅填占位符，不重新排版）
      await createPptByTemplateStream({
        templateId: selectedTemplate.value.id,
        message: text,
        style: style.value || undefined,
        signal: abortCtrl.signal,
        onEvent,
      })
    } else {
      await createPptStream({
        message: text,
        style: style.value || undefined,
        sessionId,
        signal: abortCtrl.signal,
        onEvent,
      })
    }
    // 兜底：未收到 DONE 也结束（ERROR 事件已置 streamError，出错时不再误判完成）
    if (phase.value === 'CREATING' && !streamError) phase.value = 'COMPLETED'
  } catch (e) {
    const err = e as Error & { code?: number }
    if (err.name === 'AbortError') {
      phase.value = assistantText.value ? 'COMPLETED' : 'INPUT'
    } else if (err instanceof ApiError && err.code === 40104) {
      message.error('PPT 配额不足')
      remainingQuota.value = 0
      phase.value = 'INPUT'
    } else if (err instanceof ApiError && err.code === 40100) {
      message.error('登录已过期，请重新登录')
      router.push(`/user/login?redirect=/create`)
    } else {
      message.error(err.message || '创建失败')
      phase.value = 'INPUT'
    }
  } finally {
    abortCtrl = null
    scrollToBottom()
  }
}

const stop = () => {
  abortCtrl?.abort()
}

const resetCreate = () => {
  phase.value = 'INPUT'
  topic.value = ''
  activities.value = []
  assistantText.value = ''
  outlinePages.value = []
  resultFilename.value = ''
  resumeTask.value = null
  selectedTemplate.value = null
  selectedTemplateId.value = undefined
  sessionId = genSessionId()
  // 清掉 ?resume / ?templateId 查询参数，避免刷新后重新进入
  if (route.query.resume || route.query.templateId) {
    router.replace({ path: '/create', query: {} })
  }
}

// 大纲审阅确认：提交编辑后的大纲，POST /ppt/create/resume 续跑第二段（扣配额）
const handleConfirmOutline = async (edited: API.OutlinePage[]) => {
  if (!edited.length || edited.some((p) => !p.title.trim())) {
    message.warning('请填写每页标题')
    return
  }
  activities.value = []
  assistantText.value = ''
  phase.value = 'CREATING'
  streamError = false
  resuming.value = true
  abortCtrl = new AbortController()
  scrollToBottom()
  try {
    await resumePptStream({
      message: pendingMessage.value,
      outline: edited,
      threadId: outlineThreadId.value || undefined,
      style: pendingStyle.value || undefined,
      signal: abortCtrl.signal,
      onEvent,
    })
    // 兜底：未收到 DONE 也结束（ERROR 事件已置 streamError，出错时不再误判完成）
    if (phase.value === 'CREATING' && !streamError) phase.value = 'COMPLETED'
  } catch (e) {
    const err = e as Error & { code?: number }
    if (err.name === 'AbortError') {
      phase.value = assistantText.value ? 'COMPLETED' : 'REVIEW'
    } else if (err instanceof ApiError && err.code === 40104) {
      message.error('PPT 配额不足')
      remainingQuota.value = 0
      phase.value = 'INPUT'
    } else if (err instanceof ApiError && err.code === 40100) {
      message.error('登录已过期，请重新登录')
      router.push(`/user/login?redirect=/create`)
    } else {
      // 40000 大纲非法/为空 等：保留编辑器供修正
      message.error(err.message || '续跑失败')
      phase.value = 'REVIEW'
    }
  } finally {
    abortCtrl = null
    resuming.value = false
    scrollToBottom()
  }
}

const handleCancelReview = () => {
  resetCreate()
}

// 断点恢复：从 RESUME 卡点「继续生成」，POST /ppt/resume 续跑剩余阶段（复用 onEvent）
const startResume = async () => {
  if (!resumeTask.value) return
  activities.value = []
  assistantText.value = ''
  phase.value = 'CREATING'
  streamError = false
  resuming.value = true
  abortCtrl = new AbortController()
  scrollToBottom()
  try {
    await resumePptBreakpoint({
      pptId: resumeTask.value.id,
      signal: abortCtrl.signal,
      onEvent,
    })
    // 兜底：未收到 DONE 也结束（出错时不误判完成）
    if (phase.value === 'CREATING' && !streamError) {
      phase.value = 'COMPLETED'
      if (!resultFilename.value) {
        message.info('未返回文件名，可到「我的PPT」列表下载')
      }
    }
  } catch (e) {
    const err = e as Error & { code?: number }
    if (err.name === 'AbortError') {
      // 中断：已有正文产出→完成；否则回到恢复卡，用户可再次继续
      phase.value = assistantText.value ? 'COMPLETED' : 'RESUME'
    } else if (err instanceof ApiError && err.code === 40104) {
      message.error('PPT 配额不足')
      remainingQuota.value = 0
      phase.value = 'RESUME'
    } else if (err instanceof ApiError && err.code === 40100) {
      message.error('登录已过期，请重新登录')
      router.push(
        `/user/login?redirect=${encodeURIComponent(`/create?resume=${resumeTask.value.id}`)}`,
      )
    } else {
      message.error(err.message || '继续生成失败')
      phase.value = 'RESUME'
    }
  } finally {
    abortCtrl = null
    resuming.value = false
    scrollToBottom()
  }
}

const cancelResume = () => {
  router.replace('/ppt/list')
}

const goLogin = () => {
  router.push(`/user/login?redirect=/create`)
}

// 模板下拉选项（仅自己的模板，scope=mine）
const templateOptions = computed(() =>
  myTemplates.value.map((t) => ({
    value: t.id,
    label: `${t.name}（${t.slideCount ?? '?'} 页）`,
  })),
)

const onTemplateChange = (val: number | undefined) => {
  selectedTemplate.value =
    val == null ? null : myTemplates.value.find((t) => t.id === val) ?? null
}

// 加载「我的模板」用于下拉（失败不阻塞创作）
const loadMyTemplates = async () => {
  templateLoading.value = true
  try {
    const res = await listTemplates({ current: 1, pageSize: 100, scope: 'mine' })
    if (res.data.code === 0 && res.data.data) {
      myTemplates.value = res.data.data.records ?? []
    }
  } catch {
    /* 忽略：下拉加载失败不影响普通创作 */
  } finally {
    templateLoading.value = false
  }
}

onMounted(async () => {
  // 未登录交给路由守卫；此处仅兜底
  if (!loginUserStore.loginUser.id) {
    goLogin()
    return
  }
  // INPUT 阶段模板下拉数据（后台加载，不阻塞）
  loadMyTemplates()
  // 断点恢复入口：/create?resume=<pptId>
  const resumeId = route.query.resume
  if (resumeId == null || resumeId === '') {
    // 非恢复入口：可能带 ?topic= 预填主题（来自列表页「重新创建」）
    const t = route.query.topic
    if (typeof t === 'string' && t.trim()) {
      topic.value = t
    }
    // 预选模板：/create?templateId=<id>（来自模板库「用此模板创作」/ 上传成功）
    const tplIdRaw = route.query.templateId
    if (tplIdRaw != null && tplIdRaw !== '') {
      const tplId = Number(tplIdRaw)
      if (Number.isFinite(tplId) && tplId > 0) {
        try {
          const res = await getTemplateDetail(tplId)
          if (res.data.code === 0 && res.data.data) {
            const d = res.data.data
            // 后端也会校验 owner，这里前置过滤并提示
            if (loginUserStore.loginUser.id != null && d.userId === loginUserStore.loginUser.id) {
              selectedTemplate.value = { id: d.id, name: d.name }
              selectedTemplateId.value = d.id
              // 下拉数据可能尚未返回，补一项保证显示
              if (!myTemplates.value.some((it) => it.id === d.id)) {
                myTemplates.value = [d, ...myTemplates.value]
              }
            } else {
              message.warning('仅可使用自己上传的模板创作')
            }
          } else {
            message.error(res.data.message || '模板不存在或无权访问')
          }
        } catch (e) {
          message.error('加载模板失败：' + (e as Error).message)
        }
      }
    }
    return
  }
  const pptId = Number(resumeId)
  if (!Number.isFinite(pptId) || pptId <= 0) {
    message.error('恢复参数无效')
    router.replace('/ppt/list')
    return
  }
  // 先切 RESUME 态显示加载占位，避免先闪现 INPUT 卡
  phase.value = 'RESUME'
  resumeDetailLoading.value = true
  try {
    const res = await getPptDetail(pptId)
    if (res.data.code !== 0 || !res.data.data) {
      message.error(res.data.message || '任务不存在或无权访问')
      router.replace('/ppt/list')
      return
    }
    const d = res.data.data
    if (d.status !== 'IN_PROGRESS') {
      message.warning(d.status === 'SUCCESS' ? '任务已完成，无需恢复' : '任务已失败，无法恢复')
      router.replace('/ppt/list')
      return
    }
    resumeTask.value = {
      id: d.id,
      topic: d.topic,
      style: d.style,
      stage: d.stage,
      updateTime: d.updateTime,
    }
    // 回填 topic/style：DONE 后展示一致；后端若推 OUTLINE_REVIEW 时 pendingMessage 自洽
    topic.value = d.topic
    style.value = d.style
    phase.value = 'RESUME'
  } catch (e) {
    message.error('加载任务失败：' + (e as Error).message)
    router.replace('/ppt/list')
  } finally {
    resumeDetailLoading.value = false
  }
})
</script>

<template>
  <div id="pptCreatePage">
    <div class="shell">
      <!-- 顶栏 -->
      <header class="topbar">
        <div class="title-wrap">
          <RocketOutlined class="title-icon" />
          <span class="title-text">创作 PPT</span>
        </div>
        <div :class="['quota-badge', { low: remainingQuota <= 0 }]">
          剩余配额：<b>{{ remainingQuota }}</b> 次
        </div>
      </header>

      <!-- 主体（可滚动） -->
      <div ref="bodyRef" class="body">
        <!-- ============ 输入阶段 ============ -->
        <div v-if="phase === 'INPUT'" class="input-state">
          <div class="input-card">
            <div class="input-header">
              <h1 class="input-title">创作新 PPT</h1>
              <p class="input-subtitle">输入主题，AI 智能体为你生成专业 PPT</p>
            </div>

            <a-textarea
              v-model:value="topic"
              class="topic-textarea"
              placeholder="例如：帮我做一份 3 页的 Python 入门 PPT，要点简洁"
              :rows="5"
              :maxlength="500"
              show-count
            />

            <div class="style-section">
              <div class="section-header">
                <span class="section-title">PPT 风格</span>
                <span class="section-tip">（不选使用默认风格）</span>
              </div>
              <a-radio-group v-model:value="style" class="style-group">
                <a-radio v-for="o in styleOptions" :key="o.value" :value="o.value">{{ o.label }}</a-radio>
              </a-radio-group>
            </div>

            <div class="template-section">
              <div class="section-header">
                <span class="section-title">使用模板</span>
                <span class="section-tip">（不选则从零生成；仅可选择自己的模板）</span>
              </div>
              <a-select
                v-model:value="selectedTemplateId"
                :loading="templateLoading"
                :options="templateOptions"
                placeholder="不使用模板（默认从零生成）"
                allow-clear
                class="template-select"
                @change="onTemplateChange"
              />
              <RouterLink to="/ppt/template/list" class="tpl-mgr-link">管理模板 →</RouterLink>
            </div>

            <div class="hot-section">
              <div class="section-title">热门主题</div>
              <div class="hot-tags">
                <span v-for="t in hotTopics" :key="t" class="hot-tag" @click="topic = t">
                  {{ t }}
                </span>
              </div>
            </div>

            <a-button
              type="primary"
              size="large"
              :disabled="!canCreate"
              @click="startCreate"
              class="create-btn"
            >
              <template #icon><RocketOutlined /></template>
              开始创作
            </a-button>
            <p v-if="remainingQuota <= 0" class="quota-tip">
              <ExclamationCircleOutlined /> 配额已用完，请联系管理员补充
            </p>
          </div>
        </div>

        <!-- ============ 断点恢复 ============ -->
        <div v-else-if="phase === 'RESUME'" class="resume-state">
          <a-spin :spinning="resumeDetailLoading">
            <div class="resume-card">
              <div class="resume-head">
                <ClockCircleOutlined class="resume-ico" />
                <h2>继续生成 PPT</h2>
              </div>
              <p class="resume-tip">检测到未完成的任务，确认信息后点击「继续生成」续跑剩余阶段</p>
              <div class="resume-field">
                <label>主题</label>
                <div class="resume-topic">{{ resumeTask?.topic }}</div>
              </div>
              <div class="resume-field">
                <label>风格</label>
                <span>{{ STYLE_LABELS[resumeTask?.style ?? ''] ?? resumeTask?.style }}</span>
              </div>
              <div class="resume-field">
                <label>当前进度</label>
                <span>{{ STAGE_LABELS[resumeTask?.stage ?? 'CREATED'] }}</span>
              </div>
              <div class="resume-field">
                <label>上次更新</label>
                <span>{{ formatTime(resumeTask?.updateTime) }}</span>
              </div>
              <div class="resume-actions">
                <a-button
                  type="primary"
                  size="large"
                  :loading="resuming"
                  @click="startResume"
                  class="action-btn"
                >
                  <template #icon><RocketOutlined /></template>
                  继续生成
                </a-button>
                <a-button size="large" @click="cancelResume" class="action-btn">返回列表</a-button>
              </div>
            </div>
          </a-spin>
        </div>

        <!-- ============ 大纲审阅 ============ -->
        <div v-else-if="phase === 'REVIEW'" class="review-state">
          <OutlineReviewStage
            :outline="outlinePages"
            :loading="resuming"
            @confirm="handleConfirmOutline"
            @cancel="handleCancelReview"
          />
        </div>

        <!-- ============ 生成中 / 完成 ============ -->
        <div v-else class="gen-state">
          <!-- 活动区 -->
          <div v-if="activities.length" class="activities">
            <div v-for="a in activities" :key="a.id" class="activity">
              <!-- 思考 -->
              <div v-if="a.kind === 'thinking'" class="act-thinking">
                <LoadingOutlined v-if="phase === 'CREATING'" class="spin" />
                <BulbOutlined v-else />
                <span>{{ a.text }}</span>
              </div>
              <!-- 工具 -->
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
              <div v-else-if="a.kind === 'plan-step'" class="act-plan" :class="a.status">
                <CheckCircleOutlined v-if="a.done && a.status === 'done'" class="ok" />
                <ExclamationCircleOutlined v-else-if="a.status === 'error'" class="err" />
                <LoadingOutlined v-else class="spin" />
                <span>{{ a.text }}</span>
              </div>
            </div>
          </div>

          <!-- 完成提示 -->
          <div v-if="phase === 'COMPLETED'" class="success-header">
            <CheckCircleFilled class="success-icon" />
            <span>PPT 创作完成！</span>
          </div>

          <!-- 正文 -->
          <div v-if="assistantText" class="content-preview">
            <div class="msg-text">
              {{ assistantText
              }}<span v-if="phase === 'CREATING'" class="caret">▍</span>
            </div>
          </div>
          <div v-else-if="phase === 'CREATING'" class="loading-placeholder">
            <LoadingOutlined class="big-spin" />
            <p>AI 正在思考...</p>
          </div>
        </div>
      </div>

      <!-- 底部操作 -->
      <footer class="footer">
        <template v-if="phase === 'CREATING'">
          <a-button danger size="large" @click="stop" class="action-btn">
            <span class="stop-square"></span>
            停止生成
          </a-button>
        </template>
        <template v-else-if="phase === 'COMPLETED'">
          <a-button
            size="large"
            type="primary"
            :disabled="!resultFilename"
            @click="onDownload"
            class="action-btn"
          >
            <template #icon><DownloadOutlined /></template>
            下载 PPT
          </a-button>
          <a-button size="large" @click="resetCreate" class="action-btn">
            <template #icon><RedoOutlined /></template>
            再创作一个
          </a-button>
        </template>
        <template v-else-if="phase === 'REVIEW'">
          <!-- 编辑器自带「确认并生成内容 / 放弃」按钮，footer 留空 -->
        </template>
        <template v-else-if="phase === 'RESUME'">
          <!-- 恢复卡自带「继续生成 / 返回列表」按钮，footer 留空 -->
        </template>
        <template v-else>
          <a-button
            size="large"
            type="primary"
            :disabled="!canCreate"
            @click="startCreate"
            class="action-btn"
          >
            <template #icon><RocketOutlined /></template>
            开始创作
          </a-button>
        </template>
      </footer>
    </div>
  </div>
</template>

<style scoped>
#pptCreatePage {
  height: calc(100vh - 134px);
  padding: 20px;
  background: var(--color-background-secondary);
}
.shell {
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
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--color-border);
}
.title-wrap {
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
.quota-badge {
  font-size: 13px;
  color: var(--color-text-secondary);
  background: rgba(79, 70, 229, 0.08);
  padding: 6px 14px;
  border-radius: var(--radius-full);
}
.quota-badge b {
  color: var(--color-primary);
  font-size: 15px;
}
.quota-badge.low {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error);
}
.quota-badge.low b {
  color: var(--color-error);
}

/* —— 主体 —— */
.body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
}
.body::-webkit-scrollbar {
  width: 8px;
}
.body::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: var(--radius-full);
}

/* —— 输入卡 —— */
.input-state {
  max-width: 640px;
  margin: 20px auto;
}
.input-card {
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: 32px;
}
.input-header {
  text-align: center;
  margin-bottom: 24px;
}
.input-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--color-text);
}
.input-subtitle {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}
.topic-textarea {
  font-size: 15px !important;
  border-radius: var(--radius-lg) !important;
  padding: 14px !important;
  background: var(--color-background) !important;
}
.topic-textarea :deep(textarea:focus) {
  border-color: var(--color-primary) !important;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
}

.style-section,
.hot-section,
.template-section {
  margin-top: 16px;
}
.template-select {
  width: 100%;
  max-width: 420px;
  border-radius: var(--radius-md);
}
.tpl-mgr-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-primary);
}
.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.section-tip {
  font-size: 12px;
  color: var(--color-text-muted);
}
.style-group {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.style-group :deep(.ant-radio-wrapper) {
  margin: 0;
  padding: 6px 14px;
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  transition: all 0.2s;
}
.style-group :deep(.ant-radio-wrapper:hover) {
  border-color: var(--color-primary);
}
.style-group :deep(.ant-radio-wrapper-checked) {
  border-color: var(--color-primary);
  background: rgba(79, 70, 229, 0.08);
}

.hot-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.hot-tag {
  padding: 6px 12px;
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 12px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.hot-tag:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: rgba(79, 70, 229, 0.05);
}

.create-btn {
  width: 100%;
  margin-top: 24px;
  height: 48px;
  font-size: 15px;
  font-weight: 600;
  border-radius: var(--radius-lg);
  background: var(--gradient-primary) !important;
  border: none !important;
  color: #fff !important;
  box-shadow: var(--shadow-primary) !important;
}
.create-btn:hover,
.create-btn:focus {
  background: var(--gradient-primary) !important;
  color: #fff !important;
  opacity: 0.92;
}
.create-btn:disabled {
  background: var(--color-border) !important;
  color: var(--color-text-muted) !important;
  box-shadow: none !important;
}
.quota-tip {
  margin: 12px 0 0;
  text-align: center;
  font-size: 13px;
  color: var(--color-error);
}

/* —— 断点恢复 —— */
.resume-state {
  max-width: 640px;
  margin: 20px auto;
}
.resume-card {
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: 32px;
}
.resume-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.resume-head h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
}
.resume-ico {
  font-size: 24px;
  color: var(--color-primary);
}
.resume-tip {
  margin: 0 0 22px;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.resume-field {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px dashed var(--color-border-light);
  font-size: 14px;
}
.resume-field:last-of-type {
  border-bottom: none;
}
.resume-field label {
  flex: 0 0 84px;
  color: var(--color-text-muted);
  font-size: 13px;
}
.resume-field span {
  color: var(--color-text);
}
.resume-topic {
  flex: 1;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}
.resume-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}
.resume-actions .action-btn {
  flex: 1;
}

/* —— 生成 / 完成 —— */
.gen-state {
  max-width: 760px;
  margin: 0 auto;
}
.success-header {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  background: var(--gradient-primary);
  border-radius: var(--radius-full);
  margin-bottom: 18px;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}
.success-icon {
  font-size: 16px;
}

.activities {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}
.activity {
  font-size: 13px;
}
.act-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
  background: var(--color-background-secondary);
  padding: 6px 10px;
  border-radius: var(--radius-md);
  border: 1px dashed var(--color-border);
}
.spin {
  color: var(--color-primary);
  animation: spin 1s linear infinite;
}
.big-spin {
  font-size: 28px;
  color: var(--color-primary);
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
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
}
.tool-block pre {
  margin: 0 0 8px;
  padding: 8px 10px;
  background: var(--color-background-tertiary);
  border-radius: var(--radius-sm);
  overflow: auto;
  max-height: 240px;
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

.content-preview {
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
}
.msg-text {
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text);
}
.caret {
  display: inline-block;
  color: var(--color-primary);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to {
    visibility: hidden;
  }
}
.loading-placeholder {
  text-align: center;
  padding: 48px 0;
  color: var(--color-text-secondary);
}
.loading-placeholder p {
  margin: 14px 0 0;
  font-size: 14px;
}

/* —— 底部 —— */
.footer {
  padding: 14px 20px;
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: center;
  gap: 12px;
}
.action-btn {
  min-width: 160px;
  height: 44px;
  font-weight: 600;
  border-radius: var(--radius-lg);
}
.stop-square {
  display: inline-block;
  width: 11px;
  height: 11px;
  background: currentColor;
  border-radius: 2px;
  margin-right: 2px;
}

@media (max-width: 768px) {
  #pptCreatePage {
    padding: 10px;
  }
  .input-card {
    padding: 22px;
  }
}
</style>
