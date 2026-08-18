<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { trainingApi, abilityApi } from '@/api'
import type { TrainingSessionOut, EvaluationOut, AbilityItem } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'
import EChartsRadar from '@/components/EChartsRadar.vue'

const route = useRoute()
const router = useRouter()
const sessionId = Number(route.params.id)
const session = ref<TrainingSessionOut | null>(null)
const abilities = ref<AbilityItem[]>([])
const loading = ref(true)

const evaluation = computed<EvaluationOut | null>(() => session.value?.evaluation || null)

function scoreColor(score: number) {
  if (score >= 80) return '#2e7d32'
  if (score >= 60) return '#0b5f6b'
  if (score >= 40) return '#ed6c02'
  return '#c62828'
}

function scoreLabel(score: number) {
  if (score >= 90) return '优秀'
  if (score >= 80) return '良好'
  if (score >= 70) return '中等'
  if (score >= 60) return '及格'
  return '需加强'
}

onMounted(async () => {
  try {
    const [sess, radarRes] = await Promise.allSettled([
      trainingApi.detail(sessionId),
      abilityApi.radar(),
    ])
    if (sess.status === 'fulfilled') session.value = sess.value
    if (radarRes.status === 'fulfilled') {
      const r = radarRes.value
      abilities.value = (r.labels || []).map((name, i) => ({
        key: (r.indicators?.[i]?.name || name) as AbilityKey,
        name,
        weight: 1,
        score: r.scores?.[i] ?? 0,
      }))
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <el-page-header @back="router.push('/training')" content="训练结果" />

    <div v-if="evaluation" style="margin-top: 16px">
      <!-- 总分 -->
      <div class="ots-card score-hero">
        <div class="hero-score" :style="{ color: scoreColor(evaluation.final_score) }">
          {{ evaluation.final_score }}
        </div>
        <div class="hero-label">{{ scoreLabel(evaluation.final_score) }}</div>
        <div class="hero-task">{{ session?.task_title }}</div>
      </div>

      <el-row :gutter="16">
        <!-- 规则评分 -->
        <el-col :xs="24" :md="12">
          <div class="ots-card">
            <h3 class="ots-title">评分明细</h3>
            <div class="score-breakdown">
              <div class="score-row">
                <div class="score-info">
                  <span class="score-name">数据库选项规则评分</span>
                  <span class="text-secondary">每道题按教师配置的选项分值计算</span>
                </div>
                <div class="score-val">{{ evaluation.rule_score }}</div>
              </div>
              <div class="scoring-note">
                本次成绩不调用大模型评分，题目、选项、得分和反馈均来自数据库，可由教师复核。
              </div>
            </div>
          </div>
        </el-col>

        <!-- 六维能力雷达 -->
        <el-col :xs="24" :md="12">
          <div class="ots-card">
            <h3 class="ots-title">六维能力表现</h3>
            <EChartsRadar v-if="abilities.length" :abilities="abilities" height="280px" />
            <div v-else-if="evaluation.ability_scores" class="ability-scores">
              <div
                v-for="(score, key) in evaluation.ability_scores"
                :key="key"
                class="ability-row"
              >
                <span>{{ ABILITY_LABELS[key as AbilityKey] || key }}</span>
                <el-progress :percentage="score" :stroke-width="8" :color="scoreColor(score)" />
              </div>
            </div>
            <el-empty v-else description="暂无能力数据" :image-size="60" />
          </div>
        </el-col>
      </el-row>

      <!-- 评价说明 -->
      <div class="ots-card" v-if="evaluation.explanation">
        <h3 class="ots-title">评价说明</h3>
        <p style="line-height: 1.8; white-space: pre-wrap">{{ evaluation.explanation }}</p>
      </div>

      <div class="ots-card" v-if="session?.answer_records?.length">
        <h3 class="ots-title">逐题复盘</h3>
        <el-table :data="session.answer_records" stripe>
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="review-detail">
                <p><strong>我的选择：</strong>{{ row.selected_option_key }}. {{ row.selected_option_content }}</p>
                <p><strong>反馈：</strong>{{ row.feedback }}</p>
                <p v-if="row.explanation"><strong>知识解析：</strong>{{ row.explanation }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="question_code" label="题号" width="120" />
          <el-table-column prop="stem" label="题目" min-width="280" />
          <el-table-column prop="knowledge_point" label="知识点" min-width="130" />
          <el-table-column label="结果" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.is_correct ? 'success' : 'warning'" size="small">
                {{ row.is_correct ? '正确' : '需复盘' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="得分" width="90" align="center">
            <template #default="{ row }">{{ row.score }}/{{ row.max_score }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="ots-card" v-if="evaluation.citations?.length">
        <h3 class="ots-title">本次评价的权威依据</h3>
        <el-table :data="evaluation.citations" stripe>
          <el-table-column prop="title" label="知识依据" min-width="220" />
          <el-table-column prop="source_no" label="来源编号" min-width="220" />
          <el-table-column prop="chapter" label="章节" min-width="160" />
          <el-table-column label="PDF 页码" width="100" align="center">
            <template #default="{ row }">{{ row.page ?? '—' }}</template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 操作 -->
      <div class="ots-card actions">
        <el-button @click="router.push('/training')">返回实训中心</el-button>
        <el-button type="primary" @click="router.push(`/training/${session?.task_code}`)">
          再次训练
        </el-button>
        <el-button @click="router.push('/profile')">查看能力画像</el-button>
      </div>
    </div>

    <el-empty v-else-if="!loading" description="暂无评价结果">
      <el-button @click="router.push('/training')">返回实训中心</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
.score-hero {
  text-align: center;
  padding: 30px 20px;
}
.hero-score {
  font-size: 64px;
  font-weight: 800;
  line-height: 1;
}
.hero-label {
  font-size: 18px;
  color: var(--ots-text-secondary);
  margin-top: 6px;
}
.hero-task {
  font-size: 14px;
  color: var(--ots-text-secondary);
  margin-top: 4px;
}
.score-breakdown {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.score-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px;
  background: var(--ots-bg);
  border-radius: 8px;
}
.score-name {
  font-weight: 600;
  display: block;
}
.score-val {
  font-size: 22px;
  font-weight: 700;
  color: var(--ots-primary-dark);
}
.scoring-note {
  color: var(--ots-text-secondary);
  line-height: 1.7;
  padding: 12px;
  background: var(--ots-bg);
  border-radius: 8px;
}
.review-detail {
  padding: 4px 24px;
  line-height: 1.7;
}
.review-detail p { margin: 6px 0; }
.ability-scores {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ability-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.ability-row > span {
  width: 80px;
  flex-shrink: 0;
  font-size: 13px;
}
.actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}
</style>
