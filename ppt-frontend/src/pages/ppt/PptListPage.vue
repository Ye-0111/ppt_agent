<template>
  <div id="pptListPage">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-container">
        <h1 class="page-title">我的 PPT</h1>
        <p class="page-subtitle">查看历史创作任务，未完成的可继续生成</p>
      </div>
    </div>

    <div class="container">
      <a-card :bordered="false" class="content-card">
        <!-- 搜索 -->
        <div class="search-section">
          <a-form layout="inline" class="search-form">
            <a-form-item label="状态">
              <a-select
                v-model:value="searchParams.status"
                placeholder="全部状态"
                allow-clear
                class="search-select"
                @change="doSearch"
              >
                <a-select-option v-for="o in statusOptions" :key="o.value" :value="o.value">
                  {{ o.label }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item>
              <a-button type="primary" @click="doSearch" class="search-btn">查询</a-button>
            </a-form-item>
            <a-form-item>
              <a-button @click="doReset">重置</a-button>
            </a-form-item>
          </a-form>
        </div>

        <a-divider />

        <!-- 表格 -->
        <a-table
          :columns="columns"
          :data-source="data"
          :loading="loading"
          :pagination="pagination"
          row-key="id"
          @change="doTableChange"
          class="ppt-table"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.dataIndex === 'topic'">
              <span class="topic-cell" :title="record.topic">{{ record.topic || '(无主题)' }}</span>
            </template>
            <template v-else-if="column.dataIndex === 'style'">
              {{ STYLE_LABELS[record.style] ?? record.style ?? '-' }}
            </template>
            <template v-else-if="column.dataIndex === 'status'">
              <a-tag :color="STATUS_COLOR[record.status as API.PptRecordStatus]" class="status-tag">
                {{ STATUS_LABEL[record.status as API.PptRecordStatus] ?? record.status }}
              </a-tag>
            </template>
            <template v-else-if="column.dataIndex === 'stage'">
              {{ STAGE_LABELS[record.stage as API.PptRecordStage] ?? record.stage }}
            </template>
            <template v-else-if="column.dataIndex === 'updateTime'">
              <span class="time-text">{{ formatTime(record.updateTime) }}</span>
            </template>
            <template v-else-if="column.key === 'action'">
              <template v-if="record.status === 'SUCCESS'">
                <a-button type="link" @click="onDownload(record)" class="op-btn">下载</a-button>
                <a-button type="link" @click="openDetail(record)" class="op-btn">详情</a-button>
              </template>
              <template v-else-if="record.status === 'IN_PROGRESS'">
                <a-button type="link" @click="goResume(record)" class="op-btn">继续生成</a-button>
                <a-button type="link" @click="openDetail(record)" class="op-btn">详情</a-button>
              </template>
              <template v-else>
                <a-button type="link" @click="openDetail(record)" class="op-btn">详情</a-button>
                <a-button type="link" @click="recreate(record)" class="op-btn">重新创建</a-button>
              </template>
            </template>
          </template>
        </a-table>
      </a-card>
    </div>

    <!-- 详情弹窗 -->
    <a-modal
      v-model:open="detailVisible"
      title="任务详情"
      :footer="null"
      width="720px"
      :body-style="{ maxHeight: '70vh', overflowY: 'auto' }"
      class="detail-modal"
    >
      <a-spin :spinning="detailLoading">
        <a-descriptions v-if="detailData" :column="2" bordered size="small">
          <a-descriptions-item label="任务 ID" :span="1">{{ detailData.id }}</a-descriptions-item>
          <a-descriptions-item label="状态" :span="1">
            <a-tag :color="STATUS_COLOR[detailData.status]">
              {{ STATUS_LABEL[detailData.status] ?? detailData.status }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="主题" :span="2">
            <span class="detail-topic">{{ detailData.topic || '(无主题)' }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="风格" :span="1">
            {{ STYLE_LABELS[detailData.style] ?? detailData.style ?? '-' }}
          </a-descriptions-item>
          <a-descriptions-item label="当前进度" :span="1">
            {{ STAGE_LABELS[detailData.stage] ?? detailData.stage }}
          </a-descriptions-item>
          <a-descriptions-item label="文件名" :span="2">
            <span v-if="detailData.filename" class="detail-filename">{{ detailData.filename }}</span>
            <span v-else class="muted">尚未生成</span>
          </a-descriptions-item>
          <a-descriptions-item label="创建时间" :span="1">
            {{ formatTime(detailData.createTime) }}
          </a-descriptions-item>
          <a-descriptions-item label="更新时间" :span="1">
            {{ formatTime(detailData.updateTime) }}
          </a-descriptions-item>
          <a-descriptions-item v-if="detailData.errorMessage" label="错误信息" :span="2">
            <span class="error-text">{{ detailData.errorMessage }}</span>
          </a-descriptions-item>
        </a-descriptions>
        <div v-else-if="!detailLoading" class="muted">暂无数据</div>
      </a-spin>

      <!-- 执行日志（详情加载后才拉取，静默降级，不阻塞上方描述） -->
      <template v-if="detailData">
        <a-divider orientation="left" class="log-divider">执行日志</a-divider>
        <a-spin :spinning="agentLogLoading">
          <div v-if="agentLogError" class="muted">{{ agentLogError }}</div>
          <div v-else-if="agentLogStats && agentLogStats.logs.length" class="agent-log-section">
            <div class="log-summary">
              <span>总耗时 <b>{{ formatDuration(agentLogStats.totalDurationMs) }}</b></span>
              <span class="log-sep">·</span>
              <span>智能体 <b>{{ agentLogStats.agentCount }}</b></span>
              <span class="log-sep">·</span>
              <span>整体状态
                <a-tag
                  :color="LOG_STATUS_COLOR[agentLogStats.overallStatus] ?? 'default'"
                  class="log-status-tag"
                >
                  {{ LOG_STATUS_LABEL[agentLogStats.overallStatus] ?? agentLogStats.overallStatus }}
                </a-tag>
              </span>
            </div>
            <a-collapse :bordered="false" class="log-collapse">
              <a-collapse-panel v-for="log in agentLogStats.logs" :key="log.id">
                <template #header>
                  <div class="log-panel-head">
                    <span class="log-agent-name">
                      {{ AGENT_LABELS[log.agentName] ?? log.agentName }}
                    </span>
                    <a-tag :color="LOG_STATUS_COLOR[log.status] ?? 'default'" class="log-status-tag">
                      {{ LOG_STATUS_LABEL[log.status] ?? log.status }}
                    </a-tag>
                    <span class="log-duration">{{ formatDuration(log.durationMs) }}</span>
                    <span class="log-time">{{ formatTime(log.startTime) }}</span>
                  </div>
                </template>
                <div v-if="log.errorMessage" class="log-field">
                  <div class="log-field-label">错误信息</div>
                  <pre class="log-pre log-pre-error">{{ log.errorMessage }}</pre>
                </div>
                <div v-if="log.prompt" class="log-field">
                  <div class="log-field-label">Prompt</div>
                  <pre class="log-pre">{{ log.prompt }}</pre>
                </div>
                <div v-if="prettyJson(log.inputData)" class="log-field">
                  <div class="log-field-label">输入数据</div>
                  <pre class="log-pre">{{ prettyJson(log.inputData) }}</pre>
                </div>
                <div v-if="prettyJson(log.outputData)" class="log-field">
                  <div class="log-field-label">输出数据</div>
                  <pre class="log-pre">{{ prettyJson(log.outputData) }}</pre>
                </div>
              </a-collapse-panel>
            </a-collapse>
          </div>
          <div v-else-if="!agentLogLoading" class="muted">暂无执行日志</div>
        </a-spin>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import { listPpts, getPptDetail, getAgentLog, downloadPpt } from '@/api/pptController'
import { useLoginUserStore } from '@/stores/loginUser'

const router = useRouter()
const loginUserStore = useLoginUserStore()

const columns = [
  { title: '主题', dataIndex: 'topic' },
  { title: '风格', dataIndex: 'style', width: 90 },
  { title: '状态', dataIndex: 'status', width: 100 },
  { title: '进度', dataIndex: 'stage', width: 120 },
  { title: '更新时间', dataIndex: 'updateTime', width: 170 },
  { title: '操作', key: 'action', width: 210 },
]

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
const STATUS_LABEL: Record<API.PptRecordStatus, string> = {
  SUCCESS: '已完成',
  IN_PROGRESS: '进行中',
  FAILED: '生成失败',
}
const STATUS_COLOR: Record<API.PptRecordStatus, string> = {
  SUCCESS: 'success',
  IN_PROGRESS: 'processing',
  FAILED: 'error',
}

/** specialist 角色名 → 中文标签（对齐后端 graph.py 的 outline/research/content/image/chart/beautify） */
const AGENT_LABELS: Record<string, string> = {
  outline: '大纲规划',
  research: '素材调研',
  content: '内容生成',
  image: '配图',
  chart: '图表',
  beautify: '美化',
}
/** 执行日志状态标签/颜色（含整体状态 NOT_FOUND） */
const LOG_STATUS_LABEL: Record<string, string> = {
  SUCCESS: '成功',
  RUNNING: '进行中',
  FAILED: '失败',
  NOT_FOUND: '无日志',
}
const LOG_STATUS_COLOR: Record<string, string> = {
  SUCCESS: 'success',
  RUNNING: 'processing',
  FAILED: 'error',
  NOT_FOUND: 'default',
}

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'SUCCESS', label: '已完成' },
  { value: 'IN_PROGRESS', label: '进行中' },
  { value: 'FAILED', label: '生成失败' },
]

const data = ref<API.PptRecord[]>([])
const total = ref(0)
const loading = ref(false)

const searchParams = reactive({
  current: 1,
  pageSize: 10,
  status: '' as '' | API.PptRecordStatus,
})

const fetchData = async () => {
  loading.value = true
  try {
    const res = await listPpts({
      current: searchParams.current,
      pageSize: searchParams.pageSize,
      status: searchParams.status || undefined,
    })
    if (res.data.code === 0 && res.data.data) {
      data.value = res.data.data.records ?? []
      total.value = res.data.data.total ?? 0
    } else {
      message.error('获取列表失败：' + res.data.message)
    }
  } catch (e) {
    message.error('获取列表失败：' + (e as Error).message)
  } finally {
    loading.value = false
  }
}

const pagination = computed(() => ({
  current: searchParams.current,
  pageSize: searchParams.pageSize,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t: number) => `共 ${t} 条`,
}))

