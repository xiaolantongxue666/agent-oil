<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { analyticsExtApi, competitionApi, programApi, teacherApi } from '@/api'
import { ABILITY_LABELS, type CompetitionOverviewOut, type DatasetOverviewOut, type ProgramProposalOut, type TeachingEffectOut, type TeacherStudentOut, type TeacherTaskOut } from '@/types'

const router = useRouter()
const students = ref<TeacherStudentOut[]>([])
const tasks = ref<TeacherTaskOut[]>([])
const effect = ref<TeachingEffectOut | null>(null)
const dataset = ref<DatasetOverviewOut | null>(null)
const overview = ref<CompetitionOverviewOut | null>(null)
const proposals = ref<ProgramProposalOut[]>([])

// 每卡片独立数据源状态：单接口失败只降级该卡片，不拖垮整页（§9）
type SourceState = 'loading' | 'ok' | 'error'
const overviewState = ref<SourceState>('loading')
const tasksState = ref<SourceState>('loading')
const proposalsState = ref<SourceState>('loading')
const studentsState = ref<SourceState>('loading')

const metrics = computed(() => overview.value?.metrics ?? null)
const discovery = computed(() => overview.value?.discovery ?? null)
const hasIndustrySample = computed(() => (metrics.value?.job_sample_count ?? 0) > 0)
const gapAbility = computed(() => discovery.value?.ability_name || metrics.value?.top_gap_ability || '')
const hasGap = computed(() => hasIndustrySample.value && !!gapAbility.value && (discovery.value ? discovery.value.gap > 0 : (metrics.value?.top_gap_value ?? 0) > 0))

const draftProposals = computed(() => proposals.value.filter((item) => item.status === 'draft').length)
const draftTasks = computed(() => tasks.value.filter((item) => item.status === 'draft').length)
const todoItems = computed(() => [
  { label: '培养方案调整草案待审核', count: draftProposals.value, route: '/teacher/industry?tab=program', ready: proposalsState.value === 'ok' },
  { label: '实训任务待发布', count: draftTasks.value, route: '/teacher/training', ready: tasksState.value === 'ok' },
])
const todoEmpty = computed(() => todoItems.value.every((item) => item.ready && item.count === 0))

const effectMetrics = computed(() => {
  if (!effect.value) return []
  const e = effect.value
  return [
    { label: 'AI 题库一次通过率', metric: e.question_first_pass, hint: '发布前未经修订的 AI 批次占比' },
    { label: '图谱审核通过率', metric: e.graph_publish, hint: '已发布图谱版本占全部草稿' },
    { label: '培养建议采纳率', metric: e.proposal_adoption, hint: 'reviewed/published 占进入审核的草案' },
    { label: 'RAG 引用可核验率', metric: e.citation_verifiable, hint: '引用条目可回查知识库' },
  ]
})

const totalStudents = computed(() => students.value.length)
const totalCompleted = computed(() => students.value.reduce((sum, student) => sum + student.completed_count, 0))
const avgScore = computed(() => {
  const scored = students.value.filter((student) => student.total_score > 0)
  if (!scored.length) return 0
  return Math.round(scored.reduce((sum, student) => sum + student.total_score, 0) / scored.length)
})
const publishedTasks = computed(() => tasks.value.filter((task) => task.status === 'published').length)
const focusStudents = computed(() => (
  [...students.value]
    .filter((student) => student.weakest_ability || student.total_score < 60)
    .sort((a, b) => a.total_score - b.total_score)
))
const weakDistribution = computed(() => {
  const distribution: Record<string, number> = {}
  for (const student of students.value) {
    if (student.weakest_ability) distribution[student.weakest_ability] = (distribution[student.weakest_ability] || 0) + 1
  }
  return Object.entries(distribution).sort((a, b) => b[1] - a[1]).slice(0, 5)
})
const topWeak = computed(() => weakDistribution.value[0] ?? null)
const topWeakPct = computed(() => (topWeak.value && totalStudents.value ? Math.round((topWeak.value[1] / totalStudents.value) * 100) : 0))

