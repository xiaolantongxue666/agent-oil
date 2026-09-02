<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter, RouterView } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import BrandLockup from '@/components/BrandLockup.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const menuGroups = computed(() => {
  if (auth.isTeacher) {
    return [
      { label: '教学总览', items: [
        { index: '/teacher/dashboard', label: '教师工作台', icon: 'DataAnalysis' },
        { index: '/competition', label: '比赛模式首页', icon: 'TrophyBase' },
      ] },
      { label: '教学实施', items: [
        { index: '/teacher/students', label: '学生列表', icon: 'User' },
        { index: '/teacher/tasks', label: '实训任务', icon: 'Document' },
        { index: '/teacher/training-results', label: '教学实施复盘', icon: 'TrendCharts' },
      ] },
      { label: '学习支持', items: [
        { index: '/ability-graph', label: '岗位能力图谱', icon: 'Share' },
        { index: '/knowledge/library', label: '专业知识库', icon: 'Reading' },
        { index: '/knowledge', label: '智能学习助手', icon: 'ChatLineRound' },
      ] },
    ]
  }
  return [
    { label: '成长中心', items: [
      { index: '/student/dashboard', label: '我的成长', icon: 'HomeFilled' },
      { index: '/profile', label: '能力成长档案', icon: 'TrendCharts' },
      { index: '/adaptive-learning', label: '个性化学习路径', icon: 'Guide' },
    ] },
    { label: '项目总览', items: [
      { index: '/competition', label: '比赛模式首页', icon: 'TrophyBase' },
    ] },
    { label: '岗位实训', items: [
      { index: '/ability-graph', label: '目标岗位能力', icon: 'Share' },
      { index: '/training', label: '岗位情境实训', icon: 'Operation' },
      { index: '/simulation', label: '岗位仿真实训', icon: 'Monitor' },
    ] },
    { label: '学习支持', items: [
      { index: '/knowledge/library', label: '专业资料库', icon: 'Reading' },
      { index: '/knowledge', label: '岗位学习助手', icon: 'ChatLineRound' },
    ] },
  ]
})

