import { request } from '@/utils/request'
import { useAuthStore } from '@/stores/auth'
import type {
  AbilityHistoryOut,
  AdaptiveLearningPathOut,
  AbilityGraphOut,
  AbilityProfileOut,
  ChatMessageOut,
  ChatResponseOut,
  ChatSessionOut,
  KnowledgeItemOut,
  KnowledgeChunkListOut,
  KnowledgeChunkOut,
  KnowledgeChunkDetailOut,
  KnowledgeListOut,
  KnowledgeStatsOut,
  LoginResult,
  RadarDataOut,
  RecommendationOut,
  TaskCreateBody,
  TeacherStudentHistoryOut,
  TeacherStudentOut,
  TeacherStudentProfileOut,
  TeacherQuestionBankOut,
  TeacherQuestionOut,
  TeacherQuestionUpdateBody,
  TeacherPositionAnalysis,
  TeacherPositionDetailOut,
  TeacherPositionOut,
  TeacherTaskOut,
  TeacherTrainingAnalysisOut,
  TeacherTrainingResultOut,
  TeachingPlanAction,
  TeachingPlanOut,
  TrainingSessionOut,
  TrainingTaskOut,
  UserInfo,
  PositionDemandTrendOut,
  PositionGraphDraft,
  CurriculumProgramOut,
  IndustryEvidenceOut,
  ProgramAnalysisOut,
  ProgramProposalOut,
  AdminOverviewOut,
  AdminUserOut,
  AdminFeatureOut,
  AdminAuditLogOut,
  AdminLlmConfigOut,
} from '@/types'

export interface PromptTemplateOut {
  code: string
  name: string
  category: string
  description: string
  system_prompt: string
  user_prompt_template: string
  variables: string[]
  source_location: string
  version: number
  is_default: boolean
  updated_at: string
}

export interface PromptRevisionOut {
  version: number
  system_prompt: string
  user_prompt_template: string
  change_note: string
  is_default: boolean
  changed_by: number | null
  created_at: string
}

// ---- Auth ----
export const authApi = {
  login: (username: string, password: string) =>
    request<LoginResult>({ method: 'post', url: '/auth/login', data: { username, password } }),
  me: () => request<UserInfo>({ method: 'get', url: '/auth/me' }),
}

// ---- Admin ----
export const adminApi = {
  overview: () => request<AdminOverviewOut>({ method: 'get', url: '/admin/overview' }),
  users: () => request<AdminUserOut[]>({ method: 'get', url: '/admin/users' }),
  updateUser: (id: number, body: Partial<Pick<AdminUserOut, 'real_name' | 'role' | 'student_no' | 'class_name' | 'is_active'>>) =>
    request<AdminUserOut>({ method: 'patch', url: `/admin/users/${id}`, data: body }),
  features: () => request<AdminFeatureOut[]>({ method: 'get', url: '/admin/features' }),
  updateFeature: (code: string, body: Partial<Pick<AdminFeatureOut, 'enabled' | 'read_only' | 'visible_roles' | 'change_reason'>>) =>
    request<AdminFeatureOut>({ method: 'put', url: `/admin/features/${encodeURIComponent(code)}`, data: body }),
  auditLogs: () => request<AdminAuditLogOut[]>({ method: 'get', url: '/admin/audit-logs' }),
  llmConfig: () => request<AdminLlmConfigOut>({ method: 'get', url: '/admin/llm-config' }),
  updateLlmConfig: (body: {
    provider?: string | null
    model?: string | null
    base_url?: string | null
    api_key?: string | null
    temperature?: number | null
    timeout?: number | null
    max_retries?: number | null
    use_mock?: boolean | null
  }) => request<{ saved: Record<string, string>; notice: string }>({ method: 'put', url: '/admin/llm-config', data: body }),
  testLlmConfig: () =>
    request<{ available: boolean; provider: string; use_mock: boolean; error?: string }>({
      method: 'post',
      url: '/admin/llm-config/test',
      timeout: 30000,
    }),
  prompts: () =>
    request<{ items: PromptTemplateOut[]; total: number; notice: string }>({
      method: 'get',
      url: '/admin/prompts',
    }),
  promptRevisions: (code: string) =>
    request<PromptRevisionOut[]>({
      method: 'get',
      url: `/admin/prompts/${encodeURIComponent(code)}/revisions`,
    }),
  updatePrompt: (
    code: string,
    body: { system_prompt: string; user_prompt_template: string; change_note: string },
  ) =>
    request<PromptTemplateOut>({
      method: 'put',
      url: `/admin/prompts/${encodeURIComponent(code)}`,
      data: body,
    }),
  restorePromptDefault: (code: string) =>
    request<PromptTemplateOut>({
      method: 'post',
      url: `/admin/prompts/${encodeURIComponent(code)}/restore-default`,
    }),
}