const teachingPaths = [
  { title: '产业与专业群', note: '岗位证据 → 能力缺口 → 可审核的方案调整', icon: 'OfficeBuilding', route: '/teacher/industry', tone: 'industry' },
  { title: '教学实训', note: '任务与题库设计，AI 草稿须经教师审核', icon: 'Document', route: '/teacher/training', tone: 'practice' },
  { title: '学情与评价', note: '班级诊断与学生技能证据复核', icon: 'TrendCharts', route: '/teacher/learning', tone: 'growth' },
  { title: '教学资源', note: '维护可追溯的专业知识依据', icon: 'Collection', route: '/teacher/resources', tone: 'resource' },
]

function settle<T>(result: PromiseSettledResult<T>, apply: (value: T) => void, state?: { value: SourceState }) {
  if (result.status === 'fulfilled') { apply(result.value); if (state) state.value = 'ok' }
  else { console.warn('[dashboard] 数据源加载失败，使用卡片级降级', result.reason); if (state) state.value = 'error' }
}

onMounted(async () => {
  const [studentResult, taskResult, effectResult, datasetResult, overviewResult, proposalResult] = await Promise.allSettled([
    teacherApi.students(),
    teacherApi.tasks(),
    analyticsExtApi.effectOverview(),
    analyticsExtApi.datasetOverview(),
    competitionApi.overview(),
    programApi.proposals(),
  ])
  settle(studentResult, (v) => { students.value = v }, studentsState)
  settle(taskResult, (v) => { tasks.value = v }, tasksState)
  settle(effectResult, (v) => { effect.value = v }) // 折叠区自守卫 v-if，无需独立状态
  settle(datasetResult, (v) => { dataset.value = v })
  settle(overviewResult, (v) => { overview.value = v }, overviewState)
  settle(proposalResult, (v) => { proposals.value = v }, proposalsState)
})
</script>

