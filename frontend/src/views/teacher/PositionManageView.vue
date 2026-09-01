<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { teacherApi } from '@/api'
import type {
  PositionGraphDraft,
  PositionDiscoveryRunOut,
  TeacherPositionDetailOut,
  TeacherPositionOut,
} from '@/types'

const router = useRouter()
const loading = ref(false)
const actionId = ref<number | null>(null)
const positions = ref<TeacherPositionOut[]>([])
const createVisible = ref(false)
const detailVisible = ref(false)
const detail = ref<TeacherPositionDetailOut | null>(null)
const editor = ref<PositionGraphDraft | null>(null)
const reviewed = ref(false)
const activeRun = ref<PositionDiscoveryRunOut | null>(null)
let pollingStopped = false
const createForm = reactive({
  code: '',
  name: '',
  major: '油气储运工程',
  description: '',
  aliasesText: '',
})

const abilityLabels: Record<string, string> = {
  process_understanding: '工艺流程认知',
  equipment_recognition: '设备认知',
  instrument_parameter: '参数与仪表认知',
  abnormal_detection: '异常识别',
  safety_awareness: '安全风险辨识',
  standard_recording: '规范表达与记录',
}

const currentAnalysis = computed(() => detail.value?.analyses?.[0] || null)

function statusMeta(value: string) {
  if (value === 'published') return { label: '已发布', type: 'success' as const }
  if (value === 'archived') return { label: '已归档', type: 'info' as const }
  return { label: '草稿', type: 'warning' as const }
}

function dateConfidenceMeta(value: string) {
  if (value === 'high') return { label: '高', type: 'success' as const }
  if (value === 'medium') return { label: '中', type: 'warning' as const }
  return { label: '低', type: 'info' as const }
}

function dateSourceLabel(value: string) {
  if (value === 'json_ld_datePosted') return '结构化职位字段'
  if (value.startsWith('meta:')) return '页面发布日期元数据'
  if (value === 'labeled_page_text') return '正文明确标注'
  if (value === 'search_result') return '搜索摘要日期'
  if (value === 'legacy_unverified') return '旧数据待核验'
  return '未找到发布日期'
}

async function loadPositions() {
  loading.value = true
  try {
    positions.value = await teacherApi.positions()
  } finally {
    loading.value = false
  }
}

async function createPosition() {
  if (!createForm.code.trim() || !createForm.name.trim()) {
    ElMessage.warning('请填写岗位编号和岗位名称')
    return
  }
  const result = await teacherApi.createPosition({
    code: createForm.code.trim(),
    name: createForm.name.trim(),
    major: createForm.major.trim(),
    description: createForm.description.trim(),
    aliases: createForm.aliasesText.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
  })
  createVisible.value = false
  Object.assign(createForm, {
    code: '', name: '', major: '油气储运工程', description: '', aliasesText: '',
  })
  ElMessage.success('岗位草稿已创建，请继续执行AI寻找')
  await loadPositions()
  await openDetail(result.id)
}

async function openDetail(positionId: number) {
  detailVisible.value = true
  actionId.value = positionId
  try {
    detail.value = await teacherApi.positionDetail(positionId)
    activeRun.value = detail.value.discovery_runs.find((item) => item.mode === 'browser') || null
    if (activeRun.value) {
      // 列表接口不携带逐条候选，打开详情后拉一次完整任务状态补齐校验结果
      refreshBrowserRun().catch(() => {})
    }
    const latest = detail.value.analyses?.[0]
    editor.value = latest ? structuredClone(latest.result) : null
    reviewed.value = false
  } finally {
    actionId.value = null
  }
}

async function refreshDetail() {
  if (detail.value) await openDetail(detail.value.position.id)
  await loadPositions()
}

function browserStageLabel(stage: string) {
  const labels: Record<string, string> = {
    queued: '等待启动',
    waiting_browser: '等待浏览器资源',
    starting_browser: '启动受约束浏览器',
    browsing_cnpc: '浏览中国石油招聘平台',
    browsing_sinopec: '浏览中国石化招聘网',
    completed: '采集完成',
    cancelling: '正在取消',
    cancelled: '已取消',
    failed: '采集失败',
  }
  return labels[stage] || stage
}

