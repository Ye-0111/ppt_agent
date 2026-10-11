<script setup lang="ts">
import {
  RocketOutlined,
  FileTextOutlined,
  OrderedListOutlined,
  EditOutlined,
  PictureOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons-vue'

const features = [
  { icon: FileTextOutlined, title: '智能标题', description: 'AI 自动分析主题，生成专业PPT标题方案', color: '#4F46E5' },
  { icon: OrderedListOutlined, title: '幻灯片大纲', description: '智能规划PPT结构，自动生成幻灯片大纲', color: '#3B82F6' },
  { icon: EditOutlined, title: '流式内容', description: '实时展示PPT生成过程，流式输出幻灯片内容', color: '#8B5CF6' },
  { icon: PictureOutlined, title: '智能配图', description: '自动检索高质量无版权图片，完美匹配内容', color: '#F59E0B' },
  { icon: ThunderboltOutlined, title: '高效生成', description: '快速完成PPT制作，效率大幅提升', color: '#EF4444' },
  { icon: ClockCircleOutlined, title: '历史管理', description: '随时查看和管理所有PPT创作记录，支持导出', color: '#06B6D4' },
]
</script>

<template>
  <div id="homePage">
    <!-- Hero Section -->
    <div class="hero-section">
      <div class="hero-bg"></div>
      <div class="container">
        <div class="hero-badge">
          <ThunderboltOutlined />
          <span>AI 驱动的PPT创作平台</span>
        </div>
        <h1 class="hero-title">AI PPT创作器</h1>
        <p class="hero-subtitle">让每个人都能制作专业PPT</p>
        <p class="hero-tips">工作汇报、产品介绍、技术分享、培训课件... 一键生成</p>
      </div>
    </div>

    <!-- Features Section -->
    <div class="features-section">
      <div class="container">
        <div class="section-header">
          <div class="section-badge">核心能力</div>
          <h2 class="section-title">一站式AI PPT制作工具</h2>
          <p class="section-subtitle">强大的 AI 能力，让PPT制作变得简单高效</p>
        </div>
        <div class="features-grid">
          <div v-for="(feature, index) in features" :key="index" class="feature-card">
            <div class="feature-icon-wrapper" :style="{ background: `${feature.color}15` }">
              <component :is="feature.icon" class="feature-icon" :style="{ color: feature.color }" />
            </div>
            <div class="feature-content">
              <h3 class="feature-title">{{ feature.title }}</h3>
              <p class="feature-description">{{ feature.description }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
#homePage { width: 100%; margin: 0; padding: 0; min-height: 100vh; background: var(--color-background); }

.hero-section { position: relative; padding: 80px 20px 100px; text-align: center; overflow: hidden; }
.hero-bg { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: var(--gradient-hero); z-index: 0; }
.container { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; }

.hero-badge {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 16px; background: rgba(79, 70, 229, 0.1);
  border: 1px solid rgba(79, 70, 229, 0.2); border-radius: var(--radius-full);
  font-size: 14px; font-weight: 500; margin-bottom: 24px; color: var(--color-primary-dark);
}

.hero-title {
  font-size: 52px; font-weight: 700; margin: 0 0 16px;
  letter-spacing: -1.5px; line-height: 1.1; color: var(--color-text);
  background: linear-gradient(135deg, var(--color-primary-dark) 0%, var(--color-primary) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.hero-subtitle { font-size: 20px; margin: 0 0 40px; color: var(--color-text-secondary); font-weight: 400; }
.hero-tips { font-size: 14px; color: var(--color-text-muted); margin: 0; }

.features-section { padding: 80px 20px; background: var(--color-background-secondary); }
.features-section .container { max-width: 1100px; }
.section-header { text-align: center; margin-bottom: 48px; }

.section-badge {
  display: inline-block; padding: 6px 14px; background: rgba(79, 70, 229, 0.1);
  border-radius: var(--radius-full); font-size: 13px; font-weight: 600;
  color: var(--color-primary-dark); margin-bottom: 16px;
}
.section-title { font-size: 32px; font-weight: 700; margin: 0 0 12px; color: var(--color-text); letter-spacing: -0.5px; }
.section-subtitle { font-size: 16px; color: var(--color-text-secondary); margin: 0; }

.features-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }

.feature-card {
  background: white; border-radius: var(--radius-lg); border: 1px solid var(--color-border);
  padding: 24px; display: flex; gap: 16px; align-items: flex-start;
  transition: all var(--transition-normal); cursor: pointer;
}
.feature-card:hover { border-color: var(--color-primary-light); box-shadow: var(--shadow-card-hover); transform: translateY(-2px); }

.feature-icon-wrapper {
  width: 48px; height: 48px; display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-md); flex-shrink: 0;
}
.feature-icon { font-size: 22px; }
.feature-content { flex: 1; min-width: 0; }
.feature-title { font-size: 16px; font-weight: 600; margin: 0 0 6px; color: var(--color-text); }
.feature-description { font-size: 14px; color: var(--color-text-secondary); margin: 0; line-height: 1.5; }

@media (max-width: 992px) { .features-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 768px) {
  .hero-section { padding: 60px 20px 80px; }
  .hero-title { font-size: 36px; }
  .hero-subtitle { font-size: 16px; }
  .features-grid { grid-template-columns: 1fr; }
  .section-title { font-size: 24px; }
}
</style>
