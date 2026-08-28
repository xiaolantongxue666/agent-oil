<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { ref, computed, nextTick, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { chatApi, chatStream, knowledgeApi, type ChatStreamMeta } from '@/api'
import MarkdownContent from '@/components/MarkdownContent.vue'
import type { AssistantCardOut, ChatSessionOut, CitationOut, KnowledgeChunkDetailOut, KnowledgeItemOut } from '@/types'
import { renderSafeMarkdown as renderMd } from '@/utils/safeMarkdown'
import { useAuthStore } from '@/stores/auth'

const props = withDefaults(defineProps<{
  compact?: boolean
  assistantTitle?: string
}>(), {
  compact: false,
  assistantTitle: '智能学习助手',
})

const authStore = useAuthStore()

// 候选问题按角色区分：学生问个人学习，教师问班级学情与题库管理。
const STUDENT_SUGGESTIONS = ['我的薄弱能力是什么？', '下一步学什么？', '推荐一个实训', '目标岗位需要什么能力？']
const TEACHER_SUGGESTIONS = ['班级学情怎么样？', '学生各任务的掌握情况如何？', '题库质量如何？', '现在有多少待审核的题目？', '目标岗位需要什么能力？']
const suggestedQuestions = computed(() => (authStore.isStaff ? TEACHER_SUGGESTIONS : STUDENT_SUGGESTIONS))
const emptyDescription = computed(() =>
  authStore.isStaff ? '试试问：班级学情怎么样？题库质量如何？也可以直接咨询专业知识' : '试试问：我的薄弱能力是什么？下一步学什么？推荐一个实训；目标岗位需要什么能力？',
)

const intentLabels: Record<string, string> = {
  knowledge_qa: '专业知识问答', ability_diagnosis: '能力诊断', adaptive_learning: '自适应学习',
  training_recommendation: '实训推荐', training_review: '实训复盘', position_capability: '岗位能力',
  class_insight: '班级学情', question_bank_quality: '题库质量', role_guidance: '身份提示',
  conversation: '日常对话', text_assistance: '文本处理',
}
function intentLabel(intent?: string) { return intentLabels[intent || ''] || '学习咨询' }
function traceLabel(trace?: string[]) {
  if (!trace?.length) return ''
  return trace.map((item) => ({ ability_profile_loaded: '已读取个人能力画像', adaptive_path_loaded: '已生成学习路径', training_recommendations_loaded: '已生成实训推荐', training_review_loaded: '已读取最近实训', safety_blocked_before_business_data: '安全校验已拦截业务数据', }[item] || (item.startsWith('role_guidance') ? '已提供角色使用指引' : item.startsWith('published_positions_loaded') ? '已读取已发布岗位图谱' : '已完成受控查询'))).join(' · ')
}

const retrievalStatusLabels: Record<string, string> = {
  pending: '等待判断是否需要知识库',
  not_called: '未调用知识库',
  retrieved: '已检索知识库，正在核验采用依据',
  used: '已采用知识库依据',
  retrieved_not_used: '已检索但未采用候选内容',
  no_results: '知识库未找到可用内容',
  failed: '知识库检索失败',
  blocked: '安全校验已阻止资料输出',
}
const answerBasisLabels: Record<string, string> = {
  business_data: '业务功能结果',
  business_function_error: '业务功能错误信息',
  knowledge_base: '知识库依据',
  conversation_context: '会话上下文',
  role_guidance: '角色使用指引',
}
function retrievalStatusLabel(status?: string) {
  return retrievalStatusLabels[status || ''] || ''
}
function answerBasisLabel(items?: string[]) {
  return (items || []).map((item) => answerBasisLabels[item] || item).join('、')
}

interface DisplayMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: CitationOut[]
  retrievedCount?: number
  safety?: { safe: boolean; reason?: string } | null
  intent?: string
  evidence?: Array<Record<string, unknown>>
  cards?: AssistantCardOut[]
  trace?: string[]
  executionTrace?: Array<{ step: string; status: string; summary: string }>
  retrievalStatus?: string
  answerBasis?: string[]
  thinking?: boolean
  streaming?: boolean
  statusText?: string
  requestId?: string
  showProcess?: boolean
}

