<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { abilityApi, recommendationApi, trainingApi } from '@/api'
import type { AbilityProfileOut, RecommendationOut, TrainingSessionOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'
import EChartsRadar from '@/components/EChartsRadar.vue'

const router = useRouter()
const profile = ref<AbilityProfileOut | null>(null)
const recommendations = ref<RecommendationOut[]>([])
const sessions = ref<TrainingSessionOut[]>([])
const loading = ref(true)

const abilities = computed(() => {
  if (!profile.value) return []
  return Object.entries(profile.value).map(([key, dimension]) => ({
    key: key as AbilityKey,
    name: dimension.name || ABILITY_LABELS[key as AbilityKey] || key,
    weight: dimension.weight,
    score: dimension.score,
  }))
})
const totalScore = computed(() => {
  if (!profile.value) return 0
  const values = Object.values(profile.value)
  return values.length ? Math.round(values.reduce((sum, item) => sum + item.score, 0) / values.length) : 0
})
const completedCount = computed(() => sessions.value.filter((session) => session.finished).length)
const weakAbilities = computed(() => {
  if (!profile.value) return []
  return Object.entries(profile.value)
    .filter(([, value]) => value.score < 60)
    .sort((a, b) => a[1].score - b[1].score)
    .slice(0, 3)
})
const topRecommendation = computed(() => recommendations.value[0] || null)

onMounted(async () => {
  try {
    const [profileResult, recommendationResult, sessionResult] = await Promise.allSettled([
      abilityApi.profile(),
      recommendationApi.tasks(),
      trainingApi.sessions(),
    ])
    if (profileResult.status === 'fulfilled') profile.value = profileResult.value
    if (recommendationResult.status === 'fulfilled') recommendations.value = recommendationResult.value
    if (sessionResult.status === 'fulfilled') sessions.value = sessionResult.value
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page growth-dashboard" v-loading="loading">
    <section class="growth-hero">
      <div>
        <div class="eyebrow">岗位能力成长中心</div>
        <h2>今天，从下一项岗位任务开始</h2>
        <p>系统根据你的实训记录和六维能力表现，动态推荐补强任务与学习路径。</p>
      </div>
      <el-button @click="router.push('/ability-graph')"><el-icon><Aim /></el-icon>查看目标岗位能力</el-button>
    </section>

    <section v-if="topRecommendation" class="next-task">
      <div class="next-badge"><span>下一步</span><strong>智能推荐</strong></div>
      <div class="next-copy">
        <span>岗位情境实训</span>
        <h3>{{ topRecommendation.task_title }}</h3>
        <p>{{ topRecommendation.reason_text }}</p>
        <div class="task-meta"><span><el-icon><TrendCharts /></el-icon>{{ topRecommendation.target_ability_name }}</span><span><el-icon><Timer /></el-icon>{{ topRecommendation.estimated_minutes }} 分钟</span><span><el-icon><Medal /></el-icon>难度 {{ topRecommendation.difficulty }}</span></div>
      </div>
      <div class="next-action"><small>完成后将更新能力画像与学习路径</small><el-button type="primary" size="large" @click="router.push(`/training/${topRecommendation.task_code}`)">开始任务<el-icon><ArrowRight /></el-icon></el-button></div>
    </section>
    <section v-else class="next-task empty-task">
      <div class="next-copy"><span>开始岗位能力成长</span><h3>完成第一次诊断实训</h3><p>完成任务后，系统将生成能力画像并为你推荐个性化学习路径。</p></div>
      <el-button type="primary" @click="router.push('/training')">进入实训中心</el-button>
    </section>

    <section class="growth-summary ots-card">
      <div class="summary-heading"><span>我的成长概览</span><strong>每次实训后动态更新</strong></div>
      <div class="summary-grid">
        <div><span class="summary-icon score"><el-icon><DataAnalysis /></el-icon></span><p><strong>{{ totalScore }}</strong><small>综合能力分</small></p></div>
        <div><span class="summary-icon complete"><el-icon><CircleCheck /></el-icon></span><p><strong>{{ completedCount }}</strong><small>已完成实训</small></p></div>
        <div><span class="summary-icon focus"><el-icon><Warning /></el-icon></span><p><strong>{{ weakAbilities.length }}</strong><small>优先补强维度</small></p></div>
      </div>
      <el-button text type="primary" @click="router.push('/profile')">查看能力成长档案<el-icon><ArrowRight /></el-icon></el-button>
    </section>

    <div class="ability-grid">
      <section class="ots-card radar-card">
        <div class="card-heading"><div><span>六维岗位能力</span><h3>我的能力结构</h3></div><el-tag type="success" effect="plain">综合 {{ totalScore }} 分</el-tag></div>
        <EChartsRadar v-if="abilities.length" :abilities="abilities" height="300px" />
        <el-empty v-else description="完成实训后将自动生成能力结构" />
      </section>

      <section class="ots-card focus-card">
        <div class="card-heading"><div><span>学习行动建议</span><h3>优先补强能力</h3></div><el-button text type="primary" @click="router.push('/adaptive-learning')">查看学习路径</el-button></div>
        <div v-if="weakAbilities.length" class="weak-list">
          <div v-for="([key, dimension], index) in weakAbilities" :key="key" class="weak-item">
            <span class="weak-rank">{{ index + 1 }}</span>
            <div class="weak-content"><div><strong>{{ dimension.name || ABILITY_LABELS[key as AbilityKey] }}</strong><em>{{ dimension.score.toFixed(0) }} 分</em></div><el-progress :percentage="dimension.score" :stroke-width="8" :show-text="false" /></div>
          </div>
        </div>
        <div v-else class="balanced-state"><span><el-icon><CircleCheckFilled /></el-icon></span><div><strong>当前能力表现均衡</strong><p>继续完成进阶实训，保持岗位能力持续成长。</p></div></div>
      </section>
    </div>

    <section v-if="recommendations.length > 1" class="ots-card more-tasks">
      <div class="card-heading"><div><span>后续学习任务</span><h3>为你推荐的岗位实训</h3></div><el-button text type="primary" @click="router.push('/training')">查看全部任务</el-button></div>
      <div class="task-list">
        <button v-for="item in recommendations.slice(1, 4)" :key="item.task_id" type="button" @click="router.push(`/training/${item.task_code}`)">
          <div><span>{{ item.target_ability_name }}</span><strong>{{ item.task_title }}</strong><p>{{ item.reason_text }}</p></div>
          <footer><span>难度 {{ item.difficulty }} · {{ item.estimated_minutes }} 分钟</span><el-icon><ArrowRight /></el-icon></footer>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.growth-dashboard { max-width: 1450px; margin: 0 auto; }
.growth-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin: 2px 0 17px; }
.eyebrow,.card-heading span { color: var(--ots-growth); font-size: 11px; font-weight: 600; letter-spacing: .7px; }
.growth-hero h2 { margin: 6px 0 7px; color: var(--ots-primary-dark); font-size: 25px; }
.growth-hero p { margin: 0; color: var(--ots-text-secondary); }
.next-task { display: grid; grid-template-columns: 90px minmax(280px, 1fr) 230px; align-items: center; gap: 20px; margin-bottom: 16px; padding: 23px 25px; border: 1px solid #cce4d7; border-radius: 14px; background: linear-gradient(115deg, #edf8f2, #fff 62%); box-shadow: 0 7px 24px rgba(38,105,76,.07); }
.next-badge { display: grid; place-items: center; align-content: center; width: 76px; height: 76px; border-radius: 50%; background: var(--ots-growth); color: #fff; }
.next-badge span,.next-badge strong { display: block; }
.next-badge span { font-size: 10px; opacity: .8; }
.next-badge strong { margin-top: 2px; font-size: 12px; }
.next-copy > span { color: var(--ots-growth); font-size: 11px; font-weight: 600; }
.next-copy h3 { margin: 5px 0 6px; color: var(--ots-primary-dark); font-size: 20px; }
.next-copy p { margin: 0; color: var(--ots-text-secondary); font-size: 12px; line-height: 1.55; }
.task-meta { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 11px; color: #547069; font-size: 10px; }
.task-meta span { display: flex; align-items: center; gap: 4px; }
.next-action { display: flex; align-items: flex-end; flex-direction: column; gap: 9px; }
.next-action small { color: var(--ots-text-secondary); font-size: 9px; text-align: right; }
.empty-task { grid-template-columns: 1fr auto; }
.growth-summary { display: grid; grid-template-columns: 190px minmax(0, 1fr) auto; align-items: center; padding: 17px 21px; }
.summary-heading span,.summary-heading strong { display: block; }
.summary-heading span { color: var(--ots-text-secondary); font-size: 10px; }
.summary-heading strong { margin-top: 4px; font-size: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); border-left: 1px solid var(--ots-border); }
.summary-grid > div { display: flex; align-items: center; gap: 9px; padding: 2px 18px; border-right: 1px solid var(--ots-border); }
.summary-grid > div:last-child { border-right: 0; }
.summary-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; }
.summary-icon.score { background: var(--ots-education-soft); color: var(--ots-education); }
.summary-icon.complete { background: var(--ots-growth-soft); color: var(--ots-growth); }
.summary-icon.focus { background: var(--ots-practice-soft); color: var(--ots-practice); }
.summary-grid p { margin: 0; }
.summary-grid strong,.summary-grid small { display: block; }
.summary-grid strong { color: var(--ots-primary-dark); font-size: 21px; }
.summary-grid small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }
.ability-grid { display: grid; grid-template-columns: 1.05fr .95fr; gap: 16px; }
.card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 13px; }
.card-heading h3 { margin: 3px 0 0; font-size: 17px; }
.weak-list { display: flex; flex-direction: column; gap: 9px; }
.weak-item { display: grid; grid-template-columns: 28px 1fr; align-items: center; gap: 10px; padding: 11px; border-radius: 9px; background: var(--ots-bg-subtle); }
.weak-rank { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; background: var(--ots-practice-soft); color: var(--ots-practice); font-size: 10px; font-weight: 700; }
.weak-content > div { display: flex; justify-content: space-between; margin-bottom: 7px; }
.weak-content strong { font-size: 12px; }
.weak-content em { color: var(--ots-warning); font-size: 11px; font-style: normal; font-weight: 600; }
.balanced-state { display: flex; align-items: center; gap: 12px; min-height: 160px; justify-content: center; }
.balanced-state > span { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 14px; background: var(--ots-growth-soft); color: var(--ots-growth); font-size: 23px; }
.balanced-state strong { font-size: 14px; }
.balanced-state p { margin: 5px 0 0; color: var(--ots-text-secondary); font-size: 10px; }
.task-list { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.task-list button { display: flex; flex-direction: column; justify-content: space-between; min-height: 145px; padding: 14px; border: 1px solid var(--ots-border); border-radius: 9px; background: #fff; color: var(--ots-text); text-align: left; cursor: pointer; }
.task-list button:hover { border-color: var(--ots-growth); background: #f8fcfa; }
.task-list button > div > span { color: var(--ots-growth); font-size: 10px; font-weight: 600; }
.task-list strong { display: block; margin-top: 6px; font-size: 13px; }
.task-list p { margin: 6px 0; color: var(--ots-text-secondary); font-size: 10px; line-height: 1.45; }
.task-list footer { display: flex; align-items: center; justify-content: space-between; color: var(--ots-text-secondary); font-size: 9px; }

@media (max-width: 1100px) {
  .next-task { grid-template-columns: 74px 1fr; }
  .next-action { grid-column: 1 / -1; align-items: center; flex-direction: row; justify-content: flex-end; }
  .growth-summary { grid-template-columns: 1fr; }
  .summary-heading { margin-bottom: 12px; }
  .summary-grid { margin-bottom: 8px; padding-top: 12px; border-top: 1px solid var(--ots-border); border-left: 0; }
  .ability-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .growth-hero { align-items: flex-start; flex-direction: column; }
  .growth-hero h2 { font-size: 21px; }
  .next-task,.empty-task { grid-template-columns: 1fr; padding: 18px; }
  .next-badge { width: 62px; height: 62px; }
  .next-action { grid-column: auto; align-items: stretch; flex-direction: column; }
  .next-action small { text-align: left; }
  .summary-grid,.task-list { grid-template-columns: 1fr; }
  .summary-grid > div { padding: 9px 0; border-right: 0; border-bottom: 1px solid var(--ots-border); }
  .summary-grid > div:last-child { border-bottom: 0; }
}
</style>
