<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart, HeatmapChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
} from 'echarts/components'
import { professionalGroupApi } from '@/api'
import { ABILITY_LABELS, type AbilityKey } from '@/types'
import type {
  GroupAnalysisOut,
  GroupCourseMatrixOut,
  ProfessionalGroupOut,
} from '@/types'

use([CanvasRenderer, GraphChart, HeatmapChart, BarChart, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent])

const router = useRouter()
const loading = ref(true)
const analyzing = ref(false)
const matrixLoading = ref(false)
const months = ref(12)
const groups = ref<ProfessionalGroupOut[]>([])
const currentGroupId = ref<number | null>(null)
const analysis = ref<GroupAnalysisOut | null>(null)
const matrix = ref<GroupCourseMatrixOut | null>(null)
const detailDrawer = ref(false)
const selectedGap = ref<GroupAnalysisOut['ability_gaps'][number] | null>(null)

const currentGroup = computed(
  () => groups.value.find((item) => item.id === currentGroupId.value) || null,
)

const confidenceText = (value: string) =>
  ({ high: '高', medium: '中', low: '低' })[value] || value

const abilityLabel = (key: string) =>
  ABILITY_LABELS[key as AbilityKey] || key

// ---- 关系图：专业群 → 专业 → 岗位 → 能力 → 课程（点击下钻到专业/能力） ----
const relationOption = computed(() => {
  const data = analysis.value
  if (!data || !currentGroup.value) return {}
  const nodes: Array<Record<string, unknown>> = []
  const links: Array<Record<string, unknown>> = []
  const nodeKey = (type: string, id: number | string) => `${type}-${id}`

  nodes.push({
    id: nodeKey('group', currentGroup.value.id),
    name: currentGroup.value.name,
    category: 0,
    symbolSize: 64,
    label: { fontSize: 12, fontWeight: 700 },
  })
  for (const major of data.majors) {
    nodes.push({
      id: nodeKey('major', major.id),
      name: major.name,
      category: 1,
      symbolSize: 40 + Math.min(20, (major.position_count || 0) * 3),
      nodeType: 'major',
      majorId: major.id,
      isCore: major.is_core_major,
    })
    links.push({
      source: nodeKey('group', currentGroup.value.id),
      target: nodeKey('major', major.id),
    })
  }
  for (const position of data.positions.slice(0, 10)) {
    nodes.push({
      id: nodeKey('position', position.id),
      name: position.name,
      category: 2,
      symbolSize: 22 + Math.min(16, position.sample_count),
      nodeType: 'position',
    })
    const major = data.majors.find((m) => m.name === position.major_name)
    links.push({
      source: nodeKey('major', major ? major.id : data.majors[0]?.id ?? ''),
      target: nodeKey('position', position.id),
    })
  }
  // 只画 Top Gap 能力，避免图过密
  for (const gap of data.ability_gaps.slice(0, 4)) {
    nodes.push({
      id: nodeKey('ability', gap.ability_key),
      name: gap.ability_name,
      category: 3,
      symbolSize: 26 + Math.min(20, Math.max(0, gap.gap) * 2),
      nodeType: 'ability',
      abilityKey: gap.ability_key,
      gap: gap.gap,
    })
    for (const major of data.majors) {
      links.push({ source: nodeKey('major', major.id), target: nodeKey('ability', gap.ability_key) })
    }
  }
  for (const course of matrix.value?.courses.slice(0, 6) || []) {
    nodes.push({
      id: nodeKey('course', course.course_id),
      name: course.name,
      category: 4,
      symbolSize: 24,
      nodeType: 'course',
    })
    const major = data.majors.find((m) => m.id === course.major_id)
    if (major) links.push({ source: nodeKey('major', major.id), target: nodeKey('course', course.course_id) })
    for (const gap of data.ability_gaps.slice(0, 4)) {
      if (course.cells[gap.ability_key]) {
        links.push({ source: nodeKey('course', course.course_id), target: nodeKey('ability', gap.ability_key) })
      }
    }
  }
  return {
    tooltip: { formatter: (params: { data?: { name?: string } }) => String(params.data?.name || '') },
    legend: { data: ['专业群', '专业', '岗位', '能力缺口', '课程'], bottom: 0 },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      categories: [
        { name: '专业群', itemStyle: { color: '#073f49' } },
        { name: '专业', itemStyle: { color: '#12707f' } },
        { name: '岗位', itemStyle: { color: '#5f9ea0' } },
        { name: '能力缺口', itemStyle: { color: '#e66b3c' } },
        { name: '课程', itemStyle: { color: '#72c4b2' } },
      ],
      force: { repulsion: 220, edgeLength: [60, 140] },
      label: { show: true, fontSize: 11, color: '#263238', position: 'bottom' },
      lineStyle: { color: '#a8c3c0', curveness: 0.08 },
      emphasis: { focus: 'adjacency' },
      data: nodes,
      links,
    }],
  }
})

