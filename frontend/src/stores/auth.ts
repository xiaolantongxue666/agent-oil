import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserInfo } from '@/types'
import { authApi } from '@/api'

export const useAuthStore = defineStore(
  'auth',
  () => {
    const token = ref<string>('')
    const user = ref<UserInfo | null>(null)

    const isAuthed = computed(() => !!token.value)
    const role = computed<string | null>(() => user.value?.role ?? null)
    const isAdmin = computed(() => role.value === 'admin')
    const isStaff = computed(() => role.value === 'teacher' || role.value === 'admin')
    // Kept for legacy views that use the original teacher/staff meaning.
    const isTeacher = computed(() => isStaff.value)

    async function login(username: string, password: string) {
      const res = await authApi.login(username, password)
      token.value = res.token
      user.value = res.user
      return res
    }

    function logout() {
      token.value = ''
      user.value = null
    }

    return { token, user, isAuthed, role, isAdmin, isStaff, isTeacher, login, logout }
  },
  { persist: { key: 'ots-auth', storage: localStorage } },
)
