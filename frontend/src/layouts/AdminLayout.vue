<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter, RouterView } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'
import BrandLockup from '@/components/BrandLockup.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const admin = useAdminStore()

const menuGroups = [
  {
    label: '平台管理',
    items: [
      { index: '/admin/users', label: '组织与用户', icon: 'User' },
      { index: '/admin/ai-system', label: '功能与权限', icon: 'SetUp' },
    ],
  },
  {
    label: '智能体能力',
    items: [
      { index: '/admin/llm-config', label: '模型服务', icon: 'Connection' },
      { index: '/admin/prompts', label: '教学策略工坊', icon: 'EditPen' },
    ],
  },
  {
    label: '工具',
    items: [
      { index: '/admin/competition', label: '比赛模式首页', icon: 'TrophyBase' },
      { index: '/admin/assistant', label: '智能助手', icon: 'ChatLineRound' },
    ],
  },
]

const activeMenu = computed(() => (
  menuGroups.flatMap((group) => group.items).find((item) => item.index === route.path)
))

onMounted(() => admin.loadFeatures())

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="admin-shell">
    <el-aside width="236px" class="admin-aside">
      <div class="brand">
        <BrandLockup subtitle="高水平专业群教学智能体治理台" inverted />
      </div>

      <div class="professional-badge">
        <span class="badge-dot" />
        <div>
          <strong>油气储运工程</strong>
          <span>专业群教学治理空间</span>
        </div>
      </div>

      <el-menu
        :default-active="$route.path"
        class="admin-menu"
        @select="(path: string) => router.push(path)"
      >
        <template v-for="group in menuGroups" :key="group.label">
          <div class="menu-section-label">{{ group.label }}</div>
          <el-menu-item v-for="item in group.items" :key="item.index" :index="item.index" :aria-label="item.label" :title="item.label">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </template>
      </el-menu>

      <div class="aside-foot">
        <el-icon><CircleCheck /></el-icon>
        <span>教学数据 · 生成内容 · 全程可追溯</span>
      </div>
    </el-aside>

    <el-container class="admin-workspace">
      <el-header class="admin-header">
        <div class="header-heading">
          <span>高水平专业群 · 教学智能体治理</span>
          <strong>{{ activeMenu?.label || '系统管理' }}</strong>
        </div>
        <div class="header-actions">
          <div class="environment-chip"><span class="status-dot" />教学治理环境</div>
          <el-button text type="primary" @click="router.push('/admin/assistant')">
            <el-icon><ChatLineRound /></el-icon>智能助手
          </el-button>
          <el-divider direction="vertical" />
          <div class="user-info">
            <span class="user-avatar">{{ (auth.user?.real_name || auth.user?.username || '管').slice(0, 1) }}</span>
            <div>
              <strong>{{ auth.user?.real_name || auth.user?.username }}</strong>
              <small>系统管理员</small>
            </div>
          </div>
          <el-button text @click="logout">退出</el-button>
        </div>
      </el-header>

      <el-main class="admin-main">
        <div class="governance-strip">
          <el-icon><Lock /></el-icon>
          <span>教学数据仅限授权范围使用，模型配置与教学策略变更均记录审计轨迹。</span>
          <span class="strip-tag">可信教学治理</span>
        </div>
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.admin-shell { height: 100vh; background: var(--ots-bg); }
.admin-aside { display: flex; flex-direction: column; background: linear-gradient(180deg, #073f49 0%, #0a5863 58%, #0b6670 100%); color: #fff; overflow: hidden; }
.brand { display: flex; gap: 12px; align-items: center; padding: 20px 18px 16px; border-bottom: 1px solid rgba(255,255,255,.1); }
.brand-mark { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid rgba(255,255,255,.26); border-radius: 12px; background: rgba(255,255,255,.1); font-size: 22px; flex: 0 0 auto; }
.brand-copy { min-width: 0; }
.brand-copy strong,.brand-copy small { display: block; }
.brand-copy strong { font-size: 19px; letter-spacing: 1px; }
.brand-copy small { margin-top: 4px; color: rgba(255,255,255,.68); font-size: 10px; line-height: 1.35; }
.professional-badge { display: flex; align-items: center; gap: 9px; margin: 14px 14px 8px; padding: 10px 11px; border: 1px solid rgba(255,255,255,.12); border-radius: 10px; background: rgba(255,255,255,.07); }
.professional-badge strong,.professional-badge span { display: block; }
.professional-badge strong { font-size: 13px; font-weight: 600; }
.professional-badge span:not(.badge-dot) { margin-top: 2px; color: rgba(255,255,255,.6); font-size: 10px; }
.badge-dot,.status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #69d09c; box-shadow: 0 0 0 4px rgba(105,208,156,.14); flex: 0 0 auto; }
.admin-menu { flex: 1; padding: 4px 10px 12px; background: transparent; border-right: 0; overflow-y: auto; }
.menu-section-label { padding: 16px 12px 7px; color: rgba(255,255,255,.46); font-size: 11px; letter-spacing: 1px; }
.admin-menu :deep(.el-menu-item) { height: 44px; margin: 3px 0; border-radius: 9px; color: rgba(255,255,255,.82); }
.admin-menu :deep(.el-menu-item .el-icon) { font-size: 18px; }
.admin-menu :deep(.el-menu-item.is-active),.admin-menu :deep(.el-menu-item:hover) { color: #fff; background: rgba(255,255,255,.13); }
.admin-menu :deep(.el-menu-item.is-active) { box-shadow: inset 3px 0 #8bd9b2; }
.aside-foot { display: flex; align-items: center; gap: 8px; margin: 10px 14px 16px; padding: 11px; border-top: 1px solid rgba(255,255,255,.1); color: rgba(255,255,255,.62); font-size: 10px; line-height: 1.45; }
.admin-workspace { min-width: 0; }
.admin-header { height: 68px; display: flex; justify-content: space-between; align-items: center; padding: 0 26px; background: rgba(255,255,255,.96); border-bottom: 1px solid var(--ots-border); }
.header-heading span,.header-heading strong { display: block; }
.header-heading span { color: var(--ots-text-secondary); font-size: 11px; letter-spacing: .5px; }
.header-heading strong { margin-top: 3px; color: var(--ots-primary-dark); font-size: 18px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.environment-chip { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid #d7e9df; border-radius: 999px; background: #f3faf6; color: #327153; font-size: 12px; }
.user-info { display: flex; align-items: center; gap: 8px; }
.user-info strong,.user-info small { display: block; }
.user-info strong { color: var(--ots-text); font-size: 13px; }
.user-info small { margin-top: 1px; color: var(--ots-text-secondary); font-size: 10px; }
.user-avatar { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: #e8f3f4; color: var(--ots-primary); font-weight: 700; }
.admin-main { padding: 0; background: var(--ots-bg); overflow-y: auto; }
.governance-strip { display: flex; align-items: center; gap: 9px; margin: 18px 24px 0; padding: 9px 13px; border: 1px solid #dce8e5; border-radius: 8px; background: #f8fbfa; color: #506b67; font-size: 12px; }
.governance-strip .el-icon { color: var(--ots-primary); }
.strip-tag { margin-left: auto; color: var(--ots-primary); font-weight: 600; white-space: nowrap; }

@media (max-width: 1100px) {
  .environment-chip,.header-actions .el-divider { display: none; }
  .admin-header { padding: 0 20px; }
}
@media (max-width: 768px) {
  .admin-aside { width: 72px !important; }
  .brand { justify-content: center; padding: 15px 10px; }
  .brand-copy,.professional-badge,.menu-section-label,.aside-foot,.admin-menu :deep(.el-menu-item span) { display: none; }
  .admin-menu { padding: 10px 8px; }
  .admin-menu :deep(.el-menu-item) { justify-content: center; padding: 0 !important; }
  .admin-menu :deep(.el-menu-item .el-icon) { margin: 0; }
  .admin-header { height: 60px; padding: 0 14px; }
  .header-heading span,.header-actions > .el-button:first-of-type,.user-info div { display: none; }
  .header-heading strong { margin: 0; font-size: 16px; }
  .governance-strip { margin: 12px 14px 0; }
  .strip-tag { display: none; }
}
</style>