const doTableChange = (page: { current: number; pageSize: number }) => {
  searchParams.current = page.current
  searchParams.pageSize = page.pageSize
  fetchData()
}

const doSearch = () => {
  searchParams.current = 1
  fetchData()
}

const doReset = () => {
  searchParams.status = ''
  searchParams.current = 1
  fetchData()
}

const formatTime = (t?: string) => {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm')
}

/** 毫秒 → 友好耗时：null→'-'，<1s 显示 ms，否则秒（1 位小数） */
const formatDuration = (ms?: number | null) => {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/** 美化 JSON 字符串；解析失败回退原文，空值返回空串（配合 v-if 不渲染空块） */
const prettyJson = (s?: string | null) => {
  if (!s) return ''
  try {
    return JSON.stringify(JSON.parse(s), null, 2)
  } catch {
    return s
  }
}

// —— 行操作 ——
const onDownload = async (record: API.PptRecord) => {
  if (!record.filename) {
    message.warning('该任务暂无可下载的文件')
    return
  }
  try {
    await downloadPpt(record.filename)
  } catch (e) {
    message.error((e as Error).message || '下载失败')
  }
}

const goResume = (record: API.PptRecord) => {
  router.push(`/create?resume=${record.id}`)
}

const recreate = (record: API.PptRecord) => {
  router.push({ path: '/create', query: { topic: record.topic } })
}

// —— 详情弹窗 ——
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailData = ref<API.PptDetail | null>(null)

// 执行日志（详情打开时并行拉取，静默降级：失败只显文案，不阻塞详情、不弹 message）
const agentLogStats = ref<API.AgentExecutionStats | null>(null)
const agentLogLoading = ref(false)
const agentLogError = ref<string | null>(null)

const openDetail = async (record: API.PptRecord) => {
  detailVisible.value = true
  detailLoading.value = true
  detailData.value = null
  agentLogStats.value = null
  agentLogError.value = null
  agentLogLoading.value = true

  const [detailRes, logRes] = await Promise.allSettled([
    getPptDetail(record.id),
    getAgentLog(record.id),
  ])

  // 详情（主，沿用原逻辑）
  if (detailRes.status === 'fulfilled') {
    const res = detailRes.value
    if (res.data.code === 0 && res.data.data) {
      detailData.value = res.data.data
    } else {
      message.error(res.data.message || '加载详情失败')
    }
  } else {
    message.error('加载详情失败：' + (detailRes.reason as Error)?.message)
  }
  detailLoading.value = false

  // 执行日志（辅，静默降级）
  if (logRes.status === 'fulfilled') {
    const res = logRes.value
    if (res.data.code === 0 && res.data.data) {
      agentLogStats.value = res.data.data
    } else {
      agentLogError.value = res.data.message || '执行日志加载失败'
    }
  } else {
    agentLogError.value = '执行日志加载失败'
  }
  agentLogLoading.value = false
}

onMounted(() => {
  if (!loginUserStore.loginUser.id) {
    router.replace(`/user/login?redirect=${encodeURIComponent('/ppt/list')}`)
    return
  }
  fetchData()
})
</script>

<style scoped>
#pptListPage {
  background: var(--color-background-secondary);
  min-height: calc(100vh - 134px);
  padding-bottom: 40px;
}

