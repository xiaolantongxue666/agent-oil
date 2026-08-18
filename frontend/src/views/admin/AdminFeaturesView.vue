<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'
import type { AdminFeatureOut } from '@/types'
const loading = ref(true); const features = ref<AdminFeatureOut[]>([]); const saving = ref('')
async function load() { loading.value = true; try { features.value = await adminApi.features() } finally { loading.value = false } }
async function save(feature: AdminFeatureOut) { saving.value = feature.code; try { Object.assign(feature, await adminApi.updateFeature(feature.code, { enabled: feature.enabled, read_only: feature.read_only, change_reason: feature.change_reason })); ElMessage.success('功能配置已更新') } finally { saving.value = '' } }
onMounted(load)
</script>
<template><div class="ots-page" v-loading="loading"><div class="page-heading"><div><h2>AI 系统与功能控制</h2><p>控制管理功能的可见性和写入权限。</p></div><el-button @click="load">刷新</el-button></div><div class="ots-card"><el-table :data="features"><el-table-column prop="name" label="功能" min-width="150" /><el-table-column prop="description" label="说明" min-width="220" /><el-table-column label="启用" width="100"><template #default="{ row }"><el-switch v-model="row.enabled" /></template></el-table-column><el-table-column label="只读" width="100"><template #default="{ row }"><el-switch v-model="row.read_only" /></template></el-table-column><el-table-column label="变更说明" min-width="180"><template #default="{ row }"><el-input v-model="row.change_reason" /></template></el-table-column><el-table-column label="操作" width="90"><template #default="{ row }"><el-button text type="primary" :loading="saving === row.code" @click="save(row)">保存</el-button></template></el-table-column></el-table></div></div></template>
<style scoped>.page-heading { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }.page-heading h2 { margin:0 0 6px; }.page-heading p { margin:0; color:var(--ots-text-secondary); }</style>
