<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter, RouterView } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import BrandLockup from '@/components/BrandLockup.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const menuGroups = [
  {
    label: '教学总览',
    items: [{ index: '/teacher/dashboard', label: '教学驾驶舱', icon: 'DataAnalysis' }],
  },
  {
    label: '专业群建设',
    items: [{ index: '/teacher/industry', label: '岗位与培养方案', icon: 'OfficeBuilding' }],
  },
  {
    label: '教学实施',
    items: [
      { index: '/teacher/training', label: '实训任务与题库', icon: 'Document' },
      { index: '/teacher/learning', label: '学情诊断与复盘', icon: 'TrendCharts' },
      { index: '/teacher/resources', label: '知识资源建设', icon: 'Collection' },
    ],
  },
]

const activeMenu = computed(() => (
  menuGroups.flatMap((group) => group.items).find((item) => item.index === route.path)
))

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="teacher-shell">
    <el-aside width="236px" class="teacher-aside">
      <div class="brand">
        <BrandLockup subtitle="专业群教学与实训工作台" inverted />
      </div>

      <div class="major-card">
        <span class="major-icon"><el-icon><Reading /></el-icon></span>
        <div><strong>油气储运工程</strong><small>高水平专业群建设空间</small></div>
      </div>

      <el-menu :default-active="$route.path" class="teacher-menu" @select="(path: string) => router.push(path)">
        <template v-for="group in menuGroups" :key="group.label">
          <div class="menu-section-label">{{ group.label }}</div>
          <el-menu-item v-for="item in group.items" :key="item.index" :index="item.index" :aria-label="item.label" :title="item.label">
            <el-icon><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
          </el-menu-item>
        </template>
      </el-menu>

      <div class="aside-foot"><el-icon><CircleCheck /></el-icon><span>产业需求 · 教学实施 · 能力评价</span></div>
    </el-aside>

    <el-container class="teacher-workspace">
      <el-header class="teacher-header">
        <div class="header-heading">
          <span>油气储运工程专业群</span>
          <strong>{{ activeMenu?.label || String(route.meta.title || '教师工作台') }}</strong>
        </div>
        <div class="header-actions">
          <div class="role-chip"><el-icon><UserFilled /></el-icon>教师教学空间</div>
          <el-button class="assistant-entry" text type="primary" @click="router.push('/teacher/assistant')"><el-icon><ChatLineRound /></el-icon>教学智能助手</el-button>
          <el-divider direction="vertical" />
          <div class="user-info"><span class="user-avatar">{{ (auth.user?.real_name || auth.user?.username || '师').slice(0, 1) }}</span><div><strong>{{ auth.user?.real_name || auth.user?.username }}</strong><small>专业教师</small></div></div>
          <el-button text @click="logout">退出</el-button>
        </div>
      </el-header>

      <el-main class="teacher-main">
        <div class="teaching-boundary"><el-icon><InfoFilled /></el-icon><span>系统内容仅用于教学、虚拟实训和岗位技能学习，不作为真实生产现场操作依据。</span><strong>教学模拟环境</strong></div>
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.teacher-shell { height: 100vh; background: var(--ots-bg); }
.teacher-aside { display: flex; flex-direction: column; overflow: hidden; background: linear-gradient(180deg, #123f5d 0%, #155775 55%, #0b6670 100%); color: #fff; }
.brand { display: flex; align-items: center; gap: 12px; padding: 20px 18px 16px; border-bottom: 1px solid rgba(255,255,255,.1); }
.brand-mark { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid rgba(255,255,255,.25); border-radius: 12px; background: rgba(255,255,255,.1); font-size: 22px; flex: 0 0 auto; }
.brand-copy strong,.brand-copy small { display: block; }
.brand-copy strong { font-size: 19px; letter-spacing: 1px; }
.brand-copy small { margin-top: 4px; color: rgba(255,255,255,.68); font-size: 10px; }
.major-card { display: flex; align-items: center; gap: 10px; margin: 14px 14px 7px; padding: 10px 11px; border: 1px solid rgba(255,255,255,.12); border-radius: 10px; background: rgba(255,255,255,.07); }
.major-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: rgba(255,255,255,.1); }
.major-card strong,.major-card small { display: block; }
.major-card strong { font-size: 13px; }
.major-card small { margin-top: 2px; color: rgba(255,255,255,.58); font-size: 10px; }
.teacher-menu { flex: 1; padding: 4px 10px 12px; overflow-y: auto; border-right: 0; background: transparent; }
.menu-section-label { padding: 16px 12px 7px; color: rgba(255,255,255,.45); font-size: 11px; letter-spacing: 1px; }
.teacher-menu :deep(.el-menu-item) { height: 44px; margin: 3px 0; border-radius: 9px; color: rgba(255,255,255,.84); }
.teacher-menu :deep(.el-menu-item.is-active),.teacher-menu :deep(.el-menu-item:hover) { color: #fff; background: rgba(255,255,255,.13); }
.teacher-menu :deep(.el-menu-item.is-active) { box-shadow: inset 3px 0 #8fc8ff; }
.aside-foot { display: flex; align-items: center; gap: 8px; margin: 10px 14px 16px; padding: 11px; border-top: 1px solid rgba(255,255,255,.1); color: rgba(255,255,255,.62); font-size: 10px; }
.teacher-workspace { min-width: 0; }
.teacher-header { height: 68px; display: flex; align-items: center; justify-content: space-between; padding: 0 26px; border-bottom: 1px solid var(--ots-border); background: rgba(255,255,255,.96); }
.header-heading span,.header-heading strong { display: block; }
.header-heading span { color: var(--ots-text-secondary); font-size: 11px; }
.header-heading strong { margin-top: 3px; color: #123f5d; font-size: 18px; }
.header-actions,.user-info { display: flex; align-items: center; gap: 8px; }
.role-chip { display: flex; align-items: center; gap: 6px; padding: 7px 10px; border: 1px solid #dce8f4; border-radius: 999px; background: #f2f7fc; color: #315f83; font-size: 11px; }
.user-avatar { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: #eaf2fa; color: #245b81; font-weight: 700; }
.user-info strong,.user-info small { display: block; }
.user-info strong { font-size: 12px; }
.user-info small { margin-top: 1px; color: var(--ots-text-secondary); font-size: 9px; }
.teacher-main { padding: 0; overflow-y: auto; background: var(--ots-bg); }
.teaching-boundary { display: flex; align-items: center; gap: 9px; margin: 18px 24px 0; padding: 9px 13px; border: 1px solid #dce8ef; border-radius: 8px; background: #f7fafc; color: #586d7c; font-size: 11px; }
.teaching-boundary .el-icon { color: #2f6fed; }
.teaching-boundary strong { margin-left: auto; color: #315f83; white-space: nowrap; }

@media (max-width: 1100px) { .role-chip,.header-actions .el-divider { display: none; } }
@media (max-width: 768px) {
  .teacher-aside { width: 72px !important; }
  .brand { justify-content: center; padding: 15px 10px; }
  .brand-copy,.major-card,.menu-section-label,.aside-foot,.teacher-menu :deep(.el-menu-item span) { display: none; }
  .teacher-menu { padding: 10px 8px; }
  .teacher-menu :deep(.el-menu-item) { justify-content: center; padding: 0 !important; }
  .teacher-menu :deep(.el-menu-item .el-icon) { margin: 0; }
  .teacher-header { height: 60px; padding: 0 14px; }
  .header-heading span,.assistant-entry,.user-info div { display: none; }
  .header-heading strong { margin: 0; font-size: 15px; }
  .teaching-boundary { margin: 12px 14px 0; }
  .teaching-boundary strong { display: none; }
}
</style>