.page-header {
  background: var(--gradient-hero);
  padding: 32px 20px;
  margin-bottom: 24px;
}
.header-container {
  max-width: 1200px;
  margin: 0 auto;
}
.page-title {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 6px;
  letter-spacing: -0.5px;
  color: var(--color-text);
}
.page-subtitle {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}

.content-card {
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  box-shadow: none;
  background: #fff;
}
.content-card :deep(.ant-card-body) {
  padding: 24px;
}

.search-section {
  margin-bottom: 8px;
}
.search-form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.search-form :deep(.ant-form-item) {
  margin-bottom: 0;
}
.search-form :deep(.ant-form-item-label > label) {
  font-weight: 500;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.search-select {
  width: 180px;
  border-radius: var(--radius-md);
}
.search-btn {
  border-radius: var(--radius-md);
  font-weight: 500;
  background: var(--gradient-primary) !important;
  border: none !important;
  color: #fff !important;
  box-shadow: var(--shadow-primary) !important;
}

.ppt-table :deep(.ant-table-thead > tr > th) {
  background: var(--color-background-secondary);
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  padding: 14px 16px;
}
.ppt-table :deep(.ant-table-tbody > tr > td) {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border-light);
  vertical-align: middle;
}
.ppt-table :deep(.ant-table-tbody > tr:hover > td) {
  background: rgba(79, 70, 229, 0.02);
}

