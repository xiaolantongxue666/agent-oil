<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { competitionApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { CompetitionOverviewOut } from '@/types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const overview = ref<CompetitionOverviewOut | null>(null)
const loading = ref(true)
const errorText = ref('')
const activeChain = ref(0)
const showEvidence = ref(false)
const activeTab = ref<'postings' | 'knowledge'>('postings')

// §37 主链：每个节点可点击，链到对应功能页面（点击即下钻）
const chainNodes = computed(() => [
  { label: '产业变化', desc: '岗位证据采集', to: authHome('/teacher/industry', '/ability-graph'), metric: `${overview.value?.metrics.job_sample_count ?? 0} 条岗位样本` },
  { label: '岗位需求', desc: '技能词抽取映射', to: '/ability-graph', metric: `${overview.value?.metrics.position_count ?? 0} 个对接岗位` },
  { label: '专业群能力缺口', desc: '需求 vs 供给', to: authHome('/teacher/professional-group', ''), metric: topGapText.value },
  { label: '培养方案调整', desc: 'AI 草稿 → 教师审核', to: authHome('/teacher/programs', ''), metric: `${overview.value?.metrics.course_count ?? 0} 门课程供给` },
  { label: '岗位情境实训', desc: '教学仿真实训', to: authHome('/teacher/training', '/simulation'), metric: scenarioText.value },
  { label: '能力证据', desc: '行为事件 → 证据', to: authHome('/teacher/students', '/profile'), metric: '六维画像 + 置信度' },
  { label: '补学与重练', desc: '个性化学习路径', to: authHome('/teacher/learning', '/adaptive-learning'), metric: '薄弱项驱动' },
])

const topGapText = computed(() => {
  const m = overview.value?.metrics
  if (!m) return ''
  return m.top_gap_ability ? `${m.top_gap_ability} +${m.top_gap_value}%` : '暂无缺口数据'
})

const scenarioText = computed(() => {
  const sc = overview.value?.scenario
  return sc ? sc.title : '暂无匹配场景'
})

function authHome(teacherPath: string, studentPath: string) {
  if (auth.isStaff) return teacherPath
  return studentPath || teacherPath
}

const discovery = computed(() => overview.value?.discovery ?? null)
const confidenceTag = computed(() => {
  const c = overview.value?.metrics.data_confidence ?? 'low'
  return c === 'high' ? { label: '高', type: 'success' as const } : c === 'medium' ? { label: '中', type: 'warning' as const } : { label: '低', type: 'info' as const }
})

const demandRatio = computed(() => {
  const d = discovery.value
  if (!d) return 0
  const total = d.demand_share + d.curriculum_share
  return total > 0 ? Math.round((d.demand_share / total) * 100) : 0
})

function fmtDate(value: string | null | undefined) {
  if (!value) return '未解析到发布日期'
  return String(value).slice(0, 10)
}

function openSource(url: string) {
  window.open(url, '_blank', 'noopener')
}

function gotoSimulation() {
  const code = overview.value?.scenario?.scenario_code
  if (code) router.push(`/simulation/${code}`)
}

onMounted(async () => {
  const groupId = route.query.group_id ? Number(route.query.group_id) : undefined
  try {
    overview.value = await competitionApi.overview(groupId)
  } catch (e) {
    errorText.value = (e as { message?: string })?.message || '比赛总览加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page competition-page" v-loading="loading">
    <el-alert v-if="errorText" type="error" :title="errorText" :closable="false" show-icon class="comp-alert" />

    <!-- §36 核心文案 -->
    <header class="comp-hero ots-card">
      <div class="comp-hero-text">
        <h1>产业岗位变化，如何及时转化为职业院校人才培养能力？</h1>
        <p>
          系统通过产业岗位证据、专业群能力分析、岗位仿真实训和多源能力评价，
          实现"产业需求 — 教学改革 — 技能验证"闭环。
        </p>
      </div>
      <div class="comp-hero-meta">
        <el-tag v-if="overview" :type="confidenceTag.type" effect="light" size="large">
          数据可信度：{{ confidenceTag.label }}
        </el-tag>
        <span v-if="overview" class="comp-group-name">{{ overview.group.name }}</span>
      </div>
    </header>

    <!-- §30 顶部指标 -->
    <section v-if="overview" class="metric-grid">
      <div class="metric-card"><strong>{{ overview.metrics.major_count }}</strong><span>专业数</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.position_count }}</strong><span>对接岗位数</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.task_count }}</strong><span>典型工作任务</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.ability_node_count }}</strong><span>能力节点</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.course_count }}</strong><span>课程数</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.job_sample_count }}</strong><span>岗位证据（招聘样本）</span></div>
      <div class="metric-card metric-gap">
        <strong>{{ overview.metrics.top_gap_ability || '—' }}</strong>
        <span>主要能力缺口 {{ overview.metrics.top_gap_value ? `+${overview.metrics.top_gap_value}%` : '' }}</span>
      </div>
    </section>

    <!-- §37 主链 -->
    <section v-if="overview" class="ots-card chain-card">
      <div class="section-head">
        <h3>核心闭环主链</h3>
        <span class="text-secondary">每个节点可点击进入对应功能页面</span>
      </div>
      <div class="chain-flow">
        <template v-for="(node, index) in chainNodes" :key="node.label">
          <button
            class="chain-node"
            :class="{ active: activeChain === index }"
            type="button"
            @click="activeChain = index; node.to && router.push(node.to)"
          >
            <span class="chain-step">{{ index + 1 }}</span>
            <strong>{{ node.label }}</strong>
            <small>{{ node.desc }}</small>
            <em>{{ node.metric }}</em>
          </button>
          <span v-if="index < chainNodes.length - 1" class="chain-arrow">→</span>
        </template>
      </div>
    </section>

    <!-- §38 真实发现案例 -->
    <section v-if="overview && discovery" class="ots-card discovery-card">
      <div class="section-head">
        <h3>系统真实发现</h3>
        <span class="text-secondary">以下数据由系统对当前专业群实时计算，非演示写死</span>
      </div>
      <p class="discovery-statement">
        目标岗位对「<strong>{{ discovery.ability_name }}</strong>」的需求较高
        （产业需求 {{ discovery.demand_share }}%），而当前课程能力覆盖存在不足
        （课程供给 {{ discovery.curriculum_share }}%），能力缺口 <strong>+{{ discovery.gap }} 个百分点</strong>。
        <span class="text-secondary">（基于近 {{ discovery.months }} 个月 {{ overview.metrics.job_sample_count }} 条招聘样本与 {{ overview.metrics.course_count }} 门课程能力权重计算）</span>
      </p>
      <div class="demand-bar">
        <div class="bar-segment demand" :style="{ width: demandRatio + '%' }">产业需求 {{ discovery.demand_share }}%</div>
        <div class="bar-segment supply" :style="{ width: 100 - demandRatio + '%' }">课程供给 {{ discovery.curriculum_share }}%</div>
      </div>

      <div class="discovery-detail">
        <div class="detail-block">
          <h4>产生该需求的岗位</h4>
          <ul>
            <li v-for="p in discovery.demand_positions" :key="p.id">
              {{ p.name }}
              <small class="text-secondary">{{ p.major_name }} · {{ p.sample_count }} 条样本</small>
            </li>
            <li v-if="!discovery.demand_positions.length" class="text-secondary">暂无岗位样本</li>
          </ul>
        </div>
        <div class="detail-block">
          <h4>企业技能词（未覆盖）</h4>
          <div class="skill-tags">
            <el-tag v-for="s in discovery.uncovered_skills" :key="s.name" type="danger" effect="plain">
              {{ s.name }} × {{ s.count }}
            </el-tag>
            <span v-if="!discovery.uncovered_skills.length" class="text-secondary">未发现明显未覆盖技能词</span>
          </div>
        </div>
        <div class="detail-block">
          <h4>当前课程覆盖</h4>
          <ul>
            <li v-for="c in discovery.covered_by" :key="c.course_id">
              {{ c.course_name }}
              <small class="text-secondary">{{ c.major_name }} · {{ c.total_hours }} 学时 · 权重 {{ c.weight }}</small>
            </li>
            <li v-if="!discovery.covered_by.length" class="text-secondary warning-text">⚠ 该能力当前无课程覆盖</li>
          </ul>
        </div>
      </div>

      <!-- §39 证据链下钻 -->
      <div class="evidence-section">
        <el-button type="primary" plain @click="showEvidence = !showEvidence">
          {{ showEvidence ? '收起证据' : '查看证据' }}
        </el-button>
        <el-button v-if="overview.scenario" type="success" plain @click="gotoSimulation">
          进入对应实训
        </el-button>
      </div>

      <div v-if="showEvidence" class="evidence-panel">
        <el-radio-group v-model="activeTab" size="small" class="evidence-tabs">
          <el-radio-button value="postings">招聘证据（{{ overview.evidence.job_postings.length }}）</el-radio-button>
          <el-radio-button value="knowledge">职业标准 / 权威知识（{{ overview.evidence.authoritative_knowledge.length }}）</el-radio-button>
        </el-radio-group>

        <div v-if="activeTab === 'postings'" class="posting-list">
          <div v-for="item in overview.evidence.job_postings" :key="item.id" class="posting-item">
            <div class="posting-head">
              <strong>{{ item.title }}</strong>
              <el-tag size="small" :type="item.date_confidence === 'high' ? 'success' : 'warning'" effect="plain">
                日期可信度 {{ item.date_confidence === 'high' ? '高' : '中' }}
              </el-tag>
            </div>
            <div class="posting-meta">
              {{ item.company }} · 来源：{{ item.source_name }} · 发布：{{ fmtDate(item.published_at) }} · 采集：{{ fmtDate(item.observed_at) }}
            </div>
            <div class="posting-snippet">{{ item.snippet }}</div>
            <div class="skill-tags">
              <el-tag v-for="s in item.skills" :key="s" size="small" effect="plain">{{ s }}</el-tag>
            </div>
            <el-button size="small" link type="primary" @click="openSource(item.source_url)">查看原文 ↗</el-button>
          </div>
          <el-empty v-if="!overview.evidence.job_postings.length" description="暂无招聘快照证据" :image-size="60" />
        </div>

        <div v-else class="knowledge-list">
          <div v-for="(item, i) in overview.evidence.authoritative_knowledge" :key="i" class="posting-item">
            <strong>{{ (item as Record<string, string>).title }}</strong>
            <div class="posting-meta">
              来源：{{ (item as Record<string, string>).source_name }}
              <template v-if="(item as Record<string, string>).source_no"> · 编号 {{ (item as Record<string, string>).source_no }}</template>
              <template v-if="(item as Record<string, string>).page"> · 页码 {{ (item as Record<string, string>).page }}</template>
            </div>
          </div>
          <el-empty v-if="!overview.evidence.authoritative_knowledge.length" description="暂无权威知识证据" :image-size="60" />
        </div>
      </div>
    </section>

    <!-- 教学仿真声明（红线） -->
    <el-alert
      v-if="overview?.scenario"
      type="warning"
      :closable="false"
      show-icon
      class="comp-alert"
      title="教学模拟环境声明"
      :description="overview.scenario.disclaimer"
    />
  </div>
