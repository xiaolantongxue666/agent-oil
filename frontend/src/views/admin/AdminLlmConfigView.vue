<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi } from '@/api'
import type { AdminModelConfigOut } from '@/types'

type TestState = { ok: boolean; message: string; elapsed: number } | null

const loading = ref(true)
const saving = ref<Record<string, boolean>>({})
const testing = ref<Record<string, boolean>>({})
const testResults = ref<Record<string, TestState>>({})
const config = ref<AdminModelConfigOut | null>(null)

const chatForm = reactive({
  provider: 'bailian' as 'bailian' | 'mock',
  model: 'qwen-plus',
  base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  api_key: '',
  temperature: 0.2,
  timeout: 60,
  max_retries: 3,
  use_mock: true,
})

const embeddingForm = reactive({ backend: 'api' as 'api' | 'local', model: 'BAAI/bge-m3', base_url: '', api_key: '' })
const rerankerForm = reactive({ backend: 'api' as 'api' | 'local', model: 'BAAI/bge-reranker-base', base_url: '', api_key: '' })

const modelOptions = ['qwen-plus', 'qwen-max', 'qwen-turbo', 'qwen-long', 'qwen3-235b-a22b']
const embeddingModelOptions = ['BAAI/bge-m3', 'text-embedding-v3', 'text-embedding-v4']
const rerankerModelOptions = ['BAAI/bge-reranker-base', 'BAAI/bge-reranker-v2-m3', 'gte-rerank-v2']

const capabilities = [
  { icon: 'ChatLineRound', name: '专业知识问答', note: '基于权威教学资料答疑', service: 'chat' },
  { icon: 'Reading', name: '检索增强', note: '知识库向量召回', service: 'embedding' },
  { icon: 'Sort', name: '检索重排', note: '提升引用片段相关性', service: 'reranker' },
  { icon: 'EditPen', name: '题库草稿生成', note: '教师审核后进入教学', service: 'chat' },
  { icon: 'TrendCharts', name: '岗位能力分析', note: '支撑专业群课程建设', service: 'chat' },
]

const chatDirty = computed(() => {
  if (!config.value) return false
  const current = config.value.chat
  const currentUsesMock = current.provider === 'mock' || current.use_mock
  return (
    chatForm.provider !== (currentUsesMock ? 'mock' : 'bailian')
    || chatForm.model !== current.model
    || chatForm.base_url !== current.base_url
    || chatForm.temperature !== current.temperature
    || chatForm.timeout !== current.timeout
    || chatForm.max_retries !== current.max_retries
    || chatForm.use_mock !== currentUsesMock
  )
})
const chatFormalReady = computed(() => (
  chatForm.provider === 'mock' || Boolean(chatForm.api_key || config.value?.chat.api_key_configured)
))
const temperatureProfile = computed(() => {
  if (chatForm.temperature <= 0.3) return { name: '严谨', note: '适合知识问答、评价与依据约束' }
  if (chatForm.temperature <= 0.7) return { name: '均衡', note: '兼顾稳定表达与适度启发' }
  return { name: '开放', note: '适合情境与教学素材创意草拟' }
})

function ragDirty(service: 'embedding' | 'reranker') {
  if (!config.value) return false
  const current = config.value[service]
  const form = service === 'embedding' ? embeddingForm : rerankerForm
  return (
    form.backend !== current.backend
    || form.model !== current.model
    || (form.base_url || '') !== (current.base_url || '')
    || Boolean(form.api_key)
  )
}

function ragReady(service: 'embedding' | 'reranker') {
  const form = service === 'embedding' ? embeddingForm : rerankerForm
  if (form.backend === 'local') return true
  return Boolean(form.api_key || config.value?.[service].api_key_configured)
}

function setRunMode(value: string | number | boolean | undefined) {
  const provider = value === 'mock' ? 'mock' : 'bailian'
  chatForm.provider = provider
  chatForm.use_mock = provider === 'mock'
}

