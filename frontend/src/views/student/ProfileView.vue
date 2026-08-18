<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { abilityApi } from '@/api'
import type { AbilityProfileOut, AbilityHistoryOut, AbilityItem, RadarDataOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'
import EChartsRadar from '@/components/EChartsRadar.vue'

const profile = ref<AbilityProfileOut | null>(null)
const history = ref<AbilityHistoryOut[]>([])
const radar = ref<RadarDataOut | null>(null)
const loading = ref(true)
const selectedAbility = ref<string>('')

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
  if (!profile.value) return 0
  const vals = Object.values(profile.value)
  if (!vals.length) return 0
  return Math.round(vals.reduce((s, v) => s + v.score, 0) / vals.length)
})

const totalAttempts = computed(() => {
  if (!profile.value) return 0
  return Object.values(profile.value).reduce((s, v) => s + v.attempt_count, 0)
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

function selectAbility(key: string) {
  selectedAbility.value = selectedAbility.value === key ? '' : key
  loadHistory(selectedAbility.value)
}

onMounted(async () => {
  try {
    const [p, r] = await Promise.allSettled([abilityApi.profile(), abilityApi.radar()])
    if (p.status === 'fulfilled') profile.value = p.value
    if (r.status === 'fulfilled') radar.value = r.value
    await loadHistory()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <h2 style="margin: 0 0 16px">岗位能力成长档案</h2>

    <!-- 总览 -->
    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <div class="ots-card">
          <h3 class="ots-title">六维能力雷达</h3>
          <EChartsRadar v-if="abilities.length" :abilities="abilities" height="340px" />
          <el-empty v-else description="完成训练后将自动生成能力画像" />
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="ots-card">
          <h3 class="ots-title">能力概览</h3>
          <el-row :gutter="12" style="margin-bottom: 16px">
            <el-col :span="8">
              <div class="stat-mini">
                <div class="stat-mini-val">{{ averageScore }}</div>
                <div class="stat-mini-label">平均分</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="stat-mini">
                <div class="stat-mini-val">{{ totalAttempts }}</div>
                <div class="stat-mini-label">训练次数</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="stat-mini">
                <div class="stat-mini-val">{{ abilities.length }}</div>
                <div class="stat-mini-label">维度数</div>
              </div>
            </el-col>
          </el-row>

          <h4 style="margin: 0 0 8px; font-size: 14px">各维度详情</h4>
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
              <div class="dim-attempts text-secondary">{{ profile?.[ab.key]?.attempt_count ?? 0 }}次</div>
            </div>
          </div>
          <div v-if="weakestDim" class="weak-hint">
            <el-icon><WarningFilled /></el-icon>
            当前最需提升：<strong>{{ weakestDim.name }}</strong>（{{ weakestDim.score.toFixed(0) }}分）
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 变更历史 -->
    <div class="ots-card">
      <h3 class="ots-title">
        能力变更历史
        <el-tag v-if="selectedAbility" size="small" closable @close="selectAbility(selectedAbility)">
          {{ ABILITY_LABELS[selectedAbility as AbilityKey] || selectedAbility }}
        </el-tag>
      </h3>
      <el-table v-if="history.length" :data="history" stripe empty-text="暂无记录">
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column prop="ability_name" label="维度" width="120" />
        <el-table-column label="变化" width="200">
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
        <el-table-column prop="training_score" label="本次训练分" width="120" />
      </el-table>
      <el-empty v-else description="暂无变更记录" :image-size="60" />
    </div>
  </div>
</template>

<style scoped>
.stat-mini {
  text-align: center;
  padding: 8px;
}
.stat-mini-val {
  font-size: 24px;
  font-weight: 700;
  color: var(--ots-primary-dark);
}
.stat-mini-label {
  font-size: 12px;
  color: var(--ots-text-secondary);
}
.dim-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dim-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.dim-row:hover,
.dim-row.selected {
  background: var(--ots-bg);
}
.dim-name {
  width: 80px;
  font-size: 13px;
  font-weight: 500;
  flex-shrink: 0;
}
.dim-bar {
  flex: 1;
}
.dim-score {
  width: 36px;
  text-align: right;
  font-weight: 600;
  font-size: 14px;
}
.dim-attempts {
  width: 36px;
  text-align: right;
  font-size: 12px;
}
.weak-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 10px;
  background: var(--ots-safety-bg);
  border-radius: 6px;
  font-size: 13px;
  color: #92400e;
}
</style>
