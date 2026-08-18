<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, GraphChart, HeatmapChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { positionApi } from '@/api'
import type { AbilityGraphOut, PositionDemandTrendOut } from '@/types'

use([
  CanvasRenderer,
  GraphChart,
  HeatmapChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
])

const graph = ref<AbilityGraphOut | null>(null)
const route = useRoute()
const loading = ref(true)
const error = ref('')
const selectedPositionId = ref<number | null>(null)
const relationSection = ref<HTMLElement | null>(null)
const demand = ref<PositionDemandTrendOut | null>(null)
const demandLoading = ref(false)
const COLORS = ['#063b46', '#0b5f6b', '#1e88e5', '#2e7d32', '#ed6c02']

interface HeatmapCell {
  value: [number, number, number]
  position_id: number
  task_id: number | null
  ability_id: number
  row_name: string
  ability_name: string
  itemStyle?: Record<string, unknown>
}

interface HeatmapSelection {
  positionId: number
  taskId: number | null
  abilityId: number
  rowName: string
  abilityName: string
  weight: number
}

const selectedRelation = ref<HeatmapSelection | null>(null)

const demandOption = computed(() => {
  const data = demand.value
  if (!data) return {}
  const showMovingAverage = data.summary.display_mode === 'trend'
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: showMovingAverage ? ['招聘样本', '招聘企业', '3期移动平均'] : ['招聘样本', '招聘企业'] },
    grid: { left: 55, right: 58, top: 54, bottom: 42 },
    xAxis: { type: 'category', data: data.series.map((item) => item.period) },
    yAxis: [
      { type: 'value', name: '样本', minInterval: 1 },
      { type: 'value', name: '企业', minInterval: 1, splitLine: { show: false } },
    ],
    series: [
      {
        name: '招聘样本',
        type: 'bar',
        data: data.series.map((item) => item.posting_count),
        itemStyle: { color: '#3d9285', borderRadius: [4, 4, 0, 0] },
      },
      {
        name: '招聘企业',
        type: 'line',
        yAxisIndex: 1,
        connectNulls: false,
        smooth: true,
        data: data.series.map((item) => item.employer_count),
        lineStyle: { color: '#ed6c02' },
        itemStyle: { color: '#ed6c02' },
      },
      ...(showMovingAverage ? [{
        name: '3期移动平均',
        type: 'line',
        connectNulls: false,
        smooth: true,
        data: data.series.map((item) => item.moving_average),
        lineStyle: { color: '#1e88e5', type: 'dashed' },
        itemStyle: { color: '#1e88e5' },
      }] : []),
    ],
  }
})

const categoryDemandOption = computed(() => {
  const categories = demand.value?.title_categories || []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 120, right: 32, top: 18, bottom: 28 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', inverse: true, data: categories.map((item) => item.name) },
    series: [{
      type: 'bar',
      data: categories.map((item) => item.count),
      itemStyle: { color: '#3d9285', borderRadius: [0, 5, 5, 0] },
      label: { show: true, position: 'right' },
    }],
  }
})

const skillDemandOption = computed(() => {
  const skills = demand.value?.top_skills || []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 110, right: 24, top: 18, bottom: 32 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', inverse: true, data: skills.map((item) => item.name) },
    series: [{
      type: 'bar',
      data: skills.map((item) => item.count),
      itemStyle: { color: '#d98b18', borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right' },
    }],
  }
})

const confidenceLabel = computed(() => {
  if (demand.value?.summary.confidence === 'high') return '高'
  if (demand.value?.summary.confidence === 'medium') return '中'
  return '低'
})

const latestObservedLabel = computed(() => {
  const value = demand.value?.summary.last_observed_at
  if (!value) return '尚未采集'
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
})

const latestPublishedLabel = computed(() => {
  const value = demand.value?.summary.latest_published_at
  if (!value) return '暂无可核验日期'
  return new Date(value).toLocaleDateString('zh-CN')
})

function periodLabel(period: string) {
  const [year, month] = period.split('-')
  return `${year}.${month}`
}

function dateBasisLabel(value: PositionDemandTrendOut['series'][number]['date_basis']) {
  if (value === 'published_at') return '发布日期'
  return '未覆盖'
}