function progressStatus(status: string) {
  if (status === 'failed') return 'exception'
  if (status === 'completed') return 'success'
  if (status === 'restricted') return 'warning'
  return undefined
}

async function pollDiscoveryRun(positionId: number, runId: number) {
  const terminal = new Set(['completed', 'empty', 'restricted', 'failed', 'cancelled'])
  for (let attempt = 0; attempt < 450 && !pollingStopped; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 2000))
    const current = await teacherApi.discoveryRun(positionId, runId)
    activeRun.value = current
    if (terminal.has(current.status)) return current
  }
  throw new Error('AI 浏览器任务等待超时，可稍后重新打开页面查看任务结果')
}

async function cancelBrowserRun() {
  const run = activeRun.value
  const positionId = detail.value?.position.id
  if (!run || !positionId) return
  activeRun.value = await teacherApi.cancelDiscoveryRun(positionId, run.run_id)
  ElMessage.info('已提交取消请求，浏览器会在当前动作结束后停止')
}

async function refreshBrowserRun() {
  const run = activeRun.value
  const positionId = detail.value?.position.id
  if (!run || !positionId) return
  activeRun.value = await teacherApi.discoveryRun(positionId, run.run_id)
}

async function discover(
  row: TeacherPositionOut | null = null,
  lookbackMonths = 0,
  mode: 'fast' | 'browser' = 'fast',
) {
  const positionId = row?.id || detail.value?.position.id
  if (!positionId) return
  const isBackfill = lookbackMonths > 0
  const isBrowser = mode === 'browser'
  await ElMessageBox.confirm(
    isBrowser
      ? '系统将启动受约束浏览器，由 LLM 在中石油、中石化官方招聘网站上选择公开页面操作。只允许官方白名单域名，遇验证码或访问限制立即停止；抽取结果需通过原页校验后才保存。是否继续？'
      : isBackfill
      ? `系统将按自然月检索近${lookbackMonths}个月的公开招聘页面，优先使用页面发布日期归月。无法确认发布日期的数据只作为采集快照，不会伪造历史趋势。是否继续？`
      : '系统将联网检索白名单中的近期公开招聘页面，保存来源网址和采集时间。不会自动发布图谱，是否继续？',
    isBrowser ? 'AI 浏览器深度采集' : isBackfill ? '近6个月历史回补' : '快速采集岗位数据',
    { confirmButtonText: isBrowser ? '启动浏览器' : isBackfill ? '开始回补' : '开始寻找', cancelButtonText: '取消', type: 'warning' },
  )
  actionId.value = positionId
  try {
    let result = await teacherApi.discoverPosition(
      positionId,
      isBackfill ? 50 : 20,
      lookbackMonths,
      mode,
    )
    if (isBrowser) {
      activeRun.value = result
      actionId.value = null
      result = await pollDiscoveryRun(positionId, result.run_id)
      if (result.status === 'failed') {
        await ElMessageBox.alert(
          `${result.diagnostic}\n\n${result.error_summary || '请检查后端日志。'}`,
          'AI 浏览器采集失败',
          { type: 'error' },
        )
        return
      }
      if (result.status === 'cancelled') {
        ElMessage.info('AI 浏览器深度采集已取消')
        return
      }
      if (result.status === 'restricted') {
        ElMessage.warning('官网访问受限或正在维护，本次未保存岗位数据，可稍后重试')
        return
      }
    }
    const officialStatusText = result.official_sources
      .map((item) => `${item.source}：${item.detail}`)
      .join('\n')
    if (result.saved_count > 0) {
      const officialCount = result.stage_stats.official_relevant_positions
        || result.stage_stats.accepted_count
        || 0
      if (officialCount > 0) {
        ElMessage.success(
          `${isBackfill ? '历史回补' : '近期采集'}已保存 ${result.saved_count} 条证据，重点央企官方相关 ${officialCount} 条`,
        )
      } else {
        await ElMessageBox.alert(
          `${isBackfill ? '历史回补' : '近期采集'}已保存 ${result.saved_count} 条公开招聘证据，但本次没有重点央企官方相关岗位。\n\n重点央企来源状态：\n${officialStatusText}`,
          '采集完成（官方岗位为 0）',
          { confirmButtonText: '知道了', type: 'warning' },
        )
      }
    } else {
      const stats = result.stage_stats
      await ElMessageBox.alert(
        `${result.diagnostic}\n\n重点央企来源状态：\n${officialStatusText}\n\n重点央企搜索候选：${stats.official_search_candidates || 0} 条\n官方结构化原始命中：${stats.official_structured_raw_positions || 0} 条\n官方结构化范围内：${stats.official_structured_positions || 0} 条\n官方相关岗位：${stats.official_relevant_positions || 0} 条\n全部搜索候选：${stats.search_candidates} 条\n招聘列表展开：${stats.expanded_positions} 条\n取得页面正文：${stats.fetched_pages} 条\n通过招聘语义：${stats.recruitment_semantic} 条\n最终相关岗位：${stats.relevant_positions} 条`,
        '本次未保存岗位数据',
        { confirmButtonText: '知道了', type: 'warning' },
      )
    }
    if (detailVisible.value) await refreshDetail()
    else await loadPositions()
  } finally {
    actionId.value = null
  }
}