function handleRelationClick(params: { data?: unknown }) {
  const data = params.data as { nodeType?: string; majorId?: number; abilityKey?: string } | undefined
  if (!data?.nodeType) return
  if (data.nodeType === 'major' && data.majorId) {
    void openMajorAnalysis(data.majorId)
  } else if (data.nodeType === 'ability' && data.abilityKey) {
    const gap = analysis.value?.ability_gaps.find((item) => item.ability_key === data.abilityKey)
    if (gap) openGapDetail(gap)
  } else if (data.nodeType === 'course') {
    detailDrawer.value = false
  }
}

async function openMajorAnalysis(majorId: number) {
  analyzing.value = true
  try {
    analysis.value = await professionalGroupApi.majorAnalysis(majorId, months.value)
    ElMessage.success('已切换到专业级分析视图')
  } finally {
    analyzing.value = false
  }
}

function backToGroup() {
  if (currentGroupId.value) void loadAnalysis()
}

// ---- 课程能力热力图（分值来自后端矩阵） ----
const heatmapOption = computed(() => {
  const data = matrix.value
  if (!data) return {}
  const abilityKeys = data.abilities.map((item) => item.key)
  const cells: Array<{ value: [number, number, number]; courseName: string; abilityName: string }> = []
  data.courses.forEach((course, rowIndex) => {
    abilityKeys.forEach((key, colIndex) => {
      const value = Number(course.cells[key] || 0)
      cells.push({
        value: [colIndex, rowIndex, value],
        courseName: course.name,
        abilityName: abilityLabel(key),
      })
    })
  })
  return {
    tooltip: {
      position: 'top',
      formatter: (params: { data?: { courseName?: string; abilityName?: string; value?: [number, number, number] } }) => {
        const d = params.data
        if (!d) return ''
        return `${d.courseName}<br/>${d.abilityName}：<b>${d.value?.[2] ?? 0}</b> 分`
      },
    },
    grid: { left: 170, right: 24, top: 12, bottom: 56 },
    xAxis: {
      type: 'category',
      data: data.abilities.map((item) => item.name),
      splitArea: { show: true },
      axisLabel: { fontSize: 11, color: '#34434a' },
    },
    yAxis: {
      type: 'category',
      data: data.courses.map((course) => `${course.name}（${course.major_name}）`),
      splitArea: { show: true },
      axisLabel: { fontSize: 11, color: '#34434a', width: 160, overflow: 'truncate' },
    },
    visualMap: {
      min: 0,
      max: data.max_score,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 4,
      text: ['覆盖强', '覆盖弱'],
      inRange: { color: ['#f3f8f7', '#c8e6df', '#72c4b2', '#2f9c8a', '#073f49'] },
    },
    series: [{
      name: '课程能力覆盖',
      type: 'heatmap',
      data: cells,
      label: { show: true, fontSize: 11, color: '#263238' },
      itemStyle: { borderColor: '#ffffff', borderWidth: 2, borderRadius: 3 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.22)' } },
    }],
  }
})

