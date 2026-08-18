<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { teacherApi } from '@/api'
import type {
  TeacherQuestionBankOut,
  TeacherQuestionOut,
  TeacherQuestionUpdateBody,
} from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.id)
const bank = ref<TeacherQuestionBankOut | null>(null)
const loading = ref(true)
const generating = ref(false)
const publishing = ref(false)
const saving = ref(false)
const selectedBatch = ref('')
const editVisible = ref(false)
const editingId = ref<number | null>(null)
const correctKey = ref('A')

const generateForm = reactive({
  count: 3,
  difficulty: 2,
  focusText: '',
  generationMode: 'ai' as 'ai' | 'local_rule',
  confirmExternal: false,
})
const editForm = reactive<TeacherQuestionUpdateBody>({
  stem: '', ability_key: 'safety_awareness', knowledge_point: '', explanation: '', options: [],
})

const currentBatch = computed(() => bank.value?.batches.find((item) => item.batch_code === selectedBatch.value) || null)
const currentQuestions = computed(() => (bank.value?.items || [])
  .filter((item) => item.batch_code === selectedBatch.value)
  .sort((a, b) => a.sort_order - b.sort_order))

function statusType(status: string) {
  return status === 'published' ? 'success' : status === 'draft' ? 'warning' : 'info'
}

function statusLabel(status: string) {
  return { published: '已发布', draft: '待审核', archived: '历史版本' }[status] || status
}

function providerLabel(provider?: string) {
  if (!provider) return '人工预置'
  if (provider === 'mock') return '离线模拟生成'
  return provider
}

async function loadBank(preferBatch = '') {
  loading.value = true
  try {
    bank.value = await teacherApi.taskQuestions(taskId)
    generateForm.difficulty = bank.value.task.difficulty
    generateForm.focusText ||= bank.value.task.required_points.join('\n')
    const available = bank.value.batches
    selectedBatch.value = preferBatch && available.some((item) => item.batch_code === preferBatch)
      ? preferBatch
      : available.find((item) => item.status === 'draft')?.batch_code
        || available.find((item) => item.status === 'published')?.batch_code
        || available[0]?.batch_code
        || ''
  } finally {
    loading.value = false
  }
}

async function generateQuestions() {
  generating.value = true
  try {
    const result = await teacherApi.generateTaskQuestions(taskId, {
      count: generateForm.count,
      difficulty: generateForm.difficulty,
      focus_points: generateForm.focusText.split('\n').map((item) => item.trim()).filter(Boolean),
      generation_mode: generateForm.generationMode,
      confirm_external: generateForm.generationMode === 'ai' && generateForm.confirmExternal,
    })
    await loadBank(result.batch_code)
    if (result.used_fallback) {
      ElMessage.warning(result.warning || '部分题目已用规则模板补齐，请重点审核')
    } else {
      ElMessage.success(`已生成 ${result.question_count} 道题库草稿，请逐题审核后发布`)
    }
  } finally {
    generating.value = false
  }
}

function openEdit(question: TeacherQuestionOut) {
  editingId.value = question.id
  editForm.stem = question.stem
  editForm.ability_key = question.ability_key
  editForm.knowledge_point = question.knowledge_point
  editForm.explanation = question.explanation
  editForm.options = question.options.map((option) => ({
    key: option.key,
    content: option.content,
    score: option.score,
    feedback: option.feedback,
    is_correct: option.is_correct,
  }))
  correctKey.value = editForm.options.find((item) => item.is_correct)?.key || 'A'
  editVisible.value = true
}

function changeCorrectKey(key: string) {
  for (const option of editForm.options) {
    option.is_correct = option.key === key
    if (option.is_correct) option.score = 100
    else if (option.score >= 100) option.score = 0
  }
}

async function saveQuestion() {
  if (!editingId.value) return
  changeCorrectKey(correctKey.value)
  saving.value = true
  try {
    await teacherApi.updateQuestion(editingId.value, editForm)
    editVisible.value = false
    await loadBank(selectedBatch.value)
    ElMessage.success('题目草稿已保存')
  } finally {
    saving.value = false
  }
}

async function publishBatch() {
  if (!currentBatch.value || currentBatch.value.status !== 'draft') return
  await ElMessageBox.confirm(
    `发布后，本任务当前题库将归档，学生新开始的实训使用这 ${currentBatch.value.question_count} 道题。是否确认？`,
    '审核发布题库',
    { type: 'warning', confirmButtonText: '确认发布', cancelButtonText: '继续审核' },
  )
  publishing.value = true
  try {
    await teacherApi.publishQuestionBatch(taskId, currentBatch.value.batch_code)
    await loadBank(currentBatch.value.batch_code)
    ElMessage.success('题库已审核发布，学生新实训将使用该版本')
  } finally {
    publishing.value = false
  }
}