async function refreshDates() {
  const positionId = detail.value?.position.id
  if (!positionId) return
  await ElMessageBox.confirm(
    '系统将重新访问已保存的公开招聘详情页，只核验岗位发布日期。未核验到日期的证据仍保留，但不会进入需求趋势。是否继续？',
    '重新核验发布日期',
    { confirmButtonText: '开始核验', cancelButtonText: '取消', type: 'warning' },
  )
  actionId.value = positionId
  try {
    const result = await teacherApi.refreshPositionDates(positionId)
    ElMessage.success(
      `核验完成：${result.dated_urls}/${result.total_urls} 条可按发布日期归月，${result.undated_urls} 条不进入趋势`,
    )
    await refreshDetail()
  } finally {
    actionId.value = null
  }
}

async function analyze() {
  const positionId = detail.value?.position.id
  if (!positionId) return
  actionId.value = positionId
  try {
    const analysis = await teacherApi.analyzePosition(positionId)
    editor.value = structuredClone(analysis.result)
    ElMessage.success(`AI图谱草稿 v${analysis.version} 已生成，请审核后发布`)
    await refreshDetail()
  } finally {
    actionId.value = null
  }
}

async function saveAnalysis() {
  const positionId = detail.value?.position.id
  const analysis = currentAnalysis.value
  if (!positionId || !analysis || !editor.value) return
  actionId.value = positionId
  try {
    const saved = await teacherApi.updatePositionAnalysis(positionId, analysis.id, editor.value)
    editor.value = structuredClone(saved.result)
    ElMessage.success('教师修订已保存，权重已自动归一化')
    await refreshDetail()
  } finally {
    actionId.value = null
  }
}

async function publish() {
  const positionId = detail.value?.position.id
  const analysis = currentAnalysis.value
  if (!positionId || !analysis) return
  if (!reviewed.value) {
    ElMessage.warning('请先勾选教师审核确认')
    return
  }
  await ElMessageBox.confirm(
    '发布后将生成正式岗位图谱，并为每个典型任务创建实训任务草稿。是否确认？',
    '发布岗位图谱',
    { confirmButtonText: '审核并发布', cancelButtonText: '取消', type: 'warning' },
  )
  actionId.value = positionId
  try {
    const result = await teacherApi.publishPosition(positionId, analysis.id)
    ElMessage.success(
      `已发布：${result.tasks}项任务、${result.knowledge_points}个知识点、${result.skill_points}个技能点`,
    )
    reviewed.value = false
    await refreshDetail()
  } finally {
    actionId.value = null
  }
}

