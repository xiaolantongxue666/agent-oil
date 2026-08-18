<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { teacherApi } from '@/api'
import type { TeacherStudentProfileOut, TeacherStudentHistoryOut, AbilityItem } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'
import EChartsRadar from '@/components/EChartsRadar.vue'

const route = useRoute()
const router = useRouter()
const studentId = Number(route.params.id)
const profile = ref<TeacherStudentProfileOut | null>(null)
const history = ref<TeacherStudentHistoryOut[]>([])
const loading = ref(true)

const abilities = computed<AbilityItem[]>(() => {
  if (!profile.value?.radar?.labels) return []
  return profile.value.radar.labels.map((name, i) => ({
    key: (name || '') as AbilityKey,
    name,
    weight: 1,
    score: profile.value!.radar.scores?.[i] ?? 0,
  }))
})

const weakestDims = computed(() => {
  if (!profile.value?.profile) return []
  return Object.entries(profile.value.profile)
    .sort((a, b) => a[1].score - b[1].score)
    .slice(0, 3)
})

onMounted(async () => {
  try {
    const [p, h] = await Promise.allSettled([
      teacherApi.studentProfile(studentId),
      teacherApi.studentHistory(studentId),
    ])
    if (p.status === 'fulfilled') profile.value = p.value
    if (h.status === 'fulfilled') history.value = h.value
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <el-page-header @back="router.push('/teacher/students')" :content="profile?.real_name || '学生画像'" />

    <div v-if="profile" style="margin-top: 16px">
      <!-- 学生基本信息 -->
      <el-row :gutter="16">
        <el-col :xs="24" :sm="8">
          <div class="ots-card">
            <h4 style="margin: 0 0 8px">基本信息</h4>
            <el-descriptions :column="1" size="small">
              <el-descriptions-item label="姓名">{{ profile.real_name }}</el-descriptions-item>
              <el-descriptions-item label="用户名">{{ profile.username }}</el-descriptions-item>
              <el-descriptions-item label="学号">{{ profile.student_no || '—' }}</el-descriptions-item>
              <el-descriptions-item label="班级">{{ profile.class_name || '—' }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8">
          <div class="ots-card stat-mini">
            <div class="stat-mini-val">{{ profile.avg_score.toFixed(0) }}</div>
            <div class="stat-mini-label">平均训练分</div>
          </div>
          <div class="ots-card stat-mini">
            <div class="stat-mini-val">{{ profile.completed_count }}</div>
            <div class="stat-mini-label">完成训练数</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8">
          <div class="ots-card">
            <h4 style="margin: 0 0 8px">需关注维度</h4>
            <div v-if="weakestDims.length" class="weak-list">
              <div v-for="[key, dim] in weakestDims" :key="key" class="weak-item">
                <span>{{ dim.name || ABILITY_LABELS[key as AbilityKey] }}</span>
                <span class="weak-score">{{ dim.score.toFixed(0) }}</span>
              </div>
            </div>
            <span v-else class="text-secondary">暂无数据</span>
          </div>
        </el-col>
      </el-row>

      <!-- 雷达图 -->
      <div class="ots-card">
        <h3 class="ots-title">六维能力雷达</h3>
        <EChartsRadar v-if="abilities.length" :abilities="abilities" height="320px" />
        <el-empty v-else description="暂无能力数据" :image-size="60" />
      </div>

      <!-- 训练历史 -->
      <div class="ots-card">
        <h3 class="ots-title">训练历史</h3>
        <el-table v-if="history.length" :data="history" stripe>
          <el-table-column prop="created_at" label="时间" width="180" />
          <el-table-column prop="task_title" label="任务" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.finished ? 'success' : 'warning'" size="small">
                {{ row.finished ? '已完成' : row.stage }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="attempt_count" label="作答轮" width="80" align="center" />
          <el-table-column label="得分" width="80" align="center">
            <template #default="{ row }">
              <span v-if="row.final_score != null">{{ row.final_score }}</span>
              <span v-else class="text-secondary">—</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无训练记录" :image-size="60" />
      </div>
    </div>

    <el-empty v-else-if="!loading" description="学生不存在">
      <el-button @click="router.push('/teacher/students')">返回列表</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
.stat-mini {
  text-align: center;
  padding: 14px;
}
.stat-mini-val {
  font-size: 28px;
  font-weight: 700;
  color: var(--ots-primary-dark);
}
.stat-mini-label {
  font-size: 12px;
  color: var(--ots-text-secondary);
}
.weak-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.weak-item {
  display: flex;
  justify-content: space-between;
  padding: 4px 8px;
  background: var(--ots-bg);
  border-radius: 4px;
  font-size: 13px;
}
.weak-score {
  font-weight: 600;
  color: var(--ots-warning);
}
</style>
