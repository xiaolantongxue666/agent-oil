import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

const service: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// 请求拦截：注入 JWT 与 request_id
service.interceptors.request.use(
  (config) => {
    const auth = useAuthStore()
    if (auth.token) {
      config.headers.Authorization = `Bearer ${auth.token}`
    }
    config.headers['x-request-id'] = crypto.randomUUID?.() ?? `${Date.now()}`
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截：统一解包 + 错误处理
service.interceptors.response.use(
  (response: AxiosResponse) => {
    const body = response.data as ApiResponse
    if (body && body.success === false) {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(body)
    }
    // 解包 { success: true, data: ... }，保留在 response.data
    return response
  },
  (error) => {
    const status = error.response?.status
    const data = error.response?.data
    if (status === 401) {
      const auth = useAuthStore()
      auth.logout()
      router.push('/login')
      ElMessage.error('登录已失效，请重新登录')
    } else if (status === 403) {
      ElMessage.error('无权限访问')
    } else if (data && data.success === false) {
      ElMessage.error(data.message || '请求失败')
    } else {
      ElMessage.error(error.message || '网络异常')
    }
    return Promise.reject(error)
  },
)

export async function request<T = unknown>(config: AxiosRequestConfig): Promise<T> {
  const res = await service(config)
  const body = res.data as ApiResponse<T>
  if (body.success) {
    return body.data
  }
  throw body
}

export default service