async function load() {
  loading.value = true
  testResults.value = {}
  try {
    const data = await adminApi.modelConfig()
    config.value = data
    const chat = data.chat
    const currentUsesMock = chat.provider === 'mock' || chat.use_mock
    chatForm.provider = currentUsesMock ? 'mock' : 'bailian'
    chatForm.model = chat.model
    chatForm.base_url = chat.base_url
    chatForm.temperature = chat.temperature
    chatForm.timeout = chat.timeout
    chatForm.max_retries = chat.max_retries
    chatForm.use_mock = currentUsesMock
    chatForm.api_key = ''
    embeddingForm.backend = (data.embedding.backend === 'api' ? 'api' : 'local') as 'api' | 'local'
    embeddingForm.model = data.embedding.model
    embeddingForm.base_url = data.embedding.base_url || ''
    embeddingForm.api_key = ''
    rerankerForm.backend = (data.reranker.backend === 'api' ? 'api' : 'local') as 'api' | 'local'
    rerankerForm.model = data.reranker.model
    rerankerForm.base_url = data.reranker.base_url || ''
    rerankerForm.api_key = ''
  } catch (error: any) {
    ElMessage.error(error?.message || '模型服务配置加载失败')
  } finally {
    loading.value = false
  }
}

async function runTest(service: 'chat' | 'embedding' | 'reranker') {
  testing.value = { ...testing.value, [service]: true }
  testResults.value = { ...testResults.value, [service]: null }
  const startedAt = performance.now()
  try {
    const result = await adminApi.testModelConfig(service)
    const elapsed = Math.round(performance.now() - startedAt)
    const detail = result.backend ? `（后端：${result.backend}${result.dimension ? `，维度 ${result.dimension}` : ''}）` : ''
    testResults.value = {
      ...testResults.value,
      [service]: result.available
        ? { ok: true, elapsed, message: `服务可用${detail}` }
        : { ok: false, elapsed, message: `连接失败：${result.error || '服务不可用'}` },
    }
  } catch (error: any) {
    testResults.value = {
      ...testResults.value,
      [service]: { ok: false, elapsed: Math.round(performance.now() - startedAt), message: `测试异常：${error?.message || String(error)}` },
    }
  } finally {
    testing.value = { ...testing.value, [service]: false }
  }
}

async function saveChat() {
  if (!chatFormalReady.value) {
    ElMessage.warning('启用正式模型服务前，请先配置 API Key')
    return
  }
  await ElMessageBox.confirm(
    '保存后下次模型调用立即生效，无需重启。API Key 当前将以明文保存；审计日志仅记录配置变更，不能保护密钥本身。是否继续？',
    '发布对话模型配置',
    { type: 'warning', confirmButtonText: '保存并发布' },
  )
  saving.value = { ...saving.value, chat: true }
  try {
    const body: Record<string, any> = {
      provider: chatForm.provider,
      model: chatForm.model,
      base_url: chatForm.base_url,
      temperature: chatForm.temperature,
      timeout: chatForm.timeout,
      max_retries: chatForm.max_retries,
      use_mock: chatForm.use_mock,
    }
    if (chatForm.api_key) body.api_key = chatForm.api_key
    const result = await adminApi.updateChatModelConfig(body)
    ElMessage.success(result.notice || '对话模型配置已发布')
    chatForm.api_key = ''
    await load()
  } catch (error: any) {
    ElMessage.error(error?.message || '保存失败')
  } finally {
    saving.value = { ...saving.value, chat: false }
  }
}

async function saveRag(service: 'embedding' | 'reranker', label: string) {
  if (!ragReady(service)) {
    ElMessage.warning(`${label}使用 API 后端前，请先配置 API Key`)
    return
  }
  await ElMessageBox.confirm(
    `保存后${label}将在下一次调用时按新配置重建，无需重启。是否继续？`,
    `发布${label}配置`,
    { type: 'warning', confirmButtonText: '保存并发布' },
  )
  saving.value = { ...saving.value, [service]: true }
  try {
    const form = service === 'embedding' ? embeddingForm : rerankerForm
    const body: Record<string, any> = {
      backend: form.backend,
      model: form.model,
      base_url: form.base_url || null,
    }
    if (form.api_key) body.api_key = form.api_key
    const result = await adminApi.updateRagModelConfig(service, body)
    ElMessage.success(result.notice || `${label}配置已发布`)
    form.api_key = ''
    await load()
  } catch (error: any) {
    ElMessage.error(error?.message || '保存失败')
  } finally {
    saving.value = { ...saving.value, [service]: false }
  }
}

onMounted(load)
</script>

