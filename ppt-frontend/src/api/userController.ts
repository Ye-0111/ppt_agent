import request from '@/request'

/** 用户登录 */
export async function userLogin(body: { username: string; password: string }) {
  return request.post('/user/login', body)
}

/** 恢复当前登录用户 */
export async function getLoginUser() {
  return request.get('/user/get/login')
}

/** 撤销登录会话 */
export async function userLogout() {
  return request.post('/user/logout')
}

/** 用户注册 */
export async function userRegister(body: { username: string; password: string; checkPassword: string }) {
  return request.post('/user/register', body)
}

/** 管理员设置用户配额 POST /user/quota */
export async function setUserQuota(body: { userId: number; pptQuota: number }) {
  return request.post('/user/quota', body)
}

/** 管理员分页查询用户配额 POST /user/quota/page */
export async function listUserQuotaPage(body: {
  current: number
  pageSize: number
  username?: string
}) {
  return request.post('/user/quota/page', body)
}
