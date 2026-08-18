<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'
import type { AdminUserOut, UserRole } from '@/types'
const loading = ref(true); const users = ref<AdminUserOut[]>([]); const savingId = ref<number | null>(null)
async function load() { loading.value = true; try { users.value = await adminApi.users() } finally { loading.value = false } }
async function save(row: AdminUserOut) { savingId.value = row.id; try { const updated = await adminApi.updateUser(row.id, { role: row.role, is_active: row.is_active, real_name: row.real_name, class_name: row.class_name, student_no: row.student_no }); Object.assign(row, updated); ElMessage.success('用户已更新') } finally { savingId.value = null } }
onMounted(load)
</script>
<template><div class="ots-page" v-loading="loading"><div class="page-heading"><div><h2>用户与组织</h2><p>维护账号角色与启用状态。</p></div><el-button @click="load">刷新</el-button></div><div class="ots-card"><el-table :data="users"><el-table-column prop="username" label="账号" width="130" /><el-table-column prop="real_name" label="姓名" width="130" /><el-table-column label="角色" width="150"><template #default="{ row }"><el-select v-model="row.role"><el-option v-for="role in ['student','teacher','admin']" :key="role" :label="role" :value="role as UserRole" /></el-select></template></el-table-column><el-table-column prop="class_name" label="班级/组织" /><el-table-column label="启用" width="100"><template #default="{ row }"><el-switch v-model="row.is_active" /></template></el-table-column><el-table-column prop="created_at" label="创建时间" width="180" /><el-table-column label="操作" width="90"><template #default="{ row }"><el-button text type="primary" :loading="savingId === row.id" @click="save(row)">保存</el-button></template></el-table-column></el-table></div></div></template>
<style scoped>.page-heading { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }.page-heading h2 { margin:0 0 6px; }.page-heading p { margin:0; color:var(--ots-text-secondary); }</style>
