<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { programApi } from '@/api'
import { ABILITY_LABELS } from '@/types'
import type {
  CurriculumProgramOut,
  IndustryEvidenceOut,
  ProgramAnalysisOut,
  ProgramProposalOut,
} from '@/types'

const loading = ref(true)
const analyzing = ref(false)
const publishing = ref(false)
const activeTab = ref('insight')
const months = ref(12)
const programs = ref<CurriculumProgramOut[]>([])
const currentProgram = ref<CurriculumProgramOut | null>(null)
const analysis = ref<ProgramAnalysisOut | null>(null)
const evidence = ref<IndustryEvidenceOut[]>([])
const proposals = ref<ProgramProposalOut[]>([])
const activeProposal = ref<ProgramProposalOut | null>(null)
const evidenceDialog = ref(false)
const evidenceForm = reactive({
  major: '油气储运工程',
  title: '',
  source_name: '',
  source_type: 'industry_report',
  source_no: '',
  source_url: '',
  published_at: null as string | null,
  summary: '',
  themesText: '',
  skillsText: '',
  confidence: 'medium' as 'low' | 'medium' | 'high',
  enabled: true,
})

const currentVersions = computed(() => programs.value.filter((item) => item.status === 'published'))

function statusText(value: string) {
  return { published: '当前版本', archived: '历史版本', draft: '草案', reviewed: '已审核', rejected: '已驳回' }[value] || value
}

// 草案状态统一术语（系统实际状态仅有 草案/已审核/已驳回/已发布，不造「待审核」等不存在的状态）
function proposalStatusText(value: string) {
  return { draft: '草案', reviewed: '已审核', rejected: '已驳回', published: '已发布' }[value] || value
}

function confidenceText(value: string) {
  return { high: '高', medium: '中', low: '低' }[value] || value
}

function splitTerms(value: string) {
  return value.split(/[，,、;；\n]/).map((item) => item.trim()).filter(Boolean)
}

async function loadBase() {
  loading.value = true
  try {
    const [programData, evidenceData, proposalData] = await Promise.all([
      programApi.programs(),
      programApi.evidence(),
      programApi.proposals(),
    ])
    programs.value = programData
    evidence.value = evidenceData
    proposals.value = proposalData
    const latest = currentVersions.value[0] || programs.value[0] || null
    if (!currentProgram.value || !programs.value.some((item) => item.id === currentProgram.value?.id)) {
      currentProgram.value = latest
    } else {
      currentProgram.value = programs.value.find((item) => item.id === currentProgram.value?.id) || latest
    }
    activeProposal.value = proposals.value.find((item) => item.status !== 'published') || proposals.value[0] || null
    if (currentProgram.value) await loadAnalysis()
  } finally {
    loading.value = false
  }
}

async function loadAnalysis() {
  if (!currentProgram.value) return
  analyzing.value = true
  try {
    analysis.value = await programApi.analysis(currentProgram.value.id, months.value)
  } finally {
    analyzing.value = false
  }
}

async function changeProgram(programId: number) {
  currentProgram.value = programs.value.find((item) => item.id === programId) || null
  await loadAnalysis()
}

async function addEvidence() {
  if (!evidenceForm.title.trim()) {
    ElMessage.warning('请填写证据标题')
    return
  }
  await programApi.addEvidence({
    major: evidenceForm.major,
    title: evidenceForm.title.trim(),
    source_name: evidenceForm.source_name.trim(),
    source_type: evidenceForm.source_type,
    source_no: evidenceForm.source_no.trim(),
    source_url: evidenceForm.source_url.trim(),
    published_at: evidenceForm.published_at,
    summary: evidenceForm.summary.trim(),
    themes: splitTerms(evidenceForm.themesText),
    skills: splitTerms(evidenceForm.skillsText),
    confidence: evidenceForm.confidence,
    enabled: evidenceForm.enabled,
  })
  evidenceDialog.value = false
  evidenceForm.title = ''
  evidenceForm.source_name = ''
  evidenceForm.source_no = ''
  evidenceForm.source_url = ''
  evidenceForm.summary = ''
  evidenceForm.themesText = ''
  evidenceForm.skillsText = ''
  ElMessage.success('产业证据已加入分析范围')
  await loadBase()
}

