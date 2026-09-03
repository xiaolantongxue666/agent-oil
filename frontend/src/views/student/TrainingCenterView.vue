<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { trainingApi } from '@/api'
import type { TrainingTaskOut, TrainingSessionOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const router = useRouter()
const tasks = ref<TrainingTaskOut[]>([])
const sessions = ref<TrainingSessionOut[]>([])
const loading = ref(true)

const completedCodes = new Set<string>()

function difficultyStars(d: number) {
  return '★'.repeat(Math.min(d, 5)) + '☆'.repeat(Math.max(0, 5 - d))
}

function difficultyLabel(d: number) {
  const labels: Record<number, string> = { 1: '入门', 2: '基础', 3: '进阶', 4: '高级', 5: '挑战' }
  return labels[d] || `Lv${d}`
}

function isCompleted(code: string) {
  return completedCodes.has(code)
}

onMounted(async () => {
  try {
    const [t, s] = await Promise.allSettled([trainingApi.tasks(), trainingApi.sessions()])
    if (t.status === 'fulfilled') tasks.value = t.value
    if (s.status === 'fulfilled') {
      sessions.value = s.value
      for (const sess of s.value) {
        if (sess.finished) completedCodes.add(sess.task_code)
      }
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <div class="page-header">
      <h2>岗位情境训练</h2>
      <p class="text-secondary">选择岗位情境任务，通过选择题完成岗位情境判断训练；系统按数据库评分规则生成成绩与能力分析。</p>
    </div>

    <el-empty v-if="!loading && !tasks.length" description="暂无可用训练任务" />

    <div v-else class="task-grid">
      <div
        v-for="task in tasks"
        :key="task.id"
        class="ots-card task-card"
        :class="{ completed: isCompleted(task.code) }"
        @click="router.push(`/training/${task.code}`)"
      >
        <div class="task-header">
          <div class="task-title">{{ task.title }}</div>
          <el-tag v-if="isCompleted(task.code)" type="success" size="small" effect="dark">已完成</el-tag>
        </div>
        <div class="task-desc">{{ task.description }}</div>
        <div class="task-meta">
          <span class="difficulty">
            <span class="difficulty-stars">{{ difficultyStars(task.difficulty) }}</span>
            <span class="difficulty-label">{{ difficultyLabel(task.difficulty) }}</span>
          </span>
          <span class="text-secondary">⏱ {{ task.estimated_minutes }}分钟</span>
        </div>
        <div class="task-abilities">
          <el-tag
            v-for="ab in task.target_abilities"
            :key="ab"
            size="small"
            effect="plain"
            type="info"
          >
            {{ ABILITY_LABELS[ab as AbilityKey] || ab }}
          </el-tag>
        </div>
        <div class="task-footer text-secondary">
          {{ task.question_count }} 道岗位情境选择题 · 规则自动评分
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  margin-bottom: 16px;
}
.page-header h2 {
  margin: 0 0 6px;
}
.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.task-card {
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
  border: 2px solid transparent;
}
.task-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(11, 95, 107, 0.14);
}
.task-card.completed {
  border-color: var(--ots-success);
  opacity: 0.85;
}
.task-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.task-title {
  font-size: 16px;
  font-weight: 600;
}
.task-desc {
  color: var(--ots-text-secondary);
  font-size: 13px;
  line-height: 1.5;
  margin-bottom: 10px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.task-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 8px;
}
.difficulty-stars {
  color: #f5a623;
  letter-spacing: 1px;
}
.difficulty-label {
  font-size: 12px;
  color: var(--ots-text-secondary);
  margin-left: 4px;
}
.task-abilities {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.task-footer {
  font-size: 12px;
  border-top: 1px solid var(--ots-border);
  padding-top: 8px;
}
@media (max-width: 480px) {
  .task-grid { grid-template-columns: minmax(0, 1fr); }
  .task-meta { flex-wrap: wrap; gap: 8px 12px; }
}
</style>
