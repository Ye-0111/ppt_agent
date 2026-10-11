<template>
  <div class="outline-review-stage">
    <div class="stage-header">
      <h2 class="stage-title">编辑幻灯片大纲</h2>
      <p class="stage-subtitle">AI 已生成大纲并暂停，你可以修改每页标题与用途、增删幻灯片，确认后将继续生成正文</p>
    </div>

    <div class="page-list">
      <div v-for="(page, index) in pages" :key="index" class="page-card">
        <div class="page-head">
          <span class="page-no">{{ index + 1 }}</span>
          <a-input
            v-model:value="page.title"
            placeholder="幻灯片标题（必填）"
            class="title-input"
            :maxlength="100"
          />
          <a-button type="text" danger class="del-btn" @click="deletePage(index)">
            <template #icon><DeleteOutlined /></template>
          </a-button>
        </div>
        <div class="page-purpose">
          <a-textarea
            v-model:value="page.purpose"
            placeholder="本页用途 / 要点描述（可选）"
            :rows="2"
            :maxlength="300"
          />
        </div>
      </div>
    </div>

    <a-button class="add-btn" @click="addPage">
      <template #icon><PlusOutlined /></template>
      添加幻灯片
    </a-button>

    <div class="actions">
      <a-button size="large" :disabled="loading" @click="emit('cancel')">放弃</a-button>
      <a-button
        type="primary"
        size="large"
        :loading="loading"
        :disabled="!canConfirm"
        class="confirm-btn"
        @click="handleConfirm"
      >
        <template #icon><CheckOutlined /></template>
        确认并生成内容
      </a-button>
    </div>
    <p v-if="!canConfirm" class="hint">每页需填写标题后才能继续</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { CheckOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons-vue'

/**
 * 大纲人工审阅编辑器（最简版）。
 *
 * 后端 OUTLINE_REVIEW 事件携带 outline（JSON 字符串，解析后为 API.OutlinePage[]）。
 * 本组件仅暴露 标题 / 用途 的编辑与增删页；layout_hint 不在 UI 暴露但随页对象原样保留，
 * 确认时连同编辑结果一并回传给父级，由其 POST /ppt/create/resume 续跑。
 * 不引入排序/拖拽与 AI 修改（新后端无对应接口）。
 */
interface Props {
  outline: API.OutlinePage[]
  /** 确认按钮 loading（续跑流式中） */
  loading?: boolean
}
interface Emits {
  (e: 'confirm', outline: API.OutlinePage[]): void
  (e: 'cancel'): void
}

const props = withDefaults(defineProps<Props>(), { loading: false })
const emit = defineEmits<Emits>()

// 深拷贝 + 字段规范化（purpose 落地成串，避免 a-textarea 绑定 undefined）
const pages = ref<API.OutlinePage[]>(
  (props.outline ?? []).map((p) => ({
    title: p.title ?? '',
    layout_hint: p.layout_hint ?? 'content',
    purpose: p.purpose ?? '',
  })),
)

// 至少一页且每页标题非空（对齐后端 normalize_outline：空标题页会被丢弃，全空则拒绝）
const canConfirm = computed(
  () => pages.value.length > 0 && pages.value.every((p) => p.title.trim() !== ''),
)

const addPage = () => {
  pages.value.push({ title: '', layout_hint: 'content', purpose: '' })
}

const deletePage = (index: number) => {
  pages.value.splice(index, 1)
}

const handleConfirm = () => {
  emit(
    'confirm',
    pages.value.map((p) => ({
      title: p.title.trim(),
      layout_hint: p.layout_hint,
      purpose: (p.purpose ?? '').trim(),
    })),
  )
}
</script>

<style scoped>
.outline-review-stage {
  max-width: 720px;
  margin: 0 auto;
}

.stage-header {
  text-align: center;
  margin-bottom: 24px;
}
.stage-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 8px;
  color: var(--color-text);
}
.stage-subtitle {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin: 0;
  line-height: 1.6;
}

.page-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 16px;
}

.page-card {
  background: var(--color-background-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 16px;
  transition: border-color var(--transition-fast);
}
.page-card:hover {
  border-color: var(--color-primary);
}

.page-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.page-no {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--gradient-primary);
  color: #fff;
  font-weight: 600;
  font-size: 13px;
}
.title-input {
  flex: 1;
  font-size: 15px;
  font-weight: 600;
}
.del-btn {
  flex-shrink: 0;
}

.page-purpose :deep(textarea) {
  font-size: 13px;
  border-radius: var(--radius-md);
}

.add-btn {
  width: 100%;
  border-style: dashed;
  height: 42px;
  margin-bottom: 20px;
}

.actions {
  display: flex;
  justify-content: center;
  gap: 12px;
}
.confirm-btn {
  min-width: 180px;
  height: 46px;
  font-weight: 600;
  border-radius: var(--radius-lg);
  background: var(--gradient-primary) !important;
  border: none !important;
  color: #fff !important;
  box-shadow: var(--shadow-primary) !important;
}
.confirm-btn:hover:not(:disabled),
.confirm-btn:focus:not(:disabled) {
  background: var(--gradient-primary) !important;
  color: #fff !important;
  opacity: 0.92;
}
.confirm-btn:disabled {
  background: var(--color-border) !important;
  color: var(--color-text-muted) !important;
  box-shadow: none !important;
}

.hint {
  margin: 12px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