const messages = ref<DisplayMessage[]>([])
const input = ref('')
const sending = ref(false)
const currentSessionId = ref<number | undefined>(undefined)
const chatBox = ref<HTMLElement | null>(null)
const route = useRoute()
const router = useRouter()
let activeController: AbortController | null = null
let generationSequence = 0

// ---- 聊天历史 ----
const sessions = ref<ChatSessionOut[]>([])
const loadingSessions = ref(false)
const activeSessionId = ref<number | undefined>(undefined)
const deletingSessionId = ref<number | undefined>(undefined)

async function scrollToBottom() {
  await nextTick()
  if (chatBox.value) {
    chatBox.value.scrollTop = chatBox.value.scrollHeight
  }
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    sessions.value = await chatApi.sessions()
  } catch {
    sessions.value = []
  } finally {
    loadingSessions.value = false
  }
}

async function loadSession(session: ChatSessionOut) {
  cancelActiveStream(false)
  activeSessionId.value = session.id
  currentSessionId.value = session.id
  try {
    const msgs = await chatApi.sessionDetail(session.id)
    messages.value = msgs.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
      citations: (m.citations || []) as unknown as CitationOut[],
      intent: m.intent,
      evidence: m.evidence,
      cards: m.cards,
      executionTrace: m.execution_trace,
      retrievalStatus: m.retrieval_status,
      answerBasis: m.answer_basis,
      retrievedCount: m.retrieved_count,
    }))
    await scrollToBottom()
  } catch {
    messages.value = []
  }
}

function newChat() {
  cancelActiveStream(false)
  messages.value = []
  currentSessionId.value = undefined
  activeSessionId.value = undefined
  input.value = ''
}

