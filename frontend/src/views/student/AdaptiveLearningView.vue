<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { recommendationApi } from '@/api'
import type { AdaptiveLearningPathOut } from '@/types'

const router = useRouter()
const loading = ref(true)
const path = ref<AdaptiveLearningPathOut | null>(null)

const weakPoints = computed(() => path.value?.knowledge_mastery.filter((item) => item.state !== 'mastered') || [])

const STEP_ACTIONS: Record<string, string> = {
  knowledge_review: '去补学',
  case_learning: '看案例',
  training_retry: '去训练',
  simulation_retry: '去重练',
  diagnostic_training: '开始诊断',
}
const CONFIDENCE_LABELS: Record<string, string> = { low: '较低', medium: '中', high: '高' }
const CONFIDENCE_TAG: Record<string, 'info' | 'warning' | 'success'> = { low: 'info', medium: 'warning', high: 'success' }
const TREND_LABELS: Record<string, string> = { improving: '↑ 上升', stable: '→ 平稳', declining: '↓ 下滑', insufficient: '数据积累中' }

function stepAction(type: string) {
  return STEP_ACTIONS[type] || '去学习'
}

function stateText(value: string) {
  return { weak: '待补强', learning: '学习中', mastered: '已掌握' }[value] || value
}

function stateType(value: string) {
  return value === 'mastered' ? 'success' : value === 'learning' ? 'warning' : 'danger'
}

async function loadData() {
  loading.value = true
  try {
    path.value = await recommendationApi.adaptivePath()
  } finally {
    loading.value = false
  }
}

function go(route: string) {
  router.push(route)
}

onMounted(loadData)
</script>

<template>
  <div v-loading="loading" class="adaptive-page">
    <div class="page-head">
      <div><h2>个性化学习路径</h2><p>系统统一读取你的知识答题、岗位情境训练、岗位仿真实训与教师评价证据，动态重排补学、案例、巩固与重练路径。</p></div>
      <el-button @click="loadData">刷新路径</el-button>
    </div>

    <el-alert v-if="path" :title="path.data_boundary" :description="path.refresh_rule" type="info" :closable="false" show-icon />
    <el-alert
      v-if="path?.safety_alert"
      :title="path.safety_alert.message"
      type="warning"
      :closable="false"
      show-icon
    />

    <template v-if="path">
      <div class="metric-grid">
        <div class="metric primary"><span>综合掌握度</span><strong>{{ path.summary.overall_mastery }}%</strong></div>
        <div class="metric"><span>待补强知识点</span><strong>{{ path.summary.weak_count }}</strong></div>
        <div class="metric"><span>学习中</span><strong>{{ path.summary.learning_count }}</strong></div>
        <div class="metric"><span>已掌握</span><strong>{{ path.summary.mastered_count }}</strong></div>
        <div class="metric"><span>动态路径步骤</span><strong>{{ path.summary.path_step_count }}</strong></div>
        <div class="metric"><span>证据链步骤</span><strong>{{ path.summary.evidence_driven_steps ?? 0 }}</strong></div>
      </div>

      <el-card v-if="path.next_step" shadow="never" class="next-card">
        <div class="next-inner">
          <div>
            <el-tag :type="path.next_step.safety_critical ? 'danger' : 'warning'">下一步 · {{ path.next_step.priority }}</el-tag>
            <h3>{{ path.next_step.title }}</h3>
            <p>{{ path.next_step.reason }}</p>
          </div>
          <el-button type="primary" size="large" @click="go(path.next_step!.route)">开始学习</el-button>
        </div>
      </el-card>

      <div class="content-grid">
        <el-card shadow="never">
          <template #header><b>知识点掌握诊断</b></template>
          <el-empty v-if="!path.knowledge_mastery.length" description="尚无实训结果，请先完成诊断训练" />
          <div v-for="item in path.knowledge_mastery" :key="`${item.ability_key}-${item.knowledge_point}`" class="mastery-row">
            <div class="mastery-head">
              <span><b>{{ item.knowledge_point }}</b><small>{{ item.ability_name }} · 作答 {{ item.attempt_count }} 次</small></span>
              <el-tag :type="stateType(item.state)">{{ stateText(item.state) }}</el-tag>
            </div>
            <el-progress :percentage="item.mastery_score" :status="item.mastery_score < 60 ? 'exception' : item.mastery_score >= 80 ? 'success' : undefined" />
            <div v-if="item.safety_critical" class="safety-note">安全类近期低分，已强制排到学习路径前列</div>
          </div>
        </el-card>

        <el-card shadow="never">
          <template #header><b>个人学习路径</b></template>
          <el-timeline v-if="path.learning_path.length">
            <el-timeline-item
              v-for="(step, index) in path.learning_path"
              :key="step.id"
              :type="step.safety_critical ? 'danger' : index === 0 ? 'primary' : undefined"
              :hollow="index > 0"
            >
              <div class="path-step">
                <div class="step-head">
                  <b>{{ index + 1 }}. {{ step.title }}</b>
                  <span class="step-tags">
                    <el-tag v-if="step.evidence_driven" size="small" type="primary" effect="plain">证据驱动</el-tag>
                    <el-tag size="small" effect="plain">{{ step.priority }}</el-tag>
                  </span>
                </div>
                <p>{{ step.reason }}</p>
                <span>{{ step.estimated_minutes }} 分钟 · 难度 {{ step.difficulty }}</span>
                <div v-if="step.safety_gate_warning" class="safety-note">安全意识未达标：进入该高难度任务前，请先完成前列安全补学项</div>
                <el-button size="small" :type="step.evidence_driven || index === 0 ? 'primary' : 'default'" @click="go(step.route)">{{ stepAction(step.step_type) }}</el-button>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="当前知识点均已掌握，可继续挑战进阶实训" />
        </el-card>
      </div>

      <el-card shadow="never">
        <template #header><b>六维能力状态</b></template>
        <div class="ability-grid">
          <div v-for="item in path.ability_state" :key="item.key" class="ability-item">
            <span>{{ item.name }}</span><b>{{ item.score }}</b><el-tag size="small" :type="stateType(item.state)">{{ stateText(item.state) }}</el-tag>
            <small class="ability-meta">
              {{ TREND_LABELS[item.trend || 'insufficient'] }}
              <template v-if="item.recent_avg != null"> · 近期均分 {{ item.recent_avg }}</template>
            </small>
            <el-tag
              v-if="item.confidence"
              size="small"
              effect="plain"
              :type="CONFIDENCE_TAG[item.confidence] || 'info'"
              title="能力置信度表示证据充分程度，不等同于能力高低"
            >
              置信度 {{ CONFIDENCE_LABELS[item.confidence] || item.confidence }} · {{ item.evidence_count ?? 0 }} 条证据
            </el-tag>
          </div>
        </div>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.adaptive-page { display: flex; flex-direction: column; gap: 16px; }
