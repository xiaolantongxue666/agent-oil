<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi } from '@/api'
import type { AdminLlmConfigOut } from '@/types'

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ ok: boolean; message: string; elapsed: number } | null>(null)
const config = ref<AdminLlmConfigOut | null>(null)

const form = reactive({
  provider: 'bailian' as 'bailian' | 'mock',
  model: 'qwen-plus',
  base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  api_key: '',
  temperature: 0.2,
  timeout: 60,
  max_retries: 3,
  use_mock: true,
})

const modelOptions = ['qwen-plus', 'qwen-max', 'qwen-turbo', 'qwen-long', 'qwen3-235b-a22b']
const capabilities = [
  { icon: 'ChatLineRound', name: '专业知识问答', note: '基于权威教学资料答疑' },
  { icon: 'Monitor', name: '智能实训引导', note: '情境生成与过程追问' },
  { icon: 'EditPen', name: '题库草稿生成', note: '教师审核后进入教学' },
  { icon: 'TrendCharts', name: '岗位能力分析', note: '支撑专业群课程建设' },
]

const dirty = computed(() => {
  if (!config.value) return false
  const currentUsesMock = config.value.provider === 'mock' || config.value.use_mock
  return (
    form.provider !== (currentUsesMock ? 'mock' : 'bailian')
    || form.model !== config.value.model
    || form.base_url !== config.value.base_url
    || form.temperature !== config.value.temperature
    || form.timeout !== config.value.timeout
    || form.max_retries !== config.value.max_retries
    || form.use_mock !== currentUsesMock
  )
})

const providerName = computed(() => config.value?.provider === 'mock' ? '教学演示服务' : '百炼模型服务')
const runMode = computed(() => (
  config.value?.provider === 'mock' || config.value?.use_mock ? '教学演示模式' : '正式模型服务'
))
const formalModeReady = computed(() => (
  form.provider === 'mock' || Boolean(form.api_key || config.value?.api_key_configured)
))
const temperatureProfile = computed(() => {
  if (form.temperature <= 0.3) return { name: '严谨', note: '适合知识问答、评价与依据约束' }
  if (form.temperature <= 0.7) return { name: '均衡', note: '兼顾稳定表达与适度启发' }
  return { name: '开放', note: '适合情境与教学素材创意草拟' }
})

