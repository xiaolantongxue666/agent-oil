<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { teacherApi } from '@/api'
import type {
  TeacherTrainingAnalysisOut,
  TeacherTrainingResultOut,
  TeachingPlanOut,
} from '@/types'

const loading = ref(true)
const generating = ref(false)
const saving = ref(false)
const className = ref('')
const results = ref<TeacherTrainingResultOut[]>([])
const allResults = ref<TeacherTrainingResultOut[]>([])
const analysis = ref<TeacherTrainingAnalysisOut | null>(null)
const plans = ref<TeachingPlanOut[]>([])
const activePlan = ref<TeachingPlanOut | null>(null)

const classOptions = computed(() => Array.from(new Set(
  allResults.value.map((item) => item.class_name).filter(Boolean),
)).sort())

function scoreColor(score: number) {
  if (score >= 80) return '#2e7d32'
  if (score >= 60) return '#0b5f6b'
  return '#c62828'
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function statusLabel(status: string) {
  return { draft: '草稿', active: '执行中', completed: '已完成' }[status] || status
}

function priorityLabel(priority: string) {
  return { high: '高', medium: '中', low: '低' }[priority] || priority
}

async function loadData() {
  loading.value = true
  try {
    const [resultData, analysisData, planData] = await Promise.all([
      teacherApi.trainingResults(className.value),
      teacherApi.trainingAnalysis(className.value),
      teacherApi.teachingPlans(),
    ])
    results.value = resultData
    analysis.value = analysisData
    plans.value = planData
    if (!activePlan.value && plans.value.length) activePlan.value = structuredClone(plans.value[0])
  } finally {
    loading.value = false
  }
}

async function loadInitial() {
  try {
    allResults.value = await teacherApi.trainingResults()
  } catch {
    allResults.value = []
  }
  await loadData()
}

async function generatePlan() {
  generating.value = true
  try {
    const plan = await teacherApi.generateTeachingPlan({ class_name: className.value })
    plans.value.unshift(plan)
    activePlan.value = structuredClone(plan)
    ElMessage.success('已依据班级实训数据生成课堂实施改进计划')
  } finally {
    generating.value = false
  }
}

function selectPlan(plan: TeachingPlanOut) {
  activePlan.value = structuredClone(plan)
}

async function savePlan() {
  if (!activePlan.value) return
  saving.value = true
  try {
    const updated = await teacherApi.updateTeachingPlan(activePlan.value.id, {
      title: activePlan.value.title,
      status: activePlan.value.status,
      actions: activePlan.value.actions,
      notes: activePlan.value.notes,
    })
    const index = plans.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) plans.value[index] = updated
    activePlan.value = structuredClone(updated)
    ElMessage.success('班级实施改进计划已保存')
  } finally {
    saving.value = false
  }
}