.page-head, .next-inner, .mastery-head, .step-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
h2, h3, p { margin: 0; }
.page-head p, .next-card p, .path-step p { color: var(--el-text-color-secondary); margin-top: 7px; }
.metric-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; }
.metric { background: #fff; border: 1px solid var(--ots-border); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.metric.primary { background: linear-gradient(135deg, #e8f6f3, #f8fbff); border-color: #b8ddd5; }
.metric span { color: var(--el-text-color-secondary); font-size: 13px; }
.metric strong { color: var(--ots-primary-dark); font-size: 26px; }
.next-card { border-color: #b8ddd5; background: linear-gradient(120deg, #f0faf8, #fff); }
.next-inner h3 { margin-top: 10px; }
.content-grid { display: grid; grid-template-columns: 1fr 1.05fr; gap: 14px; }
.mastery-row { padding: 12px 0; border-bottom: 1px solid var(--ots-border); }
.mastery-head { margin-bottom: 8px; }
.mastery-head small { display: block; color: var(--el-text-color-secondary); margin-top: 4px; }
.safety-note { color: #c62828; font-size: 12px; margin-top: 5px; }
.path-step { border: 1px solid var(--ots-border); border-radius: 8px; padding: 12px; }
.path-step span { display: inline-block; color: var(--el-text-color-secondary); font-size: 12px; margin: 9px 12px 0 0; }
.step-tags { display: inline-flex; gap: 6px; }
.ability-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
.ability-item { padding: 12px; border-radius: 7px; background: #f6f8fa; display: flex; flex-direction: column; align-items: center; gap: 7px; }
.ability-item b { color: var(--ots-primary); font-size: 20px; }
.ability-meta { color: var(--el-text-color-secondary); font-size: 12px; }
@media (max-width: 1100px) { .metric-grid { grid-template-columns: repeat(3, 1fr); } .content-grid { grid-template-columns: 1fr; } .ability-grid { grid-template-columns: repeat(3, 1fr); } }
</style>
