<template>
  <div id="templateListPage">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-container">
        <h1 class="page-title">模板库</h1>
        <p class="page-subtitle">上传含 <code v-pre>{{占位符}}</code> 的 .pptx 模板，选用自己的模板一键生成 PPT</p>
      </div>
    </div>

    <div class="container">
      <a-card :bordered="false" class="content-card">
        <!-- 搜索 -->
        <div class="search-section">
          <a-form layout="inline" class="search-form">
            <a-form-item label="范围">
              <a-radio-group
                v-model:value="searchParams.scope"
                button-style="solid"
                @change="doSearch"
              >
                <a-radio-button v-for="o in scopeOptions" :key="o.value" :value="o.value">
                  {{ o.label }}
                </a-radio-button>
              </a-radio-group>
            </a-form-item>
            <a-form-item label="名称">
              <a-input
                v-model:value="keyword"
                placeholder="按名称筛选"
                allow-clear
                class="search-input"
              />
            </a-form-item>
            <a-form-item>
              <a-button @click="doReset">重置</a-button>
            </a-form-item>
            <a-form-item class="upload-btn-wrap">
              <a-button type="primary" @click="goUpload" class="upload-btn">
                <template #icon><UploadOutlined /></template>
                上传模板
              </a-button>
            </a-form-item>
          </a-form>
        </div>

        <a-divider />

        <!-- 表格 -->
        <a-table
          :columns="columns"
          :data-source="filteredData"
          :loading="loading"
          :pagination="pagination"
          row-key="id"
          @change="doTableChange"
          class="tpl-table"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.dataIndex === 'name'">
              <span class="name-cell" :title="record.name">{{ record.name }}</span>
            </template>
            <template v-else-if="column.dataIndex === 'slideCount'">
              {{ record.slideCount ?? '-' }} 页
            </template>
            <template v-else-if="column.dataIndex === 'variables'">
              <template v-if="record.variables && record.variables.length">
                <a-tag v-for="v in record.variables" :key="v" class="var-tag">
                  {{ wrapVar(v) }}
                </a-tag>
              </template>
              <span v-else class="muted">-</span>
            </template>
            <template v-else-if="column.dataIndex === 'isPublic'">
              <a-tag :color="record.isPublic ? 'green' : 'default'" class="vis-tag">
                {{ record.isPublic ? '公开' : '私有' }}
              </a-tag>
            </template>
            <template v-else-if="column.dataIndex === 'createTime'">
              <span class="time-text">{{ formatTime(record.createTime) }}</span>
            </template>
            <template v-else-if="column.key === 'action'">
              <template v-if="isOwner(record)">
                <a-button type="link" @click="useTemplate(record)" class="op-btn">用此模板创作</a-button>
                <a-popconfirm title="确定删除该模板？删除后不可恢复。" @confirm="onDelete(record)">
                  <a-button type="link" danger class="op-btn">删除</a-button>
                </a-popconfirm>
              </template>
              <span v-else class="muted">仅上传者可用于创作</span>
            </template>
          </template>
        </a-table>
      </a-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UploadOutlined } from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { listTemplates, deleteTemplate } from '@/api/templateController'
import { useLoginUserStore } from '@/stores/loginUser'

const router = useRouter()
const loginUserStore = useLoginUserStore()

const columns = [
  { title: '模板名称', dataIndex: 'name' },
  { title: '页数', dataIndex: 'slideCount', width: 90 },
  { title: '占位符', dataIndex: 'variables' },
  { title: '可见性', dataIndex: 'isPublic', width: 90 },
  { title: '创建时间', dataIndex: 'createTime', width: 170 },
  { title: '操作', key: 'action', width: 220 },
]

const scopeOptions: { value: API.TemplateScope; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'mine', label: '我的' },
  { value: 'public', label: '公开' },
]

const data = ref<API.TemplateRecord[]>([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')

const searchParams = reactive({
  current: 1,
  pageSize: 10,
  scope: 'all' as API.TemplateScope,
})

const fetchData = async () => {
  loading.value = true
  try {
    const res = await listTemplates({
      current: searchParams.current,
      pageSize: searchParams.pageSize,
      scope: searchParams.scope,
    })
    if (res.data.code === 0 && res.data.data) {
      data.value = res.data.data.records ?? []
      total.value = res.data.data.total ?? 0
    } else {
      message.error('获取模板列表失败：' + res.data.message)
    }
  } catch (e) {
    message.error('获取模板列表失败：' + (e as Error).message)
  } finally {
    loading.value = false
  }
}

// 名称筛选为前端过滤（后端无该参数）；分页 total 仍按服务端
const filteredData = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return data.value
  return data.value.filter((r) => r.name.toLowerCase().includes(kw))
})

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
  searchParams.scope = 'all'
  keyword.value = ''
  searchParams.current = 1
  fetchData()
}

const formatTime = (t?: string) => {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm')
}

// 包裹占位符名用于展示（避免在模板插值里直接写 }} 字面量，Vue tokenizer 会误判插值结束）
const wrapVar = (v: string) => `{{${v}}}`

// 是否当前用户上传的模板（仅 owner 能用于创作 / 删除）
const isOwner = (record: API.TemplateRecord) =>
  loginUserStore.loginUser.id != null && record.userId === loginUserStore.loginUser.id

// —— 行操作 ——
const useTemplate = (record: API.TemplateRecord) => {
  router.push({
    path: '/create',
    query: { templateId: String(record.id), templateName: record.name },
  })
}

const onDelete = async (record: API.TemplateRecord) => {
  try {
    const res = await deleteTemplate(record.id)
    if (res.data.code === 0) {
      message.success('模板已删除')
      fetchData()
    } else {
      message.error(res.data.message || '删除失败')
    }
  } catch (e) {
    message.error('删除失败：' + (e as Error).message)
  }
}

const goUpload = () => {
  router.push('/ppt/template/upload')
}

onMounted(() => {
  if (!loginUserStore.loginUser.id) {
    router.replace(`/user/login?redirect=${encodeURIComponent('/ppt/template/list')}`)
    return
  }
  fetchData()
})
</script>

<style scoped>
#templateListPage {
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
.search-input {
  width: 200px;
  border-radius: var(--radius-md);
}
.upload-btn-wrap {
  margin-left: auto;
}
.upload-btn {
  border-radius: var(--radius-md);
  font-weight: 500;
  background: var(--gradient-primary) !important;
  border: none !important;
  color: #fff !important;
  box-shadow: var(--shadow-primary) !important;
}

.tpl-table :deep(.ant-table-thead > tr > th) {
  background: var(--color-background-secondary);
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  padding: 14px 16px;
}
.tpl-table :deep(.ant-table-tbody > tr > td) {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border-light);
  vertical-align: middle;
}
.tpl-table :deep(.ant-table-tbody > tr:hover > td) {
  background: rgba(79, 70, 229, 0.02);
}

.name-cell {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
  line-height: 1.5;
  word-break: break-word;
}
.var-tag {
  margin: 2px 4px 2px 0;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.vis-tag {
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
.muted {
  color: var(--color-text-muted);
  font-size: 13px;
}

@media (max-width: 768px) {
  .page-header {
    padding: 24px 20px;
  }
  .page-title {
    font-size: 22px;
  }
  .search-input {
    width: 100%;
  }
  .upload-btn-wrap {
    margin-left: 0;
  }
}
</style>
