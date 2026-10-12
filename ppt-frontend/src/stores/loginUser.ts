import { defineStore } from 'pinia'
import { ref } from 'vue'
import { DEFAULT_USERNAME } from '@/constants/user'
import { getLoginUser } from '@/api/userController'

export const useLoginUserStore = defineStore('loginUser', () => {
  const loginUser = ref<API.LoginUserVO>({
    nickname: DEFAULT_USERNAME,
  })
  let userLoaded = false
  let loadPromise: Promise<void> | null = null

  function setLoginUser(newLoginUser: any) {
    loginUser.value = newLoginUser
    userLoaded = true
  }

  function clearLoginUser() {
    loginUser.value = { nickname: DEFAULT_USERNAME }
    userLoaded = true
  }

  async function ensureLoginUser() {
    if (userLoaded) return
    if (!loadPromise) {
      loadPromise = (async () => {
        try {
          const response = await getLoginUser()
          if (response.data.code === 0 && response.data.data) {
            setLoginUser(response.data.data)
          }
        } catch {
          loginUser.value = { nickname: DEFAULT_USERNAME }
        } finally {
          userLoaded = true
        }
      })()
    }
    await loadPromise
  }

  return { loginUser, setLoginUser, clearLoginUser, ensureLoginUser }
})
