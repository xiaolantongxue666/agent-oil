<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock, Search } from '@element-plus/icons-vue'
import { adminApi, type PromptRevisionOut, type PromptTemplateOut } from '@/api'

const loading = ref(true)
const saving = ref(false)
const prompts = ref<PromptTemplateOut[]>([])
const selectedCode = ref('')
const activeModule = ref('')
const editorOpen = ref(false)
const usageFilter = ref<'全部' | '生产使用' | '预留未接入'>('全部')
const keyword = ref('')
const systemPrompt = ref('')
const userPrompt = ref('')
const changeNote = ref('')
const revisions = ref<PromptRevisionOut[]>([])
const historyVisible = ref(false)
const historyLoading = ref(false)

type RuntimeState = 'active' | 'standby' | 'pending'
type ManagementLevel = 'core' | 'teaching' | 'domain' | 'reserved' | 'custom'

// 运行状态由后端代码定义层审查落档并通过 API 下发，前端只负责呈现
const levelLabels: Record<ManagementLevel, string> = {
  core: '系统核心',
  teaching: '教学应用',
  domain: '专业群建设',
  reserved: '预留策略',
  custom: '自定义策略',
}

const runtimeLabels: Record<RuntimeState, string> = {
  active: '生产使用',
  standby: '后备机制',
  pending: '预留未接入',
}

interface StrategyGovernance {
  runtime: RuntimeState
  conditional: boolean
  trigger: string
  runtimeNote: string
  level: ManagementLevel
  levelLabel: string
}

function governanceOf(item: PromptTemplateOut | null | undefined): StrategyGovernance {
  const runtime = (item?.runtime_status || 'pending') as RuntimeState
  const level = (item?.level || (item?.is_custom ? 'custom' : 'reserved')) as ManagementLevel
  return {
    runtime,
    conditional: Boolean(item?.runtime_conditional),
    trigger: item?.runtime_trigger || '尚未登记',
    runtimeNote: item?.runtime_note || '该策略尚未登记运行审查结论。',
    level,
    levelLabel: levelLabels[level],
  }
}

const categoryContexts: Record<string, { stage: string; audience: string; impact: string }> = {
  知识问答: { stage: '课前预习与课后答疑', audience: '学生 / 教师', impact: '专业知识问答' },
  智能实训: { stage: '课堂实训与技能训练', audience: '学生', impact: '情境、引导与过程反馈' },
  教学评价: { stage: '学习评价与能力诊断', audience: '学生 / 教师', impact: '开放作答评价' },
  题库生成: { stage: '教师备课与资源建设', audience: '教师', impact: '题库草稿生成' },
  岗位图谱: { stage: '专业群与课程体系建设', audience: '专业负责人 / 教师', impact: '岗位能力分析' },
  岗位采集: { stage: '官方招聘数据采集', audience: '系统管理员 / 教师', impact: 'AI 浏览器采集决策与抽取' },
  模型基础设施: { stage: '模型输出质量保障', audience: '系统管理员', impact: '结构化输出稳定性' },
}

// 模块（= 提示词分类）卡片数据：关键字与使用状态过滤作用在模块内的策略上
const moduleSummaries = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  const order: string[] = []
  const byCategory = new Map<string, PromptTemplateOut[]>()
  for (const item of prompts.value) {
    if (!byCategory.has(item.category)) {
      byCategory.set(item.category, [])
      order.push(item.category)
    }
    byCategory.get(item.category)!.push(item)
  }
  const matchesUsage = (governance: StrategyGovernance) => (
    usageFilter.value === '全部'
    || (usageFilter.value === '生产使用' && governance.runtime === 'active')
    || (usageFilter.value === '预留未接入' && governance.runtime === 'pending')
  )
  return order
    .map((category) => {
      const items = byCategory.get(category)!
      const visible = items.filter((item) => {
        const governance = governanceOf(item)
        if (!matchesUsage(governance)) return false
        if (!query) return true
        return [item.name, item.code, item.description, item.source_location, governance.trigger]
          .some((value) => value.toLowerCase().includes(query))
      })
      const runtimeOf = (item: PromptTemplateOut) => governanceOf(item).runtime
      return {
        category,
        items,
        visibleCount: visible.length,
        totalCount: items.length,
        activeCount: items.filter((item) => runtimeOf(item) === 'active').length,
        pendingCount: items.filter((item) => runtimeOf(item) === 'pending').length,
        customCount: items.filter((item) => item.is_custom).length,
        context: categoryContexts[category] || null,
      }
    })
    .filter((module) => module.visibleCount > 0)
})

