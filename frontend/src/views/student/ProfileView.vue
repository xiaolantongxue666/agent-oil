<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { abilityApi } from '@/api'
import type {
  AbilityEvidenceOut,
  AbilityGrowthOut,
  AbilityProfileOut,
  AbilityHistoryOut,
  AbilityItem,
  RadarDataOut,
} from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'
import EChartsRadar from '@/components/EChartsRadar.vue'

const profile = ref<AbilityProfileOut | null>(null)
const history = ref<AbilityHistoryOut[]>([])
const radar = ref<RadarDataOut | null>(null)
const growth = ref<AbilityGrowthOut | null>(null)
const evidence = ref<AbilityEvidenceOut | null>(null)
const loading = ref(true)
const profileOk = ref(false)
const growthOk = ref(false)
const selectedAbility = ref<string>('')

// 证据来源中文标签：与后端真实 source_type 一一对应，有哪些展示哪些（不预设四类都有）
const SOURCE_LABELS: Record<string, string> = {
  knowledge_quiz: '知识测验',
  scenario_choice: '岗位情境训练·选择题',
  scenario_diagnosis: '岗位情境训练·诊断',
  operation_event: '岗位仿真实训',
  teacher_assessment: '教师评价',
}
// 置信度统一表达（全局规范：较低/中/高）；低置信 ≠ 能力差，只表示证据充分程度
const CONFIDENCE_LABELS: Record<string, string> = { low: '较低', medium: '中', high: '高' }
const CONFIDENCE_TAG: Record<string, 'info' | 'warning' | 'success'> = {
  low: 'info',
  medium: 'warning',
  high: 'success',
}
const CONFIDENCE_TIP = '能力置信度表示当前评价依据的证据充分程度，不等同于能力高低。'

const abilities = computed<AbilityItem[]>(() => {
  if (!profile.value) return []
  return Object.entries(profile.value).map(([key, dim]) => ({
    key: key as AbilityKey,
    name: dim.name || ABILITY_LABELS[key as AbilityKey] || key,
    weight: dim.weight,
    score: dim.score,
  }))
})

const averageScore = computed(() => {
  if (!profile.value) return null
  const vals = Object.values(profile.value)
  if (!vals.length) return null
  return Math.round(vals.reduce((s, v) => s + v.score, 0) / vals.length)
})

const validEvidenceTotal = computed(() => growth.value?.total_evidence ?? null)

// 置信度概览：证据已达「中/高」置信的维度数占比（不评判能力高低）
const confidenceSummary = computed(() => {
  if (!profile.value) return null
  const dims = Object.values(profile.value)
  if (!dims.length) return null
  const solid = dims.filter((d) => d.confidence === 'medium' || d.confidence === 'high').length
  return { solid, total: dims.length }
})

const weakestDim = computed(() => {
  if (!profile.value) return null
  const entries = Object.entries(profile.value).sort((a, b) => a[1].score - b[1].score)
  if (!entries.length) return null
  const [key, dim] = entries[0]
  return { key, ...dim }
})

async function loadHistory(key?: string) {
  try {
    history.value = await abilityApi.history(key || undefined)
  } catch {
    history.value = []
  }
}

async function loadEvidence(key?: string) {
  try {
    evidence.value = await abilityApi.evidence(key || undefined)
  } catch {
    evidence.value = null
  }
}

function selectAbility(key: string) {
  selectedAbility.value = selectedAbility.value === key ? '' : key
  loadHistory(selectedAbility.value)
  loadEvidence(selectedAbility.value)
}