function showGraph(positionId: number) {
  router.push({ path: '/teacher/ability-graph', query: { position: String(positionId) } })
}

function percent(value: number) {
  return `${Math.round(Number(value || 0) * 1000) / 10}%`
}

onMounted(() => {
  pollingStopped = false
  loadPositions()
})
onBeforeUnmount(() => { pollingStopped = true })
</script>

<template>
  <div class="ots-page">
    <div class="ots-card" v-loading="loading">
      <div class="page-header">
        <div>
          <h2 class="ots-title">岗位图谱配置</h2>
          <p class="text-secondary">教师创建岗位草稿，AI寻找公开招聘证据并生成图谱，审核通过后才进入正式岗位能力图谱。</p>
        </div>
        <el-button type="primary" @click="createVisible = true">新增专业岗位</el-button>
      </div>

      <el-alert
        title="需求趋势只采用可核验的岗位发布日期；采集时间仅用于审计采集活动，不会被当作岗位发布时间。"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      />

      <el-table :data="positions" stripe>
        <el-table-column prop="code" label="编号" width="130" />
        <el-table-column prop="name" label="岗位" min-width="210" />
        <el-table-column prop="major" label="专业" width="140" />
        <el-table-column label="图谱状态" width="105">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type">{{ statusMeta(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数据基础" width="200">
          <template #default="{ row }">
            <span>{{ row.snapshot_count }} 条招聘证据</span>
            <span class="separator">·</span>
            <span>{{ row.task_count }} 项任务</span>
          </template>
        </el-table-column>
        <el-table-column label="分析" width="150">
          <template #default="{ row }">
            <span v-if="row.latest_analysis">v{{ row.latest_analysis.version }} · {{ Math.round(row.latest_analysis.confidence * 100) }}%</span>
            <span v-else class="text-secondary">尚未分析</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openDetail(row.id)">配置</el-button>
            <el-button text type="primary" :loading="actionId === row.id" @click="discover(row)">快速采集</el-button>
            <el-button v-if="row.status === 'published'" text type="success" @click="showGraph(row.id)">查看图谱</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createVisible" title="新增专业岗位" width="620px">
      <el-form label-width="100px">
        <el-form-item label="岗位编号" required>
          <el-input v-model="createForm.code" placeholder="如 OGE-MAINT" />
        </el-form-item>
        <el-form-item label="岗位名称" required>
          <el-input v-model="createForm.name" placeholder="如 油气储运设备技术员" />
        </el-form-item>
        <el-form-item label="所属专业">
          <el-input v-model="createForm.major" />
        </el-form-item>
        <el-form-item label="岗位别名">
          <el-input v-model="createForm.aliasesText" placeholder="多个别名用逗号分隔" />
        </el-form-item>
        <el-form-item label="岗位说明">
          <el-input v-model="createForm.description" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="createPosition">创建草稿</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" size="86%" title="岗位证据与图谱审核">
      <div v-if="detail" class="drawer-content" v-loading="actionId === detail.position.id">
        <section class="summary-panel">
          <div>
            <div class="eyebrow">{{ detail.position.code }} · {{ detail.position.major }}</div>
            <h2>{{ detail.position.name }}</h2>
            <p>{{ detail.position.description || '暂无岗位说明' }}</p>
          </div>
          <div class="workflow-actions">
            <el-button type="primary" plain @click="discover()">1. 快速采集近期岗位</el-button>
            <el-button type="success" plain @click="discover(null, 0, 'browser')">AI浏览器深度采集</el-button>
            <el-button type="warning" plain @click="discover(null, 6)">近6个月历史回补</el-button>
            <el-button type="info" plain @click="refreshDates">核验发布日期</el-button>
            <el-button type="primary" :disabled="detail.snapshots.length === 0" @click="analyze">2. 生成图谱草稿</el-button>
            <el-button v-if="detail.position.status === 'published'" type="success" plain @click="showGraph(detail.position.id)">查看正式图谱</el-button>
          </div>
        </section>

        <el-card v-if="activeRun?.mode === 'browser'" shadow="never" class="browser-run-card">
          <div class="browser-run-header">
            <div>
              <strong>AI 浏览器任务 #{{ activeRun.run_id }}</strong>
              <span>{{ browserStageLabel(activeRun.stage) }}</span>
            </div>
            <el-button
              v-if="['queued', 'running'].includes(activeRun.status)"
              type="danger"
              text
              :disabled="activeRun.cancel_requested"
              @click="cancelBrowserRun"
            >取消任务</el-button>
            <el-button text type="primary" @click="refreshBrowserRun">刷新状态</el-button>
          </div>
          <el-progress
            :percentage="activeRun.progress"
            :status="progressStatus(activeRun.status)"
          />
          <p v-if="activeRun.diagnostic">{{ activeRun.diagnostic }}</p>
          <div v-if="activeRun.official_sources.length" class="source-status-list">
            <span v-for="source in activeRun.official_sources" :key="source.source">
              {{ source.source }}：{{ source.detail }}
            </span>
          </div>
          <el-table
            v-if="activeRun.candidates && activeRun.candidates.length"
            :data="activeRun.candidates"
            max-height="260"
            size="small"
            class="candidate-table"
          >
            <el-table-column prop="title" label="候选岗位" min-width="200" show-overflow-tooltip />
            <el-table-column prop="source_name" label="来源" width="160" show-overflow-tooltip />
            <el-table-column label="校验" width="90">
              <template #default="{ row }">
                <el-tag :type="row.validation_status === 'accepted' ? 'success' : 'danger'" size="small">
                  {{ row.validation_status === 'accepted' ? '通过' : '拒绝' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="拒绝原因" min-width="240">
              <template #default="{ row }">
                <span v-if="row.validation_errors.length">{{ row.validation_errors.join('；') }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="详情页" width="70">
              <template #default="{ row }">
                <el-link :href="row.source_url" target="_blank" type="primary">查看</el-link>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-divider content-position="left">公开招聘证据（{{ detail.snapshots.length }}）</el-divider>
        <el-table :data="detail.snapshots" max-height="300" size="small">
          <el-table-column prop="title" label="岗位信息" min-width="260" show-overflow-tooltip />
          <el-table-column prop="source_name" label="来源" width="180" />
          <el-table-column label="发布日期" width="130">
            <template #default="{ row }">{{ row.published_at ? row.published_at.slice(0, 10) : '未核验到' }}</template>
          </el-table-column>
          <el-table-column label="日期核验" min-width="190">
            <template #default="{ row }">
              <el-tooltip :content="row.date_parse_reason || '暂无核验说明'" placement="top">
                <span>
                  <el-tag :type="dateConfidenceMeta(row.date_confidence).type" size="small">
                    {{ dateConfidenceMeta(row.date_confidence).label }}
                  </el-tag>
                  {{ dateSourceLabel(row.published_at_source) }}
                </span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="采集时间" width="120">
            <template #default="{ row }">{{ row.observed_at ? row.observed_at.slice(0, 10) : '-' }}</template>
          </el-table-column>
          <el-table-column label="相关度" width="90">
            <template #default="{ row }">{{ Math.round(row.match_score * 100) }}%</template>
          </el-table-column>
          <el-table-column label="技能" min-width="220">
            <template #default="{ row }">
              <el-tag v-for="skill in row.skills.slice(0, 4)" :key="skill" size="small" style="margin-right: 4px">{{ skill }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="原始证据" width="100">
            <template #default="{ row }"><el-link :href="row.source_url" target="_blank" type="primary">查看来源</el-link></template>
          </el-table-column>
        </el-table>

        <template v-if="currentAnalysis && editor">
          <el-divider content-position="left">AI图谱草稿 v{{ currentAnalysis.version }}</el-divider>
          <el-alert
            :title="`AI 生成内容 · 基于 ${currentAnalysis.evidence_count} 条去重证据，模型 ${currentAnalysis.provider}，分析置信度 ${Math.round(currentAnalysis.confidence * 100)}%；仅在教师审核并发布后进入正式图谱。`"
            type="warning"
            :closable="false"
            show-icon
          />
          <el-form label-position="top" class="analysis-editor">
            <el-form-item label="岗位分析摘要">
              <el-input v-model="editor.position_summary" type="textarea" :rows="3" />
            </el-form-item>
            <h3>岗位总体六维权重</h3>
            <div class="weight-grid">
              <label v-for="(_, key) in editor.ability_weights" :key="key">
                <span>{{ abilityLabels[String(key)] || key }}</span>
                <el-input-number v-model="editor.ability_weights[String(key)]" :min="0" :max="1" :step="0.05" :precision="2" />
              </label>
            </div>
            <h3>典型工作任务（{{ editor.tasks.length }}）</h3>
            <el-collapse>
              <el-collapse-item v-for="(task, index) in editor.tasks" :key="task.code" :name="task.code">
                <template #title><strong>{{ index + 1 }}. {{ task.name }}</strong></template>
                <el-form-item label="任务名称"><el-input v-model="task.name" /></el-form-item>
                <el-form-item label="任务说明"><el-input v-model="task.description" type="textarea" :rows="2" /></el-form-item>
                <div class="task-weights">
                  <el-tag v-for="(value, key) in task.ability_weights" :key="key" effect="plain">
                    {{ abilityLabels[String(key)] || key }} {{ percent(value) }}
                  </el-tag>
                </div>
                <div class="knowledge-list">
                  <div v-for="point in task.knowledge_points" :key="point.code">
                    <strong>{{ point.name }}</strong>
                    <span>{{ abilityLabels[point.ability_key] }}</span>
                    <small>{{ point.skills.join('、') }}</small>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-form>
          <div class="publish-bar">
            <el-button @click="saveAnalysis">保存教师修订</el-button>
            <el-checkbox v-model="reviewed">我已核对岗位任务、能力权重和来源证据</el-checkbox>
            <el-button type="success" :disabled="!reviewed" @click="publish">审核并发布图谱</el-button>
          </div>
        </template>
        <el-empty v-else description="请先完成公开数据寻找，再生成AI图谱草稿" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-header,
.summary-panel,
.publish-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.text-secondary { color: #718087; }
.separator { margin: 0 5px; color: #aab4b8; }
.drawer-content { padding: 0 10px 28px; }
.summary-panel { align-items: flex-start; padding: 18px; border-radius: 12px; background: #f2f8f7; }
.summary-panel h2 { margin: 4px 0; color: #153f47; }
.summary-panel p { margin: 6px 0 0; color: #66777c; }
.eyebrow { color: #2f8377; font-size: 12px; font-weight: 700; }
.workflow-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; }
.browser-run-card { margin-top: 14px; border-color: #b9ddd5; }
.browser-run-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.browser-run-header > div { display: flex; gap: 12px; align-items: center; }
.browser-run-header span, .browser-run-card p, .source-status-list { color: #66777c; font-size: 13px; }
.browser-run-card p { margin: 10px 0 0; }
.source-status-list { display: grid; gap: 4px; margin-top: 8px; }
.candidate-table { margin-top: 12px; }
.analysis-editor { margin-top: 16px; }
.weight-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
.weight-grid label { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px; border: 1px solid #d9e5e2; border-radius: 8px; }
.task-weights { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.knowledge-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.knowledge-list > div { display: grid; gap: 3px; padding: 9px; border-radius: 7px; background: #f6f8f8; }
.knowledge-list span { color: #2f8377; font-size: 12px; }
.knowledge-list small { color: #7a888d; }
.publish-bar { position: sticky; bottom: 0; margin-top: 20px; padding: 14px 16px; border: 1px solid #d9e5e2; border-radius: 10px; background: #fff; box-shadow: 0 -5px 18px #244a5312; }

@media (max-width: 900px) {
  .page-header, .summary-panel, .publish-bar { align-items: stretch; flex-direction: column; }
  .weight-grid, .knowledge-list { grid-template-columns: 1fr; }
}
</style>
