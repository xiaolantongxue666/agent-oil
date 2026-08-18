<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock, Search } from '@element-plus/icons-vue'
import { adminApi, type PromptRevisionOut, type PromptTemplateOut } from '@/api'

const loading = ref(true)
const saving = ref(false)
const prompts = ref<PromptTemplateOut[]>([])
const selectedCode = ref('')
const category = ref('全部')
const usageFilter = ref<'全部' | '生产使用' | '后备机制' | '待接入'>('全部')
const keyword = ref('')
const systemPrompt = ref('')
const userPrompt = ref('')
const changeNote = ref('')
const revisions = ref<PromptRevisionOut[]>([])
const historyVisible = ref(false)
const historyLoading = ref(false)

type RuntimeState = 'active' | 'standby' | 'pending'
type ManagementLevel = 'teaching' | 'core' | 'future'

interface StrategyGovernance {
  runtime: RuntimeState
  conditional?: boolean
  trigger: string
  runtimeNote: string
  level: ManagementLevel
  levelLabel: string
  adminAdvice: string
}

const strategyGovernance: Record<string, StrategyGovernance> = {
  structured_output_contract: {
    runtime: 'standby', conditional: true, trigger: '缺少 JSON 要求的结构化模型调用',
    runtimeNote: '网关已接入该后备分支，但当前生产调用都自行声明了 JSON 要求，因此现有请求不会触发。',
    level: 'core', levelLabel: '系统核心', adminAdvice: '适合展示在高级策略区；它是后备约束，不应标记为当前已真实触发。',
  },
  structured_output_repair: {
    runtime: 'active', conditional: true, trigger: '结构化输出解析失败后的重试',
    runtimeNote: '模型返回内容无法解析为 JSON 时，下一次重试会自动使用。',
    level: 'core', levelLabel: '系统核心', adminAdvice: '适合展示在高级策略区；建议仅由了解模型输出协议的管理员修改。',
  },
  qa_query_rewrite: {
    runtime: 'active', trigger: '学生或教师在学习助手中发起问答',
    runtimeNote: '知识问答工作流会先扩展检索关键词，再查询专业资料。',
    level: 'teaching', levelLabel: '教学应用', adminAdvice: '适合管理员展示和调整，用于优化专业术语召回与连续追问理解。',
  },
  qa_answer: {
    runtime: 'active', trigger: '学习助手生成最终回答',
    runtimeNote: '结合 RAG 资料、只读业务事实和用户问题生成带来源的回答。',
    level: 'teaching', levelLabel: '教学应用', adminAdvice: '适合重点展示，是知识问答的主要教学行为策略。',
  },
  qa_evidence_boundary: {
    runtime: 'active', trigger: '知识检索改写与最终回答',
    runtimeNote: '在模型调用前声明资料、历史对话和用户输入均不能覆盖系统规则。',
    level: 'core', levelLabel: '安全核心', adminAdvice: '应展示但需突出高风险；不建议将其当作普通教学文案随意修改。',
  },
  training_strategy: {
    runtime: 'pending', trigger: '原开放式实训工作流',
    runtimeNote: '代码节点已保留，但当前学生端采用选择题流程，没有业务接口启动训练工作流。',
    level: 'future', levelLabel: '待接入策略', adminAdvice: '适合保留在待接入区，不能宣称修改后会影响当前学生实训。',
  },
  training_scenario: {
    runtime: 'pending', trigger: '原开放式实训情境生成节点',
    runtimeNote: '当前实训从数据库读取教师配置的情境，缺失时使用固定教学模拟文案。',
    level: 'future', levelLabel: '待接入策略', adminAdvice: '适合保留为未来能力，当前仅保存版本，不会改变学生页面情境。',
  },
  training_intermediate_evaluation: {
    runtime: 'pending', trigger: '原开放式实训中间评价节点',
    runtimeNote: '当前选择题由数据库规则评分，不执行开放式回答的中间 LLM 评价。',
    level: 'future', levelLabel: '待接入策略', adminAdvice: '适合在待接入区说明，不应与当前规则评分混为一谈。',
  },
  training_follow_up: {
    runtime: 'pending', trigger: '原开放式实训苏格拉底追问节点',
    runtimeNote: '追问节点和 Prompt 已保留，但当前选择题接口不会调用训练工作流。',
    level: 'future', levelLabel: '待接入策略', adminAdvice: '适合展示未来教学设计，但必须明确当前没有真实学生触发入口。',
  },
  evaluation_final: {
    runtime: 'pending', trigger: '原开放式实训最终混合评价',
    runtimeNote: '仅由尚未接入接口的训练工作流调用；当前选择题成绩由数据库规则计算。',
    level: 'future', levelLabel: '待接入策略', adminAdvice: '适合保留为未来评价策略，接入前还需教学评价和公平性审查。',
  },
  question_generation: {
    runtime: 'active', trigger: '教师进入实训任务题库并生成题目草稿',
    runtimeNote: '教师题库生成接口真实调用，生成结果仍需教师审核后发布。',
    level: 'teaching', levelLabel: '教学应用', adminAdvice: '适合重点展示，可调整题目风格、依据约束和草稿输出要求。',
  },
  position_search_terms: {
    runtime: 'active', trigger: '教师执行岗位公开证据采集',
    runtimeNote: '岗位发现服务在模型可用时生成别名和检索短语，不可用时使用规则回退。',
    level: 'teaching', levelLabel: '专业群建设', adminAdvice: '适合展示，便于优化行业岗位名称和招聘检索覆盖面。',
  },
  position_graph_analysis: {
    runtime: 'active', trigger: '教师对岗位证据执行 AI 能力图谱分析',
    runtimeNote: '根据已采集证据生成可审核草稿，最终仍由教师审核发布。',
    level: 'teaching', levelLabel: '专业群建设', adminAdvice: '适合重点展示，可控制证据约束、六维能力结构和草稿质量。',
  },
}

