<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { trainingApi } from '@/api'
import type { TrainingTaskOut, TrainingSessionOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const route = useRoute()
const router = useRouter()
const taskCode = route.params.id as string
const task = ref<TrainingTaskOut | null>(null)
const pastSessions = ref<TrainingSessionOut[]>([])
const loading = ref(true)
const starting = ref(false)

function difficultyLabel(d: number) {
  const labels: Record<number, string> = { 1: '入门', 2: '基础', 3: '进阶', 4: '高级', 5: '挑战' }
  return labels[d] || `Lv${d}`
}

async function startTraining() {
  if (!task.value) return
  starting.value = true
  try {
    const sess = await trainingApi.start(task.value.code)
    router.push(`/training/session/${sess.id}`)
  } catch {
    /* interceptor handles error toast */
  } finally {
    starting.value = false
  }
}

function resumeSession(id: number) {
  router.push(`/training/session/${id}`)
}

onMounted(async () => {
  try {
    const [tasks, sessions] = await Promise.allSettled([
      trainingApi.tasks(),
      trainingApi.sessions(),
    ])
    if (tasks.status === 'fulfilled') {
      task.value = tasks.value.find((t) => t.code === taskCode) || null
    }
    if (sessions.status === 'fulfilled') {
      pastSessions.value = sessions.value.filter((s) => s.task_code === taskCode)
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <el-page-header @back="router.push('/training')" content="训练任务详情" />

    <div v-if="task" class="ots-card" style="margin-top: 16px">
      <h2 style="margin: 0 0 8px">{{ task.title }}</h2>
      <p class="task-desc">{{ task.description }}</p>

      <el-descriptions :column="2" border style="margin: 16px 0">
        <el-descriptions-item label="任务编号">{{ task.code }}</el-descriptions-item>
        <el-descriptions-item label="难度">
          <el-tag>{{ difficultyLabel(task.difficulty) }} ({{ task.difficulty }}/5)</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="预计时间">{{ task.estimated_minutes }} 分钟</el-descriptions-item>
        <el-descriptions-item label="实训题量">{{ task.question_count }} 道单选题</el-descriptions-item>
        <el-descriptions-item label="评分方式">数据库选项规则评分</el-descriptions-item>
        <el-descriptions-item label="目标能力" :span="2">
          <el-tag
            v-for="ab in task.target_abilities"
            :key="ab"
            size="small"
            effect="plain"
            style="margin-right: 6px"
          >
            {{ ABILITY_LABELS[ab as AbilityKey] || ab }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <el-button type="primary" size="large" :loading="starting" @click="startTraining">
        开始选择题实训
      </el-button>
    </div>

    <el-empty v-else-if="!loading" description="任务不存在">
      <el-button @click="router.push('/training')">返回实训中心</el-button>
    </el-empty>

    <!-- 历史记录 -->
    <div v-if="pastSessions.length" class="ots-card">
      <h3 class="ots-title">历史训练记录</h3>
      <el-table :data="pastSessions" stripe>
        <el-table-column prop="created_at" label="开始时间" width="180" />
        <el-table-column prop="stage" label="状态">
          <template #default="{ row }">
            <el-tag :type="row.finished ? 'success' : 'warning'" size="small">
              {{ row.finished ? '已完成' : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="得分">
          <template #default="{ row }">
            <span v-if="row.evaluation">{{ row.evaluation.final_score }}</span>
            <span v-else class="text-secondary">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="answered_count" label="已答题数" width="100" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="resumeSession(row.id)">
              {{ row.finished ? '查看' : '继续' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.task-desc {
  color: var(--ots-text-secondary);
  line-height: 1.6;
}
</style>
