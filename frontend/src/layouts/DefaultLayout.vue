<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, RouterView } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import BrandLockup from '@/components/BrandLockup.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

// DefaultLayout 仅服务学生角色（父路由 roles:['student'] 收口，教师永远走 TeacherLayout）。
// Phase 4：5 大任务域一级导航；分组 index 用稳定逻辑 key（practice/ability/knowledge），
// 子项 index 即真实 URL —— 本阶段不改任何 URL，只改菜单组织与命名。
// /simulation（操作型仿真实训）与 /training（情境判断训练）不再都叫「实训」。
interface NavLeaf { index: string; label: string }
interface NavEntry extends NavLeaf { icon?: string; children?: NavLeaf[] }

const studentNav: NavEntry[] = [
  { index: '/student/dashboard', label: '我的成长', icon: 'HomeFilled' },
  { index: 'practice', label: '岗位实训', icon: 'Monitor', children: [
    { index: '/simulation', label: '岗位仿真实训' },
    { index: '/training', label: '岗位情境训练' },
  ] },
  { index: 'ability', label: '能力档案', icon: 'TrendCharts', children: [
    { index: '/profile', label: '技能画像与证据' },
    { index: '/ability-graph', label: '目标岗位能力' },
  ] },
  { index: '/adaptive-learning', label: '个性化提升', icon: 'Guide' },
  { index: 'knowledge', label: '知识助手', children: [
    { index: '/knowledge', label: '岗位学习助手' },
    { index: '/knowledge/library', label: '专业资料库' },
  ], icon: 'Collection' },
]

// 深链 → 激活子项：/simulation/{code}→/simulation、/training/{id}→/training、/knowledge/library 优先于 /knowledge
function menuIndexFor(path: string): string {
  if (path.startsWith('/knowledge/library')) return '/knowledge/library'
  if (path.startsWith('/knowledge')) return '/knowledge'
  if (path.startsWith('/simulation')) return '/simulation'
  if (path.startsWith('/training')) return '/training'
  if (path.startsWith('/profile')) return '/profile'
  if (path === '/ability-graph') return '/ability-graph'
  return path
}

const activeMenu = computed(() => menuIndexFor(route.path))
const activeLabel = computed(() => {
  for (const entry of studentNav) {
    if (entry.index === activeMenu.value) return entry.label
    const child = entry.children?.find((item) => item.index === activeMenu.value)
    if (child) return child.label
  }
  return String(route.meta.title || '学习中心')
})

// 子项 → 父分组：保证深链进入时对应一级 submenu 自动展开
const groupOfChild: Record<string, string> = {
  '/simulation': 'practice', '/training': 'practice',
  '/profile': 'ability', '/ability-graph': 'ability',
  '/knowledge': 'knowledge', '/knowledge/library': 'knowledge',
}
const activeGroup = computed(() => groupOfChild[activeMenu.value] ?? '')
const menuRef = ref<{ open: (index: string) => void } | null>(null)
watch(activeGroup, (group) => { if (group) menuRef.value?.open(group) })
onMounted(() => { if (activeGroup.value) menuRef.value?.open(activeGroup.value) })

// ≤768px 用 el-menu 真实 collapse 模式（hover 弹层可点子项），而非 CSS 隐藏文字导致子菜单不可用
const narrowQuery = window.matchMedia('(max-width: 768px)')
const isNarrow = ref(narrowQuery.matches)
const onNarrowChange = (event: MediaQueryListEvent) => { isNarrow.value = event.matches }
narrowQuery.addEventListener('change', onNarrowChange)
onBeforeUnmount(() => narrowQuery.removeEventListener('change', onNarrowChange))

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="student-shell">
    <el-aside :width="isNarrow ? '72px' : '236px'" class="student-aside">
      <div class="brand">
        <BrandLockup subtitle="岗位能力成长中心" inverted />
      </div>

      <div class="growth-card">
        <span class="growth-icon"><el-icon><Aim /></el-icon></span>
        <div><strong>油气储运工程</strong><small>岗位技能成长空间</small></div>
      </div>

      <el-menu ref="menuRef" :default-active="activeMenu" :collapse="isNarrow" :collapse-transition="false" class="student-menu" @select="(path: string) => router.push(path)">
        <template v-for="entry in studentNav" :key="entry.index">
          <el-menu-item v-if="!entry.children" :index="entry.index" :aria-label="entry.label" :title="entry.label">
            <el-icon><component :is="entry.icon" /></el-icon><span>{{ entry.label }}</span>
          </el-menu-item>
          <el-sub-menu v-else :index="entry.index" :aria-label="entry.label" popper-class="student-menu-popper" teleported>
            <template #title>
              <el-icon><component :is="entry.icon" /></el-icon><span>{{ entry.label }}</span>
            </template>
            <el-menu-item v-for="child in entry.children" :key="child.index" :index="child.index" :aria-label="child.label" :title="child.label">{{ child.label }}</el-menu-item>
          </el-sub-menu>
        </template>
      </el-menu>

      <div class="aside-foot"><el-icon><CircleCheck /></el-icon><span>岗位目标 · 实训任务 · 能力成长</span></div>
    </el-aside>

    <el-container class="student-workspace">
      <el-header class="student-header">
        <div class="header-heading"><span>油气储运工程 · 岗位技能学习</span><strong>{{ activeLabel }}</strong></div>
        <div class="header-user">
          <div class="role-chip"><el-icon><Opportunity /></el-icon>学生成长空间</div>
          <div class="user-info"><span class="user-avatar">{{ (auth.user?.real_name || auth.user?.username || '学').slice(0, 1) }}</span><div><strong>{{ auth.user?.real_name || auth.user?.username }}</strong><small>学习者</small></div></div>
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
.student-menu { flex: 1; padding: 4px 10px 12px; overflow-y: auto; border-right: 0; background: transparent; --el-menu-bg-color: transparent; --el-menu-text-color: rgba(255,255,255,.84); --el-menu-hover-bg-color: rgba(255,255,255,.13); --el-menu-active-color: #fff; }
.student-menu :deep(.el-sub-menu__title) { height: 44px; margin: 3px 0; border-radius: 9px; }
.student-menu :deep(.el-sub-menu__icon-arrow) { color: rgba(255,255,255,.55); }
.student-menu :deep(.el-sub-menu .el-menu) { padding-bottom: 2px; background: transparent; border-right: 0; }
/* 二级项：更小字号 + 缩进，与一级形成清晰层级（§11） */
.student-menu :deep(.el-sub-menu .el-menu-item) { height: 38px; margin: 2px 0; font-size: 12.5px; color: rgba(255,255,255,.72); }
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
  .brand { justify-content: center; padding: 15px 10px; }
  .brand-copy,.growth-card,.aside-foot { display: none; }
  /* collapse 模式由 el-menu 自身处理图标与子菜单弹层，不再 CSS 隐藏文字 */
  .student-menu { padding: 10px 4px; }
  .student-header { height: 60px; padding: 0 14px; }
  .header-heading span,.user-info div { display: none; }
  .header-heading strong { margin: 0; font-size: 15px; }
  .learning-boundary { margin: 12px 14px 0; }
  .learning-boundary strong { display: none; }
}
</style>