async function loadDemandTrend(positionId: number | null) {
  if (positionId == null) {
    demand.value = null
    return
  }
  demandLoading.value = true
  try {
    demand.value = await positionApi.demandTrend(positionId, 6)
  } catch {
    demand.value = null
  } finally {
    demandLoading.value = false
  }
}

const visibleGraphNodeIds = computed(() => {
  const data = graph.value
  const positionId = selectedPositionId.value
  if (!data || positionId == null) return null

  const nodeIds = new Set<string>([`position:${positionId}`])
  const taskIds = data.heatmap.tasks
    .filter((task) => task.position_id === positionId)
    .map((task) => `task:${task.id}`)
  taskIds.forEach((id) => nodeIds.add(id))

  const abilityIds = data.heatmap.position_cells
    .filter((cell) => cell.position_id === positionId && cell.weight > 0)
    .map((cell) => `ability:${cell.ability_id}`)
  abilityIds.forEach((id) => nodeIds.add(id))

  const knowledgeIds = data.links
    .filter((link) => abilityIds.includes(link.source) && link.target.startsWith('knowledge:'))
    .map((link) => link.target)
  knowledgeIds.forEach((id) => nodeIds.add(id))
  data.links
    .filter((link) => knowledgeIds.includes(link.source) && link.target.startsWith('skill:'))
    .forEach((link) => nodeIds.add(link.target))
  return nodeIds
})

const highlightedNodeIds = computed(() => {
  const data = graph.value
  const selection = selectedRelation.value
  if (!data || !selection) return null

  const nodeIds = new Set<string>([
    `position:${selection.positionId}`,
    `ability:${selection.abilityId}`,
  ])
  if (selection.taskId != null) {
    nodeIds.add(`task:${selection.taskId}`)
  } else {
    const visible = visibleGraphNodeIds.value
    for (const link of data.links) {
      if (
        link.target === `ability:${selection.abilityId}`
        && link.source.startsWith('task:')
        && (!visible || visible.has(link.source))
      ) {
        nodeIds.add(link.source)
      }
    }
  }

  const knowledgeIds = data.links
    .filter((link) => link.source === `ability:${selection.abilityId}` && link.target.startsWith('knowledge:'))
    .map((link) => link.target)
  knowledgeIds.forEach((id) => nodeIds.add(id))
  data.links
    .filter((link) => knowledgeIds.includes(link.source) && link.target.startsWith('skill:'))
    .forEach((link) => nodeIds.add(link.target))
  return nodeIds
})

const selectedPathStats = computed(() => {
  const data = graph.value
  const highlighted = highlightedNodeIds.value
  if (!data || !highlighted) {
    return { knowledgePoints: 0, skillPoints: 0, authorityRelations: 0, reviewedChunks: 0 }
  }
  const nodes = data.nodes.filter((node) => highlighted.has(node.id))
  return {
    knowledgePoints: nodes.filter((node) => node.id.startsWith('knowledge:')).length,
    skillPoints: nodes.filter((node) => node.id.startsWith('skill:')).length,
    authorityRelations: nodes.reduce((sum, node) => sum + Number(node.authority_count || 0), 0),
    reviewedChunks: nodes.reduce((sum, node) => sum + Number(node.reviewed_chunk_count || 0), 0),
  }
})