onMounted(() => loadBank())
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <el-page-header @back="router.push('/teacher/tasks')" content="AI 题库生成与审核" />

    <div v-if="bank" class="task-hero ots-card">
      <div>
        <div class="eyebrow">{{ bank.task.code }} · 数据库选择题题库</div>
        <h2>{{ bank.task.title }}</h2>
        <div class="tags">
          <el-tag v-for="ability in bank.task.target_abilities" :key="ability" effect="plain">
            {{ ABILITY_LABELS[ability as AbilityKey] || ability }}
          </el-tag>
        </div>
      </div>
      <div class="hero-metrics">
        <div><strong>{{ bank.batches.length }}</strong><span>题库版本</span></div>
        <div><strong>{{ bank.batches.find((item) => item.status === 'published')?.question_count || 0 }}</strong><span>当前发布题数</span></div>
        <div><strong>{{ bank.evidence_citations.length }}</strong><span>权威依据</span></div>
      </div>
    </div>

    <el-row v-if="bank" :gutter="16">
      <el-col :xs="24" :lg="9">
        <div class="ots-card generate-panel">
          <h3 class="ots-title">生成新题库草稿</h3>
          <el-alert
            title="AI 只生成草稿。教师审核发布后学生才能使用，实训评分阶段不调用 AI。"
            type="info"
            :closable="false"
            show-icon
          />
          <el-form label-position="top" style="margin-top: 14px">
            <el-form-item label="生成方式">
              <el-radio-group v-model="generateForm.generationMode">
                <el-radio-button value="ai">AI 结合权威知识</el-radio-button>
                <el-radio-button value="local_rule">本地规则模板</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="生成题数">
                  <el-input-number v-model="generateForm.count" :min="1" :max="10" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="题目难度">
                  <el-input-number v-model="generateForm.difficulty" :min="1" :max="5" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="重点知识点（每行一个）">
              <el-input v-model="generateForm.focusText" type="textarea" :rows="6" />
            </el-form-item>
            <el-checkbox
              v-if="generateForm.generationMode === 'ai'"
              v-model="generateForm.confirmExternal"
              class="external-confirm"
            >
              我确认将本任务元数据及关联权威知识摘要发送至当前配置的外部模型服务，用于生成题库草稿。
            </el-checkbox>
            <el-alert
              v-else
              title="本地规则模板不会向外部模型发送任何数据。"
              type="success"
              :closable="false"
              show-icon
              style="margin-bottom: 12px"
            />
            <el-button
              type="primary"
              size="large"
              style="width: 100%"
              :loading="generating"
              :disabled="generateForm.generationMode === 'ai' && !generateForm.confirmExternal"
              @click="generateQuestions"
            >
              根据任务与权威知识生成草稿
            </el-button>
          </el-form>
        </div>

        <details class="ots-card evidence-panel">
          <summary>本任务生成时可引用的权威依据</summary>
          <div v-for="item in bank.evidence_citations" :key="item.knowledge_id" class="evidence-item">
            <strong>{{ item.title }}</strong>
            <span>{{ item.source_no }} · {{ item.chapter }} · PDF 第 {{ item.page }} 页</span>
          </div>
        </details>
      </el-col>

      <el-col :xs="24" :lg="15">
        <div class="ots-card">
          <div class="section-header">
            <div>
              <h3 class="ots-title">题库版本</h3>
              <span>选择草稿逐题审核，确认无误后发布整批</span>
            </div>
            <el-button
              v-if="currentBatch?.status === 'draft'"
              type="success"
              :loading="publishing"
              @click="publishBatch"
            >
              审核并发布本批题库
            </el-button>
          </div>
          <div class="batch-list">
            <button
              v-for="item in bank.batches"
              :key="item.batch_code"
              class="batch-item"
              :class="{ active: selectedBatch === item.batch_code }"
              @click="selectedBatch = item.batch_code"
            >
              <div>
                <strong>{{ item.batch_code === 'seed' ? '内置权威题库' : item.batch_code }}</strong>
                <el-tag :type="statusType(item.status)" size="small">{{ statusLabel(item.status) }}</el-tag>
              </div>
              <span>{{ item.question_count }} 题 · {{ providerLabel(item.generation_meta.provider) }}</span>
            </button>
          </div>
        </div>

        <el-alert
          v-if="currentBatch?.generation_meta.warning"
          :title="currentBatch.generation_meta.warning"
          type="warning"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        />

        <div v-for="(question, index) in currentQuestions" :key="question.id" class="ots-card question-review">
          <div class="question-heading">
            <span class="question-no">{{ index + 1 }}</span>
            <div>
              <div class="question-code">{{ question.code }}</div>
              <h3>{{ question.stem }}</h3>
            </div>
            <el-button v-if="question.status === 'draft'" type="primary" plain @click="openEdit(question)">审核编辑</el-button>
          </div>
          <div class="question-meta">
            <el-tag size="small">{{ ABILITY_LABELS[question.ability_key as AbilityKey] || question.ability_key }}</el-tag>
            <el-tag size="small" type="info" effect="plain">{{ question.knowledge_point }}</el-tag>
            <el-tag v-if="question.generated_by_ai" size="small" type="warning" effect="dark">
              AI 生成内容 · 发布前须教师审核
            </el-tag>
            <span v-if="question.reviewed_at">教师审核：{{ new Date(question.reviewed_at).toLocaleString('zh-CN') }}</span>
          </div>
          <div class="option-preview">
            <div v-for="option in question.options" :key="option.id" :class="['option-line', { correct: option.is_correct }]">
              <strong>{{ option.key }}</strong>
              <span>{{ option.content }}</span>
              <el-tag :type="option.is_correct ? 'success' : option.score > 0 ? 'warning' : 'info'" size="small">
                {{ option.score }} 分<span v-if="option.is_correct"> · 正确</span>
              </el-tag>
            </div>
          </div>
          <details class="explanation"><summary>查看题目解析</summary><p>{{ question.explanation }}</p></details>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="editVisible" title="审核并编辑题目草稿" width="820px" destroy-on-close>
      <el-form :model="editForm" label-position="top">
        <el-form-item label="题干"><el-input v-model="editForm.stem" type="textarea" :rows="3" /></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="能力维度">
              <el-select v-model="editForm.ability_key" style="width: 100%">
                <el-option v-for="(label, key) in ABILITY_LABELS" :key="key" :label="label" :value="key" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="知识点"><el-input v-model="editForm.knowledge_point" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="正确答案">
          <el-radio-group v-model="correctKey" @change="changeCorrectKey">
            <el-radio-button v-for="option in editForm.options" :key="option.key" :value="option.key">{{ option.key }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <div v-for="option in editForm.options" :key="option.key" class="option-editor">
          <div class="option-editor-head">
            <strong>{{ option.key }} 选项</strong>
            <el-input-number v-model="option.score" :min="0" :max="option.key === correctKey ? 100 : 80" :disabled="option.key === correctKey" />
          </div>
          <el-input v-model="option.content" placeholder="选项内容" />
          <el-input v-model="option.feedback" placeholder="学生选择后的教学反馈" />
        </div>
        <el-form-item label="题目解析"><el-input v-model="editForm.explanation" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveQuestion">保存审核修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.task-hero { display: flex; justify-content: space-between; align-items: center; }
.eyebrow, .section-header span { color: var(--ots-text-secondary); font-size: 13px; }
.task-hero h2 { margin: 6px 0 12px; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; }
.hero-metrics { display: flex; gap: 30px; }
.hero-metrics div { text-align: center; }
.hero-metrics strong { display: block; font-size: 30px; color: var(--ots-primary-dark); }
.hero-metrics span { color: var(--ots-text-secondary); font-size: 12px; }
.evidence-panel summary { cursor: pointer; font-weight: 700; color: var(--ots-primary-dark); }
.evidence-item { display: grid; gap: 4px; padding: 9px 0; border-bottom: 1px solid var(--ots-border); font-size: 12px; }
.evidence-item span { color: var(--ots-text-secondary); }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.section-header .ots-title { margin: 0 0 4px; }
.batch-list { display: grid; gap: 8px; }
.batch-item { width: 100%; padding: 11px 13px; border: 1px solid var(--ots-border); border-radius: 8px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.batch-item.active, .batch-item:hover { border-color: var(--ots-primary); background: rgba(11, 95, 107, 0.06); }
.batch-item div { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.batch-item span { display: block; margin-top: 5px; color: var(--ots-text-secondary); font-size: 12px; }
.question-heading { display: grid; grid-template-columns: 38px 1fr auto; gap: 12px; align-items: start; }
.question-no { width: 34px; height: 34px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--ots-primary); color: white; font-weight: 700; }
.question-code { color: var(--ots-text-secondary); font-size: 12px; }
.question-heading h3 { margin: 4px 0 0; line-height: 1.55; }
.question-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 12px 0; font-size: 12px; color: var(--ots-text-secondary); }
.option-preview { display: grid; gap: 8px; }
.option-line { display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; background: var(--ots-bg); border-radius: 7px; border: 1px solid transparent; }
.option-line.correct { border-color: #67c23a; background: #f0f9eb; }
.explanation { margin-top: 12px; color: var(--ots-text-secondary); }
.explanation summary { cursor: pointer; }
.explanation p { line-height: 1.7; }
.option-editor { display: grid; gap: 7px; padding: 12px; margin-bottom: 10px; border: 1px solid var(--ots-border); border-radius: 8px; }
.option-editor-head { display: flex; justify-content: space-between; align-items: center; }
.external-confirm { height: auto; white-space: normal; align-items: flex-start; margin-bottom: 12px; line-height: 1.5; }
@media (max-width: 800px) {
  .task-hero { align-items: flex-start; flex-direction: column; gap: 18px; }
  .hero-metrics { width: 100%; justify-content: space-around; }
}
</style>