<template>
  <div class="ots-page teacher-dashboard">
    <section class="dashboard-hero">
      <div>
        <div class="eyebrow">专业群教学运行</div>
        <h2>教学驾驶舱</h2>
        <p>从产业变化、课程能力缺口到班级学情，帮助教师定位今天最值得处理的问题。</p>
      </div>
      <div class="hero-actions">
        <el-button class="competition-entry" type="primary" plain @click="router.push('/teacher/competition')"><el-icon><TrophyBase /></el-icon>进入竞赛展示</el-button>
        <el-button type="primary" @click="router.push('/teacher/training')"><el-icon><Plus /></el-icon>设计实训任务</el-button>
      </div>
    </section>

    <!-- 第一屏：四张行动卡（发现问题 → 点击处理） -->
    <section class="action-grid">
      <div class="ots-card action-card">
        <div class="action-head"><span class="action-chip"><el-icon><DataLine /></el-icon></span><h3>产业变化</h3></div>
        <el-skeleton v-if="overviewState === 'loading'" :rows="3" animated />
        <template v-else-if="overviewState === 'error'">
          <p class="action-empty">暂时无法获取产业证据，请稍后重试或前往页面查看。</p>
        </template>
        <template v-else-if="hasIndustrySample && discovery">
          <p class="action-core">当前值得关注<small>{{ gapAbility }}</small></p>
          <div class="action-evidence">
            <span>有效招聘样本<strong>{{ metrics?.job_sample_count }} 条</strong></span>
            <span>影响岗位<strong>{{ metrics?.position_count }} 个</strong></span>
          </div>
          <p class="action-note">近期产业岗位证据显示，该能力需求值得关注。</p>
        </template>
        <template v-else>
          <p class="action-empty">当前有效产业样本不足，扩充岗位证据后将自动生成变化提示。</p>
        </template>
        <div class="action-foot"><el-button text type="primary" @click="router.push('/teacher/industry?tab=positions')">查看产业证据<el-icon><ArrowRight /></el-icon></el-button></div>
      </div>

      <div class="ots-card action-card">
        <div class="action-head"><span class="action-chip"><el-icon><Aim /></el-icon></span><h3>最大能力缺口</h3></div>
        <el-skeleton v-if="overviewState === 'loading'" :rows="3" animated />
        <template v-else-if="overviewState === 'error'">
          <p class="action-empty">暂时无法获取能力分析，请稍后重试。</p>
        </template>
        <template v-else-if="hasGap">
          <p class="action-core">{{ gapAbility }}</p>
          <div class="action-evidence">
            <span>产业需求<strong>{{ discovery ? `${discovery.demand_share}%` : '—' }}</strong></span>
            <span>课程供给<strong>{{ discovery ? `${discovery.curriculum_share}%` : '—' }}</strong></span>
            <span class="gap-line">Gap<strong class="gap-value">{{ discovery ? `+${discovery.gap}pp` : `+${metrics?.top_gap_value ?? 0}pp` }}</strong></span>
          </div>
          <p class="action-note">供给与需求差距最大的一项，建议结合专业群分析复核。</p>
        </template>
        <template v-else>
          <p class="action-empty">暂无可验证能力缺口。</p>
        </template>
        <div class="action-foot"><el-button text type="primary" @click="router.push('/teacher/industry?tab=group')">查看专业群分析<el-icon><ArrowRight /></el-icon></el-button></div>
      </div>

      <div class="ots-card action-card">
        <div class="action-head"><span class="action-chip"><el-icon><Bell /></el-icon></span><h3>待教师处理</h3></div>
        <el-skeleton v-if="tasksState === 'loading' || proposalsState === 'loading'" :rows="3" animated />
        <template v-else-if="tasksState === 'error' && proposalsState === 'error'">
          <p class="action-empty">暂时无法获取待处理事项，请稍后重试。</p>
        </template>
        <template v-else>
          <div class="todo-list">
            <button v-for="item in todoItems" :key="item.label" type="button" class="todo-row" @click="router.push(item.route)">
              <span>{{ item.label }}<small v-if="!item.ready">暂时无法获取</small></span>
              <strong :class="{ 'todo-zero': item.ready && item.count === 0 }">{{ item.ready ? `${item.count} 项` : '—' }}</strong>
              <el-icon class="todo-arrow"><ArrowRight /></el-icon>
            </button>
          </div>
          <p v-if="todoEmpty" class="action-note">当前没有待审核草案与待发布任务，教学进度正常。</p>
        </template>
      </div>

      <div class="ots-card action-card">
        <div class="action-head"><span class="action-chip"><el-icon><TrendCharts /></el-icon></span><h3>班级能力关注</h3></div>
        <el-skeleton v-if="studentsState === 'loading'" :rows="3" animated />
        <template v-else-if="studentsState === 'error'">
          <p class="action-empty">暂时无法获取班级学情，请稍后重试。</p>
        </template>
        <template v-else-if="topWeak">
          <p class="action-core">{{ ABILITY_LABELS[topWeak[0] as keyof typeof ABILITY_LABELS] || topWeak[0] }}</p>
          <div class="action-evidence">
            <span>最弱学生数<strong>{{ topWeak[1] }} 名</strong></span>
            <span>占班级比例<strong>{{ topWeakPct }}%</strong></span>
          </div>
          <p class="action-note">按当前能力档案的最弱维度统计，建议课堂复核后针对性补强。</p>
        </template>
        <template v-else>
          <p class="action-empty">暂无有效班级能力数据。</p>
        </template>
        <div class="action-foot"><el-button text type="primary" @click="router.push('/teacher/learning?tab=class')">查看学情<el-icon><ArrowRight /></el-icon></el-button></div>
      </div>
    </section>

    <!-- 第二层：教学运行概览（保留原统计，降为横向统计条权重） -->
    <section class="teaching-summary ots-card">
      <div class="summary-title"><span>教学运行概览</span><strong>以当前班级与已发布实训数据为准</strong></div>
      <div class="summary-grid">
        <div><span class="summary-icon students"><el-icon><User /></el-icon></span><p><strong>{{ studentsState === 'ok' ? totalStudents : '—' }}</strong><small>覆盖学生</small></p></div>
        <div><span class="summary-icon completed"><el-icon><CircleCheck /></el-icon></span><p><strong>{{ studentsState === 'ok' ? totalCompleted : '—' }}</strong><small>训练完成次数</small></p></div>
        <div><span class="summary-icon score"><el-icon><DataAnalysis /></el-icon></span><p><strong>{{ studentsState === 'ok' && totalStudents ? avgScore : '—' }}</strong><small>班级平均能力分</small></p></div>
        <div><span class="summary-icon tasks"><el-icon><DocumentChecked /></el-icon></span><p><strong>{{ tasksState === 'ok' ? publishedTasks : '—' }}</strong><small>已发布实训任务</small></p></div>
      </div>
    </section>

    <!-- 第三层：班级能力关注项 + 专业群教学工作流 -->
    <div class="dashboard-grid">
      <section class="ots-card risk-card">
        <div class="card-heading"><div><span>学情诊断</span><h3>班级能力关注项</h3></div><el-tag v-if="studentsState === 'ok'" type="warning" effect="plain">{{ focusStudents.length }} 名学生需关注</el-tag></div>
        <div v-if="weakDistribution.length" class="weak-list">
          <div v-for="([key, count], index) in weakDistribution" :key="key" class="weak-row">
            <span class="rank">{{ index + 1 }}</span>
            <div><strong>{{ ABILITY_LABELS[key as keyof typeof ABILITY_LABELS] || key }}</strong><small>{{ count }} 名学生的当前最弱维度</small></div>
            <el-progress :percentage="totalStudents ? Math.round((count / totalStudents) * 100) : 0" :stroke-width="8" :show-text="false" />
            <em>{{ totalStudents ? Math.round((count / totalStudents) * 100) : 0 }}%</em>
          </div>
        </div>
        <el-empty v-else :description="studentsState === 'loading' ? '学情数据加载中…' : '暂无有效班级能力数据'" :image-size="70" />
      </section>

      <section class="ots-card path-card">
        <div class="card-heading"><div><span>教学工作流</span><h3>专业群教学工作流</h3></div></div>
        <div class="path-list">
          <button v-for="item in teachingPaths" :key="item.route" type="button" :class="item.tone" @click="router.push(item.route)">
            <span><el-icon><component :is="item.icon" /></el-icon></span>
            <div><strong>{{ item.title }}</strong><small>{{ item.note }}</small></div>
            <el-icon class="arrow"><ArrowRight /></el-icon>
          </button>
        </div>
      </section>
    </div>

    <!-- 第四层：数据与教学效果（默认折叠，支撑评委追问） -->
    <section class="ots-card governance-panel">
      <el-collapse>
        <el-collapse-item name="governance">
          <template #title>
            <div class="gov-title">
              <div><span>数据与教学效果</span><strong>真实审核数据指标 · 产业证据规模与来源分类</strong></div>
              <small>底层支撑数据，比赛主演示无需展开</small>
            </div>
          </template>
          <div v-if="effect" class="dashboard-grid effect-grid">
            <section class="ots-card inner-card">
              <div class="card-heading"><div><span>教学效果评估</span><h3>真实审核数据指标</h3></div></div>
              <div class="effect-list">
                <div v-for="item in effectMetrics" :key="item.label" class="effect-row">
                  <div><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></div>
                  <div class="effect-value">
                    <strong :class="{ 'no-data': item.metric.rate === null }">
                      {{ item.metric.rate === null ? '—' : `${item.metric.rate}%` }}
                    </strong>
                    <small v-if="item.metric.rate === null">暂无有效样本</small>
                    <small v-else>样本 {{ item.metric.total }}</small>
                  </div>
                </div>
              </div>
              <p class="effect-basis">补学提升指标需要「补学任务完成 + 前后同维证据」配对记录，当前未采集该标记，不编造提升数字。</p>
            </section>

            <section v-if="dataset" class="ots-card inner-card">
              <div class="card-heading"><div><span>可信数据集治理</span><h3>产业证据规模与来源分类</h3></div></div>
              <div class="dataset-summary">
                <div><strong>{{ dataset.scale.job_sample_count }}</strong><small>招聘样本</small></div>
                <div><strong>{{ dataset.scale.job_sample_month_span }}</strong><small>覆盖月份</small></div>
                <div><strong>{{ dataset.scale.company_source_count }}</strong><small>企业来源</small></div>
                <div><strong>{{ dataset.scale.authoritative_standard_count }}</strong><small>权威标准</small></div>
              </div>
              <div class="dataset-categories">
                <div v-for="cat in dataset.categories" :key="cat.key" class="dataset-row">
                  <span>{{ cat.label }}</span><strong>{{ cat.count }}</strong>
                </div>
              </div>
              <p class="effect-basis">{{ dataset.time_boundary }}</p>
            </section>
          </div>
          <el-empty v-else description="暂无可验证数据" :image-size="60" />
        </el-collapse-item>
      </el-collapse>
    </section>

    <section class="ots-card student-card">
      <div class="card-heading table-heading">
        <div><span>个体学习观察</span><h3>优先关注学生</h3></div>
        <el-button text type="primary" @click="router.push('/teacher/students')">查看全部学生<el-icon><ArrowRight /></el-icon></el-button>
      </div>
      <el-table :data="(focusStudents.length ? focusStudents : students).slice(0, 8)" empty-text="暂无学生学习数据">
        <el-table-column prop="real_name" label="学生" min-width="110" />
        <el-table-column prop="student_no" label="学号" min-width="120" />
        <el-table-column prop="completed_count" label="已完成实训" width="110" />
        <el-table-column label="综合能力" width="120"><template #default="{ row }"><span class="score-value">{{ row.total_score.toFixed(0) }}</span></template></el-table-column>
        <el-table-column label="当前关注能力" min-width="150"><template #default="{ row }"><el-tag v-if="row.weakest_ability" type="warning" size="small" effect="plain">{{ ABILITY_LABELS[row.weakest_ability as keyof typeof ABILITY_LABELS] || row.weakest_ability }}</el-tag><span v-else class="stable-state">表现稳定</span></template></el-table-column>
        <el-table-column label="教师行动" width="110"><template #default="{ row }"><el-button text type="primary" size="small" @click="router.push(`/teacher/students/${row.id}`)">查看画像</el-button></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.teacher-dashboard { max-width: 1500px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.dashboard-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin: 2px 0 2px; }
