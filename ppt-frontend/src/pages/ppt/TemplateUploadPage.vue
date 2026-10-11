<template>
  <div id="templateUploadPage">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-container">
        <h1 class="page-title">上传模板</h1>
        <p class="page-subtitle">上传含 <code v-pre>{{占位符}}</code> 的 .pptx，AI 创作时仅替换占位符内容、保留版式</p>
      </div>
    </div>

    <div class="container">
      <a-card :bordered="false" class="content-card">
        <!-- 上传成功结果 -->
        <div v-if="uploadResult" class="result-box">
          <div class="result-head">
            <CheckCircleFilled class="result-ico" />
            <h2>模板上传成功</h2>
          </div>
          <a-descriptions :column="1" bordered size="small" class="result-desc">
            <a-descriptions-item label="模板名称">{{ uploadResult.name }}</a-descriptions-item>
            <a-descriptions-item label="页数">{{ uploadResult.slideCount ?? '-' }} 页</a-descriptions-item>
            <a-descriptions-item label="占位符">
              <template v-if="uploadResult.variables && uploadResult.variables.length">
                <a-tag v-for="v in uploadResult.variables" :key="v" class="var-tag">
                  {{ wrapVar(v) }}
                </a-tag>
              </template>
              <span v-else class="muted">未识别到（模板可能不含占位符）</span>
            </a-descriptions-item>
          </a-descriptions>
          <div class="result-actions">
            <a-button type="primary" size="large" @click="useUploaded" class="primary-btn">
              <template #icon><RocketOutlined /></template>
              用此模板创作
            </a-button>
            <a-button size="large" @click="goList">返回模板库</a-button>
            <a-button size="large" type="link" @click="reset">再传一个</a-button>
          </div>
        </div>

        <!-- 上传表单 -->
        <div v-else class="form-box">
          <div class="hint-bar">
            <InfoCircleOutlined class="hint-ico" />
            <span>模板须为 <b>.pptx</b>，且文本中包含 <code v-pre>{{占位符}}</code>（如 <code v-pre>{{title}}</code>、<code v-pre>{{author}}</code>），否则将被拒绝。</span>
          </div>

          <a-form layout="vertical" class="upload-form">
            <a-form-item label="模板文件" required>
              <a-upload-dragger
                :file-list="fileList"
                :before-upload="handleBeforeUpload"
                :multiple="false"
                :max-count="1"
                accept=".pptx"
                @remove="handleRemove"
              >
                <p class="ant-upload-drag-icon"><InboxOutlined /></p>
                <p class="ant-upload-text">点击或拖拽 .pptx 文件到此区域上传</p>
                <p class="ant-upload-hint">仅支持单个 .pptx 文件</p>
              </a-upload-dragger>
            </a-form-item>

            <a-form-item label="模板名称" required>
              <a-input
                v-model:value="name"
                placeholder="例如：季度汇报模板"
                :maxlength="64"
                allow-clear
              />
            </a-form-item>

            <a-form-item label="是否公开">
              <a-switch v-model:checked="isPublic" />
              <span class="switch-tip">{{ isPublic ? '公开：其他用户可见（但仍仅你能用于创作）' : '私有：仅自己可见' }}</span>
            </a-form-item>

            <a-form-item>
              <a-button
                type="primary"
                size="large"
                :loading="uploading"
                :disabled="!canSubmit"
                @click="handleSubmit"
                class="primary-btn"
              >
                上传模板
              </a-button>
              <a-button size="large" @click="goList" class="cancel-btn">取消</a-button>
            </a-form-item>
          </a-form>
        </div>
      </a-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import type { UploadProps } from 'ant-design-vue'
import {
  InboxOutlined,
  RocketOutlined,
  CheckCircleFilled,
  InfoCircleOutlined,
} from '@ant-design/icons-vue'
import { uploadTemplate } from '@/api/templateController'
import { useLoginUserStore } from '@/stores/loginUser'

const router = useRouter()
const loginUserStore = useLoginUserStore()