const option = computed(() => {
  const data = graph.value
  if (!data) return {}
  const highlighted = highlightedNodeIds.value
  const visible = visibleGraphNodeIds.value
  const visibleNodes = visible ? data.nodes.filter((node) => visible.has(node.id)) : data.nodes
  const visibleLinks = visible
    ? data.links.filter((link) => visible.has(link.source) && visible.has(link.target))
    : data.links
  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { dataType?: string; data?: Record<string, unknown> }) => {
        const item = params.data || {}
        if (params.dataType === 'edge') {
          const value = Number(item.weight || 0) * 100
          const weight = item.weight == null ? '' : `<br/>权重：${value.toFixed(0)}%`
          return `${item.relation || '关系'}${weight}`
        }
        const value = Number(item.weight || 0) * 100
        const weight = item.weight == null ? '' : `<br/>岗位权重：${value.toFixed(0)}%`
        const authorityCount = Number(item.authority_count || 0)
        const authority = authorityCount > 0 ? `<br/>权威依据：${authorityCount} 条` : ''
        const reviewedCount = Number(item.reviewed_chunk_count || 0)
        const reviewed = reviewedCount > 0 ? `<br/>教师审核知识块：${reviewedCount} 条` : ''
        return `<b>${item.name || ''}</b><br/>编号：${item.code || '-'}${weight}${authority}${reviewed}<br/>${item.description || ''}`
      },
    },
    legend: { data: data.categories, top: 8 },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      animationDuration: 500,
      force: { repulsion: 240, edgeLength: [65, 150], gravity: 0.08 },
      label: { show: true, fontSize: 11, color: '#1f2d3d', formatter: '{b}' },
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [4, 8],
      lineStyle: { color: '#aebbc2', width: 1.2, curveness: 0.08 },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
      categories: data.categories.map((name, index) => ({
        name,
        itemStyle: { color: COLORS[index] },
      })),
      data: visibleNodes.map((node) => {
        const abilityId = node.id.startsWith('ability:') ? Number(node.id.split(':')[1]) : null
        const positionWeight = abilityId == null || selectedPositionId.value == null
          ? node.weight
          : data.heatmap.position_cells.find(
            (cell) => cell.position_id === selectedPositionId.value && cell.ability_id === abilityId,
          )?.weight
        return {
          ...node,
          weight: positionWeight,
          symbolSize: node.symbol_size,
          value: positionWeight,
          itemStyle: highlighted ? {
            opacity: highlighted.has(node.id) ? 1 : 0.12,
            borderColor: highlighted.has(node.id) ? '#f6c344' : 'transparent',
            borderWidth: highlighted.has(node.id) ? 3 : 0,
          } : undefined,
          label: {
            show: !highlighted || highlighted.has(node.id),
            fontSize: 11,
            color: '#1f2d3d',
          },
        }
      }),
      links: visibleLinks.map((link) => {
        const isHighlighted = !highlighted
          || (highlighted.has(link.source) && highlighted.has(link.target))
        return {
          ...link,
          lineStyle: highlighted ? {
            color: isHighlighted ? '#d98b18' : '#cfd8dc',
            width: isHighlighted ? 3 : 1,
            opacity: isHighlighted ? 1 : 0.05,
          } : undefined,
        }
      }),
    }],
  }
})

const selectedPosition = computed(() =>
  graph.value?.heatmap.positions.find((item) => item.id === selectedPositionId.value) || null,
)

const selectedTasks = computed(() => {
  if (!graph.value || selectedPositionId.value == null) return []
  return graph.value.heatmap.tasks.filter(
    (task) => task.position_id === selectedPositionId.value,
  )
})

const heatmapHeight = computed(() => `${Math.max(500, selectedTasks.value.length * 34 + 190)}px`)