.topic-cell {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  line-height: 1.5;
  color: var(--color-text);
  word-break: break-word;
}
.status-tag {
  border-radius: var(--radius-full);
  font-weight: 500;
  font-size: 12px;
  padding: 2px 10px;
}
.time-text {
  color: var(--color-text-secondary);
  font-size: 13px;
  white-space: nowrap;
}
.op-btn {
  padding: 2px 6px;
  font-weight: 500;
  font-size: 13px;
  margin-left: 0;
}

.detail-topic {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}
.detail-filename {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--color-text-secondary);
}
.muted {
  color: var(--color-text-muted);
  font-size: 13px;
}
.error-text {
  color: var(--color-error);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

/* 执行日志区块 */
.log-divider {
  margin: 20px 0 12px;
}
.log-divider :deep(.ant-divider-inner-text) {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.agent-log-section {
  margin-top: 4px;
}
.log-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 12px;
}
.log-summary b {
  color: var(--color-text);
  font-weight: 600;
}
.log-sep {
  color: var(--color-text-muted);
}
.log-status-tag {
  margin-left: 4px;
  border-radius: var(--radius-full);
  font-size: 12px;
  padding: 0 8px;
  line-height: 18px;
}
.log-collapse {
  background: transparent;
}
.log-collapse :deep(.ant-collapse-item) {
  border-bottom: 1px solid var(--color-border-light);
}
.log-collapse :deep(.ant-collapse-item:last-child) {
  border-bottom: none;
}
.log-collapse :deep(.ant-collapse-header) {
  padding: 10px 0 !important;
  align-items: center;
}
.log-collapse :deep(.ant-collapse-content-box) {
  padding: 4px 0 12px !important;
}
.log-panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.log-agent-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text);
}
.log-duration {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}
.log-time {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-left: auto;
}
.log-field {
  margin-bottom: 10px;
}
.log-field:last-child {
  margin-bottom: 0;
}
.log-field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.log-pre {
  margin: 0;
  padding: 10px 12px;
  background: var(--color-background-secondary);
  border-radius: var(--radius-md);
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}
.log-pre-error {
  color: var(--color-error);
  background: rgba(255, 77, 79, 0.06);
}

@media (max-width: 768px) {
  .page-header {
    padding: 24px 20px;
  }
  .page-title {
    font-size: 22px;
  }
  .search-select {
    width: 100%;
  }
}
</style>