async function deleteSession(session: ChatSessionOut) {
  if (sending.value && currentSessionId.value === session.id) {
    ElMessage.warning('请先停止当前回答，再删除该对话。')
    return
  }
  try {
    await ElMessageBox.confirm(
      `删除“${session.title || '未命名对话'}”及其中的全部消息？此操作不可恢复。`,
      '删除对话',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  deletingSessionId.value = session.id
  try {
    await chatApi.deleteSession(session.id)
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
    if (currentSessionId.value === session.id) {
      cancelActiveStream(false)
      messages.value = []
      currentSessionId.value = undefined
      activeSessionId.value = undefined
    }
    ElMessage.success('对话已删除')
  } catch {
    ElMessage.error('删除对话失败，请稍后重试。')
  } finally {
    deletingSessionId.value = undefined
  }
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  const generationId = ++generationSequence
  const controller = new AbortController()
  activeController = controller
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  // 预占一条助手消息，流式增量直接追加内容（打字机效果）
  const assistantMsg: DisplayMessage = {
    role: 'assistant',
    content: '',
    thinking: true,
    streaming: true,
    statusText: '正在提交问题...',
  }
  messages.value.push(assistantMsg)
  await scrollToBottom()
  try {
    await chatStream(text, currentSessionId.value, {
      onStart: (payload) => {
        if (generationId !== generationSequence) return
        assistantMsg.requestId = payload.request_id
        currentSessionId.value = payload.session_id
        activeSessionId.value = payload.session_id
      },
      onStatus: (payload) => {
        if (generationId !== generationSequence) return
        assistantMsg.statusText = payload.message
      },
      onProcess: (payload) => {
        if (generationId !== generationSequence || !payload.step) return
        const steps = assistantMsg.executionTrace || []
        const index = steps.findIndex((item) => item.step === payload.step)
        const current = {
          step: payload.step,
          status: payload.status,
          summary: payload.summary,
        }
        if (index >= 0) steps.splice(index, 1, current)
        else steps.push(current)
        assistantMsg.executionTrace = [...steps]
        assistantMsg.statusText = payload.summary
        scrollToBottom()
      },
      onMeta: (meta: ChatStreamMeta) => {
        if (generationId !== generationSequence) return
        currentSessionId.value = meta.session_id
        activeSessionId.value = meta.session_id
        assistantMsg.intent = meta.intent
        assistantMsg.trace = meta.trace_summary
        // 仅在 meta 实际携带步骤时覆盖；避免初始 meta 的空数组
        // 清空已由 onProcess 逐步累积的执行过程。
        if (meta.execution_trace?.length) {
          assistantMsg.executionTrace = meta.execution_trace
        }
        assistantMsg.retrievalStatus = meta.retrieval_status
        assistantMsg.answerBasis = meta.answer_basis
        assistantMsg.evidence = meta.evidence
        assistantMsg.cards = meta.cards as AssistantCardOut[] | undefined
        assistantMsg.retrievedCount = meta.retrieved_count
        if (meta.citations !== undefined) {
          assistantMsg.citations = meta.citations as unknown as CitationOut[]
        }
        assistantMsg.safety = meta.safety ?? null
      },
      onDelta: (content: string) => {
        if (generationId !== generationSequence) return
        assistantMsg.thinking = false
        assistantMsg.content += content
        scrollToBottom()
      },
      onSources: (payload) => {
        if (generationId !== generationSequence) return
        assistantMsg.retrievedCount = payload.retrieved_count
        assistantMsg.citations = payload.citations as unknown as CitationOut[]
      },
      onReplace: (payload) => {
        if (generationId !== generationSequence) return
        assistantMsg.thinking = false
        assistantMsg.content = payload.content
        assistantMsg.safety = payload.safety ?? null
      },
      onDone: (payload) => {
        if (generationId !== generationSequence) return
        assistantMsg.thinking = false
        assistantMsg.streaming = false
        assistantMsg.statusText = payload.completed ? '回答生成完成' : '回答生成中断'
        // 正常流不重绘；仅在最终安全校正或尾段差异时同步权威版本。
        if (payload.answer && payload.answer !== assistantMsg.content) {
          assistantMsg.content = payload.answer
        }
        if (payload.session_id) {
          currentSessionId.value = payload.session_id
          activeSessionId.value = payload.session_id
        }
      },
      onError: (message: string) => {
        if (generationId !== generationSequence) return
        assistantMsg.thinking = false
        assistantMsg.streaming = false
        assistantMsg.statusText = message
        if (!assistantMsg.content) assistantMsg.content = message
      },
    }, { signal: controller.signal })
    // 刷新会话列表（新会话或更新消息数）
    loadSessions()
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    assistantMsg.thinking = false
    assistantMsg.streaming = false
    if (!assistantMsg.content) {
      assistantMsg.content = '抱歉，问答服务暂时不可用，请稍后重试。'
    }
  } finally {
    if (generationId === generationSequence) {
      sending.value = false
      activeController = null
    }
    await scrollToBottom()
  }
}

function cancelActiveStream(showStopped = true) {
  if (!activeController) return
  activeController.abort()
  activeController = null
  generationSequence += 1
  sending.value = false
  if (!showStopped) return
  const assistantMsg = [...messages.value].reverse().find((message) => message.streaming)
  if (!assistantMsg) return
  assistantMsg.thinking = false
  assistantMsg.streaming = false
  assistantMsg.statusText = '已停止生成'
  if (!assistantMsg.content) assistantMsg.content = '（已停止生成）'
}

function stopGeneration() {
  cancelActiveStream(true)
}

function clearChat() {
  cancelActiveStream(false)
  messages.value = []
  currentSessionId.value = undefined
  activeSessionId.value = undefined
}

onBeforeUnmount(() => cancelActiveStream(false))

function formatTime(dateStr: string) {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前'
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function roleLabel(role?: string) {
  return { teacher: '教师对话', admin: '管理员对话' }[role || ''] || '学生对话'
}

// ---- 引用来源查看知识库原文 ----
const citationDialog = ref(false)
const citationLoading = ref(false)
const citationDetail = ref<KnowledgeItemOut | null>(null)
const citationChunk = ref<KnowledgeChunkDetailOut | null>(null)
const citationError = ref('')
const citationTitle = ref('')

async function openCitation(cite: CitationOut) {
  citationTitle.value = cite.title || '知识原文'
  citationDialog.value = true
  citationLoading.value = true
  citationError.value = ''
  citationDetail.value = null
  citationChunk.value = null
  try {
    // 优先展示检索命中的知识块（而非整个文件）
    if (cite.chunk_id) {
      citationChunk.value = await knowledgeApi.chunk(cite.chunk_id)
      return
    }
    if (!cite.knowledge_id) {
      citationError.value = '该引用缺少知识编号，无法定位原文。'
      return
    }
    const res = await knowledgeApi.list({ knowledge_id: cite.knowledge_id, page_size: 1 })
    const item = res.items?.[0]
    if (!item) {
      citationError.value = '知识库中未找到对应条目（可能已被停用或删除）。'
      return
    }
    citationDetail.value = await knowledgeApi.detail(item.id)
  } catch {
    citationError.value = '加载知识原文失败，请稍后重试。'
  } finally {
    citationLoading.value = false
  }
}

onMounted(() => {
  loadSessions()
  if (typeof route.query.query === 'string') input.value = route.query.query
})
</script>

<template>
  <div class="ots-page qa-page" :class="{ 'qa-page--compact': props.compact }">
    <div class="qa-layout">
      <!-- 左侧：聊天历史 -->
      <div class="session-sidebar">
        <div class="sidebar-header">
          <span class="sidebar-title">💬 聊天记录</span>
          <el-button size="small" type="primary" text @click="newChat">+ 新对话</el-button>
        </div>
        <div v-loading="loadingSessions" class="session-list">
          <div v-if="!sessions.length && !loadingSessions" class="session-empty text-secondary">
            暂无历史记录
          </div>
          <div
            v-for="sess in sessions"
            :key="sess.id"
            class="session-item"
            :class="{ active: activeSessionId === sess.id }"
            @click="loadSession(sess)"
          >
            <div class="session-title-row">
              <div class="session-title">{{ sess.title }}</div>
              <el-button
                class="session-delete"
                text
                type="danger"
                size="small"
                circle
                title="删除对话"
                aria-label="删除对话"
                :loading="deletingSessionId === sess.id"
                @click.stop="deleteSession(sess)"
              ><el-icon><Delete /></el-icon></el-button>
            </div>
            <div class="session-meta text-secondary">
              <span>
                <el-tag size="small" :type="sess.owner_role === 'teacher' ? 'warning' : 'success'" effect="plain">
                  {{ roleLabel(sess.owner_role) }}
                </el-tag>
              </span>
              <span>{{ sess.message_count }} 条消息</span>
              <span>{{ formatTime(sess.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：聊天主区域 -->
      <div class="qa-main">
        <div class="ots-card qa-header">
          <div class="qa-title-row">
            <h2 v-if="!props.compact" class="ots-title" style="margin: 0">{{ props.assistantTitle }}</h2>
            <el-tag type="warning" effect="dark">AI 生成内容</el-tag>
          </div>
          <p class="text-secondary" style="margin: 0">
            根据用户意图调用对应学习功能；仅在任务需要时检索知识库。回答仅供学习参考，不替代现场规程和教师判断。
          </p>
        </div>

        <!-- 消息区域 -->
        <div class="ots-card chat-area" ref="chatBox">
          <el-empty description="问知识、看能力、找学习路径或推荐实训" :image-size="100">
            <template #description>
              <p class="text-secondary">{{ emptyDescription }}</p>
            </template>
            <div class="hint-tags">
              <el-tag
                v-for="hint in suggestedQuestions"
                :key="hint"
                effect="plain"
                class="hint-tag"
                @click="input = hint"
              >
                {{ hint }}
              </el-tag>
            </div>
          </el-empty>

          <div v-for="(msg, i) in messages" :key="i" class="msg" :class="msg.role">
            <div class="msg-avatar">{{ msg.role === 'user' ? '🧑‍🎓' : '📚' }}</div>
            <div class="msg-body">
              <div class="msg-role">
                {{ msg.role === 'user' ? '我的问题' : props.assistantTitle }}
                <el-tag v-if="msg.role === 'assistant'" size="small" type="warning" effect="plain">AI 生成</el-tag>
              </div>

              <!-- 思考区：生成过程中（thinking / streaming）在答案上方实时展示状态 + 思考 + 步骤 -->
              <div
                v-if="msg.role === 'assistant' && (msg.thinking || msg.streaming)"
                class="thinking-phase"
              >
                <div class="thinking-status">
                  <span v-if="msg.streaming && !msg.thinking" class="stream-cursor" aria-hidden="true"></span>
                  <span class="typing">{{ msg.statusText || (msg.thinking ? '正在识别意图并调用对应功能...' : '正在生成回答...') }}</span>
                </div>
                <div v-if="msg.executionTrace?.length" class="thinking-steps">
                  <div v-for="(step, si) in msg.executionTrace" :key="`${step.step}-${si}`" class="process-step">
                    <span class="process-state" :class="step.status">{{ step.status === 'failed' || step.status === 'blocked' ? '!' : step.status === 'skipped' ? '−' : step.status === 'waiting' || step.status === 'running' ? '…' : '✓' }}</span>
                    <span>{{ step.summary }}</span>
                  </div>
                </div>
              </div>

              <div v-if="msg.role === 'assistant' && !msg.thinking" class="msg-content md-content" v-html="renderMd(msg.content)" />
              <div v-else-if="msg.role === 'user'" class="msg-content" v-text="msg.content" />

              <!-- 生成完成后：意图标签 -->
              <div v-if="msg.intent && !msg.thinking" class="assistant-meta">
                <el-tag size="small" type="success">意图：{{ intentLabel(msg.intent) }}</el-tag>
                <span v-if="!msg.executionTrace?.length && msg.trace?.length" class="text-secondary">{{ traceLabel(msg.trace) }}</span>
              </div>

              <!-- 生成完成后：可折叠的处理过程回看 -->
              <div
                v-if="msg.executionTrace?.length && !msg.thinking && !msg.streaming && msg.showProcess"
                class="assistant-process"
              >
                <div class="process-title">处理过程</div>
                <div v-for="(step, si) in msg.executionTrace" :key="`${step.step}-${si}`" class="process-step">
                  <span class="process-state" :class="step.status">{{ step.status === 'failed' || step.status === 'blocked' ? '!' : step.status === 'skipped' ? '−' : step.status === 'waiting' || step.status === 'running' ? '…' : '✓' }}</span>
                  <span>{{ step.summary }}</span>
                </div>
              </div>
              <div
                v-if="msg.executionTrace?.length && !msg.thinking && !msg.streaming"
                class="process-toggle"
                @click="msg.showProcess = !msg.showProcess"
              >
                {{ msg.showProcess ? '收起处理过程 ▲' : '查看处理过程 ▼' }}
              </div>
              <div v-if="(msg.retrievalStatus && msg.retrievalStatus !== 'not_called') || msg.answerBasis?.length" class="assistant-basis">
                <span v-if="msg.retrievalStatus && msg.retrievalStatus !== 'not_called'">知识库：{{ retrievalStatusLabel(msg.retrievalStatus) }}</span>
                <span v-if="msg.answerBasis?.length">回答依据：{{ answerBasisLabel(msg.answerBasis) }}</span>
              </div>
              <div v-if="msg.evidence?.length" class="assistant-evidence">
                业务依据：{{ msg.evidence.map((item) => String(item.title || item.type || '业务事实')).join('；') }}
              </div>
              <div v-if="msg.cards?.length" class="assistant-cards">
                <el-button v-for="card in msg.cards" :key="card.route + card.title" size="small" @click="router.push(card.route)">
                  {{ card.title }}
                </el-button>
              </div>

              <!-- 安全警告 -->
              <div v-if="msg.safety && !msg.safety.safe" class="safety-warn">
                ⚠️ {{ msg.safety.reason || '该内容存在安全风险，已被系统拦截。' }}
              </div>

              <!-- 引用来源 -->
              <div v-if="msg.citations && msg.citations.length" class="citations">
                <div class="cite-header">
                  📖 已核验回答来源（{{ msg.citations.length }} 条<template v-if="msg.retrievedCount !== undefined">；检索候选 {{ msg.retrievedCount }} 条</template>）
                </div>
                <div
                  v-for="(cite, ci) in msg.citations"
                  :key="ci"
                  class="cite-item clickable"
                  title="点击查看知识库原文"
                  @click="openCitation(cite)"
                >
                  <div class="cite-title">📄 {{ cite.title || '未知来源' }}</div>
                  <div class="cite-meta text-secondary">
                    <span v-if="cite.source_name">{{ cite.source_name }}</span>
                    <span v-if="cite.source_no"> · {{ cite.source_no }}</span>
                    <span v-if="cite.chapter"> · {{ cite.chapter }}</span>
                    <span v-if="cite.page"> · P{{ cite.page }}</span>
                  </div>
                  <div
                    v-if="cite.is_teaching_simulation"
                    class="cite-sim"
                    title="表示该资料仅用于教学环境，不代表资料出处为模拟来源"
                  >📋 教学环境引用</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="ots-card input-area">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            placeholder="输入油气储运专业问题..."
            :disabled="sending"
            @keydown.ctrl.enter="sendMessage"
          />
          <div class="input-footer">
            <div>
              <el-button text size="small" @click="clearChat" :disabled="!messages.length">
                清空对话
              </el-button>
            </div>
            <div style="display: flex; align-items: center; gap: 8px">
              <span class="text-secondary" style="font-size: 12px">Ctrl + Enter 发送</span>
              <el-button
                v-if="sending"
                type="danger"
                plain
                @click="stopGeneration"
              >
                停止生成
              </el-button>
              <el-button
                v-else
                type="primary"
                :disabled="!input.trim()"
                @click="sendMessage"
              >
                发送
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 引用来源：知识库原文查看弹窗 -->
    <el-dialog
      v-model="citationDialog"
      :title="citationTitle"
      width="720px"
      top="6vh"
      destroy-on-close
    >
      <div v-loading="citationLoading" class="cite-dialog-body">
        <template v-if="citationChunk">
          <div class="cite-dialog-meta text-secondary">
            <span v-if="citationChunk.item_title">{{ citationChunk.item_title }}</span>
            <span v-if="citationChunk.source_name"> · {{ citationChunk.source_name }}</span>
            <span v-if="citationChunk.source_no"> · {{ citationChunk.source_no }}</span>
            <span v-if="citationChunk.page_start">
              · P{{ citationChunk.page_start }}<template v-if="citationChunk.page_end && citationChunk.page_end !== citationChunk.page_start">–{{ citationChunk.page_end }}</template>
            </span>
            <el-tag size="small" type="warning" effect="plain" style="margin-left: 6px">
              教学环境引用
            </el-tag>
          </div>
          <div v-if="citationChunk.heading_path || citationChunk.chapter" class="cite-dialog-heading">
            📑 {{ citationChunk.heading_path || citationChunk.chapter }}
          </div>
          <MarkdownContent class="cite-dialog-content" :content="citationChunk.content" />
          <div class="cite-dialog-note text-secondary">
            以上为检索命中的知识块原文（教学模拟/脱敏摘录），正式引用请自行核验原始出处。
          </div>
        </template>
        <template v-else-if="citationDetail">
          <div class="cite-dialog-meta text-secondary">
            <span v-if="citationDetail.source_name">{{ citationDetail.source_name }}</span>
            <span v-if="citationDetail.source_no"> · {{ citationDetail.source_no }}</span>
            <span v-if="citationDetail.chapter"> · {{ citationDetail.chapter }}</span>
            <span v-if="citationDetail.page"> · P{{ citationDetail.page }}</span>
            <el-tag size="small" type="warning" effect="plain" style="margin-left: 6px">
              教学环境引用
            </el-tag>
          </div>
          <MarkdownContent class="cite-dialog-content" :content="citationDetail.content" />
          <div class="cite-dialog-note text-secondary">
            以上为知识库中的教学模拟/脱敏摘录，正式引用请自行核验原始出处。
          </div>
        </template>
        <el-empty v-else-if="!citationLoading && citationError" :description="citationError" :image-size="80" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.qa-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 130px);
}
.qa-layout {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
.qa-page--compact {
  height: 620px;
  min-height: 0;
  padding: 0;
}
.qa-page--compact .session-sidebar { width: 200px; }
.qa-page--compact .qa-header { padding: 12px 14px; }
.qa-page--compact .chat-area { padding: 12px; }
.qa-page--compact .input-area { padding: 12px; }

/* ---- 左侧历史栏 ---- */
.session-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 10px;
  border: 1px solid var(--ots-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--ots-border);
}
.sidebar-title {
  font-size: 14px;
  font-weight: 600;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.session-empty {
  text-align: center;
  padding: 24px 0;
  font-size: 13px;
}
.session-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}
.session-item:hover {
  background: var(--ots-bg);
}
.session-item.active {
  background: rgba(11, 95, 107, 0.08);
  border-left: 3px solid var(--ots-primary);
}
.session-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-title-row { display: flex; align-items: center; gap: 4px; }
.session-delete { flex: 0 0 auto; opacity: 0; }
.session-item:hover .session-delete, .session-item.active .session-delete { opacity: 1; }
.session-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  margin-top: 4px;
}

/* ---- 右侧主区域 ---- */
.qa-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.qa-header {
  flex-shrink: 0;
}
.qa-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.chat-area {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
}
.hint-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
}
.hint-tag {
  cursor: pointer;
}
.msg {
  display: flex;
  gap: 10px;
  max-width: 85%;
}
.msg.assistant {
  align-self: flex-start;
}
.msg.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--ots-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.msg-body {
  background: var(--ots-bg);
  border-radius: 10px;
  padding: 10px 14px;
}
.msg.user .msg-body {
  background: rgba(11, 95, 107, 0.1);
}
.msg-role {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ots-text-secondary);
  margin-bottom: 4px;
  font-weight: 600;
}
.msg-content {
  white-space: pre-wrap;
  line-height: 1.6;
}
.stream-cursor {
  width: 7px;
  height: 14px;
  border-radius: 2px;
  background: var(--ots-primary);
  animation: stream-blink 0.8s steps(1) infinite;
}
@keyframes stream-blink {
  50% { opacity: 0.2; }
}
/* 思考区：生成期间实时展示状态文字 + 过程步骤 */
.thinking-phase {
  background: rgba(25, 118, 210, 0.05);
  border: 1px solid rgba(25, 118, 210, 0.15);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.thinking-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-bottom: 6px;
}
.thinking-steps {
  border-top: 1px solid rgba(25, 118, 210, 0.1);
  padding-top: 6px;
  margin-top: 4px;
  font-size: 12px;
}
.thinking-steps .process-step {
  padding: 2px 0;
}
/* Markdown 渲染样式 */
.md-content {
  white-space: normal;
}
.md-content :deep(h1),
.md-content :deep(h2),
.md-content :deep(h3) {
  margin: 12px 0 6px;
  font-size: 15px;
  font-weight: 600;
}
.md-content :deep(h1) { font-size: 17px; }
.md-content :deep(p) {
  margin: 4px 0;
  line-height: 1.7;
}
.md-content :deep(ul),
.md-content :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}
.md-content :deep(li) {
  margin: 2px 0;
  line-height: 1.6;
}
.md-content :deep(strong) {
  font-weight: 600;
  color: #1a1a1a;
}
.md-content :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 13px;
  font-family: 'Menlo', 'Consolas', monospace;
}
.md-content :deep(pre) {
  background: #f5f5f5;
  padding: 10px 14px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
.md-content :deep(pre code) {
  background: none;
  padding: 0;
}
.md-content :deep(blockquote) {
  border-left: 3px solid var(--ots-primary);
  padding-left: 12px;
  margin: 8px 0;
  color: #555;
}
.md-content :deep(hr) {
  border: none;
  border-top: 1px solid var(--ots-border);
  margin: 12px 0;
}
.md-content :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 13px;
}
.md-content :deep(th),
.md-content :deep(td) {
  border: 1px solid var(--ots-border);
  padding: 4px 8px;
}
.md-content :deep(th) {
  background: var(--ots-bg);
  font-weight: 600;
}
.typing {
  color: var(--ots-text-secondary);
  font-style: italic;
}
.safety-warn {
  margin-top: 8px;
  padding: 8px 12px;
  background: #fde8e8;
  border: 1px solid #c62828;
  border-radius: 6px;
  font-size: 13px;
  color: #c62828;
}
.assistant-meta, .assistant-cards { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 8px; font-size: 11px; }
.assistant-evidence { margin-top: 8px; padding: 6px 8px; border-radius: 6px; background: #fff; font-size: 12px; color: var(--ots-text-secondary); }
.assistant-process { margin-top: 8px; padding: 8px 10px; border-radius: 6px; background: #fff; font-size: 12px; }
.process-toggle {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ots-text-secondary);
  cursor: pointer;
  user-select: none;
  padding: 4px 8px;
  border-radius: 4px;
  display: inline-block;
  transition: color 0.15s, background 0.15s;
}
.process-toggle:hover {
  color: var(--ots-primary, #1976d2);
  background: rgba(11, 95, 107, 0.06);
}
.process-title { margin-bottom: 4px; font-weight: 600; color: var(--ots-text-secondary); }
.process-step { display: flex; gap: 6px; align-items: flex-start; padding: 2px 0; }
.process-state { width: 14px; flex: 0 0 14px; color: var(--ots-success, #2e7d32); font-weight: 700; }
.process-state.failed { color: var(--ots-danger, #c62828); }
.process-state.blocked { color: var(--ots-danger, #c62828); }
.process-state.skipped { color: var(--ots-text-secondary); }
.process-state.running, .process-state.waiting { color: var(--ots-primary, #1976d2); }
.assistant-basis { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; color: var(--ots-text-secondary); font-size: 12px; }
.citations {
  margin-top: 10px;
  border-top: 1px solid var(--ots-border);
  padding-top: 8px;
}
.cite-header {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--ots-text-secondary);
}
.cite-item {
  padding: 6px 10px;
  background: #fff;
  border-radius: 6px;
  margin-bottom: 4px;
  border: 1px solid var(--ots-border);
}
.cite-item.clickable {
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.cite-item.clickable:hover {
  border-color: var(--ots-primary);
  background: rgba(11, 95, 107, 0.04);
}
.cite-dialog-body {
  min-height: 120px;
  max-height: 60vh;
  overflow-y: auto;
}
.cite-dialog-meta {
  font-size: 12px;
  margin-bottom: 10px;
}
.cite-dialog-heading {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #1a1a1a;
}
.cite-dialog-content {
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: 13px;
}
.cite-dialog-note {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px dashed var(--ots-border);
  font-size: 12px;
}
.cite-title {
  font-size: 13px;
  font-weight: 500;
}
.cite-meta {
  font-size: 11px;
}
.cite-sim {
  font-size: 11px;
  color: var(--ots-warning);
  margin-top: 2px;
}
.input-area {
  flex-shrink: 0;
}
.input-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

@media (max-width: 768px) {
  .qa-page--compact { height: calc(100vh - 112px); }
  .qa-page--compact .session-sidebar { width: 150px; }
  .qa-page--compact .session-meta span:nth-child(2), .qa-page--compact .session-meta span:nth-child(3) { display: none; }
}
</style>