const heatmapOption = computed(() => {
  const data = graph.value
  const position = selectedPosition.value
  if (!data || !position) return {}

  const abilities = data.heatmap.abilities
  const tasks = selectedTasks.value
  const rowLabels = [
    `岗位总体 · ${position.name}`,
    ...tasks.map((task) => `${task.code} · ${task.name}`),
  ]
  const positionWeights = new Map(
    data.heatmap.position_cells
      .filter((cell) => cell.position_id === position.id)
      .map((cell) => [cell.ability_id, cell.weight]),
  )
  const taskWeights = new Map(
    data.heatmap.task_cells.map((cell) => [
      `${cell.task_id}:${cell.ability_id}`,
      cell.weight,
    ]),
  )
  const cells: HeatmapCell[] = []

  abilities.forEach((ability, abilityIndex) => {
    const positionValue = Math.round((positionWeights.get(ability.id) || 0) * 1000) / 10
    const positionSelected = selectedRelation.value?.taskId == null
      && selectedRelation.value?.positionId === position.id
      && selectedRelation.value?.abilityId === ability.id
    cells.push({
      value: [abilityIndex, 0, positionValue],
      position_id: position.id,
      task_id: null,
      ability_id: ability.id,
      row_name: position.name,
      ability_name: ability.name,
      itemStyle: positionSelected
        ? { borderColor: '#073f49', borderWidth: 4, shadowBlur: 8, shadowColor: '#073f4966' }
        : undefined,
    })
    tasks.forEach((task, taskIndex) => {
      const weight = taskWeights.get(`${task.id}:${ability.id}`) || 0
      const taskSelected = selectedRelation.value?.taskId === task.id
        && selectedRelation.value?.abilityId === ability.id
      cells.push({
        value: [abilityIndex, taskIndex + 1, Math.round(weight * 1000) / 10],
        position_id: position.id,
        task_id: task.id,
        ability_id: ability.id,
        row_name: `${task.code} · ${task.name}`,
        ability_name: ability.name,
        itemStyle: taskSelected
          ? { borderColor: '#073f49', borderWidth: 4, shadowBlur: 8, shadowColor: '#073f4966' }
          : undefined,
      })
    })
  })
  const visualMax = Math.max(
    20,
    Math.ceil(Math.max(...cells.map((cell) => cell.value[2]), 0) / 10) * 10,
  )

  return {
    animationDuration: 450,
    tooltip: {
      position: 'top',
      formatter: (params: { data?: unknown }) => {
        const cell = params.data as HeatmapCell
        if (!cell?.value) return ''
        const value = Number(cell.value[2] || 0)
        const relation = value > 0 ? '已配置能力关系' : '未配置直接关系'
        return `<b>${cell.row_name}</b><br/>${cell.ability_name}：${value.toFixed(1)}%<br/>${relation}`
      },
    },
    grid: { top: 48, left: 210, right: 86, bottom: 78 },
    xAxis: {
      type: 'category',
      position: 'top',
      data: abilities.map((ability) => ability.name),
      splitArea: { show: true },
      axisLabel: { interval: 0, color: '#34434a', fontSize: 12 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rowLabels,
      splitArea: { show: true },
      axisLabel: {
        color: '#34434a',
        fontSize: 12,
        width: 180,
        overflow: 'truncate',
      },
      axisTick: { show: false },
    },
    visualMap: {
      min: 0,
      max: visualMax,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 8,
      text: ['能力权重高', '未配置'],
      inRange: {
        color: ['#f3f8f7', '#c8e6df', '#72c4b2', '#f4b667', '#e66b3c', '#9f2832'],
      },
    },
    series: [{
      name: '能力权重',
      type: 'heatmap',
      data: cells,
      label: {
        show: true,
        color: '#263238',
        fontSize: 11,
        formatter: (params: { data?: unknown }) => {
          const cell = params.data as HeatmapCell
          const value = cell?.value ? Number(cell.value[2] || 0) : 0
          return value > 0 ? `${value}%` : '—'
        },
      },
      itemStyle: { borderColor: '#ffffff', borderWidth: 2, borderRadius: 3 },
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.22)' },
      },
    }],
  }
})

function handleHeatmapClick(params: { data?: unknown }) {
  const cell = params.data as HeatmapCell
  const weight = Number(cell?.value?.[2] || 0)
  if (!cell?.ability_id || weight <= 0) return
  selectedRelation.value = {
    positionId: cell.position_id,
    taskId: cell.task_id,
    abilityId: cell.ability_id,
    rowName: cell.row_name,
    abilityName: cell.ability_name,
    weight,
  }
}

function clearHeatmapSelection() {
  selectedRelation.value = null
}

function handlePositionChange() {
  clearHeatmapSelection()
}