async function toggleEvidence(item: IndustryEvidenceOut) {
  await programApi.updateEvidence(item.id, { enabled: !item.enabled })
  item.enabled = !item.enabled
  await loadAnalysis()
}

async function createProposal() {
  if (!currentProgram.value || currentProgram.value.status !== 'published') {
    ElMessage.warning('请选择当前已发布的培养方案版本')
    return
  }
  const created = await programApi.createProposal(currentProgram.value.id, months.value)
  activeProposal.value = structuredClone(created)
  proposals.value.unshift(created)
  activeTab.value = 'proposal'
  ElMessage.success('已按当前产业岗位证据生成调整草案')
}

async function saveProposal(reviewed = false) {
  if (!activeProposal.value) return
  const updated = await programApi.updateProposal(activeProposal.value.id, {
    title: activeProposal.value.title,
    actions: activeProposal.value.actions,
    review_note: activeProposal.value.review_note,
    status: reviewed ? 'reviewed' : 'draft',
  })
  activeProposal.value = structuredClone(updated)
  ElMessage.success(reviewed ? '教师审核已记录' : '草案已保存')
}

async function publishProposal() {
  if (!activeProposal.value) return
  await ElMessageBox.confirm(
    '确认已核验岗位招聘、产业证据和调整行动？发布后将生成新的培养方案版本，旧版本保留用于追溯。',
    '发布培养方案新版本',
    { confirmButtonText: '确认发布', cancelButtonText: '取消', type: 'warning' },
  )
  publishing.value = true
  try {
    await saveProposal(true)
    await programApi.publishProposal(activeProposal.value.id)
    ElMessage.success('培养方案新版本已发布')
    await loadBase()
    activeTab.value = 'curriculum'
  } finally {
    publishing.value = false
  }
}

onMounted(loadBase)
</script>

