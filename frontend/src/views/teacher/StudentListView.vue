<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { teacherApi } from '@/api'
import type { TeacherStudentOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const router = useRouter()
const students = ref<TeacherStudentOut[]>([])
const loading = ref(true)
const search = ref('')

const filtered = ref<TeacherStudentOut[]>([])

function onSearch() {
  const q = search.value.trim().toLowerCase()
  filtered.value = q
    ? students.value.filter(
        (s) =>
          s.real_name.toLowerCase().includes(q) ||
          s.username.toLowerCase().includes(q) ||
          (s.student_no || '').toLowerCase().includes(q),
      )
    : students.value
}

function viewStudent(id: number) {
  router.push(`/teacher/students/${id}`)
}

onMounted(async () => {
  try {
    students.value = await teacherApi.students()
    filtered.value = students.value
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <div class="page-header">
      <h2 style="margin: 0">班级学情诊断</h2>
      <el-input
        v-model="search"
        placeholder="搜索姓名/学号..."
        clearable
        style="width: 240px"
        @input="onSearch"
      />
    </div>

    <div class="ots-card">
      <el-table :data="filtered" stripe @row-click="(row: TeacherStudentOut) => viewStudent(row.id)">
        <el-table-column prop="real_name" label="姓名" width="100" />
        <el-table-column prop="username" label="用户名" width="100" />
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column prop="class_name" label="班级" width="120" />
        <el-table-column prop="completed_count" label="完成训练" width="100" align="center" />
        <el-table-column label="能力分" width="100" align="center">
          <template #default="{ row }">
            <span :style="{ fontWeight: 600, color: row.total_score >= 60 ? '#2e7d32' : '#c62828' }">
              {{ row.total_score.toFixed(0) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最弱维度">
          <template #default="{ row }">
            <el-tag v-if="row.weakest_ability" type="warning" size="small" effect="plain">
              {{ ABILITY_LABELS[row.weakest_ability as AbilityKey] || row.weakest_ability }}
            </el-tag>
            <span v-else class="text-secondary">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click.stop="viewStudent(row.id)">
              画像
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filtered.length" description="暂无学生数据" />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
</style>
