<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import BrandLockup from '@/components/BrandLockup.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: 'student', password: 'student123' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const demoRoles = [
  { role: '学生', description: '体验岗位实训与能力成长', username: 'student', password: 'student123', icon: 'User', tone: 'student' },
  { role: '教师', description: '体验专业群教学与实训建设', username: 'teacher', password: 'teacher123', icon: 'Reading', tone: 'teacher' },
  { role: '管理员', description: '体验教学智能体可信治理', username: 'admin', password: 'admin123', icon: 'Setting', tone: 'admin' },
]

function selectDemoRole(item: typeof demoRoles[number]) {
  form.username = item.username
  form.password = item.password
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await auth.login(form.username, form.password)
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string)
        || (auth.isAdmin ? '/admin/dashboard' : auth.isStaff ? '/teacher/dashboard' : '/student/dashboard')
      router.push(redirect)
    } catch {
      // 请求拦截器负责展示接口错误。
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <main class="login-page">
    <section class="platform-panel">
      <div class="platform-grid" />
      <div class="platform-content">
        <BrandLockup subtitle="高水平专业群教学智能体平台" inverted large />
        <div class="platform-heading">
          <span>油气储运工程专业群</span>
          <h1>教学实训与岗位技能智能体</h1>
          <p>连接产业岗位需求、专业教学实施与学生能力成长，让实训过程有依据、学习成效可诊断、教学改进可追溯。</p>
        </div>

        <div class="value-path">
          <div><span><el-icon><OfficeBuilding /></el-icon></span><div><strong>对接产业岗位</strong><small>从公开证据提炼岗位任务与能力要求</small></div></div>
          <div><span><el-icon><Monitor /></el-icon></span><div><strong>支撑教学实训</strong><small>教师设计、审核并发布可信教学内容</small></div></div>
          <div><span><el-icon><TrendCharts /></el-icon></span><div><strong>伴随能力成长</strong><small>以六维能力画像驱动个性化学习路径</small></div></div>
        </div>

        <div class="trust-note"><el-icon><Lock /></el-icon><span>AI 生成明确标识 · 教学依据可追溯 · 管理操作留存审计</span></div>
      </div>
    </section>

    <section class="login-panel">
      <div class="mobile-brand"><BrandLockup subtitle="高水平专业群教学智能体平台" large /></div>
      <div class="login-card">
        <header><span>欢迎使用</span><h2>登录教学空间</h2><p>使用平台账号进入对应的学习、教学或治理工作台。</p></header>
        <el-form ref="formRef" :model="form" :rules="rules" size="large" class="login-form" @keyup.enter="handleLogin">
          <el-form-item prop="username"><el-input v-model="form.username" placeholder="用户名" prefix-icon="User" /></el-form-item>
          <el-form-item prop="password"><el-input v-model="form.password" type="password" placeholder="密码" prefix-icon="Lock" show-password /></el-form-item>
          <el-button type="primary" class="login-button" :loading="loading" @click="handleLogin">登录平台<el-icon><ArrowRight /></el-icon></el-button>
        </el-form>

        <div class="demo-area">
          <div class="demo-title"><span>竞赛演示角色</span><small>点击自动填充体验账号</small></div>
          <div class="role-list">
            <button v-for="item in demoRoles" :key="item.role" type="button" :class="item.tone" @click="selectDemoRole(item)">
              <span><el-icon><component :is="item.icon" /></el-icon></span>
              <div><strong>{{ item.role }}</strong><small>{{ item.description }}</small></div>
              <el-icon class="select-arrow"><ArrowRight /></el-icon>
            </button>
          </div>
        </div>

        <div class="safety-note"><el-icon><Warning /></el-icon><span>本平台仅用于教学、虚拟实训和岗位技能学习，不作为真实油气生产现场操作依据。</span></div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page { display: grid; grid-template-columns: minmax(470px, 1.08fr) minmax(430px, .92fr); min-height: 100vh; background: #f5f8f7; }
.platform-panel { position: relative; min-height: 100vh; overflow: hidden; background: linear-gradient(145deg, #073f49 0%, #0b6670 58%, #226b58 100%); color: #fff; }
.platform-grid { position: absolute; inset: 0; opacity: .16; background-image: linear-gradient(rgba(255,255,255,.12) 1px, transparent 1px),linear-gradient(90deg, rgba(255,255,255,.12) 1px, transparent 1px); background-size: 42px 42px; mask-image: linear-gradient(to bottom right, #000, transparent 78%); }
.platform-panel::after { position: absolute; right: -130px; bottom: -150px; width: 470px; height: 470px; border: 1px solid rgba(255,255,255,.14); border-radius: 50%; box-shadow: 0 0 0 60px rgba(255,255,255,.03),0 0 0 125px rgba(255,255,255,.025); content: ''; }
.platform-content { position: relative; z-index: 1; display: flex; flex-direction: column; min-height: 100vh; padding: 54px clamp(42px,7vw,100px) 42px; }
.platform-heading { max-width: 640px; margin: auto 0 48px; }
.platform-heading > span { color: #9fe1c1; font-size: 12px; font-weight: 600; letter-spacing: 2px; }
.platform-heading h1 { max-width: 600px; margin: 14px 0 16px; font-size: clamp(34px,4.2vw,56px); line-height: 1.17; letter-spacing: 1px; }
.platform-heading p { max-width: 590px; margin: 0; color: rgba(255,255,255,.73); font-size: 14px; line-height: 1.85; }
.value-path { display: grid; grid-template-columns: repeat(3, 1fr); gap: 11px; max-width: 700px; }
.value-path > div { display: flex; align-items: center; gap: 10px; min-height: 74px; padding: 11px; border: 1px solid rgba(255,255,255,.13); border-radius: 10px; background: rgba(255,255,255,.07); }
.value-path > div > span { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: rgba(255,255,255,.1); flex: 0 0 auto; }
.value-path strong,.value-path small { display: block; }
.value-path strong { font-size: 12px; }
.value-path small { margin-top: 3px; color: rgba(255,255,255,.6); font-size: 9px; line-height: 1.4; }
.trust-note { display: flex; align-items: center; gap: 8px; margin-top: 22px; color: rgba(255,255,255,.62); font-size: 10px; }
.login-panel { display: grid; place-items: center; min-height: 100vh; padding: 36px clamp(28px,5vw,72px); }
.mobile-brand { display: none; }
.login-card { width: min(100%, 450px); }
.login-card header > span { color: var(--ots-primary); font-size: 11px; font-weight: 600; letter-spacing: 1px; }
.login-card header h2 { margin: 7px 0 8px; color: var(--ots-primary-dark); font-size: 28px; }
.login-card header p { margin: 0; color: var(--ots-text-secondary); font-size: 12px; line-height: 1.6; }
.login-form { margin-top: 27px; }
.login-form :deep(.el-input__wrapper) { min-height: 46px; }
.login-button { width: 100%; min-height: 45px; }
.demo-area { margin-top: 25px; padding-top: 19px; border-top: 1px solid var(--ots-border); }
.demo-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.demo-title span { font-size: 12px; font-weight: 600; }
.demo-title small { color: var(--ots-text-secondary); font-size: 9px; }
.role-list { display: flex; flex-direction: column; gap: 7px; }
.role-list button { display: grid; grid-template-columns: 34px 1fr 16px; align-items: center; gap: 10px; min-height: 54px; padding: 8px 11px; border: 1px solid var(--ots-border); border-radius: 9px; background: #fff; color: var(--ots-text); text-align: left; cursor: pointer; }
.role-list button:hover { border-color: var(--ots-primary-light); background: #f8fbfa; }
.role-list button > span { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 8px; background: var(--ots-growth-soft); color: var(--ots-growth); }
.role-list button.teacher > span { background: var(--ots-education-soft); color: var(--ots-education); }
.role-list button.admin > span { background: #edf3f3; color: var(--ots-primary); }
.role-list strong,.role-list small { display: block; }
.role-list strong { font-size: 12px; }
.role-list small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }
.select-arrow { color: var(--ots-text-secondary); }
.safety-note { display: flex; align-items: flex-start; gap: 7px; margin-top: 17px; padding: 9px 10px; border-radius: 8px; background: var(--ots-practice-soft); color: #78531b; font-size: 9px; line-height: 1.5; }
.safety-note .el-icon { margin-top: 2px; flex: 0 0 auto; }

@media (max-width: 1050px) {
  .login-page { grid-template-columns: 1fr 450px; }
  .platform-content { padding-right: 42px; padding-left: 42px; }
  .value-path { grid-template-columns: 1fr; max-width: 430px; }
  .value-path > div { min-height: 60px; }
}
@media (max-width: 820px) {
  .login-page { display: block; min-height: 100vh; }
  .platform-panel { display: none; }
  .login-panel { min-height: 100vh; padding: 28px 20px; }
  .mobile-brand { display: block; width: min(100%,450px); margin-bottom: 32px; }
  .login-card header h2 { font-size: 24px; }
}
@media (max-width: 480px) {
  .login-panel { display: flex; justify-content: center; flex-direction: column; }
  .demo-title { align-items: flex-start; flex-direction: column; gap: 3px; }
}
</style>
