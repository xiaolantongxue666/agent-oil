<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import EChartsRadar from '@/components/EChartsRadar.vue'
import { recommendationApi, simulationApi } from '@/api'
import type {
  AbilityItem,
  RecommendationOut,
  SimulationReport,
  SimulationRuntime,
  SimulationScenarioView,
  SimulationStageAction,
} from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const route = useRoute()
const router = useRouter()
const code = String(route.params.code || '')

const scenario = ref<SimulationScenarioView | null>(null)
const runtime = ref<SimulationRuntime | null>(null)
const loading = ref(true)
const busy = ref(false)
const hintText = ref('')
const report = ref<SimulationReport | null>(null)
const reportVisible = ref(false)
const recommendations = ref<RecommendationOut[]>([])

// 阶段展示名（纯 UI 文案；顺序与标题语义由后端运行时下发）
const STAGE_LABELS: Record<string, string> = {
  briefing: '任务说明',
  observe: '观察取证',
  diagnose: '异常诊断',
  risk_assess: '风险判断',
  decision: '处置决策',
  record: '规范记录',
  finished: '已完成',
}

// 错误类型中文标签（仅用于报告展示；判定逻辑在后端）
const ERROR_LABELS: Record<string, string> = {
  wrong_cause: '异常原因判断错误',
  cause_not_checked: '关键原因未排查',
  overreaction: '风险过度处置',
  risk_ignored: '风险被忽视',
  delay_response: '处置不及时',
  unsafe_decision: '不安全处置',
  unexpected_action: '超出当前阶段岗位范围的操作',
  incomplete_record: '记录要素不完整',
  missed_anomaly_window: '异常区间标记偏差',
  duplicate_action: '重复操作（仅首次计分）',
}

// §19 置信度展示（判定与取值由后端 confidence_for 决定）
const CONFIDENCE_LABELS: Record<string, string> = { low: '低', medium: '中', high: '高' }
const CONFIDENCE_TAG: Record<string, 'info' | 'warning' | 'success'> = {
  low: 'info',
  medium: 'warning',
  high: 'success',
}

const SOURCE_LABELS: Record<string, string> = {
  operation_event: '操作事件',
  scenario_diagnosis: '情景诊断',
  knowledge_quiz: '知识测验',
  scenario_choice: '情境选择',
  teacher_assessment: '教师评价',
}

// 选择/提交阶段的本地输入
const choiceCode = ref('')
const recordFields = reactive<Record<string, string>>({})
// 异常区间标记
const markWindow = reactive({ start: 12, end: 22 })

const stage = computed(() => runtime.value?.stage || 'briefing')
const stageFlow = computed(() => runtime.value?.stage_flow || [])
const stageCfg = computed(() => (scenario.value && runtime.value ? scenario.value.stages[stage.value] : undefined))
const sid = computed(() => runtime.value?.session_id ?? 0)
const finished = computed(() => Boolean(runtime.value?.finished))

const observeActions = computed<SimulationStageAction[]>(() => scenario.value?.stages?.observe?.actions || [])

function findAction(eventType: string, targetId?: string) {
  return observeActions.value.find(
    (a) => a.event_type === eventType && (targetId === undefined || a.target_id === targetId),
  )
}

function isDone(eventType: string, targetId?: string) {
  return Boolean(
    runtime.value?.events.some(
      (e) => e.event_type === eventType && (targetId === undefined || e.target_id === targetId) && e.is_expected,
    ),
  )
}

function stageSubmitted(eventType: string) {
  return Boolean(runtime.value?.events.some((e) => e.event_type === eventType))
}

