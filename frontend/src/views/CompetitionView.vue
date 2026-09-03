<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { competitionApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { CompetitionOverviewOut } from '@/types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const overview = ref<CompetitionOverviewOut | null>(null)
const loading = ref(true)
const failed = ref(false)
const activeChain = ref(0)
const showEvidence = ref(false)
const activeTab = ref<'postings' | 'knowledge'>('postings')

// Phase 7/8 六步导演链：01—03 教师侧 · 教学建设；04—06 学生侧 · 技能验证。
// 学生侧三步全部经「正常登出 → 登录页学生交接 → 正常 student 认证」进入，不开任何跨角色权限。
type StudentStage = 'simulation' | 'profile' | 'adaptive'
interface ChainNode {
  step: string
  label: string
  desc: string
  role: 'teacher' | 'student'
  to: string
  stage?: StudentStage
  metric: string
}

// §11 口径：场景 code 与缺口能力全部来自 API（后端 overview.scenario 真实匹配），前端不写死。
const chainNodes = computed<ChainNode[]>(() => {
  const m = overview.value?.metrics
  const sc = overview.value?.scenario
  return [
    { step: '01', label: '产业洞察', desc: '岗位变化 · 技能需求 · 招聘证据', role: 'teacher', to: '/teacher/industry?tab=positions', metric: m ? `${m.job_sample_count} 条招聘样本 · ${m.position_count} 个对接岗位` : '—' },
    { step: '02', label: '专业群能力缺口', desc: '产业需求 vs 课程供给', role: 'teacher', to: '/teacher/industry?tab=group', metric: hasValidGap.value ? `${discovery.value?.ability_name} +${discovery.value?.gap}pp` : loading.value || failed.value ? '—' : '暂无可验证缺口' },
    { step: '03', label: '培养方案调整', desc: 'Gap 分析 → 调整草案 → 教师审核', role: 'teacher', to: '/teacher/industry?tab=program', metric: m ? `${m.course_count} 门课程供给` : '—' },
    { step: '04', label: '岗位技能实训', desc: '学生完成教学仿真任务', role: 'student', to: '', stage: 'simulation', metric: loading.value || failed.value ? '—' : sc ? sc.title : '进入仿真中心选择场景' },
    { step: '05', label: '技能证据评价', desc: '行为事件形成可追溯技能证据', role: 'student', to: '', stage: 'profile', metric: '多源证据 · 能力画像 · 置信度' },
    { step: '06', label: '个性化提升', desc: '依据薄弱能力进入补学与重练', role: 'student', to: '', stage: 'adaptive', metric: '个性化学习路径' },
  ]
})

const discovery = computed(() => overview.value?.discovery ?? null)
const metrics = computed(() => overview.value?.metrics ?? null)

// §7/§8 口径：无有效分母或无结论 → 不显示 0/0%、不输出「最大缺口」结论；接口失败 → 「—」
const hasValidGap = computed(() => {
  const d = discovery.value
  const m = metrics.value
  return !!(d && m && m.job_sample_count > 0 && d.gap > 0 && d.demand_share > 0)
})

const confidenceTag = computed(() => {
  const c = metrics.value?.data_confidence ?? 'low'
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

// §1 教师→学生统一转场（04/05/06 共用）：正常 logout → /login?redirect=学生业务路径 →
// 正常 student 登录。登录页对学生业务路径做交接高亮/预填，但不自动登录、不开跨角色权限。
const STAGE_COPY: Record<StudentStage, { target: () => string; body: string }> = {
  simulation: {
    target: () => (overview.value?.scenario ? `/simulation/${overview.value.scenario.scenario_code}` : '/simulation'),
    body: '教师侧已完成产业能力缺口分析与教学任务转化。接下来切换学生演示角色，展示学生如何通过岗位仿真实训形成技能证据。',
  },
  profile: {
    target: () => '/profile',
    body: '接下来切换学生演示角色，查看学生的技能证据档案：多源证据、能力得分与证据置信度。',
  },
  adaptive: {
    target: () => '/adaptive-learning',
    body: '接下来切换学生演示角色，展示系统如何依据薄弱能力生成个性化补学路径与重练任务。',
  },
}

function gotoStudentStage(stage: StudentStage) {
  const copy = STAGE_COPY[stage]
  ElMessageBox.confirm(copy.body, '进入学生技能验证', {
    confirmButtonText: '前往学生演示',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => {
      auth.logout()
      router.push({ path: '/login', query: { redirect: copy.target() } })
    })
    .catch(() => {})
}

function onChainNode(node: ChainNode) {
  if (node.stage) {
    gotoStudentStage(node.stage)
    return
  }
  if (node.to) router.push(node.to)
}

onMounted(async () => {
  const groupId = route.query.group_id ? Number(route.query.group_id) : undefined
  try {
    overview.value = await competitionApi.overview(groupId)
  } catch (e) {
    console.warn('[competition] 总览数据加载失败，页面降级为可导航故事线', e)
    failed.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ots-page competition-page">
    <!-- 故事线标题（导演模式，不是功能清单） -->
    <header class="comp-hero ots-card">
      <div class="comp-hero-text">
        <h1>产业岗位变化，如何及时转化为职业院校人才培养能力？</h1>
        <p>通过产业岗位证据、专业群能力分析、岗位仿真实训和多源技能评价，实现「产业需求 — 教学改革 — 技能验证」闭环。</p>
      </div>
      <div class="comp-hero-meta">
        <el-tag v-if="overview" :type="confidenceTag.type" effect="light">数据可信度：{{ confidenceTag.label }}</el-tag>
        <span v-if="overview" class="comp-group-name">{{ overview.group.name }}</span>
      </div>
    </header>

    <!-- 六步导演链：静态产品结构立即渲染，不随数据加载消失（§22） -->
    <section class="ots-card chain-card">
      <div class="section-head">
        <h3>演示故事线</h3>
        <div class="role-legend">
          <span class="role-chip teacher"><el-icon><UserFilled /></el-icon>教师侧 · 01—03 教学建设</span>
          <span class="role-chip student"><el-icon><Avatar /></el-icon>学生侧 · 04—06 技能验证</span>
        </div>
      </div>
      <div class="chain-flow">
        <template v-for="(node, index) in chainNodes" :key="node.step">
          <button
            class="chain-node"
            :class="{ active: activeChain === index, 'node-teacher': node.role === 'teacher', 'node-student': node.role === 'student' }"
            type="button"
            :title="`${node.step} ${node.label}：${node.metric}`"
            @click="activeChain = index; onChainNode(node)"
          >
            <span class="chain-step">{{ node.step }}</span>
            <strong>{{ node.label }}</strong>
            <small>{{ node.desc }}</small>
            <em>{{ node.metric }}</em>
          </button>
          <!-- 03/04 之间的小型角色转场标记：解释中途切换账号的必然性 -->
          <span v-if="index < chainNodes.length - 1" class="chain-arrow">
            <em v-if="index === 2">学生登录 ▸<br />技能验证</em>
            <template v-else>→</template>
          </span>
        </template>
      </div>
    </section>

    <!-- 规模指标：≤6 项，口径与后端统计一致（能力节点→岗位—能力关系）；骨架与内容同位 -->
    <el-skeleton v-if="loading" class="ots-card metric-skeleton" :rows="2" animated />
    <section v-else-if="overview" class="metric-grid">
      <div class="metric-card"><strong>{{ overview.metrics.major_count }}</strong><span>专业数</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.position_count }}</strong><span>对接岗位</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.task_count }}</strong><span>典型工作任务</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.ability_node_count }}</strong><span>岗位—能力关系</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.job_sample_count }}</strong><span>有效招聘样本</span></div>
      <div class="metric-card"><strong>{{ overview.metrics.course_count }}</strong><span>课程供给</span></div>
    </section>

    <!-- 系统真实发现（真实 API 数据；失败/无结论均有独立降级，不白屏不假结论） -->
    <el-skeleton v-if="loading" class="ots-card metric-skeleton" :rows="4" animated />
    <section v-else-if="failed || !overview" class="ots-card discovery-card">
      <div class="section-head"><h3>系统真实发现</h3></div>
      <p class="discovery-empty">暂时无法获取比赛总览数据。可先进入真实业务页面查看。</p>
      <div class="discovery-actions">
        <el-button type="primary" plain @click="router.push('/teacher/industry')">专业群建设</el-button>
        <el-button plain @click="router.push('/teacher/training')">教学实训</el-button>
      </div>
    </section>
    <section v-else-if="!hasValidGap" class="ots-card discovery-card">
      <div class="section-head"><h3>系统真实发现</h3><span class="text-secondary">数据由系统实时计算，无有效样本时不下结论</span></div>
      <p class="discovery-empty">当前暂无可验证能力缺口，可进入专业群建设查看数据覆盖情况。</p>
      <div class="discovery-actions">
        <el-button type="primary" plain @click="router.push('/teacher/industry?tab=positions')">查看产业证据</el-button>
        <el-button plain @click="router.push('/teacher/industry?tab=group')">查看专业群分析</el-button>
      </div>
    </section>
    <section v-else class="ots-card discovery-card">
      <div class="section-head">
        <h3>系统真实发现</h3>
        <span class="text-secondary">以下数据由系统对当前专业群实时计算，非演示写死</span>
      </div>
      <p class="discovery-statement">
        当前值得关注的能力：<strong>{{ discovery!.ability_name }}</strong>
        <span class="text-secondary">（{{ discovery!.months ? `近 ${discovery!.months} 个月 · ` : '' }}{{ overview.metrics.job_sample_count }} 条招聘样本 × {{ overview.metrics.course_count }} 门课程能力权重）</span>
      </p>
      <div class="discovery-facts">
        <div><span>产业需求</span><strong>{{ discovery!.demand_share }}%</strong></div>
        <div><span>课程供给</span><strong>{{ discovery!.curriculum_share }}%</strong></div>
        <div class="fact-gap"><span>能力 Gap（需求高于供给）</span><strong>+{{ discovery!.gap }} pp</strong></div>
        <div><span>影响岗位</span><strong>{{ discovery!.demand_positions.length }} 个</strong></div>
      </div>
      <!-- 需求 vs 供给：文字标签 + 数值 + 条纹形状三重区分，投影偏色/弱彩条件下仍可辨（§2-3） -->
      <div class="demand-bar">
        <div class="bar-segment demand" :style="{ width: demandRatio + '%' }">■ 产业需求 {{ discovery!.demand_share }}%</div>
        <div class="bar-segment supply" :style="{ width: 100 - demandRatio + '%' }">▨ 课程供给 {{ discovery!.curriculum_share }}%</div>
      </div>

      <div class="discovery-detail">
        <div class="detail-block">
          <h4>产生该需求的岗位</h4>
          <ul>
            <li v-for="p in discovery!.demand_positions" :key="p.id">
              {{ p.name }}
              <small class="text-secondary">{{ p.major_name }} · {{ p.sample_count }} 条样本</small>
            </li>
            <li v-if="!discovery!.demand_positions.length" class="text-secondary">暂无岗位样本</li>
          </ul>
        </div>
        <div class="detail-block">
          <h4>企业技能词（未覆盖）</h4>
          <div class="skill-tags">
            <el-tag v-for="s in discovery!.uncovered_skills" :key="s.name" type="danger" effect="plain">
              {{ s.name }} × {{ s.count }}
            </el-tag>
            <span v-if="!discovery!.uncovered_skills.length" class="text-secondary">未发现明显未覆盖技能词</span>
          </div>
        </div>
        <div class="detail-block">
          <h4>当前课程覆盖</h4>
          <ul>
            <li v-for="c in discovery!.covered_by" :key="c.course_id">
              {{ c.course_name }}
              <small class="text-secondary">{{ c.major_name }} · {{ c.total_hours }} 学时 · 权重 {{ c.weight }}</small>
            </li>
            <li v-if="!discovery!.covered_by.length" class="text-secondary warning-text">⚠ 该能力当前无课程覆盖</li>
          </ul>
        </div>
      </div>

      <div class="evidence-section">
        <el-button type="primary" plain @click="showEvidence = !showEvidence">
          {{ showEvidence ? '收起证据' : '查看证据' }}
        </el-button>
        <el-button plain @click="router.push('/teacher/industry?tab=positions')">查看产业证据</el-button>
        <el-button plain @click="router.push('/teacher/industry?tab=group')">查看专业群分析</el-button>
      </div>

      <!-- 场景映射：真实匹配（后端按能力 key 选择），无匹配时不大字报错、只给浏览路径 -->
      <div v-if="overview.scenario" class="scenario-line">
        <span>对应技能实训：<strong>{{ overview.scenario.title }}</strong></span>
        <el-button type="success" plain @click="gotoStudentStage('simulation')">进入对应实训</el-button>
      </div>
      <div v-else class="scenario-line scenario-none">
        <span>当前能力尚未配置直接对应的操作型仿真实训，可经学生演示账号浏览仿真中心。</span>
        <el-button plain @click="gotoStudentStage('simulation')">前往学生演示</el-button>
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

    <!-- 技术边界与可信机制（一句话版，详细留答辩追问；不展示算法参数） -->
    <section class="trust-strip ots-card">
      <div class="trust-item"><span>AI 负责</span><strong>生成 · 解释 · 推荐</strong></div>
      <div class="trust-item"><span>规则系统负责</span><strong>评分 · 权限 · 审核 · 正式发布</strong></div>
      <div class="trust-item"><span>培养方案</span><strong>Gap 分析 → 调整草案 → 教师审核</strong></div>
      <div class="trust-item"><span>技能证据</span><strong>可追溯行为事件 + 多源证据 + 能力置信度</strong></div>
      <p class="trust-note">AI 辅助生成教学说明和建议文本，正式结论与发布仍由规则分析与教师审核控制。04—06 为学生侧演示，点击上方学生节点将经登录页完成角色交接。</p>
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
.competition-page { display: flex; flex-direction: column; gap: 14px; max-width: 1460px; margin: 0 auto; }
.comp-alert { border-radius: 10px; }

