<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { abilityApi, recommendationApi, simulationApi, trainingApi } from '@/api'
import type { AbilityGrowthOut, AbilityHistoryOut, AbilityProfileOut, RecommendationOut, SimulationScenarioSummary, TrainingSessionOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'
import EChartsRadar from '@/components/EChartsRadar.vue'

const router = useRouter()
const profile = ref<AbilityProfileOut | null>(null)
const recommendations = ref<RecommendationOut[]>([])
const sessions = ref<TrainingSessionOut[]>([])
const growth = ref<AbilityGrowthOut | null>(null)
const history = ref<AbilityHistoryOut[]>([])
const scenarios = ref<SimulationScenarioSummary[]>([])

// 每数据源独立状态：单接口失败只降级对应区域（§13）
type SourceState = 'loading' | 'ok' | 'error'
const profileState = ref<SourceState>('loading')
const scenariosState = ref<SourceState>('loading')
const recommendationsState = ref<SourceState>('loading')
const growthState = ref<SourceState>('loading')
const historyState = ref<SourceState>('loading')
const sessionsState = ref<SourceState>('loading')

const CONFIDENCE_LABELS: Record<string, string> = { low: '较低', medium: '中', high: '高' }

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

// 最弱能力：忽略无有效数据的空维度（attempt 与 evidence 均为 0 视为未测）；
// 严格小于比较 + 后端返回顺序 → 同分保持首现，不随机（§3）
const weakest = computed(() => {
  if (!profile.value) return null
  let best: { abilityKey: string; abilityName: string; score: number; confidence?: string } | null = null
  for (const [key, dimension] of Object.entries(profile.value)) {
    if (!dimension || typeof dimension.score !== 'number') continue
    if ((dimension.attempt_count ?? 0) <= 0 && (dimension.evidence_count ?? 0) <= 0) continue
    if (!best || dimension.score < best.score) {
      best = { abilityKey: key, abilityName: dimension.name || ABILITY_LABELS[key as AbilityKey] || key, score: dimension.score, confidence: dimension.confidence }
    }
  }
  return best
})

// Simulation First：target_abilities 覆盖最弱能力的场景优先；
// 多个匹配时选难度更低者（稳定排序，同难度保持列表原序）；场景列表即后端可用集
const matchedScenario = computed(() => {
  const weak = weakest.value
  if (!weak || scenariosState.value !== 'ok') return null
  const covered = scenarios.value.filter((scenario) => (scenario.target_abilities || []).includes(weak.abilityKey))
  if (!covered.length) return null
  return covered.reduce((best, item) => ((item.difficulty ?? 0) < (best.difficulty ?? 0) ? item : best), covered[0])
})

const topRecommendation = computed(() => recommendations.value[0] || null)
const primaryMode = computed<'sim' | 'train' | 'none' | 'browse' | 'loading'>(() => {
  if (profileState.value === 'loading' || scenariosState.value === 'loading' || recommendationsState.value === 'loading') return 'loading'
  // profile 失败：不做能力匹配，退化为普通可用任务浏览（§13）
  if (profileState.value === 'error') return 'browse'
  if (matchedScenario.value) return 'sim'
  if (topRecommendation.value) return 'train'
  return 'none'
})
// 主推荐占用 recommendations[0] 时（fallback 态），后续列表从第 2 条起
const moreTasks = computed(() => recommendations.value.slice(primaryMode.value === 'train' ? 1 : 0, 4))
const scenarioAbilityNames = (scenario: SimulationScenarioSummary) =>
  (scenario.target_abilities || []).slice(0, 3).map((key) => ABILITY_LABELS[key as AbilityKey] || key).join(' · ')

function settle<T>(result: PromiseSettledResult<T>, apply: (value: T) => void, state?: { value: SourceState }) {
  if (result.status === 'fulfilled') { apply(result.value); if (state) state.value = 'ok' }
  else { console.warn('[student-dashboard] 数据源加载失败，区域级降级', result.reason); if (state) state.value = 'error' }
}

onMounted(async () => {
  // 一次并行，无串行等待（§14）；profile 与 scenarios 均进 computed 后才生成推荐，不互相依赖
  const [profileResult, growthResult, historyResult, scenarioResult, recommendationResult, sessionResult] = await Promise.allSettled([
    abilityApi.profile(),
    abilityApi.growth(),
    abilityApi.history(undefined, 5),
    simulationApi.scenarios(),
    recommendationApi.tasks(),
    trainingApi.sessions(),
  ])
  settle(profileResult, (v) => { profile.value = v }, profileState)
  settle(growthResult, (v) => { growth.value = v }, growthState)
  settle(historyResult, (v) => { history.value = v }, historyState)
  settle(scenarioResult, (v) => { scenarios.value = v }, scenariosState)
  settle(recommendationResult, (v) => { recommendations.value = v }, recommendationsState)
  settle(sessionResult, (v) => { sessions.value = v }, sessionsState)
})
</script>

<template>
  <div class="ots-page growth-dashboard">
    <section class="growth-hero">
      <div>
        <div class="eyebrow">岗位能力成长中心</div>
        <h2>今天，从下一项岗位任务开始</h2>
        <p>系统根据你的实训记录和六维能力表现，动态推荐补强任务与学习路径。</p>
      </div>
      <el-button @click="router.push('/ability-graph')"><el-icon><Aim /></el-icon>查看目标岗位能力</el-button>
    </section>

    <!-- 第一视觉：主推荐（仿真实训优先，情境训练回退） -->
    <section class="next-task">
      <el-skeleton v-if="primaryMode === 'loading'" class="primary-skeleton" :rows="3" animated />

      <!-- A. 有匹配仿真实训 -->
      <template v-else-if="primaryMode === 'sim' && matchedScenario && weakest">
        <div class="next-badge"><span>优先</span><strong>仿真实训</strong></div>
        <div class="next-copy">
          <span>岗位仿真实训</span>
          <h3>{{ matchedScenario.title }}</h3>
          <p>你当前“{{ weakest.abilityName }}”能力相对薄弱，本场景可以形成操作型技能证据。</p>
          <div class="task-meta">
            <span><el-icon><TrendCharts /></el-icon>目标能力 {{ scenarioAbilityNames(matchedScenario) }}</span>
            <span><el-icon><Medal /></el-icon>难度 {{ matchedScenario.difficulty }}</span>
            <span><el-icon><Timer /></el-icon>{{ matchedScenario.estimated_minutes }} 分钟</span>
          </div>
          <p class="next-note">完成仿真后，系统将根据行为事件和评分规则生成技能证据。</p>
        </div>
        <div class="next-action">
          <small>当前「{{ weakest.abilityName }}」{{ weakest.score.toFixed(0) }} 分<template v-if="weakest.confidence"> · 置信度 {{ CONFIDENCE_LABELS[weakest.confidence] || weakest.confidence }}</template></small>
          <el-button type="primary" size="large" @click="router.push(`/simulation/${matchedScenario.scenario_code}`)">开始仿真<el-icon><ArrowRight /></el-icon></el-button>
        </div>
      </template>

      <!-- B. 无匹配仿真 → 回退岗位情境训练推荐 -->
      <template v-else-if="primaryMode === 'train' && topRecommendation">
        <div class="next-badge"><span>下一步</span><strong>智能推荐</strong></div>
        <div class="next-copy">
          <span>岗位情境训练</span>
          <h3>{{ topRecommendation.task_title }}</h3>
          <p>{{ topRecommendation.reason_text }}</p>
          <div class="task-meta">
            <span><el-icon><TrendCharts /></el-icon>{{ topRecommendation.target_ability_name }}</span>
            <span><el-icon><Timer /></el-icon>{{ topRecommendation.estimated_minutes }} 分钟</span>
            <span><el-icon><Medal /></el-icon>难度 {{ topRecommendation.difficulty }}</span>
          </div>
        </div>
        <div class="next-action">
          <small>完成后将更新能力画像与学习路径</small>
          <el-button type="primary" size="large" @click="router.push(`/training/${topRecommendation.task_code}`)">开始训练<el-icon><ArrowRight /></el-icon></el-button>
        </div>
      </template>

      <!-- C. 完全无推荐：不制造推荐 -->
      <template v-else-if="primaryMode === 'none'">
        <div class="next-badge"><span>起步</span><strong>首次训练</strong></div>
        <div class="next-copy">
          <span>开始岗位能力成长</span>
          <h3>完成首次能力训练</h3>
          <p>完成首次能力训练后，系统将根据你的技能证据生成个性化推荐。</p>
        </div>
        <div class="next-action action-browse">
          <el-button type="primary" @click="router.push('/simulation')">浏览岗位仿真实训</el-button>
          <el-button @click="router.push('/training')">查看岗位情境训练</el-button>
        </div>
      </template>

      <!-- D. profile 获取失败：退化为浏览入口（§13） -->
      <template v-else-if="primaryMode === 'browse'">
        <div class="next-badge"><span>浏览</span><strong>岗位任务</strong></div>
        <div class="next-copy">
          <span>岗位任务</span>
          <h3>先看看可参加的任务</h3>
          <p>暂时无法获取你的能力档案，个性化推荐稍后自动恢复；你也可以先浏览可用任务。</p>
        </div>
        <div class="next-action action-browse">
          <el-button type="primary" @click="router.push('/simulation')">浏览岗位仿真实训</el-button>
          <el-button @click="router.push('/training')">查看岗位情境训练</el-button>
        </div>
      </template>
    </section>

    <!-- 成长概览：四项统计（Growth XP / 有效技能证据取后端 aggregate，不用 attempt_count） -->
    <section class="growth-summary ots-card">
      <div class="summary-heading"><span>我的成长概览</span><strong>每次实训后动态更新</strong></div>
      <div class="summary-grid">
        <div><span class="summary-icon score"><el-icon><DataAnalysis /></el-icon></span><p><strong>{{ profileState === 'ok' ? totalScore : '—' }}</strong><small>综合能力</small></p></div>
        <div><span class="summary-icon complete"><el-icon><CircleCheck /></el-icon></span><p><strong>{{ sessionsState === 'ok' ? completedCount : '—' }}</strong><small>完成训练</small></p></div>
        <div><span class="summary-icon xp"><el-icon><Medal /></el-icon></span><p><strong>{{ growthState === 'ok' ? growth?.total_xp : '—' }}</strong><small>Growth XP</small></p></div>
        <div><span class="summary-icon evidence"><el-icon><Files /></el-icon></span><p><strong>{{ growthState === 'ok' ? growth?.total_evidence : '—' }}</strong><small>有效技能证据</small></p></div>
      </div>
      <el-button text type="primary" @click="router.push('/profile')">查看技能画像与证据<el-icon><ArrowRight /></el-icon></el-button>
    </section>

    <!-- 第三层：最近成长 + 当前优先补强（雷达图之后不再是视觉中心） -->
    <div class="ability-grid">
      <section class="ots-card history-card">
        <div class="card-heading"><div><span>能力变化记录</span><h3>最近成长</h3></div><el-button text type="primary" @click="router.push('/profile')">查看档案<el-icon><ArrowRight /></el-icon></el-button></div>
        <div v-if="history.length" class="growth-list">
          <div v-for="item in history.slice(0, 3)" :key="item.id" class="growth-row">
            <div><strong>{{ item.ability_name || ABILITY_LABELS[item.ability_key as AbilityKey] || item.ability_key }}</strong><small>{{ item.created_at ? item.created_at.slice(5, 10) : '' }}</small></div>
            <em class="score-move" :class="{ up: item.after_score >= item.before_score, down: item.after_score < item.before_score }">{{ item.before_score.toFixed(0) }} → {{ item.after_score.toFixed(0) }}</em>
          </div>
          <p class="growth-basis">分数变化来自每次测评的更新前后记录，仅展示真实数据。</p>
        </div>
        <div v-else class="history-empty">
          <p>{{ historyState === 'error' ? '暂时无法获取成长记录。' : historyState === 'loading' ? '成长记录加载中…' : '暂无能力分数变化记录，完成一次训练后生成。' }}</p>
        </div>
      </section>

      <section class="ots-card focus-card">
        <div class="card-heading"><div><span>学习行动建议</span><h3>当前优先补强</h3></div><el-button v-if="weakest" text type="primary" @click="router.push('/adaptive-learning')">继续补强<el-icon><ArrowRight /></el-icon></el-button></div>
        <template v-if="weakest">
          <div class="weak-primary">
            <div><span>重点能力</span><strong>{{ weakest.abilityName }}</strong><em>{{ weakest.score.toFixed(0) }} 分</em></div>
            <p v-if="weakest.confidence === 'low'" class="low-confidence">当前证据较少，建议通过岗位训练继续验证。</p>
            <p v-else-if="weakest.confidence" class="confidence-line">能力置信度：{{ CONFIDENCE_LABELS[weakest.confidence] || weakest.confidence }}</p>
          </div>
          <div v-if="weakAbilities.length > 1" class="weak-list">
            <div v-for="([key, dimension], index) in weakAbilities.slice(1)" :key="key" class="weak-item">
              <span class="weak-rank">{{ index + 2 }}</span>
              <div class="weak-content"><div><strong>{{ dimension.name || ABILITY_LABELS[key as AbilityKey] }}</strong><em>{{ dimension.score.toFixed(0) }} 分</em></div><el-progress :percentage="dimension.score" :stroke-width="8" :show-text="false" /></div>
            </div>
          </div>
        </template>
        <div v-else class="history-empty"><p>{{ profileState === 'error' ? '暂时无法获取能力档案。' : '暂无有效能力数据，完成首次训练后生成补强建议。' }}</p></div>
      </section>
    </div>

    <section class="ots-card radar-card">
      <div class="card-heading"><div><span>六维岗位能力</span><h3>我的能力结构</h3></div><el-tag v-if="profileState === 'ok'" type="success" effect="plain">综合 {{ totalScore }} 分</el-tag></div>
      <EChartsRadar v-if="abilities.length" :abilities="abilities" height="300px" />
      <el-empty v-else :description="profileState === 'loading' ? '能力结构加载中…' : '完成实训后将自动生成能力结构'" />
    </section>

    <section v-if="moreTasks.length" class="ots-card more-tasks">
      <div class="card-heading"><div><span>后续学习任务</span><h3>为你推荐的岗位情境训练</h3></div><el-button text type="primary" @click="router.push('/training')">查看全部任务</el-button></div>
      <div class="task-list">
        <button v-for="item in moreTasks" :key="item.task_id" type="button" @click="router.push(`/training/${item.task_code}`)">
          <div><span>{{ item.target_ability_name }}</span><strong>{{ item.task_title }}</strong><p>{{ item.reason_text }}</p></div>
          <footer><span>难度 {{ item.difficulty }} · {{ item.estimated_minutes }} 分钟</span><el-icon><ArrowRight /></el-icon></footer>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.growth-dashboard { max-width: 1450px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.growth-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin: 2px 0 1px; }
.eyebrow,.card-heading span { color: var(--ots-growth); font-size: 11px; font-weight: 600; letter-spacing: .7px; }
.growth-hero h2 { margin: 6px 0 7px; color: var(--ots-primary-dark); font-size: 25px; }
.growth-hero p { margin: 0; color: var(--ots-text-secondary); }
.next-task { display: grid; grid-template-columns: 90px minmax(280px, 1fr) 230px; align-items: center; gap: 20px; min-height: 178px; padding: 23px 25px; border: 1px solid #cce4d7; border-radius: 14px; background: linear-gradient(115deg, #edf8f2, #fff 62%); box-shadow: 0 7px 24px rgba(38,105,76,.07); }
.primary-skeleton { grid-column: 1 / -1; }
.next-badge { display: grid; place-items: center; align-content: center; width: 76px; height: 76px; border-radius: 50%; background: var(--ots-growth); color: #fff; }
.next-badge span,.next-badge strong { display: block; }
.next-badge span { font-size: 10px; opacity: .8; }
.next-badge strong { margin-top: 2px; font-size: 12px; }
.next-copy > span { color: var(--ots-growth); font-size: 11px; font-weight: 600; }
.next-copy h3 { margin: 5px 0 6px; color: var(--ots-primary-dark); font-size: 20px; }
.next-copy p { margin: 0; color: var(--ots-text-secondary); font-size: 12px; line-height: 1.55; }
.next-note { margin-top: 9px !important; padding-top: 8px; border-top: 1px dashed #d7e8dd; color: #547069 !important; font-size: 10.5px !important; }
.task-meta { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 11px; color: #547069; font-size: 10px; }
.task-meta span { display: flex; align-items: center; gap: 4px; }
.next-action { display: flex; align-items: flex-end; flex-direction: column; gap: 9px; }
.next-action small { color: var(--ots-text-secondary); font-size: 9.5px; text-align: right; }
.action-browse { align-items: stretch; }
.growth-summary { display: grid; grid-template-columns: 190px minmax(0, 1fr) auto; align-items: center; padding: 17px 21px; }
.summary-heading span,.summary-heading strong { display: block; }
.summary-heading span { color: var(--ots-text-secondary); font-size: 10px; }
.summary-heading strong { margin-top: 4px; font-size: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); border-left: 1px solid var(--ots-border); }
.summary-grid > div { display: flex; align-items: center; gap: 9px; padding: 2px 16px; border-right: 1px solid var(--ots-border); }
.summary-grid > div:last-child { border-right: 0; }
.summary-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; }
.summary-icon.score { background: var(--ots-education-soft); color: var(--ots-education); }
.summary-icon.complete,.summary-icon.evidence { background: var(--ots-growth-soft); color: var(--ots-growth); }
.summary-icon.xp { background: var(--ots-practice-soft); color: var(--ots-practice); }
.summary-grid p { margin: 0; }
.summary-grid strong,.summary-grid small { display: block; }
.summary-grid strong { color: var(--ots-primary-dark); font-size: 21px; }
.summary-grid small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }
.ability-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 13px; }
.card-heading h3 { margin: 3px 0 0; font-size: 17px; }
.growth-list { display: flex; flex-direction: column; gap: 8px; }
.growth-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-radius: 9px; background: var(--ots-bg-subtle); }
.growth-row > div { display: flex; flex-direction: column; gap: 2px; }
.growth-row strong { font-size: 12.5px; }
.growth-row small { color: var(--ots-text-secondary); font-size: 9.5px; }
.score-move { font-size: 13px; font-style: normal; font-weight: 700; }
.score-move.up { color: var(--ots-growth); }
.score-move.down { color: var(--ots-warning); }
.growth-basis { margin: 6px 0 0; color: var(--ots-text-secondary); font-size: 9.5px; }
.history-empty { display: grid; place-items: center; min-height: 132px; color: var(--ots-text-secondary); font-size: 11.5px; text-align: center; }
.weak-primary { padding: 12px 13px; margin-bottom: 10px; border-radius: 10px; background: var(--ots-bg-subtle); }
.weak-primary > div { display: flex; align-items: baseline; gap: 10px; }
.weak-primary span { color: var(--ots-text-secondary); font-size: 10px; }
.weak-primary strong { color: var(--ots-primary-dark); font-size: 16px; }
.weak-primary em { margin-left: auto; color: var(--ots-warning); font-size: 13px; font-style: normal; font-weight: 700; }
.low-confidence { margin: 7px 0 0; color: var(--ots-practice); font-size: 10.5px; }
.confidence-line { margin: 7px 0 0; color: var(--ots-text-secondary); font-size: 10.5px; }
.weak-list { display: flex; flex-direction: column; gap: 9px; }
.weak-item { display: grid; grid-template-columns: 28px 1fr; align-items: center; gap: 10px; padding: 11px; border-radius: 9px; background: var(--ots-bg-subtle); }
.weak-rank { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; background: var(--ots-practice-soft); color: var(--ots-practice); font-size: 10px; font-weight: 700; }
.weak-content > div { display: flex; justify-content: space-between; margin-bottom: 7px; }
.weak-content strong { font-size: 12px; }
.weak-content em { color: var(--ots-warning); font-size: 11px; font-style: normal; font-weight: 600; }
.radar-card :deep(.ots-empty), .radar-card .el-empty { min-height: 220px; }
.more-tasks .task-list { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
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
  .next-task { grid-template-columns: 1fr; padding: 18px; }
  .next-badge { width: 62px; height: 62px; }
  .next-action { grid-column: auto; align-items: stretch; flex-direction: column; }
  .next-action small { text-align: left; }
  .next-action .el-button { width: 100%; min-height: 44px; }
  .summary-grid { grid-template-columns: 1fr 1fr; }
  .summary-grid > div { padding: 9px 0; border-right: 0; border-bottom: 1px solid var(--ots-border); }
  .task-list { grid-template-columns: 1fr; }
}
</style>
