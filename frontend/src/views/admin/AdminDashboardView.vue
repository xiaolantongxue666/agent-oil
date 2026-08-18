<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { adminApi } from '@/api'
import type { AdminOverviewOut } from '@/types'
const loading = ref(true); const overview = ref<AdminOverviewOut | null>(null)
async function load() { loading.value = true; try { overview.value = await adminApi.overview() } finally { loading.value = false } }
onMounted(load)
</script>
<template><div class="ots-page" v-loading="loading"><div class="page-heading"><div><h2>系统总览</h2><p>用户、教学资源与系统治理状态。</p></div><el-button @click="load">刷新</el-button></div><el-row v-if="overview" :gutter="16"><el-col :xs="12" :md="6"><div class="ots-card metric"><strong>{{ overview.users.total }}</strong><span>用户总数</span></div></el-col><el-col :xs="12" :md="6"><div class="ots-card metric"><strong>{{ overview.users.active }}</strong><span>启用用户</span></div></el-col><el-col :xs="12" :md="6"><div class="ots-card metric"><strong>{{ overview.resources.training_tasks }}</strong><span>实训任务</span></div></el-col><el-col :xs="12" :md="6"><div class="ots-card metric"><strong>{{ overview.features.enabled }}/{{ overview.features.total }}</strong><span>启用功能</span></div></el-col></el-row><div class="ots-card"><h3 class="ots-title">最近审计记录</h3><el-table :data="overview?.recent_audits || []" empty-text="暂无审计记录"><el-table-column prop="created_at" label="时间" width="180" /><el-table-column prop="actor_name" label="操作者" width="130" /><el-table-column prop="action" label="操作" width="160" /><el-table-column prop="detail" label="详情" /></el-table></div></div></template>
<style scoped>.page-heading { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }.page-heading h2 { margin:0 0 6px; }.page-heading p { margin:0; color:var(--ots-text-secondary); }.metric { display:flex; flex-direction:column; gap:8px; margin-bottom:16px; }.metric strong { font-size:28px; color:var(--ots-primary-dark); }.metric span { color:var(--ots-text-secondary); }</style>