const activeMenu = computed(() => (
  menuGroups.value.flatMap((group) => group.items).find((item) => item.index === route.path)
))

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="student-shell">
    <el-aside width="236px" class="student-aside">
      <div class="brand">
        <BrandLockup :subtitle="auth.isTeacher ? '教学资源与学习支持' : '岗位能力成长中心'" inverted />
      </div>

      <div class="growth-card">
        <span class="growth-icon"><el-icon><Aim /></el-icon></span>
        <div><strong>油气储运工程</strong><small>{{ auth.isTeacher ? '教师资源浏览空间' : '岗位技能成长空间' }}</small></div>
      </div>

      <el-menu :default-active="$route.path" class="student-menu" @select="(path: string) => router.push(path)">
        <template v-for="group in menuGroups" :key="group.label">
          <div class="menu-section-label">{{ group.label }}</div>
          <el-menu-item v-for="item in group.items" :key="item.index" :index="item.index" :aria-label="item.label" :title="item.label">
            <el-icon><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
          </el-menu-item>
        </template>
      </el-menu>

      <div class="aside-foot"><el-icon><CircleCheck /></el-icon><span>岗位目标 · 实训任务 · 能力成长</span></div>
    </el-aside>

    <el-container class="student-workspace">
      <el-header class="student-header">
        <div class="header-heading"><span>油气储运工程 · 岗位技能学习</span><strong>{{ activeMenu?.label || String(route.meta.title || '学习中心') }}</strong></div>
        <div class="header-user">
          <div class="role-chip"><el-icon><Opportunity /></el-icon>{{ auth.isTeacher ? '教师资源视图' : '学生成长空间' }}</div>
          <div class="user-info"><span class="user-avatar">{{ (auth.user?.real_name || auth.user?.username || '学').slice(0, 1) }}</span><div><strong>{{ auth.user?.real_name || auth.user?.username }}</strong><small>{{ auth.isTeacher ? '专业教师' : '学习者' }}</small></div></div>
          <el-button text @click="handleLogout">退出</el-button>
        </div>
      </el-header>

      <el-main class="student-main">
        <div class="learning-boundary"><el-icon><InfoFilled /></el-icon><span>系统内容仅用于教学、虚拟实训和岗位技能学习；工况、参数和案例均为教学模拟或脱敏数据。</span><strong>教学模拟内容</strong></div>
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.student-shell { height: 100vh; background: var(--ots-bg); }
.student-aside { display: flex; flex-direction: column; overflow: hidden; background: linear-gradient(180deg, #0a4b51 0%, #0b6670 55%, #28765c 100%); color: #fff; }
.brand { display: flex; align-items: center; gap: 12px; padding: 20px 18px 16px; border-bottom: 1px solid rgba(255,255,255,.1); }
.brand-mark { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid rgba(255,255,255,.25); border-radius: 12px; background: rgba(255,255,255,.1); font-size: 22px; flex: 0 0 auto; }
.brand-copy strong,.brand-copy small { display: block; }
.brand-copy strong { font-size: 19px; letter-spacing: 1px; }
.brand-copy small { margin-top: 4px; color: rgba(255,255,255,.68); font-size: 10px; }
.growth-card { display: flex; align-items: center; gap: 10px; margin: 14px 14px 7px; padding: 10px 11px; border: 1px solid rgba(255,255,255,.12); border-radius: 10px; background: rgba(255,255,255,.07); }
.growth-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: rgba(255,255,255,.1); }
.growth-card strong,.growth-card small { display: block; }
.growth-card strong { font-size: 13px; }
.growth-card small { margin-top: 2px; color: rgba(255,255,255,.58); font-size: 10px; }
.student-menu { flex: 1; padding: 4px 10px 12px; overflow-y: auto; border-right: 0; background: transparent; }
.menu-section-label { padding: 16px 12px 7px; color: rgba(255,255,255,.45); font-size: 11px; letter-spacing: 1px; }
.student-menu :deep(.el-menu-item) { height: 44px; margin: 3px 0; border-radius: 9px; color: rgba(255,255,255,.84); }
.student-menu :deep(.el-menu-item.is-active),.student-menu :deep(.el-menu-item:hover) { color: #fff; background: rgba(255,255,255,.13); }
.student-menu :deep(.el-menu-item.is-active) { box-shadow: inset 3px 0 #91dfb6; }
.aside-foot { display: flex; align-items: center; gap: 8px; margin: 10px 14px 16px; padding: 11px; border-top: 1px solid rgba(255,255,255,.1); color: rgba(255,255,255,.62); font-size: 10px; }
.student-workspace { min-width: 0; }
.student-header { height: 68px; display: flex; align-items: center; justify-content: space-between; padding: 0 26px; border-bottom: 1px solid var(--ots-border); background: rgba(255,255,255,.96); }
.header-heading span,.header-heading strong { display: block; }
.header-heading span { color: var(--ots-text-secondary); font-size: 11px; }
.header-heading strong { margin-top: 3px; color: var(--ots-primary-dark); font-size: 18px; }
.header-user,.user-info { display: flex; align-items: center; gap: 8px; }
.role-chip { display: flex; align-items: center; gap: 6px; padding: 7px 10px; border: 1px solid #d6e9df; border-radius: 999px; background: #f2faf5; color: #347456; font-size: 11px; }
.user-avatar { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: var(--ots-growth-soft); color: var(--ots-growth); font-weight: 700; }
.user-info strong,.user-info small { display: block; }
.user-info strong { font-size: 12px; }
.user-info small { margin-top: 1px; color: var(--ots-text-secondary); font-size: 9px; }
.student-main { padding: 0; overflow-y: auto; background: var(--ots-bg); }
.learning-boundary { display: flex; align-items: center; gap: 9px; margin: 18px 24px 0; padding: 9px 13px; border: 1px solid #dbe9e1; border-radius: 8px; background: #f7fbf8; color: #587066; font-size: 11px; }
.learning-boundary .el-icon { color: var(--ots-growth); }
.learning-boundary strong { margin-left: auto; color: var(--ots-growth); white-space: nowrap; }

@media (max-width: 1000px) { .role-chip { display: none; } }
@media (max-width: 768px) {
  .student-aside { width: 72px !important; }
  .brand { justify-content: center; padding: 15px 10px; }
  .brand-copy,.growth-card,.menu-section-label,.aside-foot,.student-menu :deep(.el-menu-item span) { display: none; }
  .student-menu { padding: 10px 8px; }
  .student-menu :deep(.el-menu-item) { justify-content: center; padding: 0 !important; }
  .student-menu :deep(.el-menu-item .el-icon) { margin: 0; }
  .student-header { height: 60px; padding: 0 14px; }
  .header-heading span,.user-info div { display: none; }
  .header-heading strong { margin: 0; font-size: 15px; }
  .learning-boundary { margin: 12px 14px 0; }
  .learning-boundary strong { display: none; }
}
</style>
