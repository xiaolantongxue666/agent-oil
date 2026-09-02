<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { analyticsExtApi, teacherApi } from '@/api'
import { ABILITY_LABELS, type DatasetOverviewOut, type TeachingEffectOut, type TeacherStudentOut, type TeacherTaskOut } from '@/types'

const router = useRouter()
const students = ref<TeacherStudentOut[]>([])
const tasks = ref<TeacherTaskOut[]>([])
const effect = ref<TeachingEffectOut | null>(null)
const dataset = ref<DatasetOverviewOut | null>(null)
const loading = ref(true)

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

const teachingPaths = [
  { title: '岗位与培养方案', note: '从产业需求到课程能力映射', icon: 'OfficeBuilding', route: '/teacher/industry', tone: 'industry' },
  { title: '实训任务设计', note: '建设任务、题库与审核流程', icon: 'Document', route: '/teacher/training', tone: 'practice' },
  { title: '学情诊断复盘', note: '定位班级薄弱能力与教学行动', icon: 'TrendCharts', route: '/teacher/learning', tone: 'growth' },
  { title: '权威教学资源', note: '维护可追溯的专业知识依据', icon: 'Collection', route: '/teacher/resources', tone: 'resource' },
]

onMounted(async () => {
  try {
    const [studentResult, taskResult, effectResult, datasetResult] = await Promise.allSettled([
      teacherApi.students(),
      teacherApi.tasks(),
      analyticsExtApi.effectOverview(),
      analyticsExtApi.datasetOverview(),
    ])
    if (studentResult.status === 'fulfilled') students.value = studentResult.value
    if (taskResult.status === 'fulfilled') tasks.value = taskResult.value
    if (effectResult.status === 'fulfilled') effect.value = effectResult.value
    if (datasetResult.status === 'fulfilled') dataset.value = datasetResult.value
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page teacher-dashboard" v-loading="loading">
    <section class="dashboard-hero">
      <div>
        <div class="eyebrow">专业群教学运行</div>
        <h2>教学驾驶舱</h2>
        <p>围绕岗位能力要求，组织实训资源、诊断学习成效并形成教学改进行动。</p>
      </div>
      <div class="hero-actions">
        <el-button @click="router.push('/teacher/students')"><el-icon><User /></el-icon>查看待关注学生</el-button>
        <el-button type="primary" @click="router.push('/teacher/tasks')"><el-icon><Plus /></el-icon>设计实训任务</el-button>
      </div>
    </section>

    <section class="teaching-summary ots-card">
      <div class="summary-title"><span>教学运行概览</span><strong>以当前班级与已发布实训数据为准</strong></div>
      <div class="summary-grid">
        <div><span class="summary-icon students"><el-icon><User /></el-icon></span><p><strong>{{ totalStudents }}</strong><small>覆盖学生</small></p></div>
        <div><span class="summary-icon completed"><el-icon><CircleCheck /></el-icon></span><p><strong>{{ totalCompleted }}</strong><small>训练完成次数</small></p></div>
        <div><span class="summary-icon score"><el-icon><DataAnalysis /></el-icon></span><p><strong>{{ avgScore }}</strong><small>班级平均能力分</small></p></div>
        <div><span class="summary-icon tasks"><el-icon><DocumentChecked /></el-icon></span><p><strong>{{ publishedTasks }}</strong><small>已发布实训任务</small></p></div>
      </div>
    </section>

    <div class="dashboard-grid">
      <section class="ots-card risk-card">
        <div class="card-heading"><div><span>学情诊断</span><h3>班级能力关注项</h3></div><el-tag type="warning" effect="plain">{{ focusStudents.length }} 名学生需关注</el-tag></div>
        <div v-if="weakDistribution.length" class="weak-list">
          <div v-for="([key, count], index) in weakDistribution" :key="key" class="weak-row">
            <span class="rank">{{ index + 1 }}</span>
            <div><strong>{{ ABILITY_LABELS[key as keyof typeof ABILITY_LABELS] || key }}</strong><small>{{ count }} 名学生的当前最弱维度</small></div>
            <el-progress :percentage="totalStudents ? Math.round((count / totalStudents) * 100) : 0" :stroke-width="8" :show-text="false" />
            <em>{{ totalStudents ? Math.round((count / totalStudents) * 100) : 0 }}%</em>
          </div>
        </div>
        <el-empty v-else description="暂无薄弱能力数据" :image-size="70" />
      </section>

      <section class="ots-card path-card">
        <div class="card-heading"><div><span>教学工作流</span><h3>专业群建设与教学实施</h3></div></div>
        <div class="path-list">
          <button v-for="item in teachingPaths" :key="item.route" type="button" :class="item.tone" @click="router.push(item.route)">
            <span><el-icon><component :is="item.icon" /></el-icon></span>
            <div><strong>{{ item.title }}</strong><small>{{ item.note }}</small></div>
            <el-icon class="arrow"><ArrowRight /></el-icon>
          </button>
        </div>
      </section>
    </div>

    <div v-if="effect" class="dashboard-grid effect-grid">
      <section class="ots-card">
        <div class="card-heading"><div><span>教学效果评估</span><h3>真实审核数据指标</h3></div><el-tag size="small" effect="plain">P1-2</el-tag></div>
        <div class="effect-list">
          <div v-for="item in effectMetrics" :key="item.label" class="effect-row">
            <div><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></div>
            <div class="effect-value">
              <strong :class="{ 'no-data': item.metric.rate === null }">
                {{ item.metric.rate === null ? '暂无数据' : `${item.metric.rate}%` }}
              </strong>
              <small>样本 {{ item.metric.total }}</small>
            </div>
          </div>
        </div>
        <p class="effect-basis">补学提升指标需要"补学任务完成 + 前后同维证据"配对记录，当前未采集该标记，如实显示 0，不编造提升数字。</p>
      </section>

      <section v-if="dataset" class="ots-card">
        <div class="card-heading"><div><span>可信数据集治理</span><h3>产业证据规模与来源分类</h3></div><el-tag size="small" effect="plain">P1-1</el-tag></div>
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
.teacher-dashboard { max-width: 1500px; margin: 0 auto; }
.dashboard-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin: 2px 0 18px; }
.eyebrow,.card-heading span { color: #2f6fed; font-size: 11px; font-weight: 600; letter-spacing: .7px; }
.dashboard-hero h2 { margin: 6px 0 7px; color: #123f5d; font-size: 25px; }
.dashboard-hero p { margin: 0; color: var(--ots-text-secondary); }
.hero-actions { display: flex; gap: 9px; flex-shrink: 0; }
.teaching-summary { display: grid; grid-template-columns: 210px minmax(0, 1fr); align-items: center; padding: 19px 22px; }
.summary-title span,.summary-title strong { display: block; }
.summary-title span { color: var(--ots-text-secondary); font-size: 11px; }
.summary-title strong { margin-top: 5px; font-size: 13px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); border-left: 1px solid var(--ots-border); }
.summary-grid > div { display: flex; align-items: center; gap: 10px; padding: 3px 17px; border-right: 1px solid var(--ots-border); }
.summary-grid > div:last-child { border-right: 0; }
.summary-icon { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px; flex: 0 0 auto; }
.summary-icon.students,.summary-icon.score { background: var(--ots-education-soft); color: var(--ots-education); }
.summary-icon.completed { background: var(--ots-growth-soft); color: var(--ots-growth); }
.summary-icon.tasks { background: var(--ots-practice-soft); color: var(--ots-practice); }
.summary-grid p { margin: 0; }
.summary-grid strong,.summary-grid small { display: block; }
.summary-grid strong { color: var(--ots-primary-dark); font-size: 22px; }
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
.table-heading { margin-bottom: 12px; }
.score-value { color: var(--ots-primary-dark); font-weight: 700; }
.stable-state { color: var(--ots-growth); font-size: 11px; }

.effect-grid { margin-bottom: 0; }
.effect-list { display: flex; flex-direction: column; gap: 8px; }
.effect-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 10px; border-radius: 8px; background: var(--ots-bg-subtle); }
.effect-row strong, .effect-row small { display: block; }
.effect-row strong { font-size: 12px; }
.effect-row small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }
.effect-value { text-align: right; }
.effect-value strong { font-size: 14px; color: var(--ots-primary-dark); }
.effect-value strong.no-data { color: var(--ots-text-secondary); font-size: 11px; font-weight: 400; }
.effect-value small { color: var(--ots-text-secondary); font-size: 9px; }
.effect-basis { margin: 10px 0 0; color: var(--ots-text-secondary); font-size: 10px; line-height: 1.6; }
.dataset-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 10px; }
.dataset-summary strong { display: block; font-size: 16px; color: var(--ots-primary-dark); }
.dataset-summary small { color: var(--ots-text-secondary); font-size: 9px; }
.dataset-categories { display: flex; flex-direction: column; gap: 6px; }
.dataset-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; border-radius: 8px; background: var(--ots-bg-subtle); font-size: 11px; }
.dataset-row strong { color: var(--ots-primary); }

@media (max-width: 1100px) {
  .teaching-summary { grid-template-columns: 1fr; }
  .summary-title { margin-bottom: 14px; }
  .summary-grid { border-top: 1px solid var(--ots-border); border-left: 0; padding-top: 14px; }
  .dashboard-grid { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .dashboard-hero { align-items: flex-start; flex-direction: column; }
  .hero-actions { width: 100%; flex-wrap: wrap; }
  .summary-grid { grid-template-columns: 1fr 1fr; gap: 14px 0; }
  .summary-grid > div:nth-child(2) { border-right: 0; }
  .path-list { grid-template-columns: 1fr; }
  .weak-row { grid-template-columns: 28px minmax(0, 1fr) 38px; }
  .weak-row .el-progress { display: none; }
}
</style>