onMounted(loadInitial)
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <div class="page-header">
      <div>
        <h2>班级教学实施复盘</h2>
        <p>依据班级能力短板和高频错题调整课堂重点、分层辅导和实训组织，不在此修改专业培养方案。</p>
      </div>
      <div class="filter-actions">
        <el-select v-model="className" clearable placeholder="全部班级" style="width: 180px" @change="loadData">
          <el-option v-for="item in classOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-button @click="loadData">刷新最新数据</el-button>
        <el-button type="primary" :loading="generating" @click="generatePlan">生成班级实施改进计划</el-button>
      </div>
    </div>

    <div v-if="analysis" class="summary-grid">
      <div class="ots-card metric-card">
        <span>参与学生</span><strong>{{ analysis.summary.student_count }}</strong><small>人</small>
      </div>
      <div class="ots-card metric-card">
        <span>完成实训</span><strong>{{ analysis.summary.completed_count }}</strong><small>次</small>
      </div>
      <div class="ots-card metric-card">
        <span>平均成绩</span><strong :style="{ color: scoreColor(analysis.summary.average_score) }">{{ analysis.summary.average_score }}</strong><small>分</small>
      </div>
      <div class="ots-card metric-card">
        <span>及格率</span><strong>{{ analysis.summary.pass_rate }}%</strong><small>≥60分</small>
      </div>
    </div>

    <el-row v-if="analysis" :gutter="16">
      <el-col :xs="24" :lg="12">
        <div class="ots-card insight-card">
          <h3 class="ots-title">能力维度表现</h3>
          <div v-if="analysis.ability_summary.length" class="ability-list">
            <div v-for="item in analysis.ability_summary" :key="item.key" class="ability-row">
              <span>{{ item.name }}</span>
              <el-progress
                :percentage="item.average_score"
                :stroke-width="10"
                :color="scoreColor(item.average_score)"
              />
              <strong>{{ item.average_score }}</strong>
            </div>
          </div>
          <el-empty v-else description="暂无能力评分数据" :image-size="60" />
        </div>
      </el-col>
      <el-col :xs="24" :lg="12">
        <div class="ots-card insight-card">
          <h3 class="ots-title">高频错题与知识薄弱点</h3>
          <el-table v-if="analysis.common_errors.length" :data="analysis.common_errors.slice(0, 5)" size="small">
            <el-table-column prop="knowledge_point" label="知识点" width="130" />
            <el-table-column prop="stem" label="题目" min-width="210" show-overflow-tooltip />
            <el-table-column label="错误率" width="90" align="right">
              <template #default="{ row }"><strong class="danger-text">{{ row.wrong_rate }}%</strong></template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无错题数据" :image-size="60" />
        </div>
      </el-col>
    </el-row>

    <div class="ots-card">
      <div class="section-header">
        <h3 class="ots-title">学生实训明细</h3>
        <span>共 {{ results.length }} 条已完成记录</span>
      </div>
      <el-table :data="results" stripe>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="answer-review">
              <div
                v-for="answer in row.answer_records"
                :key="answer.question_code"
                class="answer-item"
                :class="answer.is_correct ? 'right' : 'wrong'"
              >
                <div><strong>{{ answer.question_code }}</strong> {{ answer.stem }}</div>
                <div class="answer-meta">
                  选择 {{ answer.selected_option }}. {{ answer.selected_content }} · {{ answer.score }} 分
                </div>
                <div v-if="!answer.is_correct" class="answer-feedback">{{ answer.feedback }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="student_name" label="学生" width="110" />
        <el-table-column prop="student_no" label="学号" width="130" />
        <el-table-column prop="class_name" label="班级" width="120" />
        <el-table-column prop="task_title" label="实训任务" min-width="210" />
        <el-table-column label="成绩" width="90" align="center">
          <template #default="{ row }"><strong :style="{ color: scoreColor(row.final_score) }">{{ row.final_score }}</strong></template>
        </el-table-column>
        <el-table-column label="正确率" width="100" align="center">
          <template #default="{ row }">{{ row.correct_count }}/{{ row.question_count }}</template>
        </el-table-column>
        <el-table-column prop="weakest_ability_name" label="待加强能力" width="120">
          <template #default="{ row }">{{ row.weakest_ability_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="180">
          <template #default="{ row }">{{ formatDate(row.finished_at) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div class="plan-layout">
      <div class="ots-card plan-list">
        <div class="section-header">
          <h3 class="ots-title">班级实施计划记录</h3>
          <el-tag size="small">{{ plans.length }}</el-tag>
        </div>
        <el-empty v-if="!plans.length" description="尚未生成方案" :image-size="55" />
        <button
          v-for="plan in plans"
          :key="plan.id"
          class="plan-list-item"
          :class="{ active: activePlan?.id === plan.id }"
          @click="selectPlan(plan)"
        >
          <strong>{{ plan.title }}</strong>
          <span>{{ plan.class_name || '全部班级' }} · {{ statusLabel(plan.status) }}</span>
          <small>{{ formatDate(plan.updated_at) }}</small>
        </button>
      </div>

      <div v-if="activePlan" class="ots-card plan-editor">
        <div class="section-header">
          <h3 class="ots-title">编辑班级实施改进计划</h3>
          <el-button type="primary" :loading="saving" @click="savePlan">保存调整</el-button>
        </div>
        <el-form label-position="top">
          <el-row :gutter="14">
            <el-col :xs="24" :md="17">
              <el-form-item label="方案名称"><el-input v-model="activePlan.title" /></el-form-item>
            </el-col>
            <el-col :xs="24" :md="7">
              <el-form-item label="执行状态">
                <el-select v-model="activePlan.status" style="width: 100%">
                  <el-option label="草稿" value="draft" />
                  <el-option label="执行中" value="active" />
                  <el-option label="已完成" value="completed" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <div class="action-title">教学动作（可按班级实际情况修改）</div>
          <div v-for="action in activePlan.actions" :key="action.id" class="teaching-action">
            <div class="action-heading">
              <el-tag :type="action.priority === 'high' ? 'danger' : 'warning'" size="small">
                {{ priorityLabel(action.priority) }}优先级
              </el-tag>
              <strong>{{ action.target }}</strong>
              <el-checkbox v-model="action.completed">已落实</el-checkbox>
            </div>
            <p>{{ action.reason }}</p>
            <el-input v-model="action.strategy" type="textarea" :rows="2" />
          </div>
          <el-form-item label="教师补充说明">
            <el-input v-model="activePlan.notes" type="textarea" :rows="3" placeholder="补充课时、分组、资源和复测安排" />
          </el-form-item>
        </el-form>
        <div class="snapshot-note">
          数据快照：{{ formatDate(activePlan.analysis_snapshot.generated_at) }}；新实训数据产生后可再次生成新版本，历史方案不会被覆盖。
        </div>
      </div>
      <div v-else class="ots-card plan-editor empty-plan">
        <el-empty description="点击“生成班级实施改进计划”建立首个复盘记录" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; gap: 16px; }