function scrollToRelationGraph() {
  relationSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(async () => {
  try {
    const data = await positionApi.graph()
    graph.value = data
    const queryPosition = Number(route.query.position || 0)
    selectedPositionId.value = data.heatmap.positions.some((item) => item.id === queryPosition)
      ? queryPosition
      : data.heatmap.positions[0]?.id ?? null
  } catch {
    error.value = '岗位能力图谱加载失败，请确认后端已执行种子数据。'
  } finally {
    loading.value = false
  }
})

watch(selectedPositionId, (value) => loadDemandTrend(value))
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <div class="ots-card">
      <h2 class="ots-title">岗位能力图谱</h2>
      <p class="text-secondary" style="margin: 0 0 12px">
        岗位 → 典型工作任务 → 能力维度 → 知识点 → 技能点。节点和关系由数据库实时生成。
      </p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <template v-else-if="graph">
        <el-row :gutter="12" style="margin-bottom: 12px">
          <el-col :span="4"><el-statistic title="岗位" :value="graph.stats.positions" /></el-col>
          <el-col :span="4"><el-statistic title="典型任务" :value="graph.stats.tasks" /></el-col>
          <el-col :span="4"><el-statistic title="能力维度" :value="graph.stats.abilities" /></el-col>
          <el-col :span="4"><el-statistic title="知识点" :value="graph.stats.knowledge_points" /></el-col>
          <el-col :span="4"><el-statistic title="技能点" :value="graph.stats.skill_points" /></el-col>
          <el-col :span="4"><el-statistic title="权威依据" :value="graph.stats.authority_items" /></el-col>
        </el-row>
        <div class="ots-safety-banner" style="margin-bottom: 12px">
          图谱映射依据职业标准进行教学化设计，不连接或控制真实生产设备。
        </div>

        <section class="graph-section">
          <div class="section-header">
            <div>
              <h3 class="section-title">岗位能力热力图</h3>
              <p class="section-description">
                展示岗位总体及其 {{ selectedTasks.length }} 项典型任务对六维能力的配置权重，颜色越深代表权重越高，不代表学生成绩。
              </p>
            </div>
            <el-select
              v-model="selectedPositionId"
              class="position-select"
              placeholder="选择岗位"
              @change="handlePositionChange"
            >
              <el-option
                v-for="position in graph.heatmap.positions"
                :key="position.id"
                :label="position.name"
                :value="position.id"
              />
            </el-select>
          </div>
          <div v-if="selectedPosition" class="position-source">
            <span>岗位依据</span>{{ selectedPosition.description }}
          </div>
          <VChart
            v-if="selectedPosition"
            :option="heatmapOption"
            :style="{ height: heatmapHeight, width: '100%' }"
            autoresize
            @click="handleHeatmapClick"
          />
          <el-empty v-else description="暂无岗位能力权重数据" />
          <div v-if="selectedRelation" class="selection-panel">
            <div class="selection-main">
              <el-tag type="warning" effect="dark">联动高亮</el-tag>
              <div>
                <strong>{{ selectedRelation.rowName }}</strong>
                <span> × {{ selectedRelation.abilityName }}</span>
                <b>{{ selectedRelation.weight }}%</b>
              </div>
            </div>
            <div class="selection-stats">
              <span>关联知识点 {{ selectedPathStats.knowledgePoints }}</span>
              <span>技能点 {{ selectedPathStats.skillPoints }}</span>
              <span>权威证据关系 {{ selectedPathStats.authorityRelations }}</span>
              <span>教师启用块 {{ selectedPathStats.reviewedChunks }}</span>
            </div>
            <div class="selection-actions">
              <el-button type="primary" plain @click="scrollToRelationGraph">查看高亮链路</el-button>
              <el-button text @click="clearHeatmapSelection">清除选择</el-button>
            </div>
          </div>
          <div v-else-if="selectedPosition" class="interaction-hint">
            点击任意有权重的热力单元格，可联动高亮下方岗位—任务—能力—知识—技能链路。
          </div>
        </section>

        <el-divider />
        <section class="graph-section demand-section" v-loading="demandLoading">
          <div class="section-header">
            <div>
              <h3 class="section-title">岗位近期发布需求趋势</h3>
              <p class="section-description">
                仅按公开招聘页中可核验的岗位发布日期归月；采集时间独立展示，不参与需求趋势计算。
              </p>
            </div>
            <el-tag v-if="demand" :type="demand.summary.confidence === 'high' ? 'success' : demand.summary.confidence === 'medium' ? 'warning' : 'info'">
              数据置信度：{{ confidenceLabel }}
            </el-tag>
          </div>
          <template v-if="demand && demand.summary.total_evidence_count > 0">
            <div class="demand-metrics">
              <article><span>公开招聘证据</span><strong>{{ demand.summary.total_evidence_count }}</strong><small>按来源网址全局去重</small></article>
              <article><span>可进入趋势</span><strong>{{ demand.summary.dated_sample_count }}</strong><small>高/中置信度发布日期</small></article>
              <article><span>有效月份覆盖</span><strong>{{ demand.summary.covered_months }}/{{ demand.range_months }}</strong><small>低置信度排除 {{ demand.summary.excluded_low_confidence_count }} 条</small></article>
              <article>
                <span>最近岗位发布日期</span>
                <strong class="metric-text">{{ latestPublishedLabel }}</strong>
                <small>最近采集 {{ latestObservedLabel }}</small>
              </article>
            </div>
            <el-alert
              v-if="demand.summary.display_mode === 'snapshot'"
              :title="demand.summary.dated_sample_count === 0
                ? `现有 ${demand.summary.total_evidence_count} 条岗位证据均未核验到可用发布日期，因此不绘制虚假时间趋势；下方仍展示岗位类别与技能结构。`
                : `当前仅有 ${demand.summary.dated_sample_count} 条证据可按发布日期归月，覆盖 ${demand.summary.covered_months} 个月，暂不计算长期趋势和移动平均。`"
              type="warning"
              :closable="false"
              show-icon
              class="coverage-alert"
            />
            <div class="coverage-timeline">
              <div
                v-for="item in demand.series"
                :key="item.period"
                class="coverage-month"
                :class="{ covered: item.covered }"
              >
                <span>{{ periodLabel(item.period) }}</span>
                <strong>{{ item.covered ? `${item.posting_count} 条` : '暂无样本' }}</strong>
                <small>{{ dateBasisLabel(item.date_basis) }}</small>
              </div>
            </div>
            <div class="demand-charts">
              <div class="chart-panel">
                <h4>{{ demand.summary.display_mode === 'trend' ? '近6个月招聘样本趋势' : '当前样本岗位细分类别' }}</h4>
                <VChart
                  :option="demand.summary.display_mode === 'trend' ? demandOption : categoryDemandOption"
                  style="height: 340px; width: 100%"
                  autoresize
                />
              </div>
              <div class="chart-panel">
                <h4>招聘信息高频技能</h4>
                <VChart :option="skillDemandOption" style="height: 340px; width: 100%" autoresize />
              </div>
            </div>
            <div v-if="demand.batch_activity.length" class="batch-strip">
              <span class="batch-title">采集活动（不进入趋势）</span>
              <div v-for="batch in demand.batch_activity" :key="batch.run_id" class="batch-item">
                <b>{{ new Date(batch.observed_at).toLocaleDateString('zh-CN') }}</b>
                <span>发现 {{ batch.sample_count }} 条</span>
                <em>新增 {{ batch.new_count }} 条</em>
              </div>
            </div>
            <div class="source-strip">
              <span>证据来源（{{ demand.summary.source_count }}）</span>
              <el-tag v-for="source in demand.sources" :key="source.name" effect="plain">
                {{ source.name }} {{ source.count }}
              </el-tag>
              <span class="date-quality-label">发布日期核验</span>
              <el-tag size="small" type="success">高 {{ demand.summary.date_confidence.high }}</el-tag>
              <el-tag size="small" type="warning">中 {{ demand.summary.date_confidence.medium }}</el-tag>
              <el-tag size="small" type="info">低/排除 {{ demand.summary.date_confidence.low }}</el-tag>
            </div>
          </template>
          <el-empty v-else description="该岗位尚无公开招聘证据。教师可在“岗位图谱配置”中执行AI寻找并核验发布日期。" />
        </section>

        <el-divider />
        <section ref="relationSection" class="graph-section relation-section">
          <div class="section-header">
            <div>
              <h3 class="section-title">岗位能力关系图</h3>
              <p v-if="selectedRelation" class="section-description highlight-description">
                当前高亮：{{ selectedRelation.rowName }} → {{ selectedRelation.abilityName }} →
                {{ selectedPathStats.knowledgePoints }} 个知识点 → {{ selectedPathStats.skillPoints }} 个技能点
              </p>
              <p v-else class="section-description">
                当前展示“{{ selectedPosition?.name }}”的任务、能力与知识技能关系；拖动节点或缩放画布可查看细节。
              </p>
            </div>
            <el-button v-if="selectedRelation" text @click="clearHeatmapSelection">显示完整图谱</el-button>
          </div>
          <VChart :option="option" style="height: 680px; width: 100%" autoresize />
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.graph-section {
  min-width: 0;
}

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin: 4px 0 8px;
}