const unknownGovernance: StrategyGovernance = {
  runtime: 'pending', trigger: '尚未登记', runtimeNote: '该策略尚未登记实际调用状态。',
  level: 'future', levelLabel: '待核对', adminAdvice: '请先核对生产调用链，再决定是否修改。',
}

function governanceOf(item: PromptTemplateOut | null | undefined) {
  return item ? strategyGovernance[item.code] || unknownGovernance : unknownGovernance
}

const categoryContexts: Record<string, { stage: string; audience: string; impact: string }> = {
  知识问答: { stage: '课前预习与课后答疑', audience: '学生 / 教师', impact: '专业知识问答' },
  智能实训: { stage: '课堂实训与技能训练', audience: '学生', impact: '情境、引导与过程反馈' },
  教学评价: { stage: '学习评价与能力诊断', audience: '学生 / 教师', impact: '开放作答评价' },
  题库生成: { stage: '教师备课与资源建设', audience: '教师', impact: '题库草稿生成' },
  岗位图谱: { stage: '专业群与课程体系建设', audience: '专业负责人 / 教师', impact: '岗位能力分析' },
  模型基础设施: { stage: '模型输出质量保障', audience: '系统管理员', impact: '结构化输出稳定性' },
}

const categories = computed(() => [
  '全部',
  ...Array.from(new Set(prompts.value.map((item) => item.category))),
])

const activeCount = computed(() => prompts.value.filter((item) => governanceOf(item).runtime === 'active').length)
const standbyCount = computed(() => prompts.value.filter((item) => governanceOf(item).runtime === 'standby').length)
const pendingCount = computed(() => prompts.value.filter((item) => governanceOf(item).runtime === 'pending').length)
const coreCount = computed(() => prompts.value.filter((item) => governanceOf(item).level === 'core').length)

const filtered = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return prompts.value.filter((item) => {
    const categoryMatch = category.value === '全部' || item.category === category.value
    const governance = governanceOf(item)
    const usageMatch = usageFilter.value === '全部'
      || (usageFilter.value === '生产使用' && governance.runtime === 'active')
      || (usageFilter.value === '后备机制' && governance.runtime === 'standby')
      || (usageFilter.value === '待接入' && governance.runtime === 'pending')
    const keywordMatch = !query || [item.name, item.code, item.description, item.source_location, governance.trigger, governance.adminAdvice]
      .some((value) => value.toLowerCase().includes(query))
    return categoryMatch && usageMatch && keywordMatch
  })
})

const selected = computed(() => prompts.value.find((item) => item.code === selectedCode.value) || null)
const selectedGovernance = computed(() => governanceOf(selected.value))
const selectedContext = computed(() => (
  categoryContexts[selected.value?.category || '']
  || { stage: '教学智能体运行环节', audience: '授权用户', impact: selected.value?.description || '模型调用策略' }
))
const dirty = computed(() => Boolean(selected.value) && (
  systemPrompt.value !== selected.value?.system_prompt
  || userPrompt.value !== selected.value?.user_prompt_template
))
const missingVariables = computed(() => (
  selected.value?.variables.filter((name) => (
    !systemPrompt.value.includes(`{{${name}}}`) && !userPrompt.value.includes(`{{${name}}}`)
  )) || []
))
const publishChecks = computed(() => [
  { label: '必需教学变量完整', pass: missingVariables.value.length === 0 },
  { label: '代码层结构校验与业务规则保持独立', pass: true },
])

function selectPrompt(item: PromptTemplateOut) {
  selectedCode.value = item.code
  systemPrompt.value = item.system_prompt
  userPrompt.value = item.user_prompt_template
  changeNote.value = ''
}