// 每个模块的专属图标与配色（自定义分类使用中性兜底样式）
const moduleVisuals: Record<string, { icon: string; cls: string }> = {
  知识问答: { icon: 'ChatLineRound', cls: 'education' },
  智能实训: { icon: 'Monitor', cls: 'practice' },
  教学评价: { icon: 'Star', cls: 'growth' },
  题库生成: { icon: 'EditPen', cls: 'creation' },
  岗位图谱: { icon: 'TrendCharts', cls: 'graph' },
  岗位采集: { icon: 'Connection', cls: 'collect' },
  模型基础设施: { icon: 'Cpu', cls: 'infra' },
}
const defaultVisual = { icon: 'Collection', cls: 'generic' }
function visualOf(category: string) {
  return moduleVisuals[category] || defaultVisual
}

function ratioWidth(count: number, total: number) {
  if (!total) return '0%'
  return `${Math.max((count / total) * 100, count ? 6 : 0)}%`
}

// 当前打开模块内的策略卡片
const modulePrompts = computed(() => (
  prompts.value.filter((item) => item.category === activeModule.value)
))

const activeCount = computed(() => prompts.value.filter((item) => governanceOf(item).runtime === 'active').length)
const pendingCount = computed(() => prompts.value.filter((item) => governanceOf(item).runtime === 'pending').length)
const coreCount = computed(() => prompts.value.filter((item) => governanceOf(item).level === 'core').length)

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

function openModule(category: string) {
  activeModule.value = category
  editorOpen.value = false
  selectedCode.value = ''
}

function backToModules() {
  activeModule.value = ''
  editorOpen.value = false
  selectedCode.value = ''
}

function openEditor(item: PromptTemplateOut) {
  selectPrompt(item)
  editorOpen.value = true
}

function closeEditor() {
  editorOpen.value = false
  selectedCode.value = ''
}

async function loadPrompts(preferredCode = '') {
  loading.value = true
  try {
    const result = await adminApi.prompts()
    prompts.value = result.items
    const next = preferredCode
      ? prompts.value.find((item) => item.code === preferredCode)
      : prompts.value.find((item) => item.code === selectedCode.value)
    if (next) selectPrompt(next)
    else {
      selectedCode.value = ''
      systemPrompt.value = ''
      userPrompt.value = ''
      changeNote.value = ''
    }
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
    : '该策略为预留策略：代码链路已保留，当前业务未调用；保存只形成新版本，不会影响现有学生或教师流程。'
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
    const savedState = '已保存为预留版本'
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
      : '已恢复默认版本，保持预留状态'
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

const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  code: '',
  name: '',
  category: '',
  description: '',
  variables: '',
  system_prompt: '',
  user_prompt_template: '',
})

function openCreate() {
  createForm.code = ''
  createForm.name = ''
  createForm.category = activeModule.value || ''
  createForm.description = ''
  createForm.variables = ''
  createForm.system_prompt = ''
  createForm.user_prompt_template = ''
  createVisible.value = true
}

const createCategoryOptions = computed(() => (
  Array.from(new Set([...Object.keys(categoryContexts), ...prompts.value.map((item) => item.category)]))
))