const name = ref('')
const isPublic = ref(false)
const uploading = ref(false)
const selectedFile = ref<File | null>(null)
const fileList = ref<UploadProps['fileList']>([])
const uploadResult = ref<API.TemplateRecord | null>(null)

const canSubmit = computed(() => !!selectedFile.value && name.value.trim().length > 0)

// 包裹占位符名用于展示（避免在模板插值里直接写 }} 字面量，Vue tokenizer 会误判插值结束）
const wrapVar = (v: string) => `{{${v}}}`

// before-upload 返回 false 阻止 antd 自动上传，仅保存所选文件
const handleBeforeUpload: UploadProps['beforeUpload'] = (file) => {
  selectedFile.value = file
  fileList.value = [
    {
      uid: file.uid,
      name: file.name,
      status: 'done',
      size: file.size,
      type: file.type,
    },
  ]
  return false
}

const handleRemove: UploadProps['onRemove'] = () => {
  selectedFile.value = null
  fileList.value = []
  return true
}

const handleSubmit = async () => {
  if (!selectedFile.value) {
    message.warning('请选择 .pptx 模板文件')
    return
  }
  if (!name.value.trim()) {
    message.warning('请输入模板名称')
    return
  }
  uploading.value = true
  try {
    const res = await uploadTemplate(selectedFile.value, name.value.trim(), isPublic.value)
    if (res.data.code === 0 && res.data.data) {
      message.success('模板上传成功')
      uploadResult.value = res.data.data
    } else if (res.data.code === 40100) {
      // 拦截器已弹「请先登录」，这里补跳转
      router.push(`/user/login?redirect=${encodeURIComponent('/ppt/template/upload')}`)
    } else {
      // 40000：非 .pptx / 无占位符 / 解析失败 等，展示后端 message
      message.error(res.data.message || '上传失败')
    }
  } catch (e) {
    message.error('上传失败：' + (e as Error).message)
  } finally {
    uploading.value = false
  }
}

const reset = () => {
  uploadResult.value = null
  selectedFile.value = null
  fileList.value = []
  name.value = ''
  isPublic.value = false
}

const useUploaded = () => {
  if (!uploadResult.value) return
  router.push({
    path: '/create',
    query: { templateId: String(uploadResult.value.id), templateName: uploadResult.value.name },
  })
}

const goList = () => {
  router.push('/ppt/template/list')
}

onMounted(() => {
  if (!loginUserStore.loginUser.id) {
    router.replace(`/user/login?redirect=${encodeURIComponent('/ppt/template/upload')}`)
  }
})
</script>

<style scoped>
#templateUploadPage {
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
  max-width: 760px;
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
  padding: 32px;
}

.hint-bar {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  margin-bottom: 24px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}
.hint-ico {
  color: var(--color-info);
  font-size: 16px;
  margin-top: 2px;
}
.hint-bar code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: var(--color-background-tertiary);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--color-primary-dark);
}

.upload-form :deep(.ant-form-item-label > label) {
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text);
}
.upload-form :deep(.ant-upload-dragger) {
  border-radius: var(--radius-md);
}
.ant-upload-drag-icon {
  color: var(--color-primary);
  font-size: 44px;
  margin: 0 0 8px;
}
.ant-upload-text {
  font-size: 14px;
  color: var(--color-text);
  margin: 0 0 4px;
}
.ant-upload-hint {
  font-size: 12px;
  color: var(--color-text-muted);
}
.switch-tip {
  margin-left: 12px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.primary-btn {
  border-radius: var(--radius-md);
  font-weight: 600;
  background: var(--gradient-primary) !important;
  border: none !important;
  color: #fff !important;
  box-shadow: var(--shadow-primary) !important;
  margin-right: 12px;
}
.cancel-btn {
  border-radius: var(--radius-md);
}

.result-box {
  text-align: left;
}
.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}
.result-ico {
  font-size: 28px;
  color: var(--color-success);
}
.result-head h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
}
.result-desc {
  margin-bottom: 24px;
}
.var-tag {
  margin: 2px 4px 2px 0;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.result-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.result-actions .primary-btn {
  margin-right: 12px;
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
  .content-card :deep(.ant-card-body) {
    padding: 20px;
  }
}
</style>