</template>

<style scoped>
.competition-page { display: flex; flex-direction: column; gap: 14px; }
.comp-alert { border-radius: 10px; }

.comp-hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; padding: 26px 28px; background: linear-gradient(135deg, #0b6670 0%, #0e7a80 60%, #14958f 100%); color: #fff; border: 0; }
.comp-hero h1 { margin: 0 0 10px; font-size: 24px; line-height: 1.35; }
.comp-hero p { margin: 0; max-width: 720px; color: rgba(255, 255, 255, 0.86); font-size: 13.5px; line-height: 1.7; }
.comp-hero-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; flex: 0 0 auto; }
.comp-group-name { color: rgba(255, 255, 255, 0.9); font-size: 12px; }

.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 10px; }
.metric-card { display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; border: 1px solid var(--ots-border); border-radius: 12px; background: var(--ots-bg-panel); }
.metric-card strong { font-size: 20px; color: var(--ots-primary); }
.metric-card span { font-size: 11.5px; color: var(--ots-text-secondary); }
.metric-card.metric-gap strong { color: var(--ots-danger); font-size: 15px; }

.chain-card, .discovery-card { padding: 20px 22px; }
.section-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; }
.section-head h3 { margin: 0; font-size: 16px; }
.section-head .text-secondary { font-size: 12px; }