async function submitCreate() {
  if (!createForm.code.trim() || !createForm.name.trim() || !createForm.category.trim()) {
    ElMessage.warning('编号、名称和所属模块为必填项')
    return
  }
  if (!createForm.system_prompt.trim() || !createForm.user_prompt_template.trim()) {
    ElMessage.warning('系统提示词与任务模板均不能为空')
    return
  }
  creating.value = true
  try {
    const created = await adminApi.createPrompt({
      code: createForm.code.trim(),
      name: createForm.name.trim(),
      category: createForm.category.trim(),
      description: createForm.description.trim(),
      system_prompt: createForm.system_prompt,
      user_prompt_template: createForm.user_prompt_template,
      variables: createForm.variables.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean),
    })
    createVisible.value = false
    await loadPrompts(created.code)
    activeModule.value = created.category
    selectPrompt(created)
    editorOpen.value = true
    ElMessage.success(`已创建自定义策略 ${created.name}；接入业务代码前保存的版本不会自动生效`)
  } catch (error: any) {
    ElMessage.error(error?.message || '自定义策略创建失败')
  } finally {
    creating.value = false
  }
}

async function deletePrompt() {
  if (!selected.value?.deletable) return
  try {
    await ElMessageBox.confirm(
      `将删除自定义策略「${selected.value.name}」及其全部版本历史，不可恢复。是否继续？`,
      '删除自定义教学策略',
      { type: 'warning', confirmButtonText: '确认删除' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    await adminApi.deletePrompt(selected.value.code)
    ElMessage.success('自定义策略已删除')
    editorOpen.value = false
    selectedCode.value = ''
    await loadPrompts()
  } catch (error: any) {
    ElMessage.error(error?.message || '删除失败')
  } finally {
    saving.value = false
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
      <span>运行状态由后端代码审查落档：生产使用 = 当前业务真实触发；预留未接入 = 代码链路保留但当前无调用入口。规则评分、安全守卫与教师审核始终由代码层强制执行。</span>
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
      <button type="button" :class="{ active: usageFilter === '预留未接入' }" :aria-pressed="usageFilter === '预留未接入'" @click="usageFilter = '预留未接入'">
        <span class="overview-icon pending"><el-icon><Clock /></el-icon></span>
        <div><small>预留未接入</small><strong>{{ pendingCount }}</strong><p>代码保留但当前业务未调用</p></div>
      </button>
    </section>

    <!-- 一级：教学模块卡片（点击进入，不直接展示策略内容） -->
    <template v-if="!activeModule">
      <div class="module-toolbar">
        <el-input v-model="keyword" clearable :prefix-icon="Search" class="module-search" placeholder="搜索策略名称、编号或调用位置" />
        <el-button type="primary" plain @click="openCreate">新增自定义策略</el-button>
      </div>
      <div class="module-grid">
        <button
          v-for="module in moduleSummaries"
          :key="module.category"
          type="button"
          class="module-card"
          :class="visualOf(module.category).cls"
          @click="openModule(module.category)"
        >
          <header class="module-head">
            <span class="module-icon"><el-icon><component :is="visualOf(module.category).icon" /></el-icon></span>
            <div class="module-titles">
              <strong>{{ module.category }}</strong>
              <small v-if="module.context">{{ module.context.stage }}</small>
            </div>
            <em class="module-count">{{ module.totalCount }}<small>项策略</small></em>
          </header>
          <p class="module-desc">{{ module.context ? `${module.context.audience} · ${module.context.impact}` : '自定义模块，策略说明待补充' }}</p>
          <div class="ratio-bar" :class="visualOf(module.category).cls">
            <span class="seg active" :style="{ width: ratioWidth(module.activeCount, module.totalCount) }" />
            <span class="seg pending" :style="{ width: ratioWidth(module.pendingCount, module.totalCount) }" />
          </div>
          <footer class="module-stats">
            <span class="stat active">{{ module.activeCount }} 生产使用</span>
            <span v-if="module.pendingCount" class="stat pending">{{ module.pendingCount }} 预留</span>
            <span v-if="module.customCount" class="stat custom">{{ module.customCount }} 自定义</span>
          </footer>
          <span class="module-enter">进入模块<el-icon><ArrowRight /></el-icon></span>
        </button>
        <el-empty v-if="!moduleSummaries.length" description="没有匹配的教学模块" :image-size="80" />
      </div>
    </template>

    <!-- 二级：模块内策略列表 → 点击进入编辑器 -->
    <template v-else>
      <section class="module-hero" :class="visualOf(activeModule).cls">
        <div class="hero-left">
          <el-button text class="back-btn" @click="backToModules"><el-icon><ArrowLeft /></el-icon>模块列表</el-button>
          <span class="module-icon"><el-icon><component :is="visualOf(activeModule).icon" /></el-icon></span>
          <div class="hero-titles">
            <strong>{{ activeModule }}</strong>
            <p v-if="categoryContexts[activeModule]">
              {{ categoryContexts[activeModule].stage }} · 适用 {{ categoryContexts[activeModule].audience }} · 影响 {{ categoryContexts[activeModule].impact }}
            </p>
          </div>
        </div>
        <div class="hero-meta">
          <div class="hero-chip"><span>策略总数</span><strong>{{ modulePrompts.length }}</strong></div>
          <div class="hero-chip"><span>生产使用</span><strong>{{ moduleSummaries.find(m => m.category === activeModule)?.activeCount || 0 }}</strong></div>
          <div class="hero-chip"><span>自定义</span><strong>{{ modulePrompts.filter(i => i.is_custom).length }}</strong></div>
          <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新增策略</el-button>
        </div>
      </section>

      <div v-if="!editorOpen" class="prompt-grid">
        <button
          v-for="item in modulePrompts"
          :key="item.code"
          type="button"
          class="prompt-card"
          @click="openEditor(item)"
        >
          <div class="item-topline">
            <code>{{ item.code }}</code>
            <em class="runtime-dot" :class="governanceOf(item).runtime">
              {{ governanceOf(item).runtime === 'active' ? (governanceOf(item).conditional ? '生产使用·条件触发' : '生产使用') : '预留未接入' }}
            </em>
          </div>
          <strong>{{ item.name }}</strong>
          <p>{{ item.description || '暂无描述' }}</p>
          <div class="item-footer">
            <span :class="item.is_default ? 'default' : 'custom'">v{{ item.version }} · {{ item.is_default ? '系统默认' : item.is_custom ? '自定义' : '自定义启用中' }}</span>
            <em>查看与编辑<el-icon><ArrowRight /></el-icon></em>
          </div>
        </button>
        <el-empty v-if="!modulePrompts.length" description="该模块暂无策略" :image-size="70" />
      </div>

      <main v-if="selected && editorOpen" class="strategy-editor ots-card">
        <div class="editor-header">
          <div class="editor-identity">
            <div class="category-mark"><el-icon><Reading /></el-icon></div>
            <div>
              <div class="title-row">
                <h3>{{ selected.name }}</h3>
                <el-tag effect="plain">v{{ selected.version }}</el-tag>
                <el-tag :type="selected.is_default ? 'info' : 'warning'">{{ selected.is_default ? '系统默认' : '自定义启用中' }}</el-tag>
                <el-tag :type="selectedGovernance.runtime === 'active' ? 'success' : 'info'" effect="dark">
                  {{ selectedGovernance.runtime === 'active' ? (selectedGovernance.conditional ? '生产使用 · 条件触发' : '生产使用') : '预留未接入' }}
                </el-tag>
              </div>
              <p>{{ selected.description }}</p>
              <span class="source-location">代码定位：<code>{{ selected.source_location }}</code></span>
            </div>
          </div>
          <div class="header-actions">
            <el-button @click="closeEditor"><el-icon><ArrowLeft /></el-icon>返回策略列表</el-button>
            <el-button :icon="Clock" @click="showHistory">版本历史</el-button>
            <el-button :disabled="selected.is_default || selected.is_custom" @click="restoreDefault">恢复默认</el-button>
            <el-button v-if="selected.deletable" type="danger" plain @click="deletePrompt">删除</el-button>
          </div>
        </div>

        <section class="runtime-panel" :class="selectedGovernance.runtime">
          <span class="runtime-icon"><el-icon><VideoPlay v-if="selectedGovernance.runtime === 'active'" /><Clock v-else /></el-icon></span>
          <div class="runtime-copy">
            <div>
              <strong>{{ selectedGovernance.runtime === 'active' ? '已接入当前生产链路' : '预留策略：代码链路保留，当前业务未调用' }}</strong>
              <el-tag size="small" effect="plain" :type="selectedGovernance.level === 'core' ? 'danger' : selectedGovernance.level === 'reserved' ? 'info' : 'success'">
                {{ selectedGovernance.levelLabel }}
              </el-tag>
            </div>
            <p>{{ selectedGovernance.runtimeNote }}</p>
          </div>
          <dl>
            <div><dt>真实触发位置</dt><dd>{{ selectedGovernance.trigger }}</dd></div>
            <div><dt>审查等级</dt><dd>{{ selectedGovernance.levelLabel }}</dd></div>
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
            <div class="release-heading"><el-icon><Checked /></el-icon><div><strong>保存前检查</strong><span>{{ selectedGovernance.runtime === 'active' ? '保存后影响下一次匹配调用' : '保存新版本，暂不影响当前业务' }}</span></div></div>
            <div v-for="item in publishChecks" :key="item.label" class="check-item" :class="{ pass: item.pass }">
              <el-icon><CircleCheckFilled v-if="item.pass" /><WarningFilled v-else /></el-icon><span>{{ item.label }}</span>
            </div>
          </div>
        </section>

        <footer class="editor-footer">
          <span :class="dirty ? 'changed' : 'saved'"><i />{{ dirty ? '有尚未保存的教学策略修改' : selectedGovernance.runtime === 'active' ? '当前版本已在生产链路使用' : '当前版本已保存，保持预留状态' }}</span>
          <div>
            <el-button :disabled="!dirty" @click="resetEditor">撤销修改</el-button>
            <el-button type="primary" :loading="saving" :disabled="!dirty" @click="savePrompt">
              {{ selectedGovernance.runtime === 'active' ? '保存并启用' : '保存预留版本' }}
            </el-button>
          </div>
        </footer>
      </main>
    </template>

    <el-dialog v-model="createVisible" title="新增自定义教学策略" width="min(720px, 94vw)" top="6vh">
      <div class="create-intro">
        <el-icon><Guide /></el-icon>
        <span>自定义策略用于沉淀教学策略素材；创建后可在工坊中继续编辑和版本管理，接入业务代码前不会影响任何运行流程。</span>
      </div>
      <el-form label-position="top">
        <div class="create-grid">
          <el-form-item label="策略编号（小写字母/数字/下划线）" required>
            <el-input v-model="createForm.code" placeholder="例如 my_qa_style" maxlength="64" />
          </el-form-item>
          <el-form-item label="策略名称" required>
            <el-input v-model="createForm.name" placeholder="例如 专业问答语气优化" maxlength="128" />
          </el-form-item>
        </div>
        <div class="create-grid">
          <el-form-item label="所属模块" required>
            <el-select v-model="createForm.category" filterable allow-create default-first-option placeholder="选择或输入模块名称">
              <el-option v-for="item in createCategoryOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
          <el-form-item label="运行时变量（逗号分隔，模板中以 {{ '{{变量名}}' }} 使用）">
            <el-input v-model="createForm.variables" placeholder="例如 position_name, evidence" />
          </el-form-item>
        </div>
        <el-form-item label="策略说明">
          <el-input v-model="createForm.description" maxlength="500" placeholder="说明该策略的用途与边界" />
        </el-form-item>
        <el-form-item label="系统提示词（System Prompt）" required>
          <el-input v-model="createForm.system_prompt" type="textarea" :rows="6" spellcheck="false" />
        </el-form-item>
        <el-form-item label="用户提示词模板（User Prompt）" required>
          <el-input v-model="createForm.user_prompt_template" type="textarea" :rows="8" spellcheck="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建策略</el-button>
      </template>
    </el-dialog>

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
.module-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 14px; margin-bottom: 18px; }
.module-search { max-width: 400px; }
.module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.module-card { position: relative; display: flex; flex-direction: column; gap: 10px; overflow: hidden; padding: 20px 20px 16px; border: 1px solid var(--ots-border); border-radius: 14px; background: linear-gradient(160deg, #fff 55%, var(--module-tint, #f7fbfa)); color: inherit; text-align: left; cursor: pointer; transition: transform .22s, box-shadow .22s, border-color .22s; }
.module-card::before { content: ''; position: absolute; inset: 0 0 auto; height: 3px; background: var(--module-accent, var(--ots-primary)); opacity: .85; }
.module-card:hover { transform: translateY(-3px); border-color: var(--module-accent, var(--ots-primary-light)); box-shadow: 0 14px 30px -18px var(--module-accent, rgba(15,94,104,.55)); }
.module-card:hover .module-icon { transform: scale(1.06) rotate(-3deg); }
.module-head { display: flex; align-items: center; gap: 12px; }
.module-icon { display: grid; place-items: center; width: 44px; height: 44px; flex: 0 0 auto; border-radius: 12px; background: var(--module-icon-bg, var(--ots-education-soft)); color: var(--module-accent, var(--ots-education)); font-size: 21px; transition: transform .22s; }
.module-titles { min-width: 0; flex: 1; }
.module-titles strong { display: block; color: var(--ots-primary-dark); font-size: 16px; letter-spacing: .3px; }
.module-titles small { display: block; margin-top: 3px; color: var(--ots-text-secondary); font-size: 10px; }
.module-count { flex: 0 0 auto; display: flex; align-items: baseline; gap: 3px; color: var(--module-accent, var(--ots-primary)); font-size: 24px; font-style: normal; font-weight: 700; line-height: 1; }
.module-count small { color: var(--ots-text-secondary); font-size: 10px; font-weight: 400; }
.module-desc { margin: 0; color: var(--ots-text-secondary); font-size: 11px; line-height: 1.6; }
.ratio-bar { display: flex; height: 6px; overflow: hidden; border-radius: 999px; background: var(--ots-bg-subtle); }
.ratio-bar .seg { height: 100%; transition: width .3s; }
.ratio-bar .seg.active { background: var(--module-accent, var(--ots-growth)); }
.ratio-bar .seg.standby { background: #9db8cf; }
.ratio-bar .seg.pending { background: #e3c88f; }
.module-stats { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.module-stats .stat { padding: 3px 10px; border-radius: 999px; font-size: 10px; background: #f2f7f6; color: #5a7471; }
.module-stats .stat.active { background: color-mix(in srgb, var(--module-accent, #3a8d68) 12%, #fff); color: var(--module-accent, var(--ots-growth)); font-weight: 600; }
.module-stats .stat.standby { background: #eef4f9; color: #48708f; }
.module-stats .stat.pending { background: #faf3e4; color: #9a7a2f; }
.module-stats .stat.custom { background: var(--ots-practice-soft); color: var(--ots-practice); }
.module-enter { display: inline-flex; align-items: center; gap: 5px; align-self: flex-end; color: var(--module-accent, var(--ots-primary)); font-size: 11px; font-weight: 600; }
.module-enter .el-icon { transition: transform .22s; }
.module-card:hover .module-enter .el-icon { transform: translateX(3px); }
/* 七套模块配色 */
.module-card.education { --module-accent: #3576c0; --module-icon-bg: #e8f1fb; --module-tint: #f7fafd; }
.module-card.practice { --module-accent: #c07b35; --module-icon-bg: #fbf1e6; --module-tint: #fdf9f4; }
.module-card.growth { --module-accent: #3a8d68; --module-icon-bg: #e7f5ee; --module-tint: #f5fbf8; }
.module-card.creation { --module-accent: #8355c8; --module-icon-bg: #f1ebfb; --module-tint: #faf8fd; }
.module-card.graph { --module-accent: #158f8f; --module-icon-bg: #e4f4f4; --module-tint: #f4fbfb; }
.module-card.collect { --module-accent: #2f8ea3; --module-icon-bg: #e5f3f6; --module-tint: #f4fafc; }
.module-card.infra { --module-accent: #5f6f86; --module-icon-bg: #eceff4; --module-tint: #f8f9fb; }
.module-card.generic { --module-accent: #6a8f7d; --module-icon-bg: #ecf3ef; --module-tint: #f7fbf9; }
/* 二级：模块详情面板头 */
.module-hero { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; padding: 16px 20px; border: 1px solid var(--ots-border); border-radius: 14px; background: linear-gradient(120deg, var(--module-tint, #f7fbfa), #fff 60%); }
.module-hero .back-btn { margin-right: 2px; }
.module-hero .module-icon { width: 46px; height: 46px; font-size: 23px; }
.hero-left { display: flex; align-items: center; gap: 13px; min-width: 0; }
.hero-titles strong { display: block; color: var(--ots-primary-dark); font-size: 19px; }
.hero-titles p { margin: 4px 0 0; color: var(--ots-text-secondary); font-size: 11px; }
.hero-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.hero-chip { min-width: 74px; padding: 7px 13px; border: 1px solid var(--ots-border); border-radius: 10px; background: #fff; text-align: center; }
.hero-chip span { display: block; color: var(--ots-text-secondary); font-size: 9px; }
.hero-chip strong { display: block; margin-top: 2px; color: var(--ots-primary-dark); font-size: 16px; }
/* 策略卡片 */
.prompt-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 14px; }
.prompt-card { position: relative; display: flex; flex-direction: column; gap: 8px; overflow: hidden; padding: 16px 17px; border: 1px solid var(--ots-border); border-radius: 12px; background: #fff; color: inherit; text-align: left; cursor: pointer; transition: transform .2s, box-shadow .2s, border-color .2s; }
.prompt-card::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--ots-border-strong); opacity: 0; transition: opacity .2s; }
.prompt-card:hover { transform: translateY(-2px); border-color: var(--ots-primary-light); box-shadow: 0 12px 26px -18px rgba(15,94,104,.5); }
.prompt-card:hover::before { opacity: 1; background: var(--ots-primary); }
.prompt-card > strong { font-size: 13.5px; }
.prompt-card p { display: -webkit-box; margin: 0; overflow: hidden; color: var(--ots-text-secondary); font-size: 10.5px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.prompt-card .item-footer em { display: inline-flex; align-items: center; gap: 3px; color: var(--ots-primary); font-size: 10px; font-style: normal; font-weight: 600; }
.prompt-card:hover .item-footer em .el-icon { transform: translateX(2px); }
.create-intro { display: flex; gap: 8px; margin-bottom: 14px; padding: 10px 12px; border-radius: 8px; background: var(--ots-education-soft); color: #486480; font-size: 11px; line-height: 1.55; }
.create-intro .el-icon { margin-top: 2px; flex: 0 0 auto; }
.create-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
@media (max-width: 768px) { .create-grid { grid-template-columns: 1fr; } }
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
  .prompt-grid, .module-grid { grid-template-columns: 1fr 1fr; }
  .release-section { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .page-hero,.editor-header,.editor-footer { align-items: flex-start; flex-direction: column; }
  .page-hero h2 { font-size: 21px; }
  .hero-status { white-space: normal; }
  .governance-notice .el-tag { display: none; }
  .prompt-grid,.module-grid,.teaching-context { grid-template-columns: 1fr; }
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
  .runtime-panel dl { grid-template-columns: 1fr; }
  .strategy-overview p { white-space: normal; }
}
</style>