onMounted(async () => {
  try {
    const [p, r, g] = await Promise.allSettled([
      abilityApi.profile(),
      abilityApi.radar(),
      abilityApi.growth(),
    ])
    if (p.status === 'fulfilled') { profile.value = p.value; profileOk.value = true }
    if (r.status === 'fulfilled') radar.value = r.value
    if (g.status === 'fulfilled') { growth.value = g.value; growthOk.value = true }
    await Promise.all([loadHistory(), loadEvidence()])
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <div class="page-title">
      <h2>技能证据档案</h2>
      <p>基于多源训练与评价证据形成岗位能力画像。</p>
    </div>

    <!-- 第一屏：综合能力 / Growth XP / 有效技能证据 / 置信度概览 + 六维（得分·置信度·证据数） -->
    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <div class="ots-card">
          <h3 class="ots-title">
            能力概览
            <el-tooltip :content="CONFIDENCE_TIP" placement="top">
              <span class="conf-help"><el-icon><QuestionFilled /></el-icon></span>
            </el-tooltip>
          </h3>
          <div class="stat-row">
            <div class="stat-mini">
              <div class="stat-mini-val">{{ profileOk ? (averageScore ?? '—') : '—' }}</div>
              <div class="stat-mini-label">综合能力</div>
            </div>
            <div class="stat-mini">
              <div class="stat-mini-val">{{ growthOk ? (growth?.total_xp ?? '—') : '—' }}</div>
              <div class="stat-mini-label">Growth XP</div>
            </div>
            <div class="stat-mini">
              <div class="stat-mini-val">{{ growthOk ? (validEvidenceTotal ?? '—') : '—' }}</div>
              <div class="stat-mini-label">有效技能证据</div>
            </div>
            <div class="stat-mini">
              <div class="stat-mini-val">{{ confidenceSummary ? `${confidenceSummary.solid}/${confidenceSummary.total}` : '—' }}</div>
              <div class="stat-mini-label">证据较充分维度</div>
            </div>
          </div>

          <h4 class="dim-heading">各维度能力（点击查看对应证据）</h4>
          <div class="dim-list">
            <div
              v-for="ab in abilities"
              :key="ab.key"
              class="dim-row"
              :class="{ selected: selectedAbility === ab.key }"
              @click="selectAbility(ab.key)"
            >
              <div class="dim-name">{{ ab.name }}</div>
              <div class="dim-bar">
                <el-progress :percentage="ab.score" :stroke-width="10" :show-text="false" />
              </div>
              <div class="dim-score">{{ ab.score.toFixed(0) }}</div>
              <el-tooltip v-if="profile?.[ab.key]?.confidence" :content="CONFIDENCE_TIP" placement="top">
                <el-tag
                  size="small"
                  effect="plain"
                  :type="CONFIDENCE_TAG[profile?.[ab.key]?.confidence as string] || 'info'"
                >
                  置信度：{{ CONFIDENCE_LABELS[profile?.[ab.key]?.confidence as string] || profile?.[ab.key]?.confidence }}
                </el-tag>
              </el-tooltip>
              <div class="dim-evidence text-secondary">
                {{ profile?.[ab.key]?.evidence_count ?? 0 }} 条有效证据
              </div>
            </div>
            <div v-if="!abilities.length && !loading" class="text-secondary dim-empty">
              {{ profileOk ? '暂无能力数据' : '暂时无法获取能力档案' }}
            </div>
          </div>
          <div v-if="weakestDim" class="weak-hint">
            <el-icon><WarningFilled /></el-icon>
            当前最需提升：<strong>{{ weakestDim.name }}</strong>（{{ weakestDim.score.toFixed(0) }}分）
            <span v-if="weakestDim.confidence === 'low'" class="text-secondary">该维度证据较少，置信度较低，建议先通过训练补充证据再判断。</span>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="ots-card">
          <h3 class="ots-title">六维能力雷达</h3>
          <EChartsRadar v-if="abilities.length" :abilities="abilities" height="340px" />
          <el-empty v-else description="完成训练后将自动生成能力画像" />
        </div>
      </el-col>
    </el-row>

    <!-- 证据档案主视图：来源分布 + 可读列表（原始分/权重等算法细节收进下方折叠区） -->
    <div class="ots-card">
      <h3 class="ots-title">
        技能证据
        <el-tag v-if="selectedAbility" size="small" closable @close="selectAbility(selectedAbility)">
          {{ ABILITY_LABELS[selectedAbility as AbilityKey] || selectedAbility }}
        </el-tag>
      </h3>
      <div v-if="evidence && Object.keys(evidence.by_source_type).length" style="margin-bottom: 10px">
        <el-tag
          v-for="(count, type) in evidence.by_source_type"
          :key="type"
          size="small"
          type="info"
          effect="plain"
          style="margin: 0 8px 4px 0"
        >
          {{ SOURCE_LABELS[type] || type }} × {{ count }}
        </el-tag>
      </div>
      <el-table v-if="evidence?.items.length" :data="evidence.items" stripe size="small">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            {{ row.created_at ? row.created_at.slice(0, 19).replace('T', ' ') : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="能力维度" width="120">
          <template #default="{ row }">{{ ABILITY_LABELS[row.ability_key as AbilityKey] || row.ability_key }}</template>
        </el-table-column>
        <el-table-column label="证据来源" min-width="180">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ SOURCE_LABELS[row.source_type] || row.source_type }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else :description="evidence ? '暂无有效样本：完成实训或仿真实训后将自动累积证据' : '暂时无法获取证据记录'" :image-size="60" />
    </div>

    <!-- 评价算法详情：技术答辩备查，默认折叠，不抢占技能档案第一视觉 -->
    <div class="ots-card algo-card">
      <el-collapse>
        <el-collapse-item title="查看评价算法详情（原始得分 · 证据权重 · 难度系数 · 能力更新记录）" name="algo">
          <h4 class="algo-heading">证据评分明细</h4>
          <el-table v-if="evidence?.items.length" :data="evidence.items" stripe size="small">
            <el-table-column label="时间" width="170">
              <template #default="{ row }">
                {{ row.created_at ? row.created_at.slice(0, 19).replace('T', ' ') : '—' }}
              </template>
            </el-table-column>
            <el-table-column label="维度" width="110">
              <template #default="{ row }">{{ ABILITY_LABELS[row.ability_key as AbilityKey] || row.ability_key }}</template>
            </el-table-column>
            <el-table-column label="来源" width="140">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ SOURCE_LABELS[row.source_type] || row.source_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="原始得分 → 证据得分" width="170">
              <template #default="{ row }">{{ row.raw_score.toFixed(0) }} → {{ row.final_score.toFixed(1) }}</template>
            </el-table-column>
            <el-table-column label="证据权重" width="100">
              <template #default="{ row }">×{{ row.evidence_weight.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="难度系数">
              <template #default="{ row }">×{{ row.difficulty_weight.toFixed(2) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else :description="evidence ? '暂无有效样本' : '暂时无法获取'" :image-size="60" />

          <h4 class="algo-heading">能力更新记录</h4>
          <el-table v-if="history.length" :data="history" stripe size="small" empty-text="暂无记录">
            <el-table-column label="时间" width="180">
              <template #default="{ row }">{{ row.created_at ? row.created_at.slice(0, 19).replace('T', ' ') : '—' }}</template>
            </el-table-column>
            <el-table-column prop="ability_name" label="维度" width="120" />
            <el-table-column label="变化" width="220">
              <template #default="{ row }">
                <span>{{ row.before_score.toFixed(0) }}</span>
                <el-icon style="margin: 0 4px"><Right /></el-icon>
                <span :style="{ color: row.after_score >= row.before_score ? '#2e7d32' : '#c62828' }">
                  {{ row.after_score.toFixed(0) }}
                </span>
                <span class="text-secondary" style="margin-left: 4px">
                  ({{ row.after_score >= row.before_score ? '+' : ''
                    }}{{ (row.after_score - row.before_score).toFixed(1) }})
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="training_score" label="本次训练得分" width="130" />
          </el-table>
          <el-empty v-else description="暂无变更记录" :image-size="60" />
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<style scoped>
.page-title { margin-bottom: 14px; }
.page-title h2 { margin: 0 0 4px; }
.page-title p { margin: 0; color: var(--ots-text-secondary); font-size: 13px; }
.ots-title { display: flex; align-items: center; gap: 8px; }
.conf-help { color: var(--ots-primary); font-size: 12px; cursor: help; }
.stat-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 16px; }
.stat-mini { text-align: center; padding: 8px; background: var(--ots-bg); border-radius: 8px; }
.stat-mini-val { font-size: 22px; font-weight: 700; color: var(--ots-primary-dark); }
.stat-mini-label { font-size: 12px; color: var(--ots-text-secondary); }
.dim-heading { margin: 0 0 8px; font-size: 13px; }
.dim-list { display: flex; flex-direction: column; gap: 8px; }
.dim-row { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 6px; cursor: pointer; transition: background 0.15s; }
.dim-row:hover,.dim-row.selected { background: var(--ots-bg); }
.dim-name { width: 80px; font-size: 13px; font-weight: 500; flex-shrink: 0; }
.dim-bar { flex: 1; }
.dim-score { width: 36px; text-align: right; font-weight: 600; font-size: 14px; }
.dim-evidence { width: 96px; text-align: right; font-size: 12px; flex-shrink: 0; }
.dim-empty { padding: 12px 0; font-size: 13px; }
.weak-hint { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 12px; padding: 10px; background: var(--ots-safety-bg); border-radius: 6px; font-size: 13px; color: #92400e; }
.weak-hint .text-secondary { width: 100%; font-size: 12px; }
.algo-card { padding-top: 4px; }
.algo-heading { margin: 8px 0 10px; font-size: 13px; color: var(--ots-text-secondary); }
.algo-heading:first-child { margin-top: 0; }
</style>
