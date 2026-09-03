<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { trainingApi } from '@/api'
import type { TrainingSessionOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const route = useRoute()
const router = useRouter()
const sessionId = Number(route.params.id)
const session = ref<TrainingSessionOut | null>(null)
const selectedOptionId = ref<number | null>(null)
const submitting = ref(false)
const loading = ref(true)
const showFeedback = ref(false)

const progress = computed(() => {
  if (!session.value?.question_count) return 0
  return Math.round((session.value.answered_count / session.value.question_count) * 100)
})

const currentNumber = computed(() => Math.min(
  (session.value?.answered_count || 0) + 1,
  session.value?.question_count || 1,
))

async function submitChoice() {
  const question = session.value?.current_question
  if (!question || selectedOptionId.value === null || submitting.value) return
  submitting.value = true
  try {
    session.value = await trainingApi.submitChoice(sessionId, question.id, selectedOptionId.value)
    selectedOptionId.value = null
    showFeedback.value = true
  } catch {
    ElMessage.error('提交失败，请重新选择后再试')
  } finally {
    submitting.value = false
  }
}

function continueTraining() {
  if (session.value?.finished) {
    router.push(`/training/result/${sessionId}`)
    return
  }
  showFeedback.value = false
}

onMounted(async () => {
  try {
    session.value = await trainingApi.detail(sessionId)
    if (session.value.finished) showFeedback.value = false
  } catch {
    router.push('/training')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page choice-training" v-loading="loading">
    <div class="ots-card training-header">
      <div class="header-row">
        <div>
          <h2>{{ session?.task_title || '加载中...' }}</h2>
          <p>岗位情境训练 · 数据库规则评分</p>
        </div>
        <div class="header-status">
          <el-tag :type="session?.finished ? 'success' : 'warning'" effect="dark">
            {{ session?.finished ? '已完成' : `第 ${currentNumber}/${session?.question_count || 0} 题` }}
          </el-tag>
          <strong>{{ progress }}%</strong>
        </div>
      </div>
      <el-progress :percentage="progress" :stroke-width="8" />
    </div>

    <div v-if="session?.scenario_text" class="ots-card scenario-card">
      <div class="section-kicker">工作情境</div>
      <p>{{ session.scenario_text }}</p>
    </div>

    <div
      v-if="showFeedback && session?.last_answer_feedback"
      class="ots-card feedback-card"
      :class="session.last_answer_feedback.is_correct ? 'correct' : 'incorrect'"
    >
      <div class="feedback-icon">{{ session.last_answer_feedback.is_correct ? '✓' : '!' }}</div>
      <div class="feedback-content">
        <h3>{{ session.last_answer_feedback.is_correct ? '判断正确' : '本题需要复盘' }}</h3>
        <p>{{ session.last_answer_feedback.feedback }}</p>
        <div class="feedback-score">
          本题得分 {{ session.last_answer_feedback.score }}/{{ session.last_answer_feedback.max_score }}
        </div>
      </div>
      <el-button type="primary" size="large" @click="continueTraining">
        {{ session.finished ? '查看训练结果' : '继续下一题' }}
      </el-button>
    </div>

    <div v-else-if="!session?.finished && session?.current_question" class="ots-card question-card">
      <div class="question-meta">
        <span class="question-index">题目 {{ currentNumber }}</span>
        <el-tag
          v-if="session.current_question.generated_by_ai"
          size="small"
          type="warning"
          effect="dark"
        >AI 生成题目 · 已经教师审核</el-tag>
        <el-tag size="small" effect="plain">
          {{ ABILITY_LABELS[session.current_question.ability_key as AbilityKey] || session.current_question.ability_key }}
        </el-tag>
        <span v-if="session.current_question.knowledge_point" class="knowledge-point">
          知识点：{{ session.current_question.knowledge_point }}
        </span>
      </div>
      <h3 class="question-stem">{{ session.current_question.stem }}</h3>

      <el-radio-group v-model="selectedOptionId" class="option-list">
        <el-radio
          v-for="option in session.current_question.options"
          :key="option.id"
          :value="option.id"
          class="option-card"
          border
        >
          <span class="option-key">{{ option.key }}</span>
          <span class="option-text">{{ option.content }}</span>
        </el-radio>
      </el-radio-group>

      <div class="submit-row">
        <span>选择最符合岗位规范的选项后提交；AI 生成题目以权威教学依据和教师审核版本为准。</span>
        <el-button
          type="primary"
          size="large"
          :loading="submitting"
          :disabled="selectedOptionId === null"
          @click="submitChoice"
        >
          确认本题答案
        </el-button>
      </div>
    </div>

    <div v-else-if="session?.finished" class="ots-card finished-card">
      <div class="finished-mark">✓</div>
      <h2>本次训练已完成</h2>
      <p>系统已根据每道题的数据库评分规则生成成绩和能力分析。</p>
      <el-button type="primary" size="large" @click="router.push(`/training/result/${sessionId}`)">
        查看结果与错题复盘
      </el-button>
    </div>

    <details v-if="session?.evidence_citations?.length" class="ots-card evidence-panel">
      <summary>查看本任务的 {{ session.evidence_citations.length }} 条权威教学依据</summary>
      <div v-for="item in session.evidence_citations" :key="item.knowledge_id" class="evidence-item">
        <strong>{{ item.title }}</strong>
        <span>{{ item.source_no }} · {{ item.chapter }}<template v-if="item.page"> · PDF 第 {{ item.page }} 页</template></span>
      </div>
    </details>
  </div>
</template>

<style scoped>
.choice-training { max-width: 980px; margin: 0 auto; }
.training-header h2 { margin: 0 0 6px; }
.training-header p { margin: 0; color: var(--ots-text-secondary); }
.header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.header-status { display: flex; align-items: center; gap: 14px; }
.header-status strong { color: var(--ots-primary-dark); font-size: 20px; }
.scenario-card { border-left: 4px solid var(--ots-primary); }
.section-kicker { color: var(--ots-primary-dark); font-size: 13px; font-weight: 700; margin-bottom: 8px; }
.scenario-card p { line-height: 1.7; margin: 0; }
.question-card { padding: 24px; }
.question-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.question-index { color: var(--ots-primary-dark); font-weight: 700; }
.knowledge-point { color: var(--ots-text-secondary); font-size: 13px; }
.question-stem { margin: 18px 0; font-size: 21px; line-height: 1.6; }
.option-list { display: grid; width: 100%; gap: 12px; }
.option-card { width: 100%; height: auto; min-height: 58px; margin: 0 !important; padding: 14px 18px; border-radius: 10px; }
.option-card:hover { border-color: var(--ots-primary); background: rgba(11, 95, 107, 0.04); }
.option-card.is-checked { background: rgba(11, 95, 107, 0.08); box-shadow: 0 0 0 1px var(--ots-primary); }
.option-key { display: inline-flex; width: 28px; height: 28px; border-radius: 50%; align-items: center; justify-content: center; background: var(--ots-bg); font-weight: 700; margin-right: 10px; }
.option-text { white-space: normal; line-height: 1.5; }
.submit-row { display: flex; justify-content: space-between; align-items: center; margin-top: 22px; padding-top: 16px; border-top: 1px solid var(--ots-border); color: var(--ots-text-secondary); font-size: 13px; }
.feedback-card { display: flex; align-items: center; gap: 18px; border: 1px solid; padding: 24px; }
.feedback-card.correct { border-color: #67c23a; background: #f0f9eb; }
.feedback-card.incorrect { border-color: #e6a23c; background: #fdf6ec; }
.feedback-icon, .finished-mark { width: 52px; height: 52px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: var(--ots-primary); color: white; font-size: 28px; font-weight: 800; flex-shrink: 0; }
.feedback-content { flex: 1; }
.feedback-content h3, .feedback-content p { margin: 0 0 8px; }
.feedback-content p { line-height: 1.6; }
.feedback-score { font-weight: 700; color: var(--ots-primary-dark); }
.finished-card { text-align: center; padding: 42px; }
.finished-mark { margin: 0 auto 14px; background: #67c23a; }
.evidence-panel summary { cursor: pointer; color: var(--ots-primary-dark); font-weight: 600; }
.evidence-item { display: flex; justify-content: space-between; gap: 16px; padding: 9px 0; border-bottom: 1px solid var(--ots-border); font-size: 13px; }
.evidence-item span { color: var(--ots-text-secondary); text-align: right; }
@media (max-width: 700px) {
  .header-row, .submit-row, .feedback-card { align-items: stretch; flex-direction: column; }
  .evidence-item { flex-direction: column; gap: 4px; }
  .evidence-item span { text-align: left; }
}
</style>