.section-title {
  margin: 0 0 6px;
  color: var(--ots-primary-dark);
  font-size: 18px;
}

.section-description {
  margin: 0;
  color: #6c7a80;
  font-size: 13px;
  line-height: 1.6;
}

.position-select {
  width: 290px;
  flex: 0 0 auto;
}

.position-source {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin: 8px 0 0;
  padding: 9px 12px;
  border-left: 3px solid #3d9285;
  border-radius: 0 6px 6px 0;
  background: #f3f8f7;
  color: #596b70;
  font-size: 12px;
  line-height: 1.6;
}

.position-source span {
  flex: 0 0 auto;
  color: #0b5f6b;
  font-weight: 700;
}

.interaction-hint {
  margin: 2px 0 8px;
  padding: 10px 14px;
  border: 1px dashed #9fc8c0;
  border-radius: 8px;
  background: #f4faf8;
  color: #53716c;
  font-size: 13px;
  text-align: center;
}

.selection-panel {
  display: grid;
  grid-template-columns: minmax(260px, 1.4fr) minmax(360px, 2fr) auto;
  align-items: center;
  gap: 18px;
  margin: 2px 0 8px;
  padding: 14px 16px;
  border: 1px solid #efc36b;
  border-radius: 10px;
  background: linear-gradient(90deg, #fff9e9 0%, #f3faf8 100%);
}

.selection-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.selection-main > div {
  min-width: 0;
  color: #405057;
  font-size: 13px;
}

.selection-main strong {
  color: #173d44;
}

.selection-main b {
  margin-left: 8px;
  color: #a64b19;
  font-size: 18px;
}

.selection-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  color: #52666c;
  font-size: 12px;
}

