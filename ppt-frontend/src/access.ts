import router from '@/router'
import { message } from 'ant-design-vue'
import { useLoginUserStore } from '@/stores/loginUser'

/**
 * 全局路由守卫
 * - /admin/* 需要管理员角色
 * - /create 需要登录
 */
router.beforeEach(async (to, from, next) => {
  const store = useLoginUserStore()
  await store.ensureLoginUser()
  const user = store.loginUser

  // 管理员页面
  if (to.path.startsWith('/admin')) {
    if (user.userRole !== 'admin') {
      message.error('需要管理员权限')
      return next('/')
    }
    return next()
  }

  // 需要登录的页面（创作 + 我的作品）
  if ((to.path === '/create' || to.path.startsWith('/ppt')) && !user.id) {
    message.warning('请先登录')
    return next(`/user/login?redirect=${encodeURIComponent(to.fullPath)}`)
  }

  next()
})