<template>
  <div v-loading="loading" class="program-page">
    <div class="page-head">
      <div>
        <h2>培养方案与调整</h2>
        <p>Gap 分析 → 调整草案 → 教师审核：岗位动态与产业证据驱动培养方案版本演进；学生成绩不进入本模块。</p>
      </div>
      <div class="head-actions">
        <el-select
          v-if="currentProgram"
          :model-value="currentProgram.id"
          style="width: 270px"
          @change="changeProgram"
        >
          <el-option
            v-for="item in programs"
            :key="item.id"
            :label="`${item.name} V${item.version} · ${statusText(item.status)}`"
            :value="item.id"
          />
        </el-select>
        <el-select v-model="months" style="width: 125px" @change="loadAnalysis">
          <el-option :value="6" label="近 6 个月" />
          <el-option :value="12" label="近 12 个月" />
          <el-option :value="24" label="近 24 个月" />
          <el-option :value="36" label="近 36 个月" />
        </el-select>
        <el-button type="primary" :loading="analyzing" @click="loadAnalysis">重新分析</el-button>
      </div>
    </div>

    <el-alert
      title="专业培养方案数据边界"
      type="info"
      :closable="false"
      show-icon
      description="本页只读取岗位招聘发布时间、岗位能力图谱、教师审核的产业资料和权威知识来源；班级实训结果仅用于教学实施复盘，个人实训结果仅用于学生自适应学习。"
    />

    <el-tabs v-model="activeTab" class="main-tabs">
      <el-tab-pane label="岗位证据分析" name="insight">
        <template v-if="analysis">
          <div class="metric-grid">
            <div class="metric"><span>关联岗位</span><strong>{{ analysis.summary.position_count }}</strong></div>
            <div class="metric"><span>有效招聘样本</span><strong>{{ analysis.summary.job_sample_count }}</strong></div>
            <div class="metric"><span>发布时间覆盖</span><strong>{{ analysis.summary.job_sample_month_count }} 个月</strong></div>
            <div class="metric"><span>产业资料</span><strong>{{ analysis.summary.industry_evidence_count }}</strong></div>
            <div class="metric"><span>权威标准证据</span><strong>{{ analysis.summary.authoritative_evidence_count }}</strong></div>
            <div class="metric"><span>实践学时占比</span><strong>{{ analysis.summary.practice_ratio }}%</strong></div>
            <div class="metric"><span>分析置信度</span><strong>{{ confidenceText(analysis.summary.confidence) }}</strong></div>
          </div>
          <el-alert
            :title="`置信度判定依据：${analysis.summary.confidence_basis}`"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          />

          <div class="panel-grid">
            <el-card shadow="never">
              <template #header><b>岗位需求—课程能力覆盖差距</b></template>
              <el-table :data="analysis.ability_gaps" size="small">
                <el-table-column prop="ability_name" label="能力" min-width="110" />
                <el-table-column prop="demand_share" label="岗位需求占比" width="120">
                  <template #default="{ row }">{{ row.demand_share }}%</template>
                </el-table-column>
                <el-table-column prop="curriculum_share" label="课程覆盖占比" width="120">
                  <template #default="{ row }">{{ row.curriculum_share }}%</template>
                </el-table-column>
                <el-table-column prop="gap" label="差距" width="100">
                  <template #default="{ row }">
                    <el-tag :type="row.gap > 5 ? 'danger' : row.gap > 1.5 ? 'warning' : 'success'">
                      {{ row.gap > 0 ? '+' : '' }}{{ row.gap }}%
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
            <el-card shadow="never">
              <template #header><b>岗位样本覆盖</b></template>
              <el-table :data="analysis.positions" size="small">
                <el-table-column prop="name" label="岗位" min-width="170" />
                <el-table-column prop="sample_count" label="样本" width="70" />
                <el-table-column prop="graph_version" label="图谱版本" width="90" />
              </el-table>
            </el-card>
          </div>

          <el-card shadow="never" class="term-card">
            <template #header>
              <div class="card-head"><b>近期高频技能与未覆盖技能</b><span>来自发布日期落入分析窗口的招聘样本</span></div>
            </template>
            <div class="term-row">
              <div><label>高频技能</label><el-tag v-for="item in analysis.top_skills" :key="item.name" class="term">{{ item.name }} {{ item.count }}</el-tag></div>
              <div><label>课程待覆盖</label><el-tag v-for="item in analysis.uncovered_skills" :key="item.name" class="term" type="warning">{{ item.name }} {{ item.count }}</el-tag><span v-if="!analysis.uncovered_skills.length" class="muted">暂无显著缺口</span></div>
            </div>
          </el-card>

          <div class="section-head">
            <div><h3>产业分析证据</h3><p>教师可维护产业政策、行业报告、企业技术路线等资料，并控制是否进入分析。</p></div>
            <el-button @click="evidenceDialog = true">添加产业证据</el-button>
          </div>
          <el-table :data="evidence" border>
            <el-table-column prop="title" label="证据标题" min-width="220" />
            <el-table-column prop="source_name" label="来源" min-width="140" />
            <el-table-column prop="source_no" label="编号" min-width="120" />
            <el-table-column prop="source_type" label="类型" width="120" />
            <el-table-column prop="confidence" label="置信度" width="90">
              <template #default="{ row }">{{ confidenceText(row.confidence) }}</template>
            </el-table-column>
            <el-table-column label="进入分析" width="105">
              <template #default="{ row }"><el-switch :model-value="row.enabled" @change="toggleEvidence(row)" /></template>
            </el-table-column>
          </el-table>
          <div class="proposal-cta">
            <div><b>证据核验完成后生成调整草案</b><p>草案不会自动发布，教师可逐项修改、审核并决定是否形成新版本。</p></div>
            <el-button type="primary" @click="createProposal">生成培养方案调整草案</el-button>
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="培养方案版本" name="curriculum">
        <template v-if="currentProgram">
          <el-descriptions :column="3" border>
            <el-descriptions-item label="方案">{{ currentProgram.name }}</el-descriptions-item>
            <el-descriptions-item label="版本">V{{ currentProgram.version }}</el-descriptions-item>
            <el-descriptions-item label="状态"><el-tag>{{ statusText(currentProgram.status) }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="培养目标" :span="3">{{ currentProgram.objectives }}</el-descriptions-item>
            <el-descriptions-item label="本版变更" :span="3">{{ currentProgram.change_summary || '基线版本' }}</el-descriptions-item>
          </el-descriptions>
          <el-table :data="currentProgram.courses" border class="course-table">
            <el-table-column prop="course_code" label="课程代码" width="105" />
            <el-table-column prop="name" label="课程名称" min-width="170" />
            <el-table-column prop="category" label="类别" width="110" />
            <el-table-column prop="total_hours" label="总学时" width="80" />
            <el-table-column prop="practice_hours" label="实践学时" width="90" />
            <el-table-column prop="practice_ratio" label="实践占比" width="90"><template #default="{ row }">{{ row.practice_ratio }}%</template></el-table-column>
            <el-table-column label="能力覆盖" min-width="260">
              <template #default="{ row }">
                <el-tag v-for="(weight, key) in row.ability_weights" :key="key" class="term" effect="plain">{{ ABILITY_LABELS[String(key) as keyof typeof ABILITY_LABELS] || key }} {{ Math.round(Number(weight) * 100) }}%</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="知识模块" min-width="220"><template #default="{ row }">{{ row.knowledge_points.join('、') }}</template></el-table-column>
          </el-table>
        </template>
      </el-tab-pane>

      <el-tab-pane label="调整草案工作台" name="proposal">
        <div class="proposal-select">
          <el-select v-model="activeProposal" value-key="id" placeholder="选择草案" style="width: 360px">
            <el-option v-for="item in proposals" :key="item.id" :label="`${item.title} · ${proposalStatusText(item.status)}`" :value="item" />
          </el-select>
        </div>
        <el-empty v-if="!activeProposal" description="尚无调整草案，请先从产业岗位洞察生成" />
        <template v-else>
          <el-card shadow="never">
            <el-form label-position="top">
              <el-form-item label="草案标题"><el-input v-model="activeProposal.title" :disabled="activeProposal.status === 'published'" /></el-form-item>
              <el-form-item label="教师审核意见"><el-input v-model="activeProposal.review_note" type="textarea" :rows="3" :disabled="activeProposal.status === 'published'" placeholder="记录证据核验、专业委员会讨论或修改依据" /></el-form-item>
            </el-form>
          </el-card>
          <el-table :data="activeProposal.actions" border class="action-table">
            <el-table-column prop="priority" label="优先级" width="90">
              <template #default="{ row }"><el-select v-model="row.priority" :disabled="activeProposal?.status === 'published'"><el-option label="高" value="high" /><el-option label="中" value="medium" /><el-option label="低" value="low" /></el-select></template>
            </el-table-column>
            <el-table-column prop="target" label="调整对象" min-width="130"><template #default="{ row }"><el-input v-model="row.target" :disabled="activeProposal?.status === 'published'" /></template></el-table-column>
            <el-table-column prop="reason" label="证据理由" min-width="240"><template #default="{ row }"><el-input v-model="row.reason" type="textarea" :rows="2" :disabled="activeProposal?.status === 'published'" /></template></el-table-column>
            <el-table-column prop="suggestion" label="调整建议" min-width="260"><template #default="{ row }"><el-input v-model="row.suggestion" type="textarea" :rows="2" :disabled="activeProposal?.status === 'published'" /></template></el-table-column>
            <el-table-column prop="hours_delta" label="建议学时" width="105"><template #default="{ row }"><el-input-number v-model="row.hours_delta" :min="0" :max="40" :disabled="activeProposal?.status === 'published'" controls-position="right" /></template></el-table-column>
          </el-table>
          <div class="proposal-actions" v-if="activeProposal.status !== 'published'">
            <el-button @click="saveProposal(false)">保存草案</el-button>
            <el-button type="success" @click="saveProposal(true)">记录教师审核</el-button>
            <el-button type="primary" :loading="publishing" @click="publishProposal">发布为 V{{ activeProposal.target_version }}</el-button>
          </div>
        </template>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="evidenceDialog" title="添加产业分析证据" width="680px">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="证据标题" class="span-2"><el-input v-model="evidenceForm.title" /></el-form-item>
          <el-form-item label="发布/主管机构"><el-input v-model="evidenceForm.source_name" /></el-form-item>
          <el-form-item label="文件或报告编号"><el-input v-model="evidenceForm.source_no" /></el-form-item>
          <el-form-item label="证据类型"><el-select v-model="evidenceForm.source_type" style="width:100%"><el-option label="产业政策" value="policy" /><el-option label="行业标准" value="standard" /><el-option label="产业报告" value="industry_report" /><el-option label="企业技术资料" value="enterprise" /></el-select></el-form-item>
          <el-form-item label="发布日期"><el-date-picker v-model="evidenceForm.published_at" type="date" value-format="YYYY-MM-DDTHH:mm:ssZ" style="width:100%" /></el-form-item>
          <el-form-item label="来源网址" class="span-2"><el-input v-model="evidenceForm.source_url" /></el-form-item>
          <el-form-item label="产业主题（逗号分隔）"><el-input v-model="evidenceForm.themesText" /></el-form-item>
          <el-form-item label="涉及技能（逗号分隔）"><el-input v-model="evidenceForm.skillsText" /></el-form-item>
          <el-form-item label="内容摘要" class="span-2"><el-input v-model="evidenceForm.summary" type="textarea" :rows="3" /></el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="evidenceDialog = false">取消</el-button><el-button type="primary" @click="addEvidence">保存并启用</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.program-page { display: flex; flex-direction: column; gap: 16px; }
.page-head, .head-actions, .section-head, .card-head, .proposal-cta, .proposal-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2, h3, p { margin: 0; }
.page-head p, .section-head p, .proposal-cta p, .card-head span, .muted { color: var(--el-text-color-secondary); font-size: 13px; margin-top: 6px; }
.main-tabs { background: #fff; border: 1px solid var(--ots-border); border-radius: 10px; padding: 6px 16px 18px; }
.metric-grid { display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 12px; margin-bottom: 14px; }
.metric { padding: 16px; border-radius: 8px; background: linear-gradient(135deg, #f3faf9, #f7f9fc); border: 1px solid #d9ebe8; display: flex; flex-direction: column; gap: 8px; }
.metric span { color: var(--el-text-color-secondary); font-size: 13px; }
.metric strong { color: var(--ots-primary-dark); font-size: 24px; }
.panel-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; }
.term-card, .course-table, .action-table, .section-head, .proposal-cta { margin-top: 16px; }
.term-row { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.term-row label { display: block; font-weight: 600; margin-bottom: 8px; }
.term { margin: 3px 6px 3px 0; }
.proposal-cta { padding: 18px; border: 1px solid #b9ded7; background: #f0faf8; border-radius: 8px; }
.proposal-select { margin-bottom: 14px; }
.proposal-actions { justify-content: flex-end; margin-top: 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.span-2 { grid-column: span 2; }
@media (max-width: 1100px) { .metric-grid { grid-template-columns: repeat(3, 1fr); } .panel-grid { grid-template-columns: 1fr; } }
</style>