.page-header h2 { margin: 0 0 6px; }
.page-header p { margin: 0; color: var(--ots-text-secondary); }
.filter-actions { display: flex; gap: 10px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.metric-card { display: grid; grid-template-columns: 1fr auto; align-items: end; }
.metric-card span { grid-column: 1 / -1; color: var(--ots-text-secondary); font-size: 13px; }
.metric-card strong { font-size: 34px; color: var(--ots-primary-dark); }
.metric-card small { margin: 0 0 5px 6px; color: var(--ots-text-secondary); }
.insight-card { min-height: 295px; }
.ability-list { display: flex; flex-direction: column; gap: 15px; }
.ability-row { display: grid; grid-template-columns: 84px 1fr 40px; gap: 10px; align-items: center; }
.ability-row > strong { text-align: right; }
.danger-text { color: #c62828; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.section-header .ots-title { margin: 0; }
.section-header > span { color: var(--ots-text-secondary); font-size: 13px; }
.answer-review { padding: 4px 22px; display: grid; gap: 8px; }
.answer-item { padding: 10px 12px; border-left: 3px solid; background: var(--ots-bg); }
.answer-item.right { border-color: #67c23a; }
.answer-item.wrong { border-color: #e6a23c; }
.answer-meta, .answer-feedback { color: var(--ots-text-secondary); font-size: 13px; margin-top: 5px; }
.answer-feedback { color: #8a5a00; }
.plan-layout { display: grid; grid-template-columns: 280px 1fr; gap: 16px; align-items: start; }
.plan-list-item { display: flex; flex-direction: column; width: 100%; text-align: left; gap: 5px; padding: 12px; margin-bottom: 8px; border: 1px solid var(--ots-border); border-radius: 8px; background: transparent; cursor: pointer; color: inherit; }
.plan-list-item:hover, .plan-list-item.active { border-color: var(--ots-primary); background: rgba(11, 95, 107, 0.06); }
.plan-list-item span, .plan-list-item small { color: var(--ots-text-secondary); }
.action-title { font-weight: 700; margin: 4px 0 12px; }
.teaching-action { border: 1px solid var(--ots-border); border-radius: 9px; padding: 14px; margin-bottom: 12px; }
.action-heading { display: flex; align-items: center; gap: 10px; }
.action-heading .el-checkbox { margin-left: auto; }
.teaching-action p { color: var(--ots-text-secondary); margin: 9px 0; font-size: 13px; }
.snapshot-note { border-top: 1px solid var(--ots-border); padding-top: 12px; color: var(--ots-text-secondary); font-size: 12px; }
.empty-plan { min-height: 300px; display: flex; align-items: center; justify-content: center; }
@media (max-width: 1000px) {
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .plan-layout { grid-template-columns: 1fr; }
  .page-header { flex-direction: column; }
}
@media (max-width: 650px) {
  .filter-actions { flex-wrap: wrap; }
  .summary-grid { grid-template-columns: 1fr; }
}
</style>
