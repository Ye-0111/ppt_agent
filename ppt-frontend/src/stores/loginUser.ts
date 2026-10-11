import { defineStore } from 'pinia'
import { ref } from 'vue'
import { DEFAULT_USERNAME } from '@/constants/user'

export const useLoginUserStore = defineStore('loginUser', () => {
  const loginUser = ref<API.LoginUserVO>({
    nickname: DEFAULT_USERNAME,
  })

  function setLoginUser(newLoginUser: any) {
    loginUser.value = newLoginUser
  }

  function clearLoginUser() {
    loginUser.value = { nickname: DEFAULT_USERNAME }
  }

  return { loginUser, setLoginUser, clearLoginUser }
})