// ---- Training ----
export const trainingApi = {
  tasks: () => request<TrainingTaskOut[]>({ method: 'get', url: '/training/tasks' }),
  sessions: () => request<TrainingSessionOut[]>({ method: 'get', url: '/training/sessions' }),
  start: (taskCode: string) =>
    request<TrainingSessionOut>({
      method: 'post',
      url: '/training/start',
      data: { task_code: taskCode },
    }),
  submitChoice: (sessionId: number, questionId: number, optionId: number) =>
    request<TrainingSessionOut>({
      method: 'post',
      url: `/training/${sessionId}/answer-choice`,
      data: { question_id: questionId, option_id: optionId },
    }),
  detail: (sessionId: number) =>
    request<TrainingSessionOut>({ method: 'get', url: `/training/${sessionId}` }),
}

// ---- Chat (RAG QA) ----
export const chatApi = {
  chat: (message: string, sessionId?: number) =>
    request<ChatResponseOut>({
      method: 'post',
      url: '/chat',
      data: { message, session_id: sessionId },
    }),
  sessions: () =>
    request<ChatSessionOut[]>({
      method: 'get',
      url: '/chat/sessions',
    }),
  sessionDetail: (sessionId: number) =>
    request<ChatMessageOut[]>({
      method: 'get',
      url: `/chat/sessions/${sessionId}`,
    }),
}

// ---- Chat 流式输出 (SSE) ----
export interface ChatStreamMeta {
  session_id: number
  request_id?: string
  intent?: string
  secondary_intents?: string[]
  evidence?: Array<Record<string, unknown>>
  cards?: Array<{ title: string; route: string }>
  actions?: Array<Record<string, unknown>>
  trace_summary?: string[]
  retrieved_count?: number
  citations?: Array<Record<string, unknown>>
  safety?: { safe: boolean; reason?: string; category?: string } | null
}

export interface ChatStreamEvents {
  onStart?: (payload: { session_id: number; request_id: string }) => void
  onStatus?: (payload: { request_id: string; message: string }) => void
  onMeta?: (meta: ChatStreamMeta) => void
  onDelta?: (content: string) => void
  onSources?: (payload: {
    request_id: string
    retrieved_count: number
    citations: Array<Record<string, unknown>>
  }) => void
  onReplace?: (payload: {
    request_id: string
    content: string
    safety?: { safe: boolean; reason?: string; category?: string } | null
  }) => void
  onDone?: (payload: {
    answer: string
    session_id: number
    request_id: string
    completed: boolean
  }) => void
  onError?: (message: string) => void
}

export interface ChatStreamOptions {
  signal?: AbortSignal
}

