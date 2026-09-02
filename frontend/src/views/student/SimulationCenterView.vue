<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { simulationApi } from '@/api'
import type { SimulationScenarioSummary } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const router = useRouter()
const scenarios = ref<SimulationScenarioSummary[]>([])
const loading = ref(true)

function difficultyStars(d: number) {
  return '★'.repeat(Math.min(d, 5)) + '☆'.repeat(Math.max(0, 5 - d))
}

function difficultyLabel(d: number) {
  const labels: Record<number, string> = { 1: '入门', 2: '基础', 3: '进阶', 4: '高级', 5: '挑战' }
  return labels[d] || `Lv${d}`
}

onMounted(async () => {
  try {
    scenarios.value = await simulationApi.scenarios()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <div class="page-header">
      <h2>岗位仿真实训</h2>
      <p class="text-secondary">
        面向站场操作岗的教学仿真任务：按"观察 → 诊断 → 风险判断 → 处置决策 → 规范记录"完整流程演练，
        系统以行为事件 + 状态机 + Rubric 确定性评分，结果写入能力画像。
      </p>
    </div>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      class="sim-notice"
      title="教学模拟环境"
      description="场景内全部参数、报警与设备状态均为模拟数据，仅用于教学训练，不对应任何真实生产系统，严禁将实训操作用于真实设备控制。"
    />

    <el-empty v-if="!loading && !scenarios.length" description="暂无可用仿真实训场景" />

    <div v-else class="task-grid">
      <div
        v-for="sc in scenarios"
        :key="sc.scenario_code"
        class="ots-card task-card"
        @click="router.push(`/simulation/${sc.scenario_code}`)"
      >
        <div class="task-header">
          <div class="task-title">{{ sc.title }}</div>
          <el-tag v-if="sc.teaching_simulation" type="warning" size="small" effect="dark">教学模拟</el-tag>
        </div>
        <div class="task-desc">{{ sc.description }}</div>
        <div class="task-meta">
          <span class="difficulty">
            <span class="difficulty-stars">{{ difficultyStars(sc.difficulty) }}</span>
            <span class="difficulty-label">{{ difficultyLabel(sc.difficulty) }}</span>
          </span>
          <span class="text-secondary">⏱ 约 {{ sc.estimated_minutes }} 分钟</span>
        </div>
        <div class="task-abilities">
          <el-tag v-for="ab in sc.target_abilities" :key="ab" size="small" effect="plain" type="info">
            {{ ABILITY_LABELS[ab as AbilityKey] || ab }}
          </el-tag>
        </div>
        <div class="task-footer text-secondary">
          {{ sc.disclaimer || '行为事件驱动评分 · LLM 不参与判分' }}
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
.sim-notice {
  margin-bottom: 16px;
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
