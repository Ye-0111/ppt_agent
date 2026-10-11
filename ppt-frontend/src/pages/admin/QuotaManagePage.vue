<template>
  <div id="quotaManagePage">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-container">
        <h1 class="page-title">配额管理</h1>
        <p class="page-subtitle">管理各用户的 PPT 创作配额</p>
      </div>
    </div>

    <div class="container">
      <a-card :bordered="false" class="content-card">
        <!-- 搜索 -->
        <div class="search-section">
          <a-form layout="inline" class="search-form">
            <a-form-item label="用户名">
              <a-input
                v-model:value="searchParams.username"
                placeholder="输入用户名"
                allow-clear
                class="search-input"
                @pressEnter="doSearch"
              />
            </a-form-item>
            <a-form-item>
              <a-button type="primary" @click="doSearch" class="search-btn">搜索</a-button>
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
          class="quota-table"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.dataIndex === 'userRole'">
              <a-tag v-if="record.userRole === 'admin'" color="purple" class="role-tag">管理员</a-tag>
              <a-tag v-else color="blue" class="role-tag">普通用户</a-tag>
            </template>
            <template v-else-if="column.dataIndex === 'pptQuota'">
              <span :class="['quota-num', { zero: record.pptQuota <= 0 }]">{{ record.pptQuota }}</span>
            </template>
            <template v-else-if="column.dataIndex === 'createTime'">
              <span class="time-text">{{ formatTime(record.createTime) }}</span>
            </template>
            <template v-else-if="column.key === 'action'">
              <a-button type="link" @click="openEdit(record)" class="edit-btn">修改配额</a-button>
            </template>
          </template>
        </a-table>
      </a-card>
    </div>

    <!-- 修改配额弹窗 -->
    <a-modal
      v-model:open="editVisible"
      title="修改配额"
      :confirm-loading="editLoading"
      ok-text="保存"
      cancel-text="取消"
      @ok="doEdit"
    >
      <a-form layout="vertical">
        <a-form-item label="用户">
          <a-input :value="editForm.username" disabled />
        </a-form-item>
        <a-form-item label="PPT 创作配额">
          <a-input-number
            v-model:value="editForm.pptQuota"
            :min="0"
            :max="100000"
            precision="0"
            style="width: 100%"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import { setUserQuota, listUserQuotaPage } from '@/api/userController'
import { useLoginUserStore } from '@/stores/loginUser'
import { USER_ROLE_ADMIN } from '@/constants/user'

const router = useRouter()
const loginUserStore = useLoginUserStore()

const columns = [
  { title: 'ID', dataIndex: 'id', width: 72 },
  { title: '用户名', dataIndex: 'username' },
  { title: '昵称', dataIndex: 'nickname' },
  { title: '角色', dataIndex: 'userRole', width: 110 },
  { title: '配额', dataIndex: 'pptQuota', width: 100 },
  { title: '创建时间', dataIndex: 'createTime' },
  { title: '操作', key: 'action', width: 120 },
]

const data = ref<API.QuotaRecord[]>([])
const total = ref(0)
const loading = ref(false)

const searchParams = reactive({
  current: 1,
  pageSize: 10,
  username: '',
})

const fetchData = async () => {
  loading.value = true
  try {
    const res = await listUserQuotaPage({
      current: searchParams.current,
      pageSize: searchParams.pageSize,
      username: searchParams.username.trim() || undefined,
    })
    if (res.data.code === 0 && res.data.data) {
      data.value = res.data.data.records ?? []
      total.value = res.data.data.total ?? 0
    } else {
      message.error('获取数据失败：' + res.data.message)
    }
  } catch (e) {
    message.error('获取数据失败：' + (e as Error).message)
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
  searchParams.username = ''
  searchParams.current = 1
  fetchData()
}

const formatTime = (t?: string) => {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

// —— 修改配额 ——
const editVisible = ref(false)
const editLoading = ref(false)
const editForm = reactive({ userId: 0, username: '', pptQuota: 0 })

const openEdit = (record: API.QuotaRecord) => {
  editForm.userId = record.id
  editForm.username = record.username
  editForm.pptQuota = record.pptQuota
  editVisible.value = true
}

const doEdit = async () => {
  if (editForm.pptQuota < 0) {
    message.warning('配额不能为负')
    return
  }
  editLoading.value = true
  try {
    const res = await setUserQuota({ userId: editForm.userId, pptQuota: editForm.pptQuota })
    if (res.data.code === 0) {
      message.success('配额已更新')
      editVisible.value = false
      fetchData()
    } else {
      message.error('更新失败：' + res.data.message)
    }
  } catch (e) {
    message.error('更新失败：' + (e as Error).message)
  } finally {
    editLoading.value = false
  }
}

onMounted(() => {
  if (loginUserStore.loginUser.userRole !== USER_ROLE_ADMIN) {
    message.error('需要管理员权限')
    router.replace('/')
    return
  }
  fetchData()
})
</script>

<style scoped>
#quotaManagePage {
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
.search-btn {
  border-radius: var(--radius-md);
  font-weight: 500;
  background: var(--gradient-primary) !important;
  border: none !important;
  color: #fff !important;
  box-shadow: var(--shadow-primary) !important;
}

.quota-table :deep(.ant-table-thead > tr > th) {
  background: var(--color-background-secondary);
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  padding: 14px 16px;
}
.quota-table :deep(.ant-table-tbody > tr > td) {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border-light);
}
.quota-table :deep(.ant-table-tbody > tr:hover > td) {
  background: rgba(79, 70, 229, 0.02);
}

.role-tag {
  border-radius: var(--radius-full);
  font-weight: 500;
  font-size: 12px;
  padding: 2px 10px;
}
.quota-num {
  font-weight: 700;
  font-size: 15px;
  color: var(--color-primary);
}
.quota-num.zero {
  color: var(--color-error);
}
.time-text {
  color: var(--color-text-secondary);
  font-size: 13px;
}
.edit-btn {
  padding: 4px 8px;
  font-weight: 500;
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
}
</style>