.selection-stats span::before {
  content: '•';
  margin-right: 5px;
  color: #cf831b;
}

.selection-actions {
  display: flex;
  white-space: nowrap;
}

.relation-section {
  scroll-margin-top: 18px;
}

.demand-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0;
}

.demand-metrics article {
  display: flex;
  min-height: 92px;
  flex-direction: column;
  justify-content: center;
  padding: 13px 16px;
  border: 1px solid #dce8e5;
  border-radius: 10px;
  background: linear-gradient(145deg, #ffffff, #f3f9f7);
}

.demand-metrics span,
.demand-metrics small {
  color: #687a80;
  font-size: 12px;
}

.demand-metrics strong {
  margin: 4px 0;
  color: #123f48;
  font-size: 25px;
}

.demand-metrics .metric-text {
  font-size: 18px;
}

.coverage-alert {
  margin-bottom: 12px;
}

.coverage-timeline {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}

.coverage-month {
  display: flex;
  min-height: 68px;
  flex-direction: column;
  justify-content: center;
  padding: 8px 10px;
  border: 1px dashed #c9d4d2;
  border-radius: 8px;
  background: repeating-linear-gradient(135deg, #fafcfc 0, #fafcfc 8px, #f4f7f6 8px, #f4f7f6 16px);
  color: #879397;
}

.coverage-month.covered {
  border: 1px solid #64aa9e;
  background: linear-gradient(145deg, #eaf7f3, #f8fcfb);
  color: #174b53;
}

.coverage-month span,
.coverage-month small {
  font-size: 11px;
}

.coverage-month strong {
  margin: 3px 0;
  font-size: 15px;
}

.demand-charts {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 14px;
}

.chart-panel {
  min-width: 0;
  padding: 12px;
  border: 1px solid #dbe7e4;
  border-radius: 10px;
  background: #fbfdfc;
}

.chart-panel h4 {
  margin: 0 0 5px;
  color: #315159;
}

.source-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}

.source-strip > span {
  color: #64777c;
  font-size: 12px;
  font-weight: 700;
}

.source-strip .date-quality-label {
  margin-left: 12px;
}

.batch-strip {
  display: flex;
  align-items: stretch;
  gap: 8px;
  margin-top: 12px;
  overflow-x: auto;
}

.batch-title {
  display: flex;
  align-items: center;
  color: #64777c;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.batch-item {
  display: grid;
  min-width: 145px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f3f7f6;
  color: #5a6e73;
  font-size: 11px;
}

.batch-item b {
  color: #244b53;
}

.batch-item em {
  color: #c06f13;
  font-style: normal;
}

.highlight-description {
  color: #a35e16;
  font-weight: 600;
}

@media (max-width: 768px) {
  .section-header {
    flex-direction: column;
  }

  .position-select {
    width: 100%;
  }

  .selection-panel {
    grid-template-columns: 1fr;
  }

  .demand-charts {
    grid-template-columns: 1fr;
  }

  .demand-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .coverage-timeline {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .selection-actions {
    justify-content: flex-end;
  }
}
</style>