/* 首屏高度收敛：hero 不超高，链与指标在 1080p 第一屏可见 */
.comp-hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; padding: 18px 24px; background: linear-gradient(135deg, #0b6670 0%, #0e7a80 60%, #14958f 100%); color: #fff; border: 0; }
.comp-hero h1 { margin: 0 0 8px; font-size: 23px; line-height: 1.35; }
.comp-hero p { margin: 0; max-width: 780px; color: rgba(255, 255, 255, 0.9); font-size: 13px; line-height: 1.7; }
.comp-hero-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex: 0 0 auto; }
.comp-group-name { color: rgba(255, 255, 255, 0.9); font-size: 13px; }

.metric-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.metric-card { display: flex; flex-direction: column; gap: 4px; padding: 13px 14px; border: 1px solid var(--ots-border); border-radius: 12px; background: var(--ots-bg-panel); }
.metric-card strong { font-size: 22px; color: var(--ots-primary); }
.metric-card span { font-size: 12px; color: var(--ots-text-secondary); }
.metric-skeleton { padding: 18px 20px; }

.chain-card, .discovery-card { padding: 16px 22px 18px; }
.section-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.section-head h3 { margin: 0; font-size: 16px; }
.section-head .text-secondary { font-size: 12.5px; }
.role-legend { display: flex; gap: 8px; }
.role-chip { display: flex; align-items: center; gap: 5px; padding: 5px 11px; border-radius: 999px; font-size: 12px; }
.role-chip.teacher { background: #eaf2fa; color: #245b81; }
.role-chip.student { background: var(--ots-growth-soft); color: var(--ots-growth); }

/* 六步一行优先，中等宽度横向滚动，不折行；教师/学生轻量差异=顶部细色条+虚线框，不引入新颜色 */
.chain-flow { display: flex; align-items: stretch; gap: 6px; overflow-x: auto; padding-bottom: 4px; flex-wrap: nowrap; }
.chain-node { position: relative; display: flex; flex-direction: column; gap: 4px; min-width: 158px; padding: 13px 13px 11px; border: 1px solid var(--ots-border); border-radius: 12px; background: var(--ots-bg-subtle); text-align: left; cursor: pointer; transition: border-color 0.15s, background 0.15s, box-shadow 0.15s; flex: 1 0 auto; }
.chain-node.node-teacher { box-shadow: inset 0 3px 0 var(--ots-education); }
.chain-node.node-student { border-style: dashed; box-shadow: inset 0 3px 0 var(--ots-growth); }
.chain-node:hover { border-color: var(--ots-primary); background: #eef6f6; }
.chain-node:focus-visible { outline: 2px solid var(--ots-primary); outline-offset: 2px; }
.chain-node.active { border-color: var(--ots-primary); background: #e7f2f2; }
.chain-step { position: absolute; top: 9px; right: 11px; font-size: 11px; font-weight: 700; color: var(--ots-text-secondary); }
.chain-node strong { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 14px; line-height: 1.3; color: var(--ots-text); padding-right: 22px; }
.chain-node small { font-size: 12px; color: var(--ots-text-secondary); line-height: 1.45; }
.chain-node em { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-style: normal; font-size: 12px; color: var(--ots-primary); font-weight: 600; line-height: 1.4; }
.chain-arrow { align-self: center; color: var(--ots-border-strong); font-size: 16px; flex: 0 0 auto; }
.chain-arrow em { display: block; font-style: normal; font-size: 11px; font-weight: 600; color: var(--ots-growth); white-space: nowrap; text-align: center; line-height: 1.35; }

.discovery-statement { margin: 0 0 12px; font-size: 14px; line-height: 1.8; }
.discovery-empty { margin: 0 0 14px; color: var(--ots-text-secondary); font-size: 13px; }
.discovery-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
.discovery-facts > div { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border-radius: 10px; background: var(--ots-bg-subtle); }
.discovery-facts span { color: var(--ots-text-secondary); font-size: 12px; }
.discovery-facts strong { color: var(--ots-primary-dark); font-size: 17px; }
.discovery-facts .fact-gap { border: 1px solid #ecd2d0; background: #fdf4f3; }
.discovery-facts .fact-gap strong { color: var(--ots-danger); }
.demand-bar { display: flex; height: 32px; border-radius: 9px; overflow: hidden; margin-bottom: 14px; font-size: 12.5px; font-weight: 600; color: #fff; }
.bar-segment { display: flex; align-items: center; justify-content: center; white-space: nowrap; min-width: 0; overflow: hidden; }
.bar-segment.demand { background: var(--ots-danger); }
/* 供给段用条纹底形：与纯红的需求段在黑白/偏色投影下仍可区分 */
.bar-segment.supply { background: repeating-linear-gradient(135deg, var(--ots-growth) 0 8px, #2f7a55 8px 14px); }

.discovery-detail { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 14px; }
.detail-block { padding: 12px 14px; border: 1px solid var(--ots-border); border-radius: 10px; background: var(--ots-bg-subtle); }
.detail-block h4 { margin: 0 0 8px; font-size: 13px; color: var(--ots-text-secondary); }
.detail-block ul { margin: 0; padding-left: 16px; font-size: 13px; line-height: 1.9; }
.detail-block li small { font-size: 12px; }
.warning-text { color: var(--ots-warning); }
.skill-tags { display: flex; flex-wrap: wrap; gap: 6px; }

.evidence-section { display: flex; flex-wrap: wrap; gap: 10px; }
.scenario-line { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-top: 12px; padding: 12px 14px; border: 1px dashed var(--ots-border-strong); border-radius: 10px; background: #fbfdfc; font-size: 13px; }
.scenario-line strong { color: var(--ots-primary-dark); }
.scenario-line.scenario-none span { color: var(--ots-text-secondary); }
.evidence-panel { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--ots-border-strong); }
.evidence-tabs { margin-bottom: 12px; }
.posting-list, .knowledge-list { display: flex; flex-direction: column; gap: 10px; }
.posting-item { padding: 12px 14px; border: 1px solid var(--ots-border); border-radius: 10px; }
.posting-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.posting-meta { margin: 5px 0; font-size: 12.5px; color: var(--ots-text-secondary); }
.posting-snippet { margin-bottom: 8px; font-size: 13px; color: var(--ots-text); line-height: 1.6; }

.trust-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; padding: 14px 18px; }
.trust-item { display: flex; flex-direction: column; gap: 3px; }
.trust-item span { color: var(--ots-text-secondary); font-size: 12px; }
.trust-item strong { color: var(--ots-primary-dark); font-size: 13px; }
.trust-note { grid-column: 1 / -1; margin: 0; padding-top: 8px; border-top: 1px dashed var(--ots-border); color: var(--ots-text-secondary); font-size: 12px; }

@media (max-width: 1280px) {
  .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1100px) {
  .trust-strip { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 900px) {
  .comp-hero { flex-direction: column; }
  .comp-hero-meta { align-items: flex-start; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .discovery-facts { grid-template-columns: 1fr 1fr; }
}
</style>