.eyebrow,.card-heading span { color: #2f6fed; font-size: 11px; font-weight: 600; letter-spacing: .7px; }
.dashboard-hero h2 { margin: 6px 0 7px; color: #123f5d; font-size: 25px; }
.dashboard-hero p { margin: 0; color: var(--ots-text-secondary); }
.hero-actions { display: flex; gap: 9px; flex-shrink: 0; }

/* 第一屏行动卡：统一结构（小标题/核心结论/证据/行动按钮），同一色相不同图标 */
.action-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.action-card { display: flex; flex-direction: column; gap: 9px; min-height: 218px; padding: 16px 18px; }
.action-head { display: flex; align-items: center; gap: 9px; }
.action-chip { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: var(--ots-education-soft); color: var(--ots-education); font-size: 16px; }
.action-head h3 { margin: 0; font-size: 13px; color: #123f5d; }
.action-core { margin: 0; color: var(--ots-primary-dark); font-size: 18px; font-weight: 700; line-height: 1.35; }
.action-core small { display: block; margin-top: 3px; color: var(--ots-warning-dark, #b26a00); font-size: 12px; font-weight: 600; }
.action-evidence { display: flex; flex-direction: column; gap: 5px; }
.action-evidence span { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; color: var(--ots-text-secondary); font-size: 11.5px; }
.action-evidence strong { color: #123f5d; font-size: 12.5px; }
.action-evidence .gap-value { color: var(--ots-danger); }
.action-note { margin: 0; color: var(--ots-text-secondary); font-size: 10.5px; line-height: 1.55; }
.action-empty { margin: 0; color: var(--ots-text-secondary); font-size: 12px; line-height: 1.6; }
.action-foot { margin-top: auto; padding-top: 4px; }
.action-foot .el-button { font-weight: 600; }
.todo-list { display: flex; flex-direction: column; gap: 8px; }
.todo-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 11px; border: 1px solid var(--ots-border); border-radius: 9px; background: #fff; color: var(--ots-text); font-size: 12px; text-align: left; cursor: pointer; }
.todo-row:hover { border-color: var(--ots-primary-light); background: #f8fbfa; }
.todo-row span { display: flex; flex-direction: column; gap: 2px; }
.todo-row small { color: var(--ots-text-secondary); font-size: 9.5px; }
.todo-row strong { color: var(--ots-primary-dark); font-size: 13px; white-space: nowrap; }
.todo-row strong.todo-zero { color: var(--ots-growth); }
.todo-arrow { color: var(--ots-text-secondary); font-size: 13px; }

.teaching-summary { display: grid; grid-template-columns: 210px minmax(0, 1fr); align-items: center; padding: 15px 22px; }
.summary-title span,.summary-title strong { display: block; }
.summary-title span { color: var(--ots-text-secondary); font-size: 11px; }
.summary-title strong { margin-top: 5px; font-size: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); border-left: 1px solid var(--ots-border); }
.summary-grid > div { display: flex; align-items: center; gap: 10px; padding: 3px 17px; border-right: 1px solid var(--ots-border); }
.summary-grid > div:last-child { border-right: 0; }
.summary-icon { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; flex: 0 0 auto; }
.summary-icon.students,.summary-icon.score { background: var(--ots-education-soft); color: var(--ots-education); }
.summary-icon.completed { background: var(--ots-growth-soft); color: var(--ots-growth); }
.summary-icon.tasks { background: var(--ots-practice-soft); color: var(--ots-practice); }
.summary-grid p { margin: 0; }
.summary-grid strong,.summary-grid small { display: block; }
.summary-grid strong { color: var(--ots-primary-dark); font-size: 19px; }
.summary-grid small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }

.dashboard-grid { display: grid; grid-template-columns: 1.05fr .95fr; gap: 16px; }
.card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 15px; }
.card-heading h3 { margin: 3px 0 0; font-size: 17px; }
.weak-list { display: flex; flex-direction: column; gap: 8px; }
.weak-row { display: grid; grid-template-columns: 28px minmax(145px, .8fr) minmax(100px, 1fr) 38px; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 8px; background: var(--ots-bg-subtle); }
.rank { display: grid; place-items: center; width: 25px; height: 25px; border-radius: 7px; background: var(--ots-practice-soft); color: var(--ots-practice); font-size: 10px; font-weight: 700; }
.weak-row strong,.weak-row small { display: block; }
.weak-row strong { font-size: 12px; }
.weak-row small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }
.weak-row em { color: var(--ots-warning); font-size: 10px; font-style: normal; text-align: right; }
.path-list { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.path-list button { display: grid; grid-template-columns: 35px 1fr 16px; align-items: center; gap: 9px; min-height: 64px; padding: 10px; border: 1px solid var(--ots-border); border-radius: 9px; background: #fff; color: var(--ots-text); text-align: left; cursor: pointer; }
.path-list button:hover { border-color: var(--ots-primary-light); background: #f8fbfa; }
.path-list button > span { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; background: var(--ots-education-soft); color: var(--ots-education); }
.path-list button.practice > span { background: var(--ots-practice-soft); color: var(--ots-practice); }
.path-list button.growth > span { background: var(--ots-growth-soft); color: var(--ots-growth); }
.path-list button.resource > span { background: #edf6f7; color: var(--ots-primary); }
.path-list strong,.path-list small { display: block; }
.path-list strong { font-size: 12px; }
.path-list small { margin-top: 3px; color: var(--ots-text-secondary); font-size: 9px; line-height: 1.4; }
.path-list .arrow { color: var(--ots-text-secondary); }

.governance-panel { padding: 4px 18px; }
.governance-panel :deep(.el-collapse) { border-top: 0; }
.governance-panel :deep(.el-collapse-item__header) { height: 58px; border-bottom: 0; }
.governance-panel :deep(.el-collapse-item__wrap) { border-bottom: 0; }
.governance-panel :deep(.el-collapse-item__content) { padding-bottom: 18px; }
.gov-title { display: flex; align-items: center; justify-content: space-between; gap: 18px; width: 100%; padding-right: 8px; }
.gov-title > div span { display: block; color: #2f6fed; font-size: 11px; font-weight: 600; letter-spacing: .7px; }
.gov-title > div strong { display: block; margin-top: 3px; color: #123f5d; font-size: 15px; }
.gov-title small { color: var(--ots-text-secondary); font-size: 10.5px; }
.effect-grid { margin-top: 8px; }
.inner-card { padding: 16px 18px; }
.effect-list { display: flex; flex-direction: column; gap: 8px; }
.effect-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 10px; border-radius: 8px; background: var(--ots-bg-subtle); }
.effect-row strong, .effect-row small { display: block; }
.effect-row strong { font-size: 12px; }
.effect-row small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }
.effect-value { text-align: right; }
.effect-value strong { font-size: 14px; color: var(--ots-primary-dark); }
.effect-value strong.no-data { color: var(--ots-text-secondary); font-size: 14px; }
.effect-value small { color: var(--ots-text-secondary); font-size: 9px; }
.effect-basis { margin: 10px 0 0; color: var(--ots-text-secondary); font-size: 10px; line-height: 1.6; }
.dataset-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 10px; }
.dataset-summary strong { display: block; font-size: 16px; color: var(--ots-primary-dark); }
.dataset-summary small { color: var(--ots-text-secondary); font-size: 9px; }
.dataset-categories { display: flex; flex-direction: column; gap: 6px; }
.dataset-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; border-radius: 8px; background: var(--ots-bg-subtle); font-size: 11px; }
.dataset-row strong { color: var(--ots-primary); }

.table-heading { margin-bottom: 12px; }
.score-value { color: var(--ots-primary-dark); font-weight: 700; }
.stable-state { color: var(--ots-growth); font-size: 11px; }

@media (max-width: 1280px) { .action-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 1100px) {
  .teaching-summary { grid-template-columns: 1fr; }
  .summary-title { margin-bottom: 14px; }
  .summary-grid { border-top: 1px solid var(--ots-border); border-left: 0; padding-top: 14px; }
  .dashboard-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .dashboard-hero { align-items: flex-start; flex-direction: column; }
  .hero-actions { width: 100%; flex-wrap: wrap; }
  .action-grid { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: 1fr 1fr; gap: 14px 0; }
  .summary-grid > div:nth-child(2) { border-right: 0; }
  .path-list { grid-template-columns: 1fr; }
  .weak-row { grid-template-columns: 28px minmax(0, 1fr) 38px; }
  .weak-row .el-progress { display: none; }
  .gov-title { flex-direction: column; align-items: flex-start; gap: 2px; }
}
</style>