async function load() {
  loading.value = true
  testResult.value = null
  try {
    const data = await adminApi.llmConfig()
    config.value = data
    const currentUsesMock = data.provider === 'mock' || data.use_mock
    form.provider = currentUsesMock ? 'mock' : 'bailian'
    form.model = data.model
    form.base_url = data.base_url
    form.temperature = data.temperature
    form.timeout = data.timeout
    form.max_retries = data.max_retries
    form.use_mock = currentUsesMock
    form.api_key = ''
  } catch (error: any) {
    ElMessage.error(error?.message || '模型服务配置加载失败')
  } finally {
    loading.value = false
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  const startedAt = performance.now()
  try {
    const result = await adminApi.testLlmConfig()
    const elapsed = Math.round(performance.now() - startedAt)
    testResult.value = result.available
      ? { ok: true, elapsed, message: `服务可用：${result.provider}${result.use_mock ? '（教学演示）' : ''}` }
      : { ok: false, elapsed, message: `连接失败：${result.error || '服务不可用'}` }
  } catch (error: any) {
    testResult.value = {
      ok: false,
      elapsed: Math.round(performance.now() - startedAt),
      message: `测试异常：${error?.message || String(error)}`,
    }
  } finally {
    testing.value = false
  }
}

async function save() {
  if (!formalModeReady.value) {
    ElMessage.warning('启用正式模型服务前，请先配置 API Key')
    return
  }
  await ElMessageBox.confirm(
    '保存后下次模型调用立即生效，无需重启。API Key 当前将以明文保存；审计日志仅记录配置变更，不能保护密钥本身。是否继续？',
    '发布模型服务配置',
    { type: 'warning', confirmButtonText: '保存并发布' },
  )
  saving.value = true
  try {
    const body: Record<string, any> = {
      provider: form.provider,
      model: form.model,
      base_url: form.base_url,
      temperature: form.temperature,
      timeout: form.timeout,
      max_retries: form.max_retries,
      use_mock: form.use_mock,
    }
    if (form.api_key) body.api_key = form.api_key
    const result = await adminApi.updateLlmConfig(body)
    ElMessage.success(result.notice || '模型服务配置已发布')
    form.api_key = ''
    await load()
  } catch (error: any) {
    ElMessage.error(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function setRunMode(value: string | number | boolean | undefined) {
  const provider = value === 'mock' ? 'mock' : 'bailian'
  form.provider = provider
  form.use_mock = provider === 'mock'
}

onMounted(load)
</script>

<template>
  <div class="ots-page llm-page" v-loading="loading">
    <header class="page-hero">
      <div>
        <div class="eyebrow">智能体能力 / 模型服务</div>
        <h2>教学智能体模型服务</h2>
        <p>为专业知识问答、智能实训、题库生成和岗位能力分析提供统一模型能力。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新状态</el-button>
    </header>

    <section v-if="config" class="service-overview ots-card">
      <div class="service-primary">
        <div class="service-icon" :class="{ mock: config.provider === 'mock' || config.use_mock }">
          <el-icon><Connection /></el-icon>
        </div>
        <div>
          <div class="service-state" :class="{ verified: testResult?.ok }">
            <span class="live-dot" />{{ testResult?.ok ? '模型服务验证可用' : '当前配置已加载 · 连通性待验证' }}
          </div>
          <h3>{{ providerName }}</h3>
          <p>{{ config.provider === 'mock' || config.use_mock ? '当前使用教学模拟响应，适合功能演示与流程验证。' : '当前已加载正式模型配置，可通过服务验证确认连接状态。' }}</p>
        </div>
      </div>
      <div class="overview-metrics">
        <div><span>当前模型</span><strong>{{ config.model }}</strong></div>
        <div><span>运行模式</span><strong>{{ runMode }}</strong></div>
        <div><span>配置来源</span><strong>{{ config.has_db_override ? '治理台发布' : '环境默认' }}</strong></div>
        <div><span>最近更新</span><strong>{{ config.last_updated_at ? new Date(config.last_updated_at).toLocaleString() : '使用默认配置' }}</strong></div>
      </div>
    </section>

    <div class="content-grid">
      <section class="configuration ots-card">
        <div class="section-heading">
          <div><span>配置工作区</span><h3>模型能力设置</h3></div>
          <el-tag v-if="dirty || form.api_key" type="warning" effect="plain">有待发布修改</el-tag>
          <el-tag v-else type="success" effect="plain">当前配置已生效</el-tag>
        </div>

        <el-form label-position="top">
          <div class="form-section">
            <div class="form-section-title"><span>01</span><div><strong>服务接入</strong><small>选择承载教学智能体的模型服务与模型版本</small></div></div>
            <div class="two-columns">
              <el-form-item label="模型标识">
                <el-select v-model="form.model" filterable allow-create default-first-option placeholder="选择或输入模型标识">
                  <el-option v-for="model in modelOptions" :key="model" :label="model" :value="model" />
                </el-select>
              </el-form-item>
              <el-form-item label="服务接入地址">
                <el-input v-model="form.base_url" placeholder="https://..." />
              </el-form-item>
            </div>
          </div>

          <div class="form-section">
            <div class="form-section-title"><span>02</span><div><strong>教学生成策略</strong><small>控制回答的稳定程度，具体数值仍可精确调整</small></div></div>
            <div class="strategy-row">
              <button type="button" :class="{ active: form.temperature <= 0.3 }" @click="form.temperature = 0.2"><strong>严谨</strong><span>知识答疑与评价</span></button>
              <button type="button" :class="{ active: form.temperature > 0.3 && form.temperature <= 0.7 }" @click="form.temperature = 0.5"><strong>均衡</strong><span>启发式教学引导</span></button>
              <button type="button" :class="{ active: form.temperature > 0.7 }" @click="form.temperature = 0.9"><strong>开放</strong><span>情境与素材草拟</span></button>
            </div>
            <div class="temperature-control">
              <div><strong>当前策略：{{ temperatureProfile.name }}</strong><span>{{ temperatureProfile.note }}</span></div>
              <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.05" :precision="2" />
            </div>
          </div>

          <div class="form-section compact-section">
            <div class="form-section-title"><span>03</span><div><strong>稳定性设置</strong><small>设置上游等待时间与失败恢复次数</small></div></div>
            <div class="two-columns">
              <el-form-item label="单次响应超时（秒）">
                <el-input-number v-model="form.timeout" :min="1" :max="600" :step="5" />
              </el-form-item>
              <el-form-item label="失败重试次数">
                <el-input-number v-model="form.max_retries" :min="0" :max="10" :step="1" />
              </el-form-item>
            </div>
          </div>

          <div class="form-section">
            <div class="form-section-title"><span>04</span><div><strong>运行模式</strong><small>正式服务与教学演示使用同一入口，切换后不会产生配置冲突</small></div></div>
            <el-radio-group :model-value="form.provider" class="mode-choice" @change="setRunMode">
              <el-radio-button value="bailian">正式模型服务</el-radio-button>
              <el-radio-button value="mock">教学演示模式</el-radio-button>
            </el-radio-group>
            <el-alert v-if="form.provider === 'mock'" title="演示模式使用模拟响应，不代表真实模型生成质量。" type="warning" :closable="false" show-icon />
            <el-alert v-else-if="!formalModeReady" title="尚未配置 API Key，无法发布正式模型服务。" type="error" :closable="false" show-icon />
          </div>
        </el-form>

        <div class="publish-bar">
          <div>
            <strong>发布后立即用于后续教学智能体调用</strong>
            <span>{{ dirty || form.api_key ? '存在未发布修改；服务验证仅检查当前已生效配置。' : '本次操作将写入管理审计记录，无需重启服务。' }}</span>
          </div>
          <div>
            <el-button :loading="testing" @click="testConnection">验证当前服务</el-button>
            <el-button type="primary" :loading="saving" :disabled="(!form.api_key && !dirty) || !formalModeReady" @click="save">保存并发布</el-button>
          </div>
        </div>
      </section>

      <aside class="side-column">
        <section class="ots-card capability-card">
          <div class="side-title"><el-icon><Reading /></el-icon><div><strong>教学能力范围</strong><span>当前模型服务支撑的业务环节</span></div></div>
          <div class="capability-list">
            <div v-for="item in capabilities" :key="item.name">
              <span class="capability-icon"><el-icon><component :is="item.icon" /></el-icon></span>
              <div><strong>{{ item.name }}</strong><small>{{ item.note }}</small></div>
            </div>
          </div>
        </section>

        <section class="ots-card secret-card">
          <div class="side-title"><el-icon><Key /></el-icon><div><strong>密钥与安全</strong><span>高风险配置，请在可信环境操作</span></div></div>
          <div class="key-state">
            <span>API Key</span>
            <el-tag :type="config?.api_key_configured ? 'success' : 'info'" size="small">{{ config?.api_key_configured ? '已配置' : '未配置' }}</el-tag>
          </div>
          <el-input v-model="form.api_key" type="password" show-password placeholder="留空表示不修改现有密钥" />
          <code class="masked-key">{{ config?.api_key_masked }}</code>
          <div class="security-warning"><el-icon><Warning /></el-icon><span>API Key 当前以明文保存；审计仅记录配置变更，不提供密钥保护。</span></div>
        </section>

        <section v-if="testResult" class="test-result" :class="testResult.ok ? 'success' : 'failure'">
          <el-icon><CircleCheckFilled v-if="testResult.ok" /><CircleCloseFilled v-else /></el-icon>
          <div><strong>{{ testResult.ok ? '服务验证通过' : '服务验证失败' }}</strong><span>{{ testResult.message }}</span><small>本次验证耗时 {{ testResult.elapsed }} ms</small></div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.llm-page { max-width: 1500px; margin: 0 auto; }
.page-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin: 2px 0 18px; }
.eyebrow { margin-bottom: 7px; color: var(--ots-primary); font-size: 12px; font-weight: 600; letter-spacing: .8px; }
.page-hero h2 { margin: 0 0 7px; color: var(--ots-primary-dark); font-size: 25px; }
.page-hero p { margin: 0; color: var(--ots-text-secondary); }
.service-overview { display: grid; grid-template-columns: minmax(300px, 1.05fr) minmax(480px, 1.45fr); gap: 28px; padding: 22px 24px; background: linear-gradient(115deg, #f7fcfb, #fff 55%); }
.service-primary { display: flex; align-items: center; gap: 15px; }
.service-icon { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 15px; background: var(--ots-growth-soft); color: var(--ots-growth); font-size: 25px; flex: 0 0 auto; }
.service-icon.mock { background: var(--ots-practice-soft); color: var(--ots-practice); }
.service-state { display: flex; align-items: center; gap: 7px; margin-bottom: 3px; color: var(--ots-education); font-size: 12px; font-weight: 600; }
.service-state.verified { color: var(--ots-growth); }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 4px rgba(47,111,237,.12); }
.service-state.verified .live-dot { box-shadow: 0 0 0 4px rgba(58,141,104,.12); }
.service-primary h3 { margin: 0; font-size: 19px; }
.service-primary p { margin: 5px 0 0; color: var(--ots-text-secondary); font-size: 12px; line-height: 1.5; }
.overview-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-left: 1px solid var(--ots-border); }
.overview-metrics > div { min-width: 0; padding: 4px 17px; border-right: 1px solid var(--ots-border); }
.overview-metrics > div:last-child { border-right: 0; }
.overview-metrics span,.overview-metrics strong { display: block; }
.overview-metrics span { margin-bottom: 7px; color: var(--ots-text-secondary); font-size: 11px; }
.overview-metrics strong { overflow: hidden; color: var(--ots-text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.content-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
.configuration { padding: 0; overflow: hidden; }
.section-heading { display: flex; justify-content: space-between; align-items: center; padding: 20px 22px 16px; border-bottom: 1px solid var(--ots-border); }
.section-heading span { color: var(--ots-text-secondary); font-size: 11px; }
.section-heading h3 { margin: 3px 0 0; font-size: 19px; }
.form-section { padding: 20px 22px; border-bottom: 1px solid var(--ots-border); }
.form-section-title { display: flex; align-items: center; gap: 11px; margin-bottom: 18px; }
.form-section-title > span { display: grid; place-items: center; width: 29px; height: 29px; border-radius: 9px; background: #e9f3f3; color: var(--ots-primary); font-size: 11px; font-weight: 700; }
.form-section-title strong,.form-section-title small { display: block; }
.form-section-title strong { font-size: 15px; }
.form-section-title small { margin-top: 3px; color: var(--ots-text-secondary); font-size: 11px; font-weight: 400; }
.two-columns { display: grid; grid-template-columns: 1fr 1.35fr; gap: 14px; }
.two-columns :deep(.el-select),.two-columns :deep(.el-input-number) { width: 100%; }
.strategy-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.strategy-row button { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border: 1px solid var(--ots-border); border-radius: 9px; background: #fff; color: var(--ots-text); text-align: left; cursor: pointer; }
.strategy-row button span { color: var(--ots-text-secondary); font-size: 11px; }
.strategy-row button:hover { border-color: var(--ots-primary-light); }
.strategy-row button.active { border-color: var(--ots-primary); background: #f0f8f7; box-shadow: inset 3px 0 var(--ots-primary); }
.temperature-control { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-top: 12px; padding: 11px 13px; border-radius: 8px; background: var(--ots-bg-subtle); }
.temperature-control strong,.temperature-control span { display: block; }
.temperature-control strong { font-size: 13px; }
.temperature-control span { margin-top: 3px; color: var(--ots-text-secondary); font-size: 11px; }
.compact-section .two-columns { grid-template-columns: 1fr 1fr; }
.mode-choice { display: flex; margin-bottom: 12px; }
.publish-bar { display: flex; justify-content: space-between; align-items: center; gap: 20px; padding: 17px 22px; background: #f8faf9; }
.publish-bar strong,.publish-bar span { display: block; }
.publish-bar strong { font-size: 13px; }
.publish-bar span { margin-top: 3px; color: var(--ots-text-secondary); font-size: 11px; }
.publish-bar > div:last-child { display: flex; gap: 9px; flex-shrink: 0; }
.side-column { position: sticky; top: 16px; }
.side-title { display: flex; align-items: center; gap: 10px; padding-bottom: 13px; border-bottom: 1px solid var(--ots-border); }
.side-title > .el-icon { color: var(--ots-primary); font-size: 20px; }
.side-title strong,.side-title span { display: block; }
.side-title strong { font-size: 15px; }
.side-title span { margin-top: 2px; color: var(--ots-text-secondary); font-size: 10px; }
.capability-list > div { display: flex; align-items: center; gap: 10px; padding: 12px 0; border-bottom: 1px dashed var(--ots-border); }
.capability-list > div:last-child { border-bottom: 0; padding-bottom: 0; }
.capability-icon { display: grid; place-items: center; width: 33px; height: 33px; border-radius: 9px; background: var(--ots-education-soft); color: var(--ots-education); }
.capability-list strong,.capability-list small { display: block; }
.capability-list strong { font-size: 13px; }
.capability-list small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 10px; }
.key-state { display: flex; justify-content: space-between; align-items: center; margin: 14px 0 8px; font-size: 12px; }
.masked-key { display: block; margin-top: 8px; color: var(--ots-text-secondary); font-size: 11px; overflow-wrap: anywhere; }
.security-warning { display: flex; align-items: flex-start; gap: 7px; margin-top: 13px; padding: 9px 10px; border-radius: 7px; background: var(--ots-practice-soft); color: #805817; font-size: 11px; line-height: 1.5; }
.security-warning .el-icon { margin-top: 2px; flex: 0 0 auto; }
.test-result { display: flex; gap: 10px; padding: 14px; border: 1px solid; border-radius: var(--ots-radius); }
.test-result.success { border-color: #cce6d7; background: var(--ots-growth-soft); color: #2f7455; }
.test-result.failure { border-color: #efd6c7; background: #fff4ed; color: #a34b2e; }
.test-result > .el-icon { margin-top: 2px; font-size: 19px; }
.test-result strong,.test-result span,.test-result small { display: block; }
.test-result span { margin-top: 4px; font-size: 11px; line-height: 1.5; }
.test-result small { margin-top: 5px; opacity: .72; }

@media (max-width: 1250px) {
  .service-overview { grid-template-columns: 1fr; }
  .overview-metrics { border-left: 0; border-top: 1px solid var(--ots-border); padding-top: 15px; }
}
@media (max-width: 1100px) {
  .content-grid { grid-template-columns: 1fr; }
  .side-column { position: static; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .side-column .ots-card { margin-bottom: 0; }
  .test-result { grid-column: 1 / -1; }
}
@media (max-width: 768px) {
  .page-hero { align-items: flex-start; flex-direction: column; }
  .page-hero h2 { font-size: 21px; }
  .page-hero > .el-button { flex-shrink: 0; }
  .service-overview { padding: 17px; }
  .overview-metrics { grid-template-columns: 1fr 1fr; gap: 14px 0; }
  .overview-metrics > div:nth-child(2) { border-right: 0; }
  .two-columns,.compact-section .two-columns,.strategy-row,.side-column { grid-template-columns: 1fr; }
  .form-section { padding: 18px 16px; }
  .temperature-control,.publish-bar { align-items: stretch; flex-direction: column; }
  .publish-bar > div:last-child { justify-content: flex-end; }
}
</style>