async function loadPrompts(preferredCode = '') {
  loading.value = true
  try {
    const result = await adminApi.prompts()
    prompts.value = result.items
    const next = prompts.value.find((item) => item.code === (preferredCode || selectedCode.value))
      || prompts.value[0]
    if (next) selectPrompt(next)
  } catch (error: any) {
    ElMessage.error(error?.message || '教学策略加载失败')
  } finally {
    loading.value = false
  }
}

async function savePrompt() {
  if (!selected.value || !dirty.value) return
  const warning = missingVariables.value.length
    ? `以下变量已从模板中移除：${missingVariables.value.join('、')}。对应运行数据将不再发送给模型。\n\n`
    : ''
  const runtimeMessage = selectedGovernance.value.runtime === 'active'
    ? '保存后将在下一次匹配的模型调用中生效。'
    : selectedGovernance.value.runtime === 'standby'
      ? '该策略属于生产后备机制，当前调用不会触发；保存后仅在未来满足触发条件时生效。'
      : '该策略当前没有生产业务入口，保存后只生成待接入版本，不会影响现有学生或教师流程。'
  const coreMessage = selectedGovernance.value.level === 'core'
    ? '\n\n这是系统核心策略，错误修改可能影响多个智能体能力。'
    : ''
  try {
    await ElMessageBox.confirm(
      `${warning}${runtimeMessage}${coreMessage}\n\n代码层安全守卫、结构校验和教师审核仍然有效。是否继续？`,
      '保存教学策略新版本',
      {
        type: missingVariables.value.length || selectedGovernance.value.level === 'core' ? 'warning' : 'info',
        confirmButtonText: selectedGovernance.value.runtime === 'active' ? '保存并启用' : '确认保存',
      },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const updated = await adminApi.updatePrompt(selected.value.code, {
      system_prompt: systemPrompt.value,
      user_prompt_template: userPrompt.value,
      change_note: changeNote.value.trim() || '管理员编辑',
    })
    const index = prompts.value.findIndex((item) => item.code === updated.code)
    if (index >= 0) prompts.value[index] = updated
    selectPrompt(updated)
    const savedState = selectedGovernance.value.runtime === 'standby' ? '作为后备版本保存' : '等待业务接入'
    ElMessage.success(selectedGovernance.value.runtime === 'active'
      ? `已启用 ${updated.name} v${updated.version}`
      : `已保存 ${updated.name} v${updated.version}，${savedState}`)
  } catch (error: any) {
    ElMessage.error(error?.message || '教学策略发布失败')
  } finally {
    saving.value = false
  }
}

async function restoreDefault() {
  if (!selected.value) return
  try {
    await ElMessageBox.confirm(
      '将生成一个新版本并恢复为代码内置默认 Prompt，历史版本仍会保留。是否继续？',
      '恢复默认教学策略',
      { type: 'warning', confirmButtonText: '恢复默认' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const updated = await adminApi.restorePromptDefault(selected.value.code)
    const index = prompts.value.findIndex((item) => item.code === updated.code)
    if (index >= 0) prompts.value[index] = updated
    selectPrompt(updated)
    const restoreState = selectedGovernance.value.runtime === 'active'
      ? '已恢复默认并启用'
      : selectedGovernance.value.runtime === 'standby'
        ? '已恢复为默认后备版本'
        : '已恢复默认版本，等待业务接入'
    ElMessage.success(`${restoreState} v${updated.version}`)
  } catch (error: any) {
    ElMessage.error(error?.message || '恢复默认教学策略失败')
  } finally {
    saving.value = false
  }
}

async function showHistory() {
  if (!selected.value) return
  historyVisible.value = true
  historyLoading.value = true
  try {
    revisions.value = await adminApi.promptRevisions(selected.value.code)
  } catch (error: any) {
    ElMessage.error(error?.message || '版本历史加载失败')
  } finally {
    historyLoading.value = false
  }
}

function loadRevision(item: PromptRevisionOut) {
  systemPrompt.value = item.system_prompt
  userPrompt.value = item.user_prompt_template
  changeNote.value = `基于历史版本 v${item.version} 恢复`
  historyVisible.value = false
  ElMessage.info('历史内容已载入编辑器，点击页面底部保存按钮后才会写入新版本')
}

function resetEditor() {
  if (selected.value) selectPrompt(selected.value)
}

function placeholder(name: string) {
  return `{{${name}}}`
}

onMounted(loadPrompts)
</script>

<template>
  <div class="ots-page strategy-page" v-loading="loading">
    <header class="page-hero">
      <div>
        <div class="eyebrow">智能体能力 / 教学策略</div>
        <h2>教学策略工坊</h2>
        <p>管理教学智能体在知识问答、技能实训、教学评价和岗位分析中的行为策略。</p>
      </div>
      <div class="hero-status"><el-icon><CircleCheck /></el-icon><span>版本留痕</span><i />安全守卫独立生效</div>
    </header>

    <div class="governance-notice">
      <el-icon><Guide /></el-icon>
      <span>目录同时包含生产使用和待接入策略。只有标记为“生产使用”的策略会影响当前业务；规则评分、安全守卫与教师审核仍由代码层强制执行。</span>
      <el-tag type="danger" effect="plain" size="small">{{ coreCount }} 项系统核心</el-tag>
    </div>

    <section class="strategy-overview" aria-label="教学策略使用概览">
      <button type="button" :class="{ active: usageFilter === '全部' }" :aria-pressed="usageFilter === '全部'" @click="usageFilter = '全部'">
        <span class="overview-icon catalog"><el-icon><Collection /></el-icon></span>
        <div><small>策略目录</small><strong>{{ prompts.length }}</strong><p>全部可管理 Prompt</p></div>
      </button>
      <button type="button" :class="{ active: usageFilter === '生产使用' }" :aria-pressed="usageFilter === '生产使用'" @click="usageFilter = '生产使用'">
        <span class="overview-icon running"><el-icon><VideoPlay /></el-icon></span>
        <div><small>生产使用</small><strong>{{ activeCount }}</strong><p>当前业务可真实触发</p></div>
      </button>
      <button type="button" :class="{ active: usageFilter === '待接入' }" :aria-pressed="usageFilter === '待接入'" @click="usageFilter = '待接入'">
        <span class="overview-icon pending"><el-icon><Clock /></el-icon></span>
        <div><small>待接入</small><strong>{{ pendingCount }}</strong><p>保存版本但暂不生效</p></div>
      </button>
      <button type="button" :class="{ active: usageFilter === '后备机制' }" :aria-pressed="usageFilter === '后备机制'" @click="usageFilter = '后备机制'">
        <span class="overview-icon core"><el-icon><Lock /></el-icon></span>
        <div><small>后备机制</small><strong>{{ standbyCount }}</strong><p>已接入代码但当前不触发</p></div>
      </button>
    </section>

    <div class="workspace">
      <aside class="strategy-library ots-card">
        <div class="library-title">
          <div><span>教学策略目录</span><strong>{{ prompts.length }} 项策略</strong></div>
          <el-icon><Collection /></el-icon>
        </div>
        <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索名称、编号或调用位置" />
        <div class="library-filters">
          <el-select v-model="category" class="category-select">
            <el-option v-for="item in categories" :key="item" :label="item === '全部' ? '全部教学环节' : item" :value="item" />
          </el-select>
          <el-select v-model="usageFilter" class="usage-select">
            <el-option label="全部使用状态" value="全部" />
            <el-option label="生产使用" value="生产使用" />
            <el-option label="后备机制" value="后备机制" />
            <el-option label="待接入" value="待接入" />
          </el-select>
        </div>
        <div class="list-count">当前显示 {{ filtered.length }} 项</div>

        <div class="strategy-list">
          <button
            v-for="item in filtered"
            :key="item.code"
            type="button"
            class="strategy-item"
            :class="{ active: item.code === selectedCode }"
            @click="selectPrompt(item)"
          >
            <div class="item-topline">
              <span>{{ item.category }}</span>
              <em class="runtime-dot" :class="governanceOf(item).runtime">
                {{ governanceOf(item).runtime === 'active' ? (governanceOf(item).conditional ? '生产使用·条件触发' : '生产使用') : governanceOf(item).runtime === 'standby' ? '后备机制' : '待接入' }}
              </em>
            </div>
            <strong>{{ item.name }}</strong>
            <p>{{ item.description }}</p>
            <div class="item-footer">
              <code>{{ item.code }}</code>
              <span :class="item.is_default ? 'default' : 'custom'">v{{ item.version }} · {{ item.is_default ? '系统默认' : '自定义' }}</span>
            </div>
          </button>
          <el-empty v-if="!filtered.length" description="没有匹配的教学策略" :image-size="70" />
        </div>
      </aside>

      <main v-if="selected" class="strategy-editor ots-card">
        <div class="editor-header">
          <div class="editor-identity">
            <div class="category-mark"><el-icon><Reading /></el-icon></div>
            <div>
              <div class="title-row">
                <h3>{{ selected.name }}</h3>
                <el-tag effect="plain">v{{ selected.version }}</el-tag>
                <el-tag :type="selected.is_default ? 'info' : 'warning'">{{ selected.is_default ? '系统默认' : '自定义启用中' }}</el-tag>
                <el-tag :type="selectedGovernance.runtime === 'active' ? 'success' : selectedGovernance.runtime === 'standby' ? 'warning' : 'info'" effect="dark">
                  {{ selectedGovernance.runtime === 'active' ? (selectedGovernance.conditional ? '生产使用 · 条件触发' : '生产使用') : selectedGovernance.runtime === 'standby' ? '后备机制 · 当前不触发' : '待接入' }}
                </el-tag>
              </div>
              <p>{{ selected.description }}</p>
              <span class="source-location">代码定位：<code>{{ selected.source_location }}</code></span>
            </div>
          </div>
          <div class="header-actions">
            <el-button :icon="Clock" @click="showHistory">版本历史</el-button>
            <el-button :disabled="selected.is_default" @click="restoreDefault">恢复默认</el-button>
          </div>
        </div>

        <section class="runtime-panel" :class="selectedGovernance.runtime">
          <span class="runtime-icon"><el-icon><VideoPlay v-if="selectedGovernance.runtime === 'active'" /><Lock v-else-if="selectedGovernance.runtime === 'standby'" /><Clock v-else /></el-icon></span>
          <div class="runtime-copy">
            <div>
              <strong>{{ selectedGovernance.runtime === 'active' ? '已接入当前生产链路' : selectedGovernance.runtime === 'standby' ? '生产后备分支，当前没有真实触发' : '尚未接入当前业务流程' }}</strong>
              <el-tag size="small" effect="plain" :type="selectedGovernance.level === 'core' ? 'danger' : selectedGovernance.level === 'future' ? 'info' : 'success'">
                {{ selectedGovernance.levelLabel }}
              </el-tag>
            </div>
            <p>{{ selectedGovernance.runtimeNote }}</p>
          </div>
          <dl>
            <div><dt>真实触发位置</dt><dd>{{ selectedGovernance.trigger }}</dd></div>
            <div><dt>管理员展示建议</dt><dd>{{ selectedGovernance.adminAdvice }}</dd></div>
          </dl>
        </section>

        <section class="teaching-context">
          <div><span>教学环节</span><strong>{{ selectedContext.stage }}</strong></div>
          <div><span>适用角色</span><strong>{{ selectedContext.audience }}</strong></div>
          <div><span>影响范围</span><strong>{{ selectedContext.impact }}</strong></div>
        </section>

        <section class="variable-panel">
          <div class="panel-heading">
            <div><el-icon><Tickets /></el-icon><span><strong>运行时教学变量</strong><small>变量由系统在模型调用时替换，不支持表达式</small></span></div>
            <el-tag :type="missingVariables.length ? 'warning' : 'success'" effect="plain" size="small">
              {{ missingVariables.length ? `${missingVariables.length} 项缺失` : '变量完整' }}
            </el-tag>
          </div>
          <div v-if="selected.variables.length" class="variables">
            <el-tag
              v-for="item in selected.variables"
              :key="item"
              size="small"
              effect="plain"
              :type="missingVariables.includes(item) ? 'warning' : 'info'"
            >{{ placeholder(item) }}</el-tag>
          </div>
          <span v-else class="no-variable">该策略不依赖运行时变量</span>
        </section>

        <section class="prompt-fields">
          <div class="field-block">
            <div class="field-heading">
              <div><span class="field-index">A</span><span><strong>系统教学约束</strong><small>定义智能体角色、专业边界和安全原则</small></span></div>
              <el-tag size="small" effect="plain">System Prompt</el-tag>
            </div>
            <el-input v-model="systemPrompt" type="textarea" :rows="10" resize="vertical" spellcheck="false" placeholder="请输入系统教学约束" />
          </div>

          <div class="field-block">
            <div class="field-heading">
              <div><span class="field-index practice">B</span><span><strong>教学任务模板</strong><small>组织情境、教学资料、学生输入与输出要求</small></span></div>
              <el-tag size="small" type="warning" effect="plain">User Prompt 模板</el-tag>
            </div>
            <el-input v-model="userPrompt" type="textarea" :rows="16" resize="vertical" spellcheck="false" placeholder="请输入教学任务模板，可使用上方变量" />
          </div>
        </section>

        <section class="release-section">
          <div class="change-note">
            <div class="release-heading"><el-icon><Edit /></el-icon><div><strong>本次策略调整说明</strong><span>便于教师团队和管理员理解版本变更目的</span></div></div>
            <el-input v-model="changeNote" maxlength="500" show-word-limit placeholder="例如：增强岗位能力依据约束，优化学生追问方式" />
          </div>
          <div class="publish-checks">
            <div class="release-heading"><el-icon><Checked /></el-icon><div><strong>保存前检查</strong><span>{{ selectedGovernance.runtime === 'active' ? '保存后影响下一次匹配调用' : selectedGovernance.runtime === 'standby' ? '保存为满足条件时使用的后备版本' : '保存版本但暂不影响当前业务' }}</span></div></div>
            <div v-for="item in publishChecks" :key="item.label" class="check-item" :class="{ pass: item.pass }">
              <el-icon><CircleCheckFilled v-if="item.pass" /><WarningFilled v-else /></el-icon><span>{{ item.label }}</span>
            </div>
          </div>
        </section>

        <footer class="editor-footer">
          <span :class="dirty ? 'changed' : 'saved'"><i />{{ dirty ? '有尚未保存的教学策略修改' : selectedGovernance.runtime === 'active' ? '当前版本已在生产链路使用' : selectedGovernance.runtime === 'standby' ? '当前版本已保存为生产后备策略' : '当前版本已保存，等待业务接入' }}</span>
          <div>
            <el-button :disabled="!dirty" @click="resetEditor">撤销修改</el-button>
            <el-button type="primary" :loading="saving" :disabled="!dirty" @click="savePrompt">
              {{ selectedGovernance.runtime === 'active' ? '保存并启用' : selectedGovernance.runtime === 'standby' ? '保存后备版本' : '保存待接入版本' }}
            </el-button>
          </div>
        </footer>
      </main>
    </div>

    <el-drawer v-model="historyVisible" title="教学策略版本历史" size="min(720px, 94vw)">
      <div v-loading="historyLoading" class="history-drawer">
        <div class="history-intro"><el-icon><Clock /></el-icon><span>所有版本均保留完整内容和调整说明。载入历史版本不会立即生效，需重新发布。</span></div>
        <el-timeline>
          <el-timeline-item v-for="item in revisions" :key="item.version" :timestamp="new Date(item.created_at).toLocaleString()" placement="top">
            <el-card shadow="never">
              <div class="revision-head">
                <div><strong>版本 v{{ item.version }}</strong><el-tag v-if="item.is_default" size="small" type="info">默认内容</el-tag><span>{{ item.change_note }}</span></div>
                <el-button size="small" @click="loadRevision(item)">载入编辑器</el-button>
              </div>
              <el-collapse>
                <el-collapse-item title="查看该版本完整策略内容">
                  <div class="revision-label">系统教学约束</div><pre>{{ item.system_prompt }}</pre>
                  <div class="revision-label">教学任务模板</div><pre>{{ item.user_prompt_template }}</pre>
                </el-collapse-item>
              </el-collapse>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.strategy-page { max-width: 1600px; margin: 0 auto; }
.page-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin: 2px 0 17px; }
.eyebrow { margin-bottom: 7px; color: var(--ots-primary); font-size: 12px; font-weight: 600; letter-spacing: .8px; }
.page-hero h2 { margin: 0 0 7px; color: var(--ots-primary-dark); font-size: 25px; }
.page-hero p { margin: 0; color: var(--ots-text-secondary); }
.hero-status { display: flex; align-items: center; gap: 7px; padding: 8px 11px; border: 1px solid #d8e8e3; border-radius: 999px; background: #f6fbf8; color: #477066; font-size: 11px; white-space: nowrap; }
.hero-status .el-icon { color: var(--ots-growth); }
.hero-status i { width: 1px; height: 11px; margin: 0 2px; background: var(--ots-border-strong); }
.governance-notice { display: flex; align-items: center; gap: 9px; margin-bottom: 16px; padding: 11px 13px; border: 1px solid #dce7ef; border-radius: 9px; background: #f6f9fc; color: #536879; font-size: 12px; }
.governance-notice > .el-icon { color: var(--ots-education); font-size: 17px; }
.governance-notice > span { flex: 1; }
.strategy-overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 11px; margin-bottom: 16px; }
.strategy-overview > button { display: flex; align-items: center; gap: 12px; min-width: 0; padding: 13px 14px; border: 1px solid var(--ots-border); border-radius: 10px; background: #fff; color: inherit; text-align: left; }
.strategy-overview > button { cursor: pointer; transition: border-color .2s, box-shadow .2s, transform .2s; }
.strategy-overview > button:hover { transform: translateY(-1px); border-color: var(--ots-primary-light); box-shadow: var(--ots-shadow-hover); }
.strategy-overview > button.active { border-color: var(--ots-primary); box-shadow: inset 0 -2px var(--ots-primary); }
.overview-icon { display: grid; place-items: center; width: 37px; height: 37px; flex: 0 0 auto; border-radius: 10px; font-size: 18px; }
.overview-icon.catalog { background: var(--ots-primary-soft); color: var(--ots-primary); }
.overview-icon.running { background: var(--ots-success-soft); color: var(--ots-growth); }
.overview-icon.pending { background: var(--ots-warning-soft); color: var(--ots-warning); }
.overview-icon.core { background: var(--ots-danger-soft); color: var(--ots-danger); }
.strategy-overview small,.strategy-overview strong,.strategy-overview p { display: block; }
.strategy-overview small { color: var(--ots-text-secondary); font-size: 10px; }
.strategy-overview strong { margin-top: 2px; color: var(--ots-primary-dark); font-size: 21px; line-height: 1; }
.strategy-overview p { margin: 4px 0 0; overflow: hidden; color: var(--ots-text-secondary); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.workspace { display: grid; grid-template-columns: minmax(270px, 320px) minmax(0, 1fr); gap: 16px; align-items: start; }
.strategy-library { position: sticky; top: 16px; max-height: calc(100vh - 115px); padding: 15px; overflow-y: auto; }
.library-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.library-title span,.library-title strong { display: block; }
.library-title span { color: var(--ots-text-secondary); font-size: 11px; }
.library-title strong { margin-top: 3px; font-size: 16px; }
.library-title .el-icon { color: var(--ots-primary); font-size: 21px; }
.library-filters { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-top: 9px; }
.category-select,.usage-select { width: 100%; }
.list-count { margin: 12px 2px 8px; color: var(--ots-text-secondary); font-size: 11px; }
.strategy-list { display: flex; flex-direction: column; gap: 8px; }
.strategy-item { width: 100%; padding: 11px 12px; border: 1px solid var(--ots-border); border-radius: 9px; background: #fff; color: inherit; text-align: left; cursor: pointer; transition: border-color .2s, background .2s; }
.strategy-item:hover { border-color: var(--ots-primary-light); background: #f8fbfa; }
.strategy-item.active { border-color: var(--ots-primary); background: #eef7f6; box-shadow: inset 3px 0 var(--ots-primary); }
.item-topline,.item-footer { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.item-topline span { color: var(--ots-primary); font-size: 10px; font-weight: 600; }
.item-topline em { font-size: 9px; font-style: normal; }
.runtime-dot { display: inline-flex; align-items: center; gap: 4px; }
.runtime-dot::before { width: 6px; height: 6px; border-radius: 50%; background: currentColor; content: ''; }
.runtime-dot.active { color: var(--ots-growth); }
.runtime-dot.standby { color: var(--ots-education); }
.runtime-dot.pending { color: var(--ots-warning); }
.strategy-item > strong { display: block; margin-top: 6px; font-size: 13px; }
.strategy-item p { display: -webkit-box; margin: 5px 0 9px; overflow: hidden; color: var(--ots-text-secondary); font-size: 10px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.item-footer code { min-width: 0; overflow: hidden; color: #647471; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.item-footer span { flex: 0 0 auto; font-size: 9px; }
.item-footer .default { color: var(--ots-text-secondary); }
.item-footer .custom { color: var(--ots-practice); }
.strategy-editor { min-width: 0; padding: 0; overflow: hidden; }
.editor-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; padding: 20px 22px 18px; border-bottom: 1px solid var(--ots-border); }
.editor-identity { display: flex; gap: 12px; min-width: 0; }
.category-mark { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 11px; background: var(--ots-education-soft); color: var(--ots-education); font-size: 19px; flex: 0 0 auto; }
.title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.title-row h3 { margin: 0; font-size: 19px; }
.editor-identity p { margin: 6px 0; color: var(--ots-text-secondary); font-size: 12px; }
.source-location { color: var(--ots-text-secondary); font-size: 10px; }
.source-location code { color: var(--ots-primary-dark); overflow-wrap: anywhere; }
.header-actions { display: flex; gap: 8px; flex-shrink: 0; }
.runtime-panel { display: grid; grid-template-columns: auto minmax(180px, .8fr) minmax(300px, 1.2fr); align-items: start; gap: 12px; margin: 17px 22px 0; padding: 14px; border: 1px solid; border-radius: 10px; }
.runtime-panel.active { border-color: #cfe5dc; background: #f5faf7; }
.runtime-panel.standby { border-color: #d4e2ee; background: #f5f9fc; }
.runtime-panel.pending { border-color: #eadfc8; background: #fdf9f1; }
.runtime-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; font-size: 17px; }
.runtime-panel.active .runtime-icon { background: var(--ots-success-soft); color: var(--ots-growth); }
.runtime-panel.standby .runtime-icon { background: var(--ots-education-soft); color: var(--ots-education); }
.runtime-panel.pending .runtime-icon { background: var(--ots-warning-soft); color: var(--ots-warning); }
.runtime-copy > div { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.runtime-copy strong { font-size: 13px; }
.runtime-copy p { margin: 6px 0 0; color: var(--ots-text-secondary); font-size: 10px; line-height: 1.55; }
.runtime-panel dl { display: grid; grid-template-columns: 1fr 1fr; gap: 11px; margin: 0; padding-left: 14px; border-left: 1px solid var(--ots-border-strong); }
.runtime-panel dt { margin-bottom: 4px; color: var(--ots-text-secondary); font-size: 9px; }
.runtime-panel dd { margin: 0; font-size: 10px; line-height: 1.5; }
.teaching-context { display: grid; grid-template-columns: repeat(3, 1fr); margin: 0 22px; padding: 16px 0; border-bottom: 1px solid var(--ots-border); }
.teaching-context > div { padding: 0 18px; border-right: 1px solid var(--ots-border); }
.teaching-context > div:first-child { padding-left: 0; }
.teaching-context > div:last-child { border-right: 0; }
.teaching-context span,.teaching-context strong { display: block; }
.teaching-context span { margin-bottom: 5px; color: var(--ots-text-secondary); font-size: 10px; }
.teaching-context strong { font-size: 12px; }
.variable-panel { margin: 17px 22px 0; padding: 12px 14px; border: 1px solid #dce8e5; border-radius: 9px; background: #f7faf9; }
.panel-heading,.panel-heading > div,.field-heading,.field-heading > div { display: flex; justify-content: space-between; align-items: center; gap: 9px; }
.panel-heading > div { justify-content: flex-start; }
.panel-heading .el-icon { color: var(--ots-primary); }
.panel-heading strong,.panel-heading small,.field-heading strong,.field-heading small { display: block; }
.panel-heading strong,.field-heading strong { font-size: 12px; }
.panel-heading small,.field-heading small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; font-weight: 400; }
.variables { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--ots-border-strong); }
.no-variable { display: block; margin-top: 9px; color: var(--ots-text-secondary); font-size: 10px; }
.prompt-fields { padding: 5px 22px 0; }
.field-block { margin-top: 18px; }
.field-heading { margin-bottom: 9px; }
.field-index { display: grid; place-items: center; width: 27px; height: 27px; border-radius: 8px; background: var(--ots-education-soft); color: var(--ots-education); font-size: 11px; font-weight: 700; }
.field-index.practice { background: var(--ots-practice-soft); color: var(--ots-practice); }
:deep(.el-textarea__inner) { font-family: Consolas, 'Microsoft YaHei', monospace; line-height: 1.65; background: #fbfcfc; }
.release-section { display: grid; grid-template-columns: 1fr 310px; gap: 15px; margin: 20px 22px; }
.change-note,.publish-checks { padding: 14px; border: 1px solid var(--ots-border); border-radius: 9px; }
.release-heading { display: flex; align-items: center; gap: 9px; margin-bottom: 11px; }
.release-heading > .el-icon { color: var(--ots-primary); font-size: 17px; }
.release-heading strong,.release-heading span { display: block; }
.release-heading strong { font-size: 12px; }
.release-heading span { margin-top: 2px; color: var(--ots-text-secondary); font-size: 9px; }
.check-item { display: flex; align-items: center; gap: 7px; margin-top: 8px; color: var(--ots-warning); font-size: 10px; }
.check-item.pass { color: var(--ots-growth); }
.editor-footer { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 16px 22px; border-top: 1px solid var(--ots-border); background: #f8faf9; }
.editor-footer > span { display: flex; align-items: center; gap: 7px; font-size: 11px; }
.editor-footer > span i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.editor-footer .changed { color: var(--ots-warning); }
.editor-footer .saved { color: var(--ots-growth); }
.editor-footer > div { display: flex; gap: 8px; }
.history-intro { display: flex; gap: 8px; margin-bottom: 20px; padding: 11px; border-radius: 8px; background: var(--ots-education-soft); color: #486480; font-size: 11px; line-height: 1.5; }
.revision-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.revision-head > div { display: flex; align-items: center; gap: 8px; }
.revision-head span { color: var(--ots-text-secondary); font-size: 11px; }
.revision-label { margin: 10px 0 5px; font-weight: 600; }
pre { max-height: 320px; padding: 12px; overflow: auto; border-radius: 7px; background: #f6f8f7; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }

@media (max-width: 1100px) {
  .strategy-overview { grid-template-columns: 1fr 1fr; }
  .workspace { grid-template-columns: 1fr; }
  .strategy-library { position: static; max-height: 420px; }
  .strategy-list { display: grid; grid-template-columns: 1fr 1fr; }
  .release-section { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .page-hero,.editor-header,.editor-footer { align-items: flex-start; flex-direction: column; }
  .page-hero h2 { font-size: 21px; }
  .hero-status { white-space: normal; }
  .governance-notice .el-tag { display: none; }
  .strategy-list,.teaching-context { grid-template-columns: 1fr; }
  .editor-header,.prompt-fields { padding-right: 16px; padding-left: 16px; }
  .header-actions { width: 100%; flex-wrap: wrap; }
  .teaching-context { margin: 0 16px; }
  .teaching-context > div { padding: 9px 0; border-right: 0; border-bottom: 1px solid var(--ots-border); }
  .teaching-context > div:last-child { border-bottom: 0; }
  .runtime-panel { grid-template-columns: auto 1fr; margin-right: 16px; margin-left: 16px; }
  .runtime-panel dl { grid-column: 1 / -1; padding: 11px 0 0; border-top: 1px solid var(--ots-border-strong); border-left: 0; }
  .variable-panel,.release-section { margin-right: 16px; margin-left: 16px; }
  .editor-footer { padding: 15px 16px; }
  .editor-footer > div { align-self: flex-end; }
}
@media (max-width: 520px) {
  .strategy-overview { grid-template-columns: 1fr; }
  .library-filters,.runtime-panel dl { grid-template-columns: 1fr; }
  .strategy-overview p { white-space: normal; }
}
</style>
