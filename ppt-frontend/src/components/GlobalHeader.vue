<template>
  <a-layout-header class="header">
    <div class="header-container">
      <div class="header-left">
        <RouterLink to="/" class="logo-link">
          <div class="logo-wrapper">
            <img src="@/assets/logo.png" alt="Logo" class="logo-img" />
            <h1 class="site-title">AI PPT创作器</h1>
          </div>
        </RouterLink>
      </div>

      <nav class="nav-center">
        <RouterLink
          v-for="item in menuItems"
          :key="item.key"
          :to="item.key"
          :class="['nav-item', { active: selectedKeys.includes(item.key) }]"
        >
          <component :is="item.icon" class="nav-icon" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="header-right">
        <div v-if="loginUserStore.loginUser.id" class="user-dropdown">
          <a-dropdown>
            <a-space class="user-info">
              <a-avatar :size="36" class="user-avatar">
                {{ loginUserStore.loginUser.nickname?.charAt(0) ?? 'U' }}
              </a-avatar>
              <span class="quota-chip" title="PPT 创作配额">
                配额 {{ loginUserStore.loginUser.pptQuota ?? 0 }}
              </span>
              <span class="user-name">
                {{ loginUserStore.loginUser.nickname ?? '无名' }}
              </span>
            </a-space>
            <template #overlay>
              <a-menu class="dropdown-menu">
                <a-menu-item @click="doLogout" class="dropdown-item">
                  <LogoutOutlined />
                  <span>退出登录</span>
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
        <div v-else>
          <RouterLink to="/user/login" class="login-btn">登录</RouterLink>
        </div>
      </div>
    </div>
  </a-layout-header>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useLoginUserStore } from '@/stores/loginUser'
import {
  LogoutOutlined,
  HomeOutlined,
  MessageOutlined,
  EditOutlined,
  FileOutlined,
  AppstoreOutlined,
  SettingOutlined,
} from '@ant-design/icons-vue'

const loginUserStore = useLoginUserStore()
const router = useRouter()
const selectedKeys = ref<string[]>(['/'])

router.afterEach((to) => {
  selectedKeys.value = [to.path]
})

const menuItems = computed(() => {
  const originItems = [
    { key: '/', icon: HomeOutlined, label: '首页' },
    { key: '/chat', icon: MessageOutlined, label: 'AI对话' },
    { key: '/create', icon: EditOutlined, label: '创作' },
    { key: '/ppt/list', icon: FileOutlined, label: '我的PPT' },
    { key: '/ppt/template/list', icon: AppstoreOutlined, label: '模板库' },
    { key: '/admin/quota', icon: SettingOutlined, label: '配额管理', admin: true },
  ]
  return originItems.filter((item) => {
    if (item.admin) {
      return loginUserStore.loginUser.userRole === 'admin'
    }
    return true
  })
})

const doLogout = async () => {
  loginUserStore.clearLoginUser()
  message.success('退出登录成功')
  await router.push('/user/login')
}
</script>

<style scoped>
.header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  padding: 0;
  height: 64px;
  line-height: 64px;
  border-bottom: 1px solid var(--color-border);
  overflow: hidden;
}

.header-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
}

.header-left { display: flex; align-items: center; }

.logo-link { display: block; transition: opacity var(--transition-fast); }
.logo-link:hover { opacity: 0.8; }

.logo-wrapper { display: flex; align-items: center; gap: 10px; }

.logo-img { width: 36px; height: 36px; object-fit: contain; }

.site-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
  letter-spacing: -0.3px;
}

.nav-center { display: flex; align-items: center; gap: 8px; }

.nav-item {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: var(--radius-md);
  font-size: 14px; font-weight: 500;
  color: var(--color-text-secondary);
  transition: all var(--transition-fast);
  text-decoration: none;
}
.nav-item:hover { color: var(--color-text); background: var(--color-background-secondary); }
.nav-item.active { color: var(--color-primary-dark); background: rgba(79, 70, 229, 0.1); }

.nav-icon { font-size: 16px; }

.header-right { display: flex; align-items: center; gap: 16px; }

.quota-chip {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-dark);
  background: rgba(79, 70, 229, 0.1);
  padding: 4px 12px;
  border-radius: var(--radius-full);
  white-space: nowrap;
}

.user-dropdown { cursor: pointer; height: 64px; display: flex; align-items: center; gap: 16px; }

.user-info {
  padding: 6px 12px; border-radius: var(--radius-md);
  transition: all var(--transition-fast); display: flex; align-items: center;
}
.user-info:hover { background: var(--color-background-secondary); }

.user-avatar { border: 2px solid var(--color-border); }
.user-name { font-weight: 500; color: var(--color-text); font-size: 14px; }

.login-btn {
  display: inline-flex; align-items: center; justify-content: center;
  height: 38px; padding: 0 24px; border-radius: var(--radius-md);
  font-size: 14px; font-weight: 600; color: white;
  background: var(--gradient-primary); border: none;
  box-shadow: var(--shadow-primary);
  transition: all var(--transition-normal); text-decoration: none;
}
.login-btn:hover { color: white; box-shadow: 0 6px 20px rgba(79, 70, 229, 0.35); }

.dropdown-menu { border-radius: var(--radius-md); overflow: hidden; box-shadow: var(--shadow-lg); border: 1px solid var(--color-border); }

.dropdown-item { display: flex; align-items: center; gap: 8px; padding: 10px 16px; transition: all var(--transition-fast); }
.dropdown-item:hover { background: var(--color-background-secondary); }

@media (max-width: 768px) {
  .header-container { padding: 0 16px; }
  .site-title { display: none; }
  .nav-item span { display: none; }
  .nav-item { padding: 8px 12px; }
  .user-name { display: none; }
}
</style>