// ---- Gap 对比条形图（产业需求 vs 课程供给） ----
const gapOption = computed(() => {
  const data = analysis.value
  if (!data) return {}
  const gaps = data.ability_gaps.slice().reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['产业需求', '课程供给'], bottom: 0 },
    grid: { left: 110, right: 30, top: 12, bottom: 44 },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    yAxis: {
      type: 'category',
      data: gaps.map((item) => item.ability_name),
      axisLabel: { fontSize: 12, color: '#34434a' },
    },
    series: [
      {
        name: '产业需求',
        type: 'bar',
        data: gaps.map((item) => item.demand_share),
        itemStyle: { color: '#e66b3c', borderRadius: [0, 4, 4, 0] },
        barGap: 0,
      },
      {
        name: '课程供给',
        type: 'bar',
        data: gaps.map((item) => item.curriculum_share),
        itemStyle: { color: '#72c4b2', borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

function openGapDetail(gap: GroupAnalysisOut['ability_gaps'][number]) {
  selectedGap.value = gap
  detailDrawer.value = true
}

async function loadAnalysis() {
  if (!currentGroupId.value) return
  analyzing.value = true
  try {
    const [analysisData, matrixData] = await Promise.all([
      professionalGroupApi.analysis(currentGroupId.value, months.value),
      professionalGroupApi.courseMatrix(currentGroupId.value),
    ])
    analysis.value = analysisData
    matrix.value = matrixData
  } finally {
    analyzing.value = false
  }
}

async function changeGroup(groupId: number) {
  currentGroupId.value = groupId
  await loadAnalysis()
}

function gotoProposal() {
  router.push('/teacher/programs')
}

onMounted(async () => {
  loading.value = true
  try {
    groups.value = await professionalGroupApi.groups()
    currentGroupId.value = groups.value[0]?.id ?? null
    if (currentGroupId.value) await loadAnalysis()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading" class="pg-page">
    <div class="page-head">
      <div>
        <h2>专业群建设驾驶舱</h2>
        <p>产业岗位需求、课程能力供给与能力 Gap 的群级聚合视图（不含学生实训成绩）。</p>
      </div>
      <div class="head-actions">
        <el-select
          :model-value="currentGroupId"
          style="width: 280px"
          @update:model-value="changeGroup"
        >
          <el-option
            v-for="group in groups"
            :key="group.id"
            :label="group.name"
            :value="group.id"
          />
        </el-select>
        <el-select v-model="months" style="width: 125px" @change="loadAnalysis">
          <el-option :value="6" label="近 6 个月" />
          <el-option :value="12" label="近 12 个月" />
          <el-option :value="24" label="近 24 个月" />
          <el-option :value="36" label="近 36 个月" />
        </el-select>
        <el-button @click="loadAnalysis">重新分析</el-button>
        <el-button type="primary" plain @click="gotoProposal">生成培养方案调整草案</el-button>
      </div>
    </div>

    <el-alert
      v-if="analysis"
      type="info"
      :closable="false"
      show-icon
      class="boundary-alert"
    >
      <template #title>
        {{ analysis.scope.data_boundary }}
        数据置信度：{{ confidenceText(analysis.summary.confidence) }}（{{ analysis.summary.confidence_basis }}）
      </template>
    </el-alert>

    <div v-if="analysis" class="metric-grid">
      <div class="metric"><span>专业数</span><strong>{{ analysis.summary.major_count }}</strong></div>
      <div class="metric"><span>对接岗位</span><strong>{{ analysis.summary.position_count }}</strong></div>
      <div class="metric"><span>有效招聘样本</span><strong>{{ analysis.summary.job_sample_count }}</strong></div>
      <div class="metric"><span>课程数</span><strong>{{ analysis.summary.course_count }}</strong></div>
      <div class="metric"><span>实践学时占比</span><strong>{{ analysis.summary.practice_ratio }}%</strong></div>
      <div class="metric"><span>产业证据</span><strong>{{ analysis.summary.industry_evidence_count }}</strong></div>
      <div class="metric"><span>权威标准证据</span><strong>{{ analysis.summary.authoritative_evidence_count }}</strong></div>
      <div class="metric metric-danger">
        <span>当前最大能力缺口</span>
        <strong>{{ analysis.ability_gaps[0]?.ability_name || '—' }} {{ analysis.ability_gaps[0]?.gap ?? 0 }}pp</strong>
      </div>
    </div>

    <div v-if="analysis" class="panel-grid">
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="card-head">
            <b>专业群关系图（点击专业下钻 / 点击能力查看缺口）</b>
            <el-button v-if="analysis.scope.target.type === 'major'" size="small" @click="backToGroup">
              返回群级视图
            </el-button>
          </div>
        </template>
        <VChart
          :option="relationOption"
          style="height: 460px; width: 100%"
          autoresize
          @click="handleRelationClick"
        />
      </el-card>
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="card-head"><b>产业需求 vs 课程供给（按能力维度）</b></div>
        </template>
        <VChart :option="gapOption" style="height: 460px; width: 100%" autoresize />
      </el-card>
    </div>

    <el-card v-if="analysis" shadow="never" class="panel-card">
      <template #header>
        <div class="card-head">
          <b>能力 Gap 明细</b>
          <span>Gap = 产业需求占比 − 课程供给占比（百分点）；点击查看岗位证据与课程覆盖</span>
        </div>
      </template>
      <el-table :data="analysis.ability_gaps" border @row-click="openGapDetail">
        <el-table-column label="能力维度" min-width="140">
          <template #default="{ row }"><b>{{ row.ability_name }}</b></template>
        </el-table-column>
        <el-table-column label="产业需求" width="110" align="center">
          <template #default="{ row }">{{ row.demand_share }}%</template>
        </el-table-column>
        <el-table-column label="课程供给" width="110" align="center">
          <template #default="{ row }">{{ row.curriculum_share }}%</template>
        </el-table-column>
        <el-table-column label="Gap" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.gap > 5 ? 'danger' : row.gap > 1.5 ? 'warning' : 'success'">
              {{ row.gap > 0 ? '+' : '' }}{{ row.gap }}pp
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="课程覆盖（按学时加权贡献）" min-width="280">
          <template #default="{ row }">
            <template v-if="row.covered_by.length">
              <el-tag
                v-for="course in row.covered_by.slice(0, 3)"
                :key="course.course_id"
                class="term"
                effect="plain"
              >
                {{ course.course_name }} · {{ course.hours_weighted }}
              </el-tag>
              <span v-if="row.covered_by.length > 3" class="muted">等 {{ row.covered_by.length }} 门</span>
            </template>
            <span v-else class="muted">暂无课程覆盖此能力</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <div v-if="analysis" class="panel-grid">
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="card-head">
            <b>共享能力与专业特色能力</b>
            <span>由各专业特色权重（Major.ability_weights）规则判定</span>
          </div>
        </template>
        <div class="ability-block">
          <label>群共享能力</label>
          <div>
            <el-tag
              v-for="item in analysis.shared_abilities"
              :key="item.ability_key"
              class="term"
              type="success"
              effect="plain"
            >
              {{ item.ability_name }}（{{ item.weight_range[0] }}~{{ item.weight_range[1] }}）
            </el-tag>
            <span v-if="!analysis.shared_abilities.length" class="muted">暂无满足共享规则的能力维度</span>
          </div>
        </div>
        <div class="ability-block">
          <label>专业特色能力</label>
          <div>
            <el-tag
              v-for="item in analysis.major_specific_abilities"
              :key="`${item.major_id}-${item.ability_key}`"
              class="term"
              type="warning"
              effect="plain"
            >
              {{ item.major_name }} · {{ item.ability_name }} {{ item.weight }}
            </el-tag>
            <span v-if="!analysis.major_specific_abilities.length" class="muted">暂无显著特色差异</span>
          </div>
        </div>
        <el-divider />
        <div class="major-table">
          <el-table :data="analysis.majors" size="small">
            <el-table-column label="专业" min-width="150">
              <template #default="{ row }">
                <b>{{ row.name }}</b>
                <el-tag v-if="row.is_core_major" size="small" type="primary" effect="dark" class="core-tag">核心</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="岗位" prop="position_count" width="70" align="center" />
            <el-table-column label="方案" prop="program_count" width="70" align="center" />
            <el-table-column label="特色权重" min-width="240">
              <template #default="{ row }">
                <el-tag
                  v-for="(weight, key) in row.ability_weights"
                  :key="key"
                  size="small"
                  class="term"
                  effect="plain"
                >
                  {{ abilityLabel(String(key)) }} {{ weight }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-button link type="primary" @click="openMajorAnalysis(row.id)">专业分析</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-card>
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="card-head"><b>培养方案调整建议（规则生成，需教师审核）</b></div>
        </template>
        <div class="recommend-list">
          <div v-for="item in analysis.recommendations" :key="item.id" class="recommend-item">
            <div class="recommend-head">
              <el-tag :type="item.priority === 'high' ? 'danger' : item.priority === 'medium' ? 'warning' : 'info'" size="small">
                {{ item.priority === 'high' ? '高' : item.priority === 'medium' ? '中' : '低' }}
              </el-tag>
              <b>{{ item.target }}</b>
              <span v-if="item.hours_delta" class="muted">建议学时 +{{ item.hours_delta }}</span>
            </div>
            <p>{{ item.reason }}</p>
            <p class="suggestion">{{ item.suggestion }}</p>
          </div>
        </div>
        <el-button class="proposal-cta" type="primary" plain @click="gotoProposal">
          前往培养方案管理生成草案并审核
        </el-button>
      </el-card>
    </div>

    <el-card v-if="matrix" shadow="never" class="panel-card">
      <template #header>
        <div class="card-head">
          <b>课程能力矩阵（课程 × 六维能力）</b>
          <span>{{ matrix.basis }}</span>
        </div>
      </template>
      <div v-loading="matrixLoading">
        <VChart :option="heatmapOption" style="height: 420px; width: 100%" autoresize />
      </div>
    </el-card>

    <el-drawer v-model="detailDrawer" title="能力缺口证据下钻" size="520px">
      <template v-if="selectedGap">
        <div class="gap-summary">
          <div class="gap-stat"><span>产业需求</span><strong>{{ selectedGap.demand_share }}%</strong></div>
          <div class="gap-stat"><span>课程供给</span><strong>{{ selectedGap.curriculum_share }}%</strong></div>
          <div class="gap-stat"><span>Gap</span><strong>{{ selectedGap.gap }}pp</strong></div>
        </div>
        <h4>产生需求的岗位</h4>
        <el-table :data="analysis?.positions || []" size="small" max-height="220">
          <el-table-column prop="name" label="岗位" min-width="160" />
          <el-table-column prop="major_name" label="专业" min-width="130" />
          <el-table-column prop="sample_count" label="招聘样本" width="90" align="center" />
        </el-table>
        <h4 class="drawer-gap">覆盖该能力的课程</h4>
        <template v-if="selectedGap.covered_by.length">
          <div v-for="course in selectedGap.covered_by" :key="course.course_id" class="coverage-row">
            <b>{{ course.course_name }}</b>
            <span>{{ course.major_name }} · {{ course.program_name }} · {{ course.total_hours }} 学时 · 权重 {{ course.weight }}</span>
          </div>
        </template>
        <el-alert v-else type="warning" :closable="false" show-icon title="当前课程体系未覆盖该能力，建议优先调整" />
        <h4 class="drawer-gap">未覆盖高频技能</h4>
        <div>
          <el-tag v-for="item in analysis?.uncovered_skills || []" :key="item.name" class="term" type="warning">
            {{ item.name }} × {{ item.count }}
          </el-tag>
          <span v-if="!analysis?.uncovered_skills.length" class="muted">暂无显著未覆盖技能</span>
        </div>
        <h4 class="drawer-gap">证据链（岗位招聘 / 产业证据 / 权威标准）</h4>
        <div class="evidence-list">
          <div v-for="(item, index) in (analysis?.evidence_refs || []).slice(0, 12)" :key="index" class="evidence-row">
            <el-tag size="small" :type="item.type === 'job_posting' ? 'primary' : item.type === 'industry_evidence' ? 'warning' : 'success'">
              {{ item.type === 'job_posting' ? '招聘' : item.type === 'industry_evidence' ? '产业' : '标准' }}
            </el-tag>
            <span>{{ item.title || item.source_name }}</span>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.pg-page { display: flex; flex-direction: column; gap: 16px; }
.page-head, .head-actions, .card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.page-head h2 { margin: 0; font-size: 20px; }
.page-head p, .card-head span, .muted { color: var(--el-text-color-secondary); font-size: 13px; margin: 0; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.metric { background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: 10px; padding: 12px 16px; display: flex; flex-direction: column; gap: 4px; }
.metric span { color: var(--el-text-color-secondary); font-size: 12px; }
.metric strong { font-size: 18px; }
.metric-danger strong { color: var(--el-color-danger); }
.panel-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; }
.panel-card { border-radius: 10px; }
.boundary-alert { border-radius: 10px; }
.term { margin: 2px 4px 2px 0; }
.ability-block { display: flex; gap: 12px; margin-bottom: 12px; }
.ability-block label { flex: 0 0 92px; color: var(--el-text-color-secondary); font-size: 13px; padding-top: 3px; }
.core-tag { margin-left: 6px; }
.recommend-list { display: flex; flex-direction: column; gap: 12px; }
.recommend-item { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px 12px; }
.recommend-item p { margin: 6px 0 0; font-size: 13px; color: var(--el-text-color-regular); }
.recommend-item .suggestion { color: var(--el-color-primary); }
.recommend-head { display: flex; align-items: center; gap: 8px; }
.proposal-cta { width: 100%; margin-top: 12px; }
.gap-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }
.gap-stat { background: var(--el-fill-color-light); border-radius: 8px; padding: 10px; text-align: center; }
.gap-stat span { display: block; font-size: 12px; color: var(--el-text-color-secondary); }
.gap-stat strong { font-size: 18px; }
.coverage-row, .evidence-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px dashed var(--el-border-color-lighter); font-size: 13px; }
.coverage-row span { color: var(--el-text-color-secondary); }
.drawer-gap { margin: 18px 0 8px; }
@media (max-width: 1100px) {
  .metric-grid { grid-template-columns: repeat(2, 1fr); }
  .panel-grid { grid-template-columns: 1fr; }
}
</style>