function trendOption(s: { label: string; unit: string; points: Array<[number, number]> }) {
  return {
    grid: { left: 48, right: 16, top: 30, bottom: 26 },
    tooltip: { trigger: 'axis' as const },
    xAxis: { type: 'value' as const, name: '分钟', min: 0, max: 30, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value' as const, name: s.unit, scale: true, axisLabel: { fontSize: 10 } },
    series: [
      {
        type: 'line' as const,
        name: s.label,
        data: s.points,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#0b5f6b', width: 2 },
        areaStyle: { color: 'rgba(11, 95, 107, 0.08)' },
      },
    ],
  }
}

async function emit(ev: {
  event_type: string
  target_type?: string
  target_id?: string
  payload?: Record<string, unknown>
}) {
  if (!runtime.value || busy.value) return
  busy.value = true
  try {
    const res = await simulationApi.event(sid.value, ev)
    runtime.value = res.runtime
    if (res.event.error_type === 'unexpected_action') {
      ElMessage.warning('该操作不属于当前阶段的岗位动作，已如实记录')
    }
  } finally {
    busy.value = false
  }
}

async function doAdvance() {
  if (!runtime.value || busy.value) return
  busy.value = true
  try {
    runtime.value = await simulationApi.advance(sid.value)
    choiceCode.value = ''
    hintText.value = ''
  } finally {
    busy.value = false
  }
}

async function doHint() {
  if (!runtime.value) return
  const res = await simulationApi.hint(sid.value)
  hintText.value = res.hint
}

function reportFromEvaluation(): SimulationReport | null {
  const ev = runtime.value?.evaluation
  if (!ev || !scenario.value) return null
  return {
    total_score: ev.final_score,
    dimension_scores: ev.dimension_scores,
    errors: (ev.error_types || []).map((t) => ({ code: '', action: '', error_type: t, critical: false })),
    missed_actions: ev.missing_points || [],
    missed_critical: [],
    critical_evidence: [],
    ability_evidence: [],
    feedback_summary: { explanation: ev.explanation, strengths: ev.strengths || [], disclaimer: scenario.value.disclaimer },
  }
}

async function loadRecommendations() {
  // §19 推荐补学：完成评价后按最新画像拉取（失败不打断报告展示）
  try {
    recommendations.value = (await recommendationApi.tasks()).slice(0, 3)
  } catch {
    recommendations.value = []
  }
}

async function doComplete() {
  if (!runtime.value || busy.value) return
  busy.value = true
  try {
    report.value = await simulationApi.complete(sid.value)
    runtime.value = await simulationApi.runtime(sid.value)
    reportVisible.value = true
    void loadRecommendations()
  } finally {
    busy.value = false
  }
}

async function restartTraining() {
  // §19 再次训练：开新会话，回到"训练→评价→补学→重练"闭环
  if (busy.value) return
  busy.value = true
  try {
    const fresh = await simulationApi.start(code)
    runtime.value = fresh
    report.value = null
    recommendations.value = []
    reportVisible.value = false
    hintText.value = ''
    Object.keys(recordFields).forEach((key) => delete recordFields[key])
    Object.assign(markWindow, { start: 12, end: 22 })
    await router.replace({ query: { ...route.query, session: String(fresh.session_id) } })
  } finally {
    busy.value = false
  }
}

const radarAbilities = computed<AbilityItem[]>(() => {
  const dims = report.value?.dimension_scores || {}
  return Object.entries(dims).map(([k, v]) => ({
    key: k as AbilityKey,
    name: ABILITY_LABELS[k as AbilityKey] || k,
    weight: scenario.value?.rubric?.dimensions?.[k] ?? 0,
    score: v,
  }))
})

const markAction = computed(() => findAction('MARK_ABNORMAL_POINT'))

// ---- 阶段关键提交（选择类 diagnose/risk_assess/decision + record）----
// 事件类型一律读场景配置 allowed_event_types[0]（与各阶段 gate.required_event_types 一致），
// payload 键与后端判分函数对齐：SUBMIT_* → payload.choice_code，SUBMIT_RECORD → payload.fields。

/** 本阶段的关键提交事件类型（配置驱动，不按阶段名猜测） */
const stageSubmitEvent = computed(() => stageCfg.value?.allowed_event_types?.[0] || '')

/** 本阶段关键事件是否已提交（事实来源 = runtime.events，不用本地变量伪造） */
const stageSubmittedByKey = computed(() => stageSubmitted(stageSubmitEvent.value))

// 提交按钮文案（纯 UI 映射；缺失时回落到阶段标题）
const CHOICE_SUBMIT_LABELS: Record<string, string> = {
  diagnose: '提交诊断',
  risk_assess: '提交风险判断',
  decision: '提交处置方案',
}
const choiceSubmitLabel = computed(
  () => CHOICE_SUBMIT_LABELS[stage.value] || stageCfg.value?.title || '提交',
)

/** 选择类阶段：提交判断事件（radio-group 只更新 choiceCode，必须经此按钮落事件） */
async function submitChoice() {
  if (!runtime.value || busy.value || !stageSubmitEvent.value) return
  if (!choiceCode.value) {
    ElMessage.warning('请先选择一个选项再提交')
    return
  }
  await emit({
    event_type: stageSubmitEvent.value,
    target_type: 'stage',
    target_id: stage.value,
    payload: { choice_code: choiceCode.value },
  })
}

// record 阶段必填校验：所有 required_fields 非空才允许提交（不自动提交，输入变化不产生事件）
const recordRequired = computed<string[]>(() => stageCfg.value?.required_fields || [])
const recordMissing = computed(() =>
  recordRequired.value.filter((f) => !(recordFields[f] || '').trim()),
)
const recordReady = computed(
  () => recordRequired.value.length > 0 && recordMissing.value.length === 0,
)

/** 记录阶段：提交规范记录事件 */
async function submitRecord() {
  if (!runtime.value || busy.value || !stageSubmitEvent.value) return
  if (!recordReady.value) {
    ElMessage.warning(`还有 ${recordMissing.value.length} 项必填内容未填写`)
    return
  }
  await emit({
    event_type: stageSubmitEvent.value,
    target_type: 'stage',
    target_id: stage.value,
    payload: { fields: { ...recordFields } },
  })
}

onMounted(async () => {
  try {
    scenario.value = await simulationApi.detail(code)
    const q = Number(route.query.session)
    if (q > 0) {
      runtime.value = await simulationApi.runtime(q)
    } else {
      runtime.value = await simulationApi.start(code)
      router.replace({ query: { ...route.query, session: String(runtime.value.session_id) } })
    }
    if (runtime.value.finished) {
      report.value = reportFromEvaluation()
      reportVisible.value = true
      void loadRecommendations()
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <template v-if="scenario && runtime">
      <div class="page-header">
        <div class="header-left">
          <el-button link @click="router.push('/simulation')">← 返回场景列表</el-button>
          <h2>{{ scenario.title }}</h2>
          <el-tag type="warning" size="small" effect="dark">教学模拟</el-tag>
        </div>
        <div class="header-meta text-secondary">
          阶段：{{ STAGE_LABELS[stage] || stage }} · 已记录行为 {{ runtime.event_count }} 条
        </div>
      </div>

      <el-steps :active="stageFlow.indexOf(stage)" align-center finish-status="success" class="stage-steps">
        <el-step v-for="s in stageFlow.filter((x) => x !== 'finished')" :key="s" :title="STAGE_LABELS[s] || s" />
      </el-steps>

      <el-alert v-if="scenario.disclaimer" type="info" :closable="false" show-icon class="sim-notice" :description="scenario.disclaimer" />

      <div class="workbench">
        <!-- 左侧工作区 -->
        <div class="workspace">
          <!-- briefing -->
          <div v-if="stage === 'briefing'" class="ots-card panel">
            <h3>岗位情境</h3>
            <p class="situation">{{ scenario.briefing.situation }}</p>
            <h4>训练目标</h4>
            <ul class="goal-list">
              <li v-for="(g, i) in scenario.briefing.objectives" :key="i">{{ g }}</li>
            </ul>
            <h4>安全声明</h4>
            <ul class="goal-list safety">
              <li v-for="(s, i) in scenario.briefing.safety_notes" :key="i">{{ s }}</li>
            </ul>
          </div>

          <!-- observe：监控面板 -->
          <div v-else-if="stage === 'observe'" class="observe-grid">
            <div v-for="s in scenario.monitor.series" :key="s.id" class="ots-card panel chart-card">
              <div class="panel-head">
                <span>{{ s.label }}（模拟）</span>
                <span class="panel-actions">
                  <template v-if="findAction('VIEW_TREND', s.id)">
                    <el-tag v-if="isDone('VIEW_TREND', s.id)" type="success" size="small">已查看</el-tag>
                    <el-button v-else size="small" :disabled="busy" @click="emit({ event_type: 'VIEW_TREND', target_type: 'trend', target_id: s.id })">
                      查看趋势
                    </el-button>
                  </template>
                </span>
              </div>
              <VChart :option="trendOption(s)" :style="{ height: '180px', width: '100%' }" autoresize />
              <div v-if="markAction && markAction.target_id === s.id" class="mark-row">
                <span>标记异常起始(分)</span>
                <el-input-number v-model="markWindow.start" :min="0" :max="30" size="small" controls-position="right" />
                <span>结束(分)</span>
                <el-input-number v-model="markWindow.end" :min="0" :max="30" size="small" controls-position="right" />
                <el-tag v-if="isDone('MARK_ABNORMAL_POINT', s.id)" type="success" size="small">已标记</el-tag>
                <el-button
                  v-else
                  size="small"
                  type="primary"
                  plain
                  :disabled="busy || markWindow.end <= markWindow.start"
                  @click="emit({ event_type: 'MARK_ABNORMAL_POINT', target_type: markAction.target_type, target_id: s.id, payload: { window_start: markWindow.start, window_end: markWindow.end } })"
                >
                  标记异常区间
                </el-button>
              </div>
            </div>

            <div class="ots-card panel">
              <div class="panel-head"><span>报警信息（模拟）</span>
                <el-button v-if="findAction('VIEW_ALARM') && !isDone('VIEW_ALARM')" size="small" :disabled="busy" @click="emit({ event_type: 'VIEW_ALARM', target_type: 'alarm_panel', target_id: findAction('VIEW_ALARM')?.target_id })">查看报警列表</el-button>
                <el-tag v-else-if="findAction('VIEW_ALARM')" type="success" size="small">已查看</el-tag>
              </div>
              <el-table :data="scenario.monitor.alarms" size="small" max-height="160">
                <el-table-column prop="time_min" label="时刻(分)" width="80" />
                <el-table-column prop="level" label="级别" width="80" />
                <el-table-column prop="text" label="内容" show-overflow-tooltip />
              </el-table>
            </div>

            <div class="ots-card panel">
              <div class="panel-head"><span>主要设备状态（模拟）</span></div>
              <div class="device-grid">
                <div v-for="d in scenario.monitor.devices" :key="d.id" class="device-card">
                  <div class="device-name">{{ d.name }}</div>
                  <div class="device-status">{{ d.status }}</div>
                  <div class="device-metrics text-secondary">{{ Object.entries(d.metrics).map(([k, v]) => `${k}: ${v}`).join(' · ') }}</div>
                  <template v-if="findAction('VIEW_DEVICE_STATUS', d.id)">
                    <el-tag v-if="isDone('VIEW_DEVICE_STATUS', d.id)" type="success" size="small">已检查</el-tag>
                    <el-button v-else size="small" :disabled="busy" @click="emit({ event_type: 'VIEW_DEVICE_STATUS', target_type: 'device', target_id: d.id })">检查设备</el-button>
                  </template>
                </div>
              </div>
            </div>

            <div class="ots-card panel">
              <div class="panel-head"><span>近期工况与资料</span></div>
              <p class="text-secondary history">{{ scenario.monitor.history.text }}</p>
              <div class="flow-row">
                <template v-for="a in observeActions.filter((x) => x.event_type === 'VIEW_PROCESS_FLOW')" :key="a.code">
                  <el-tag v-if="isDone('VIEW_PROCESS_FLOW', a.target_id)" type="success" size="small">{{ a.name }} ✓</el-tag>
                  <el-button v-else size="small" :disabled="busy" @click="emit({ event_type: 'VIEW_PROCESS_FLOW', target_type: 'diagram', target_id: a.target_id })">{{ a.name }}</el-button>
                </template>
              </div>
              <div class="doc-row">
                <div v-for="doc in scenario.monitor.knowledge_docs" :key="doc.id" class="doc-item">
                  <div class="doc-title">{{ doc.title }}</div>
                  <div class="text-secondary doc-summary">{{ doc.summary }}</div>
                  <el-tag v-if="isDone('OPEN_KNOWLEDGE', doc.id)" type="success" size="small">已查阅</el-tag>
                  <el-button v-else-if="findAction('OPEN_KNOWLEDGE', doc.id)" size="small" :disabled="busy" @click="emit({ event_type: 'OPEN_KNOWLEDGE', target_type: 'knowledge_doc', target_id: doc.id })">查阅资料</el-button>
                </div>
              </div>
            </div>
          </div>

          <!-- 选择类阶段：diagnose / risk_assess / decision -->
          <div v-else-if="stageCfg && stageCfg.options" class="ots-card panel">
            <h3>{{ stageCfg.title }}</h3>
            <p class="text-secondary">{{ stageCfg.goal }}</p>
            <p class="question">{{ stageCfg.question }}</p>
            <el-radio-group v-model="choiceCode" :disabled="stageSubmitted(stageCfg.allowed_event_types?.[0] || '')" class="option-group">
              <el-radio v-for="o in stageCfg.options" :key="o.code" :value="o.code" class="option-item">{{ o.text }}</el-radio>
            </el-radio-group>
            <div class="submit-row">
              <el-button
                type="primary"
                :disabled="busy || !choiceCode || stageSubmittedByKey"
                @click="submitChoice"
              >
                {{ choiceSubmitLabel }}
              </el-button>
              <span v-if="!stageSubmittedByKey" class="text-secondary tiny">
                {{ choiceCode ? '确认后点击提交，提交前不会记录事件' : '先选择选项，再点击提交' }}
              </span>
              <el-tag v-else type="success" size="small">已提交，可进入下一阶段</el-tag>
            </div>
          </div>

          <!-- record 阶段 -->
          <div v-else-if="stageCfg && stageCfg.required_fields" class="ots-card panel">
            <h3>{{ stageCfg.title }}</h3>
            <p class="text-secondary">{{ stageCfg.goal }}</p>
            <el-form label-position="top" :disabled="stageSubmitted('SUBMIT_RECORD')">
              <el-form-item v-for="f in stageCfg.required_fields" :key="f" :label="(stageCfg.field_templates && stageCfg.field_templates[f]) || f">
                <el-input v-model="recordFields[f]" type="textarea" :rows="2" :placeholder="`规范填写：${(stageCfg.field_templates && stageCfg.field_templates[f]) || f}（模拟内容）`" />
              </el-form-item>
            </el-form>
            <div class="submit-row">
              <el-button
                type="primary"
                :disabled="busy || !recordReady || stageSubmitted('SUBMIT_RECORD')"
                @click="submitRecord"
              >
                提交记录
              </el-button>
              <span v-if="stageSubmitted('SUBMIT_RECORD')" class="text-secondary tiny">记录已提交，可完成实训生成评价</span>
              <span v-else-if="!recordReady" class="text-secondary tiny">还差 {{ recordMissing.length }} 项必填内容</span>
            </div>
          </div>

          <!-- 完成态 -->
          <div v-else class="ots-card panel">
            <h3>{{ finished ? '实训已完成' : stageCfg?.title || '' }}</h3>
            <p class="text-secondary">{{ finished ? '本次仿真实训已结束，评价已写入能力画像。' : stageCfg?.goal }}</p>
          </div>
        </div>

        <!-- 右侧任务栏 -->
        <div class="side-rail">
          <div class="ots-card panel">
            <div class="panel-head"><span>本阶段任务清单</span></div>
            <el-empty v-if="!runtime.pending_actions.length" :image-size="48" description="本阶段动作已完成" />
            <ul v-else class="pending-list">
              <li v-for="p in runtime.pending_actions" :key="p.code">
                <el-tag v-if="p.critical" type="danger" size="small" effect="plain">关键</el-tag>
                <span>{{ p.name }}</span>
              </li>
            </ul>
            <div class="rail-actions">
              <el-button size="small" @click="doHint">启发提示</el-button>
              <el-button
                v-if="stage !== 'record' && stage !== 'finished'"
                type="primary"
                size="small"
                :disabled="busy || finished || (Boolean(stageCfg?.options) && !stageSubmitted(stageCfg?.allowed_event_types?.[0] || ''))"
                @click="doAdvance"
              >
                下一阶段
              </el-button>
            </div>
            <p v-if="hintText" class="hint-box">{{ hintText }}</p>
          </div>

          <div class="ots-card panel">
            <div class="panel-head"><span>行为记录</span><span class="text-secondary">{{ runtime.events.length }} 条</span></div>
            <div class="event-feed">
              <div v-for="e in [...runtime.events].reverse().slice(0, 30)" :key="e.id" class="event-row">
                <span class="event-type">#{{ e.sequence_no }} {{ e.event_type }}</span>
                <el-tag v-if="e.error_type === 'unexpected_action'" type="warning" size="small" effect="plain">误操作</el-tag>
                <el-tag v-else-if="e.error_type === 'duplicate_action'" type="info" size="small" effect="plain">重复</el-tag>
              </div>
            </div>
          </div>

          <div v-if="stage === 'record' && stageSubmitted('SUBMIT_RECORD')" class="ots-card panel complete-panel">
            <el-button type="success" :disabled="busy" @click="doComplete">完成实训并生成评价</el-button>
            <p class="text-secondary tiny">评分由行为事件 + 状态机 + Rubric 确定性生成，LLM 不参与判分。</p>
          </div>
        </div>
      </div>

      <!-- 完成报告 -->
      <el-dialog v-model="reportVisible" title="仿真实训评价报告" width="720px" top="6vh">
        <div v-if="report" class="report">
          <div class="report-score">
            <span class="score-num">{{ report.total_score }}</span>
            <span class="text-secondary">/ 100（确定性规则评分）</span>
          </div>
          <EChartsRadar v-if="radarAbilities.length" :abilities="radarAbilities" height="280px" />
          <div v-if="report.feedback_summary.strengths.length" class="report-block">
            <h4>优势</h4>
            <ul><li v-for="(s, i) in report.feedback_summary.strengths" :key="i">{{ s }}</li></ul>
          </div>
          <div v-if="report.missed_critical.length" class="report-block">
            <h4 class="danger">遗漏的关键动作</h4>
            <ul><li v-for="(m, i) in report.missed_critical" :key="i">{{ m }}</li></ul>
          </div>
          <div v-if="report.errors.length" class="report-block">
            <h4>操作偏差</h4>
            <ul>
              <li v-for="(e, i) in report.errors" :key="i">
                {{ e.action || e.code }}：{{ ERROR_LABELS[e.error_type] || e.error_type }}<el-tag v-if="e.critical" type="danger" size="small" effect="plain">关键</el-tag>
              </li>
            </ul>
          </div>
          <div v-if="report.ability_evidence.length" class="report-block">
            <h4>能力证据（写入画像）</h4>
            <el-table :data="report.ability_evidence" size="small">
              <el-table-column label="能力维度" prop="ability_key">
                <template #default="{ row }">{{ ABILITY_LABELS[row.ability_key as AbilityKey] || row.ability_key }}</template>
              </el-table-column>
              <el-table-column label="证据来源" prop="source_type">
                <template #default="{ row }">{{ SOURCE_LABELS[row.source_type] || row.source_type }}</template>
              </el-table-column>
              <el-table-column label="表现分" prop="score" width="76" />
              <el-table-column label="能力变化" width="128">
                <template #default="{ row }">
                  <span v-if="row.before_score != null && row.after_score != null">
                    {{ row.before_score.toFixed(1) }} → {{ row.after_score.toFixed(1) }}
                  </span>
                  <span v-else class="text-secondary">—</span>
                </template>
              </el-table-column>
              <el-table-column label="置信度" width="80">
                <template #default="{ row }">
                  <el-tag v-if="row.confidence" :type="CONFIDENCE_TAG[row.confidence] || 'info'" size="small" effect="plain">
                    {{ CONFIDENCE_LABELS[row.confidence] || row.confidence }}
                  </el-tag>
                  <span v-else class="text-secondary">—</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="report-block">
            <h4>推荐补学</h4>
            <ul v-if="recommendations.length">
              <li v-for="rec in recommendations" :key="rec.task_id">
                {{ rec.task_title }}（{{ rec.target_ability_name }} 当前 {{ Math.round(rec.current_ability_score) }} 分：{{ rec.reason_text }}）
              </li>
            </ul>
            <p v-else class="text-secondary">暂无待补强任务；画像置信度会随后续训练持续提升。</p>
            <el-button size="small" @click="router.push('/adaptive-learning')">查看个性化学习路径</el-button>
          </div>
          <p v-if="report.feedback_summary.explanation" class="report-explain">{{ report.feedback_summary.explanation }}</p>
          <el-alert type="warning" :closable="false" show-icon :description="report.feedback_summary.disclaimer || scenario.disclaimer" />
        </div>
        <template #footer>
          <el-button @click="reportVisible = false">查看回放记录</el-button>
          <el-button @click="router.push('/simulation')">返回场景列表</el-button>
          <el-button type="primary" @click="restartTraining">再练一次</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 12px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-left h2 {
  margin: 0;
  font-size: 20px;
}
.header-meta {
  font-size: 13px;
}
.stage-steps {
  margin: 12px 0 16px;
}
.sim-notice {
  margin-bottom: 14px;
}
.workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 14px;
  align-items: start;
}
.panel {
  padding: 14px 16px;
  margin-bottom: 14px;
}
.panel h3 {
  margin: 0 0 8px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  margin-bottom: 8px;
}
.situation {
  line-height: 1.7;
  color: var(--ots-text);
}
.goal-list {
  margin: 0 0 12px;
  padding-left: 20px;
  line-height: 1.8;
}
.goal-list.safety li {
  color: var(--ots-warning, #b8860b);
}
.observe-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.chart-card {
  margin-bottom: 0;
}
.mark-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--ots-text-secondary);
  flex-wrap: wrap;
}
.device-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}
.device-card {
  border: 1px solid var(--ots-border);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
}
.device-name {
  font-weight: 600;
  margin-bottom: 2px;
}
.device-status {
  color: var(--ots-primary, #0b5f6b);
  margin-bottom: 4px;
}
.device-metrics {
  margin-bottom: 6px;
  line-height: 1.5;
}
.history {
  margin: 0 0 8px;
  font-size: 13px;
}
.flow-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.doc-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.doc-item {
  border-top: 1px dashed var(--ots-border);
  padding-top: 6px;
  font-size: 12px;
}
.doc-title {
  font-weight: 600;
}
.doc-summary {
  margin: 2px 0 4px;
}
.question {
  font-weight: 600;
  margin: 10px 0;
}
.option-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 12px;
}
.option-item {
  height: auto;
  white-space: normal;
  line-height: 1.6;
}
.pending-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 2;
}
.rail-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.submit-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.hint-box {
  margin-top: 10px;
  padding: 8px 10px;
  background: rgba(11, 95, 107, 0.06);
  border-left: 3px solid var(--ots-primary, #0b5f6b);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.event-feed {
  max-height: 260px;
  overflow-y: auto;
}
.event-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  padding: 3px 0;
  border-bottom: 1px dashed var(--ots-border);
}
.event-type {
  color: var(--ots-text-secondary);
}
.complete-panel {
  text-align: center;
}
.tiny {
  font-size: 11px;
  margin: 8px 0 0;
}
.report-score {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}
.score-num {
  font-size: 36px;
  font-weight: 700;
  color: var(--ots-primary, #0b5f6b);
}
.report-block h4 {
  margin: 14px 0 6px;
}
.report-block h4.danger {
  color: var(--el-color-danger);
}
.report-block ul {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
}
.report-explain {
  font-size: 13px;
  line-height: 1.7;
  color: var(--ots-text-secondary);
  margin: 12px 0;
}
@media (max-width: 900px) {
  .workbench { grid-template-columns: minmax(0, 1fr); }
  .observe-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