.chain-flow { display: flex; align-items: stretch; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
.chain-node { position: relative; display: flex; flex-direction: column; gap: 3px; min-width: 118px; padding: 12px 12px 10px; border: 1px solid var(--ots-border); border-radius: 12px; background: var(--ots-bg-subtle); text-align: left; cursor: pointer; transition: all 0.15s; }
.chain-node:hover, .chain-node.active { border-color: var(--ots-primary); background: #eef6f6; transform: translateY(-2px); }
.chain-step { position: absolute; top: 8px; right: 10px; font-size: 10px; color: var(--ots-text-secondary); }
.chain-node strong { font-size: 13px; color: var(--ots-text); padding-right: 14px; }
.chain-node small { font-size: 11px; color: var(--ots-text-secondary); }
.chain-node em { font-style: normal; font-size: 11px; color: var(--ots-primary); font-weight: 600; }
.chain-arrow { align-self: center; color: var(--ots-border-strong); font-size: 16px; flex: 0 0 auto; }

.discovery-statement { margin: 0 0 14px; font-size: 14px; line-height: 1.8; }
.demand-bar { display: flex; height: 34px; border-radius: 9px; overflow: hidden; margin-bottom: 16px; font-size: 12px; color: #fff; }
.bar-segment { display: flex; align-items: center; justify-content: center; white-space: nowrap; min-width: 0; overflow: hidden; }
.bar-segment.demand { background: var(--ots-danger); }
.bar-segment.supply { background: var(--ots-growth); }

.discovery-detail { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 14px; }
.detail-block { padding: 12px 14px; border: 1px solid var(--ots-border); border-radius: 10px; background: var(--ots-bg-subtle); }
.detail-block h4 { margin: 0 0 8px; font-size: 12.5px; color: var(--ots-text-secondary); }
.detail-block ul { margin: 0; padding-left: 16px; font-size: 12.5px; line-height: 1.9; }
.warning-text { color: var(--ots-warning); }
.skill-tags { display: flex; flex-wrap: wrap; gap: 6px; }

.evidence-section { display: flex; gap: 10px; }
.evidence-panel { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--ots-border-strong); }
.evidence-tabs { margin-bottom: 12px; }
.posting-list, .knowledge-list { display: flex; flex-direction: column; gap: 10px; }
.posting-item { padding: 12px 14px; border: 1px solid var(--ots-border); border-radius: 10px; }
.posting-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.posting-meta { margin: 5px 0; font-size: 12px; color: var(--ots-text-secondary); }
.posting-snippet { margin-bottom: 8px; font-size: 12.5px; color: var(--ots-text); line-height: 1.6; }

@media (max-width: 900px) {
  .comp-hero { flex-direction: column; }
  .comp-hero-meta { align-items: flex-start; }
  .chain-arrow { display: none; }
}
</style>
