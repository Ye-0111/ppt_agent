import { createRouter, createWebHistory } from 'vue-router'
import HomePage from '@/pages/HomePage.vue'
import ChatPage from '@/pages/chat/ChatPage.vue'
import UserLoginPage from '@/pages/user/UserLoginPage.vue'
import UserRegisterPage from '@/pages/user/UserRegisterPage.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: '主页',
      component: HomePage,
    },
    {
      path: '/chat',
      name: 'AI对话',
      component: ChatPage,
    },
    {
      path: '/create',
      name: '创作PPT',
      component: () => import('@/pages/ppt/PptCreatePage.vue'),
    },
    {
      path: '/ppt/list',
      name: '我的PPT',
      component: () => import('@/pages/ppt/PptListPage.vue'),
    },
    {
      path: '/ppt/template/list',
      name: '模板库',
      component: () => import('@/pages/ppt/TemplateListPage.vue'),
    },
    {
      path: '/ppt/template/upload',
      name: '上传模板',
      component: () => import('@/pages/ppt/TemplateUploadPage.vue'),
    },
    {
      path: '/admin/quota',
      name: '配额管理',
      component: () => import('@/pages/admin/QuotaManagePage.vue'),
    },
    {
      path: '/user/login',
      name: '用户登录',
      component: UserLoginPage,
    },
    {
      path: '/user/register',
      name: '用户注册',
      component: UserRegisterPage,
    },
  ],
})

export default router