<template>
  <div class="ots-page llm-page" v-loading="loading">
    <header class="page-hero">
      <div>
        <div class="eyebrow">智能体能力 / 模型服务</div>
        <h2>教学智能体模型服务</h2>
        <p>对话、向量与重排模型各自独立配置；保存后按模型分别生效，无需重启服务。</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新状态</el-button>
    </header>

    <section v-if="config" class="service-strip ots-card">
      <div v-for="item in [
        { key: 'chat', label: '对话模型', value: config.chat.model, mode: config.chat.use_mock ? '教学演示' : config.chat.provider },
        { key: 'embedding', label: '向量模型', value: config.embedding.model, mode: config.embedding.backend },
        { key: 'reranker', label: '重排模型', value: config.reranker.model, mode: config.reranker.backend },
      ]" :key="item.key" class="strip-item">
        <span class="strip-label">{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <el-tag size="small" effect="plain" :type="item.mode === '教学演示' ? 'warning' : 'success'">{{ item.mode }}</el-tag>
      </div>
    </section>

    <div class="model-grid">
      <!-- 对话模型 -->
      <section class="ots-card model-card">
        <div class="card-heading">
          <div class="card-title">
            <span class="card-icon"><el-icon><ChatLineRound /></el-icon></span>
            <div><span>业务主模型</span><h3>对话模型</h3></div>
          </div>
          <el-tag v-if="chatDirty || chatForm.api_key" type="warning" effect="plain">有待发布修改</el-tag>
          <el-tag v-else type="success" effect="plain">当前配置已生效</el-tag>
        </div>
        <p class="card-desc">驱动知识问答、题库生成、岗位图谱分析与浏览器采集决策。</p>

        <el-form label-position="top">
          <el-form-item label="运行模式">
            <el-radio-group :model-value="chatForm.provider" @change="setRunMode">
              <el-radio-button value="bailian">正式模型服务</el-radio-button>
              <el-radio-button value="mock">教学演示模式</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <div class="field-grid">
            <el-form-item label="模型标识">
              <el-select v-model="chatForm.model" filterable allow-create default-first-option>
                <el-option v-for="model in modelOptions" :key="model" :label="model" :value="model" />
              </el-select>
            </el-form-item>
            <el-form-item label="服务接入地址">
              <el-input v-model="chatForm.base_url" placeholder="https://..." />
            </el-form-item>
          </div>
          <div class="temperature-control">
            <div><strong>生成策略：{{ temperatureProfile.name }}</strong><span>{{ temperatureProfile.note }}</span></div>
            <el-input-number v-model="chatForm.temperature" :min="0" :max="2" :step="0.05" :precision="2" />
          </div>
          <div class="field-grid two">
            <el-form-item label="单次响应超时（秒）">
              <el-input-number v-model="chatForm.timeout" :min="1" :max="600" :step="5" />
            </el-form-item>
            <el-form-item label="失败重试次数">
              <el-input-number v-model="chatForm.max_retries" :min="0" :max="10" :step="1" />
            </el-form-item>
          </div>
          <el-form-item label="API Key">
            <el-input v-model="chatForm.api_key" type="password" show-password placeholder="留空表示不修改现有密钥" />
          </el-form-item>
          <el-alert v-if="chatForm.provider === 'mock'" title="演示模式使用模拟响应，不代表真实模型生成质量。" type="warning" :closable="false" show-icon />
          <el-alert v-else-if="!chatFormalReady" title="尚未配置 API Key，无法发布正式模型服务。" type="error" :closable="false" show-icon />
        </el-form>

        <div class="card-actions">
          <el-button :loading="testing.chat" @click="runTest('chat')">测试连通</el-button>
          <el-button type="primary" :loading="saving.chat" :disabled="(!chatForm.api_key && !chatDirty) || !chatFormalReady" @click="saveChat">保存并发布</el-button>
        </div>
        <div v-if="testResults.chat" class="test-result" :class="testResults.chat.ok ? 'success' : 'failure'">
          <el-icon><CircleCheckFilled v-if="testResults.chat.ok" /><CircleCloseFilled v-else /></el-icon>
          <span>{{ testResults.chat.message }}</span><small>{{ testResults.chat.elapsed }} ms</small>
        </div>
      </section>

      <!-- 向量模型 -->
      <section class="ots-card model-card">
        <div class="card-heading">
          <div class="card-title">
            <span class="card-icon embedding"><el-icon><Coordinate /></el-icon></span>
            <div><span>知识库检索</span><h3>向量模型</h3></div>
          </div>
          <el-tag v-if="ragDirty('embedding')" type="warning" effect="plain">有待发布修改</el-tag>
          <el-tag v-else type="success" effect="plain">当前配置已生效</el-tag>
        </div>
        <p class="card-desc">把知识块编码为向量参与检索；后端不可用时自动降级为本地词袋模式。</p>

        <el-form label-position="top">
          <el-form-item label="后端方式">
            <el-radio-group v-model="embeddingForm.backend">
              <el-radio-button value="api">云端 API</el-radio-button>
              <el-radio-button value="local">本地模型</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="模型标识">
            <el-select v-model="embeddingForm.model" filterable allow-create default-first-option>
              <el-option v-for="model in embeddingModelOptions" :key="model" :label="model" :value="model" />
            </el-select>
          </el-form-item>
          <el-form-item label="服务接入地址（可留空使用对话模型地址）">
            <el-input v-model="embeddingForm.base_url" placeholder="https://..." />
          </el-form-item>
          <el-form-item label="API Key（可留空沿用对话模型密钥）">
            <el-input v-model="embeddingForm.api_key" type="password" show-password placeholder="留空表示不修改现有密钥" />
          </el-form-item>
          <el-alert v-if="embeddingForm.backend === 'api' && !ragReady('embedding')" title="API 后端需要 API Key。" type="error" :closable="false" show-icon />
        </el-form>

        <div class="card-actions">
          <el-button :loading="testing.embedding" @click="runTest('embedding')">测试连通</el-button>
          <el-button type="primary" :loading="saving.embedding" :disabled="!ragDirty('embedding') || !ragReady('embedding')" @click="saveRag('embedding', '向量模型')">保存并发布</el-button>
        </div>
        <div v-if="testResults.embedding" class="test-result" :class="testResults.embedding.ok ? 'success' : 'failure'">
          <el-icon><CircleCheckFilled v-if="testResults.embedding.ok" /><CircleCloseFilled v-else /></el-icon>
          <span>{{ testResults.embedding.message }}</span><small>{{ testResults.embedding.elapsed }} ms</small>
        </div>
      </section>

      <!-- 重排模型 -->
      <section class="ots-card model-card">
        <div class="card-heading">
          <div class="card-title">
            <span class="card-icon reranker"><el-icon><Sort /></el-icon></span>
            <div><span>引用质量</span><h3>重排模型</h3></div>
          </div>
          <el-tag v-if="ragDirty('reranker')" type="warning" effect="plain">有待发布修改</el-tag>
          <el-tag v-else type="success" effect="plain">当前配置已生效</el-tag>
        </div>
        <p class="card-desc">对召回片段做相关性重排序，决定引用卡片的取舍与顺序。</p>

        <el-form label-position="top">
          <el-form-item label="后端方式">
            <el-radio-group v-model="rerankerForm.backend">
              <el-radio-button value="api">云端 API</el-radio-button>
              <el-radio-button value="local">本地模型</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="模型标识">
            <el-select v-model="rerankerForm.model" filterable allow-create default-first-option>
              <el-option v-for="model in rerankerModelOptions" :key="model" :label="model" :value="model" />
            </el-select>
          </el-form-item>
          <el-form-item label="服务接入地址（可留空使用对话模型地址）">
            <el-input v-model="rerankerForm.base_url" placeholder="https://..." />
          </el-form-item>
          <el-form-item label="API Key（可留空沿用对话模型密钥）">
            <el-input v-model="rerankerForm.api_key" type="password" show-password placeholder="留空表示不修改现有密钥" />
          </el-form-item>
          <el-alert v-if="rerankerForm.backend === 'api' && !ragReady('reranker')" title="API 后端需要 API Key。" type="error" :closable="false" show-icon />
        </el-form>

        <div class="card-actions">
          <el-button :loading="testing.reranker" @click="runTest('reranker')">测试连通</el-button>
          <el-button type="primary" :loading="saving.reranker" :disabled="!ragDirty('reranker') || !ragReady('reranker')" @click="saveRag('reranker', '重排模型')">保存并发布</el-button>
        </div>
        <div v-if="testResults.reranker" class="test-result" :class="testResults.reranker.ok ? 'success' : 'failure'">
          <el-icon><CircleCheckFilled v-if="testResults.reranker.ok" /><CircleCloseFilled v-else /></el-icon>
          <span>{{ testResults.reranker.message }}</span><small>{{ testResults.reranker.elapsed }} ms</small>
        </div>
      </section>
    </div>

    <section class="ots-card capability-card">
      <div class="side-title"><el-icon><Reading /></el-icon><div><strong>模型能力与业务环节</strong><span>各业务环节所依赖的模型服务</span></div></div>
      <div class="capability-list">
        <div v-for="item in capabilities" :key="item.name">
          <span class="capability-icon"><el-icon><component :is="item.icon" /></el-icon></span>
          <div><strong>{{ item.name }}</strong><small>{{ item.note }}</small></div>
          <code>{{ item.service === 'chat' ? '对话' : item.service === 'embedding' ? '向量' : '重排' }}</code>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.llm-page { max-width: 1400px; margin: 0 auto; }
.page-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin: 2px 0 16px; }
.eyebrow { margin-bottom: 7px; color: var(--ots-primary); font-size: 12px; font-weight: 600; letter-spacing: .8px; }
.page-hero h2 { margin: 0 0 7px; color: var(--ots-primary-dark); font-size: 25px; }
.page-hero p { margin: 0; color: var(--ots-text-secondary); }
.service-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 15px 18px; margin-bottom: 16px; }
.strip-item { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 10px 13px; border: 1px solid var(--ots-border); border-radius: 10px; background: #fbfdfd; }
.strip-label { flex: 0 0 auto; color: var(--ots-text-secondary); font-size: 11px; }
.strip-item strong { flex: 1 1 auto; min-width: 0; overflow: hidden; color: var(--ots-primary-dark); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.model-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; align-items: start; }
.model-card { padding: 20px 22px; }
.card-heading { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.card-title { display: flex; align-items: center; gap: 11px; }
.card-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 11px; background: var(--ots-education-soft); color: var(--ots-education); font-size: 19px; }
.card-icon.embedding { background: var(--ots-growth-soft); color: var(--ots-growth); }
.card-icon.reranker { background: var(--ots-practice-soft); color: var(--ots-practice); }
.card-title span { display: block; color: var(--ots-text-secondary); font-size: 10px; }
.card-title h3 { margin: 2px 0 0; font-size: 17px; }
.card-desc { margin: 10px 0 14px; color: var(--ots-text-secondary); font-size: 11px; line-height: 1.5; }
.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field-grid :deep(.el-select),.field-grid :deep(.el-input-number) { width: 100%; }
.temperature-control { display: flex; justify-content: space-between; align-items: center; gap: 14px; margin-bottom: 14px; padding: 10px 12px; border-radius: 8px; background: var(--ots-bg-subtle); }
.temperature-control strong,.temperature-control span { display: block; }
.temperature-control strong { font-size: 12px; }
.temperature-control span { margin-top: 2px; color: var(--ots-text-secondary); font-size: 10px; }
.card-actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--ots-border); }
.test-result { display: flex; align-items: center; gap: 8px; margin-top: 11px; padding: 9px 11px; border: 1px solid; border-radius: 8px; font-size: 11px; }
.test-result.success { border-color: #cce6d7; background: var(--ots-growth-soft); color: #2f7455; }
.test-result.failure { border-color: #efd6c7; background: #fff4ed; color: #a34b2e; }
.test-result small { margin-left: auto; opacity: .7; }
.capability-card { margin-top: 16px; padding: 17px 20px; }
.side-title { display: flex; align-items: center; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid var(--ots-border); }
.side-title > .el-icon { color: var(--ots-primary); font-size: 19px; }
.side-title strong,.side-title span { display: block; }
.side-title strong { font-size: 14px; }
.side-title span { margin-top: 2px; color: var(--ots-text-secondary); font-size: 10px; }
.capability-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.capability-list > div { display: flex; align-items: center; gap: 10px; padding: 12px 14px 12px 0; border-bottom: 1px dashed var(--ots-border); }
.capability-list > div:last-child { border-bottom: 0; }
.capability-list code { margin-left: auto; padding: 2px 8px; border-radius: 999px; background: var(--ots-education-soft); color: var(--ots-education); font-size: 10px; }
.capability-icon { display: grid; place-items: center; width: 33px; height: 33px; border-radius: 9px; background: var(--ots-education-soft); color: var(--ots-education); flex: 0 0 auto; }
.capability-list strong,.capability-list small { display: block; }
.capability-list strong { font-size: 13px; }
.capability-list small { margin-top: 2px; color: var(--ots-text-secondary); font-size: 10px; }

@media (max-width: 900px) {
  .service-strip { grid-template-columns: 1fr; }
  .field-grid { grid-template-columns: 1fr; }
}
</style>
