<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { adminApi } from '@/api'
import type { AdminAuditLogOut } from '@/types'
const loading = ref(true); const logs = ref<AdminAuditLogOut[]>([])
async function load() { loading.value = true; try { logs.value = await adminApi.auditLogs() } finally { loading.value = false } }
onMounted(load)
</script>
<template><div class="ots-page" v-loading="loading"><div class="page-heading"><div><h2>审计与运行</h2><p>查看管理操作与系统治理痕迹。</p></div><el-button @click="load">刷新</el-button></div><div class="ots-card"><el-table :data="logs"><el-table-column prop="created_at" label="时间" width="180" /><el-table-column prop="actor_name" label="操作者" width="140" /><el-table-column prop="action" label="操作" width="180" /><el-table-column prop="resource_type" label="资源类型" width="140" /><el-table-column prop="detail" label="详情" min-width="240" /></el-table></div></div></template>
<style scoped>.page-heading { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }.page-heading h2 { margin:0 0 6px; }.page-heading p { margin:0; color:var(--ots-text-secondary); }</style>