/** 以 SSE 方式调用问答接口，逐块回调正文增量。 */
export async function chatStream(
  message: string,
  sessionId: number | undefined,
  events: ChatStreamEvents,
  options: ChatStreamOptions = {},
): Promise<void> {
  const auth = useAuthStore()
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {}),
    },
    body: JSON.stringify({ message, session_id: sessionId ?? null }),
    signal: options.signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`stream request failed: ${resp.status}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const handleEvent = (rawEvent: string) => {
    rawEvent = rawEvent.replace(/\r\n/g, '\n')
    let eventName = 'message'
    let dataStr = ''
    for (const line of rawEvent.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
    }
    if (!dataStr) return
    let payload: Record<string, unknown> = {}
    try {
      payload = JSON.parse(dataStr)
    } catch {
      return
    }
    if (eventName === 'start') {
      events.onStart?.({
        session_id: Number(payload.session_id ?? 0),
        request_id: String(payload.request_id ?? ''),
      })
    } else if (eventName === 'status') {
      events.onStatus?.({
        request_id: String(payload.request_id ?? ''),
        message: String(payload.message ?? ''),
      })
    } else if (eventName === 'meta') events.onMeta?.(payload as unknown as ChatStreamMeta)
    else if (eventName === 'delta') events.onDelta?.(String(payload.content ?? ''))
    else if (eventName === 'sources') {
      events.onSources?.({
        request_id: String(payload.request_id ?? ''),
        retrieved_count: Number(payload.retrieved_count ?? 0),
        citations: Array.isArray(payload.citations)
          ? payload.citations as Array<Record<string, unknown>>
          : [],
      })
    } else if (eventName === 'replace') {
      events.onReplace?.({
        request_id: String(payload.request_id ?? ''),
        content: String(payload.content ?? ''),
        safety: payload.safety as ChatStreamMeta['safety'],
      })
    }
    else if (eventName === 'done') {
      events.onDone?.({
        answer: String(payload.answer ?? ''),
        session_id: Number(payload.session_id ?? 0),
        request_id: String(payload.request_id ?? ''),
        completed: payload.completed !== false,
      })
    } else if (eventName === 'error') events.onError?.(String(payload.message ?? '问答服务暂时不可用'))
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const rawEvent = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      handleEvent(rawEvent)
    }
  }
  const tail = buffer + decoder.decode()
  if (tail.trim()) handleEvent(tail)
}

// ---- Ability Profile ----
export const abilityApi = {
  profile: () => request<AbilityProfileOut>({ method: 'get', url: '/ability/profile' }),
  history: (abilityKey?: string, limit = 50) =>
    request<AbilityHistoryOut[]>({
      method: 'get',
      url: '/ability/history',
      params: { ability_key: abilityKey, limit },
    }),
  radar: () => request<RadarDataOut>({ method: 'get', url: '/ability/radar' }),
}

// ---- Position Ability Graph ----
export const positionApi = {
  graph: () => request<AbilityGraphOut>({ method: 'get', url: '/positions/graph' }),
  demandTrend: (positionId: number, months = 6) =>
    request<PositionDemandTrendOut>({
      method: 'get',
      url: `/positions/${positionId}/demand-trend`,
      params: { months },
    }),
}

// ---- Recommendation ----
export const recommendationApi = {
  tasks: () =>
    request<RecommendationOut[]>({ method: 'get', url: '/recommendation/tasks' }),
  adaptivePath: () =>
    request<AdaptiveLearningPathOut>({ method: 'get', url: '/recommendation/adaptive-path' }),
}

// ---- Health ----
export const healthApi = {
  check: () =>
    request<{ status: string; services: Record<string, string> }>({ method: 'get', url: '/health' }),
}

// ---- Knowledge ----
export const knowledgeApi = {
  list: (params?: { ability?: string; source_type?: string; authority_only?: boolean; keyword?: string; knowledge_id?: string; page?: number; page_size?: number }) =>
    request<KnowledgeListOut>({ method: 'get', url: '/knowledge/items', params }),
  detail: (itemId: number) =>
    request<KnowledgeItemOut>({ method: 'get', url: `/knowledge/items/${itemId}` }),
  chunk: (chunkId: number) =>
    request<KnowledgeChunkDetailOut>({ method: 'get', url: `/knowledge/chunks/${chunkId}` }),
  chunks: (itemId: number) =>
    request<KnowledgeChunkListOut>({ method: 'get', url: `/knowledge/items/${itemId}/chunks` }),
  updateChunk: (chunkId: number, data: { enabled?: boolean; knowledge_point_id?: number | null }) =>
    request<{ chunk: KnowledgeChunkOut; vector_points: number }>({
      method: 'patch',
      url: `/knowledge/chunks/${chunkId}`,
      data,
    }),
  stats: () =>
    request<KnowledgeStatsOut>({ method: 'get', url: '/knowledge/stats' }),
  create: (data: { title: string; content: string; ability?: string; source_type?: string; source_name?: string; difficulty?: number }) =>
    request<{ id: number; knowledge_id: string; title: string }>({ method: 'post', url: '/knowledge/items', data }),
  upload: (formData: FormData) =>
    request<{
      id: number; knowledge_id: string; title: string
      file_name: string; file_type: string; file_size: number
      text_length: number; page_count: number; vector_points: number
      chunk_count: number; enabled_chunk_count: number; disabled_chunk_count: number
    }>({
      method: 'post',
      url: '/knowledge/upload',
      data: formData,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    }),
  delete: (itemId: number) =>
    request<{ deleted: boolean; id: number }>({ method: 'delete', url: `/knowledge/items/${itemId}` }),
}

// ---- Teacher ----
export const teacherApi = {
  positions: () =>
    request<TeacherPositionOut[]>({ method: 'get', url: '/teacher/positions' }),
  positionDetail: (positionId: number) =>
    request<TeacherPositionDetailOut>({
      method: 'get',
      url: `/teacher/positions/${positionId}`,
    }),
  createPosition: (body: {
    code: string
    name: string
    major: string
    description: string
    aliases: string[]
  }) =>
    request<{ id: number; status: string }>({
      method: 'post',
      url: '/teacher/positions',
      data: body,
    }),
  updatePosition: (positionId: number, body: {
    name?: string
    major?: string
    description?: string
    aliases?: string[]
  }) =>
    request<{ id: number; status: string }>({
      method: 'put',
      url: `/teacher/positions/${positionId}`,
      data: body,
    }),
  discoverPosition: (positionId: number, maxResults = 20, lookbackMonths = 0) =>
    request<{
      run_id: number
      status: string
      query_terms: string[]
      source_domains: string[]
      found_count: number
      saved_count: number
      lookback_months: number
      stage_stats: {
        official_search_candidates: number
        official_structured_positions: number
        official_structured_raw_positions: number
        official_source_requests: number
        official_relevant_positions: number
        search_candidates: number
        direct_entries: number
        direct_search_positions: number
        expanded_positions: number
        fetched_pages: number
        recruitment_semantic: number
        relevant_positions: number
      }
      official_sources: Array<{
        source: string
        status: 'available' | 'closed' | 'maintenance' | 'access_restricted' | 'unavailable' | 'unreachable'
        available: boolean
        url: string
        detail: string
      }>
      diagnostic: string
      warnings: string[]
    }>({
      method: 'post',
      url: `/teacher/positions/${positionId}/discover`,
      data: {
        max_results: maxResults,
        lookback_months: lookbackMonths,
        confirm_public_search: true,
      },
      timeout: 180000,
    }),
  refreshPositionDates: (positionId: number) =>
    request<{
      total_urls: number
      dated_urls: number
      undated_urls: number
      refetched_urls: number
      date_confidence: { high: number; medium: number; low: number }
      semantics: string
    }>({
      method: 'post',
      url: `/teacher/positions/${positionId}/refresh-dates`,
      data: { confirm_public_refresh: true },
      timeout: 180000,
    }),
  analyzePosition: (positionId: number) =>
    request<TeacherPositionAnalysis>({
      method: 'post',
      url: `/teacher/positions/${positionId}/analyze`,
      timeout: 180000,
    }),
  updatePositionAnalysis: (
    positionId: number,
    analysisId: number,
    result: PositionGraphDraft,
  ) =>
    request<TeacherPositionAnalysis>({
      method: 'put',
      url: `/teacher/positions/${positionId}/analyses/${analysisId}`,
      data: { result },
    }),
  publishPosition: (positionId: number, analysisId: number) =>
    request<{
      position_id: number
      analysis_id: number
      version: number
      status: string
      tasks: number
      knowledge_points: number
      skill_points: number
      training_tasks: number
    }>({
      method: 'post',
      url: `/teacher/positions/${positionId}/publish`,
      data: { analysis_id: analysisId, confirm_reviewed: true },
      timeout: 120000,
    }),
  students: () =>
    request<TeacherStudentOut[]>({ method: 'get', url: '/teacher/students' }),
  studentProfile: (studentId: number) =>
    request<TeacherStudentProfileOut>({
      method: 'get',
      url: `/teacher/students/${studentId}`,
    }),
  studentHistory: (studentId: number) =>
    request<TeacherStudentHistoryOut[]>({
      method: 'get',
      url: `/teacher/students/${studentId}/history`,
    }),
  tasks: () =>
    request<TeacherTaskOut[]>({ method: 'get', url: '/teacher/tasks' }),
  createTask: (body: TaskCreateBody) =>
    request<{ id: number; code: string; title: string }>({
      method: 'post',
      url: '/teacher/tasks',
      data: body,
    }),
  updateTask: (taskId: number, body: Partial<TaskCreateBody> & { status?: string }) =>
    request<{ id: number; code: string; title: string }>({
      method: 'put',
      url: `/teacher/tasks/${taskId}`,
      data: body,
    }),
  taskQuestions: (taskId: number) =>
    request<TeacherQuestionBankOut>({
      method: 'get',
      url: `/teacher/tasks/${taskId}/questions`,
    }),
  generateTaskQuestions: (
    taskId: number,
    body: {
      count: number
      difficulty?: number
      focus_points?: string[]
      generation_mode?: 'ai' | 'local_rule'
      confirm_external?: boolean
    },
  ) =>
    request<{
      batch_code: string
      question_count: number
      provider: string
      used_fallback: boolean
      warning: string
      items: TeacherQuestionOut[]
    }>({
      method: 'post',
      url: `/teacher/tasks/${taskId}/questions/generate`,
      data: body,
      timeout: 120000,
    }),
  updateQuestion: (questionId: number, body: TeacherQuestionUpdateBody) =>
    request<TeacherQuestionOut>({
      method: 'put',
      url: `/teacher/questions/${questionId}`,
      data: body,
    }),
  publishQuestionBatch: (taskId: number, batchCode: string) =>
    request<{ batch_code: string; status: string; question_count: number; reviewed_at: string }>({
      method: 'post',
      url: `/teacher/tasks/${taskId}/questions/batches/${encodeURIComponent(batchCode)}/publish`,
    }),
  trainingResults: (className = '') =>
    request<TeacherTrainingResultOut[]>({
      method: 'get',
      url: '/teacher/training-results',
      params: { class_name: className || undefined },
    }),
  trainingAnalysis: (className = '') =>
    request<TeacherTrainingAnalysisOut>({
      method: 'get',
      url: '/teacher/training-analysis',
      params: { class_name: className || undefined },
    }),
  teachingPlans: () =>
    request<TeachingPlanOut[]>({ method: 'get', url: '/teacher/teaching-plans' }),
  generateTeachingPlan: (body: { class_name?: string; title?: string }) =>
    request<TeachingPlanOut>({
      method: 'post',
      url: '/teacher/teaching-plans/generate',
      data: body,
    }),
  updateTeachingPlan: (
    planId: number,
    body: { title?: string; status?: string; actions?: TeachingPlanAction[]; notes?: string },
  ) =>
    request<TeachingPlanOut>({
      method: 'patch',
      url: `/teacher/teaching-plans/${planId}`,
      data: body,
    }),
}

export const programApi = {
  programs: () =>
    request<CurriculumProgramOut[]>({ method: 'get', url: '/teacher/programs' }),
  detail: (programId: number) =>
    request<CurriculumProgramOut>({ method: 'get', url: `/teacher/programs/${programId}` }),
  analysis: (programId: number, months = 12) =>
    request<ProgramAnalysisOut>({
      method: 'get',
      url: `/teacher/programs/${programId}/analysis`,
      params: { months },
    }),
  evidence: (major = '油气储运工程') =>
    request<IndustryEvidenceOut[]>({
      method: 'get',
      url: '/teacher/programs/industry-evidence',
      params: { major },
    }),
  addEvidence: (body: Omit<IndustryEvidenceOut, 'id' | 'created_at'>) =>
    request<IndustryEvidenceOut>({
      method: 'post',
      url: '/teacher/programs/industry-evidence',
      data: body,
    }),
  updateEvidence: (id: number, body: Partial<IndustryEvidenceOut>) =>
    request<IndustryEvidenceOut>({
      method: 'patch',
      url: `/teacher/programs/industry-evidence/${id}`,
      data: body,
    }),
  proposals: () =>
    request<ProgramProposalOut[]>({ method: 'get', url: '/teacher/programs/proposals' }),
  createProposal: (programId: number, months = 12) =>
    request<ProgramProposalOut>({
      method: 'post',
      url: `/teacher/programs/${programId}/proposals`,
      data: { months },
    }),
  updateProposal: (
    proposalId: number,
    body: { title?: string; actions?: ProgramProposalOut['actions']; review_note?: string; status?: string },
  ) => request<ProgramProposalOut>({
    method: 'patch',
    url: `/teacher/programs/proposals/${proposalId}`,
    data: body,
  }),
  publishProposal: (proposalId: number) =>
    request<CurriculumProgramOut>({
      method: 'post',
      url: `/teacher/programs/proposals/${proposalId}/publish`,
      data: { confirm_reviewed: true },
    }),
}
