// 统一 API 响应类型
export interface ApiSuccess<T = unknown> {
  success: true
  data: T
}

export interface ApiError {
  success: false
  code: string
  message: string
  request_id: string
}

export type ApiResponse<T = unknown> = ApiSuccess<T> | ApiError

// 用户与认证
export type UserRole = 'student' | 'teacher' | 'admin'

export interface UserInfo {
  id: number
  username: string
  real_name: string
  role: string
  student_no?: string | null
  class_name?: string | null
}

export interface LoginResult {
  token: string
  token_type: string
  user: UserInfo
}

// 管理端
export interface AdminUserOut {
  id: number
  username: string
  real_name: string
  role: UserRole
  student_no: string | null
  class_name: string | null
  is_active: boolean
  created_at: string
}

export interface AdminFeatureOut {
  code: string
  name: string
  description: string
  enabled: boolean
  read_only: boolean
  visible_roles: string[]
  version: number
  change_reason: string
  updated_by: number | null
  updated_at: string
}

export interface AdminAuditLogOut {
  id: number
  actor_id: number | null
  actor_name: string
  action: string
  resource_type: string
  resource_id: string | null
  detail: string
  created_at: string
}

export interface AdminModelConfigOut {
  chat: {
    provider: string
    model: string
    base_url: string
    api_key_masked: string
    api_key_configured: boolean
    temperature: number
    timeout: number
    max_retries: number
    use_mock: boolean
  }
  embedding: {
    backend: string
    model: string
    base_url: string
    api_key_masked: string
    api_key_configured: boolean
    has_db_override: boolean
  }
  reranker: {
    backend: string
    model: string
    base_url: string
    api_key_masked: string
    api_key_configured: boolean
    has_db_override: boolean
  }
}

export interface AdminLlmConfigOut {
  provider: string
  model: string
  base_url: string
  api_key_masked: string
  api_key_configured: boolean
  temperature: number
  timeout: number
  max_retries: number
  use_mock: boolean
  has_db_override: boolean
  last_updated_at: string
}

// 六维能力
export type AbilityKey =
  | 'process_understanding'
  | 'equipment_recognition'
  | 'instrument_parameter'
  | 'abnormal_detection'
  | 'safety_awareness'
  | 'standard_recording'

export const ABILITY_LABELS: Record<AbilityKey, string> = {
  process_understanding: '流程理解',
  equipment_recognition: '设备认知',
  instrument_parameter: '仪表参数',
  abnormal_detection: '异常检测',
  safety_awareness: '安全意识',
  standard_recording: '规范记录',
}

export interface AbilityItem {
  key: AbilityKey
  name: string
  weight: number
  score: number
}

export interface AbilityDimOut {
  name: string
  score: number
  attempt_count: number
  weight: number
}

export type AbilityProfileOut = Record<string, AbilityDimOut>

export interface AbilityHistoryOut {
  id: number
  ability_key: string
  ability_name: string
  before_score: number
  training_score: number
  after_score: number
  training_session_id: number | null
  created_at: string
}

export interface RadarDataOut {
  labels: string[]
  scores: number[]
  max_scores: number[]
  indicators: { name: string; max: number }[]
}

// 训练任务
export interface TrainingTaskOut {
  id: number
  code: string
  title: string
  description: string
  difficulty: number
  target_abilities: string[]
  estimated_minutes: number
  max_follow_ups: number
  mode: 'choice'
  question_count: number
}

export interface TrainingQuestionOptionOut {
  id: number
  key: string
  content: string
}

export interface TrainingQuestionOut {
  id: number
  code: string
  stem: string
  ability_key: string
  knowledge_point: string
  sort_order: number
  generated_by_ai: boolean
  options: TrainingQuestionOptionOut[]
}

export interface TrainingAnswerRecordOut {
  question_id: number
  question_code: string
  stem: string
  ability_key: string
  knowledge_point: string
  selected_option_id: number
  selected_option_key: string
  selected_option_content: string
  score: number
  max_score: number
  is_correct: boolean
  feedback: string
  explanation: string
}

// 训练会话
export interface EvaluationOut {
  final_score: number
  rule_score: number
  semantic_score: number
  llm_score: number
  ability_scores: Record<string, number>
  strengths: string[]
  missing_points: string[]
  error_types: string[]
  explanation: string
  citations: CitationOut[]
  scoring_mode: 'database_choice_rule'
}

export interface TrainingSessionOut {
  id: number
  task_code: string
  task_title: string
  stage: string
  attempt_count: number
  follow_up_count: number
  max_follow_ups: number
  finished: boolean
  current_coach_question: string
  mode: 'choice'
  question_count: number
  answered_count: number
  current_question: TrainingQuestionOut | null
  answer_records: TrainingAnswerRecordOut[]
  last_answer_feedback: {
    question_id: number
    selected_option_key: string
    score: number
    max_score: number
    is_correct: boolean
    feedback: string
    explanation: string
  } | null
  scenario_text: string
  messages: { role: string; content: string; round?: string }[]
  evidence_citations: CitationOut[]
  evaluation: EvaluationOut | null
  created_at: string
}

// 知识问答
export interface CitationOut {
  knowledge_id: string
  title: string
  source_name: string
  source_no: string
  chapter: string
  page: number | null
  chunk_id?: number | null
  is_teaching_simulation: boolean
}

export interface ChatResponseOut {
  session_id: number
  answer: string
  citations: CitationOut[]
  retrieved_count: number
  safety: { safe: boolean; reason?: string } | null
  intent: string
  intent_confidence: number
  secondary_intents: string[]
  evidence: Array<Record<string, unknown>>
  cards: AssistantCardOut[]
  actions: AssistantActionOut[]
  trace_summary: string[]
  execution_trace: Array<{ step: string; status: string; summary: string }>
  retrieval_status: string
  answer_basis: string[]
  ai_generated: boolean
}

export interface AssistantCardOut {
  type: string
  title: string
  route: string
  reason?: string
}

export interface AssistantActionOut {
  type: string
  label: string
  route: string
  requires_confirmation: boolean
}

export interface ChatSessionOut {
  id: number
  title: string
  message_count: number
  owner_role: string
  created_at: string
}

export interface ChatMessageOut {
  id: number
  role: string
  content: string
  citations: Record<string, unknown>[]
  intent?: string
  evidence?: Array<Record<string, unknown>>
  cards?: AssistantCardOut[]
  execution_trace?: Array<{ step: string; status: string; summary: string }>
  retrieval_status?: string
  answer_basis?: string[]
  retrieved_count?: number
  created_at: string
}

// 教师
export interface TeacherStudentOut {
  id: number
  username: string
  real_name: string
  student_no: string
  class_name: string
  total_score: number
  completed_count: number
  weakest_ability: string | null
}

export interface TeacherStudentProfileOut {
  id: number
  username: string
  real_name: string
  student_no: string
  class_name: string
  profile: AbilityProfileOut
  radar: RadarDataOut
  completed_count: number
  avg_score: number
}

export interface TeacherStudentHistoryOut {
  id: number
  task_title: string
  task_code: string
  finished: boolean
  stage: string
  attempt_count: number
  final_score: number | null
  created_at: string
}

export interface TeacherTaskOut extends TrainingTaskOut {
  status: string
  required_points: string[]
  reference_points: string[]
  scenario: Record<string, unknown>
}

export interface TeacherQuestionOptionOut {
  id: number
  key: string
  content: string
  score: number
  feedback: string
  is_correct: boolean
}

export interface TeacherQuestionOut {
  id: number
  task_id: number
  code: string
  stem: string
  ability_key: string
  knowledge_point: string
  explanation: string
  sort_order: number
  max_score: number
  active: boolean
  status: 'draft' | 'published' | 'archived'
  batch_code: string
  generated_by_ai: boolean
  generation_meta: {
    provider?: string
    used_fallback?: boolean
    attempts?: number
    warning?: string
    difficulty?: number
    focus_points?: string[]
    generation_mode?: 'ai' | 'local_rule'
    external_transfer_confirmed?: boolean
    evidence_citations?: CitationOut[]
    generated_at?: string
  }
  reviewed_by: number | null
  reviewed_at: string
  options: TeacherQuestionOptionOut[]
}

export interface TeacherQuestionBankOut {
  task: {
    id: number
    code: string
    title: string
    difficulty: number
    target_abilities: string[]
    knowledge_points: string[]
    required_points: string[]
  }
  items: TeacherQuestionOut[]
  batches: Array<{
    batch_code: string
    status: 'draft' | 'published' | 'archived'
    question_count: number
    generated_by_ai: boolean
    generation_meta: TeacherQuestionOut['generation_meta']
    created_at: string
  }>
  evidence_citations: CitationOut[]
}

export interface TeacherQuestionUpdateBody {
  stem: string
  ability_key: string
  knowledge_point: string
  explanation: string
  options: Array<{
    key: string
    content: string
    score: number
    feedback: string
    is_correct: boolean
  }>
}

export interface TaskCreateBody {
  code: string
  title: string
  description?: string
  difficulty?: number
  target_abilities?: string[]
  estimated_minutes?: number
  max_follow_ups?: number
  required_points?: string[]
  reference_points?: string[]
  scenario?: Record<string, unknown>
}

export interface TeacherTrainingResultOut {
  id: number
  student_id: number
  student_name: string
  student_no: string
  class_name: string
  task_code: string
  task_title: string
  final_score: number
  question_count: number
  correct_count: number
  correct_rate: number
  ability_scores: Record<string, number>
  weakest_ability: string
  weakest_ability_name: string
  finished_at: string
  answer_records: Array<{
    question_code: string
    stem: string
    knowledge_point: string
    selected_option: string
    selected_content: string
    score: number
    is_correct: boolean
    feedback: string
  }>
}

export interface TeacherTrainingAnalysisOut {
  class_name: string
  generated_at: string
  summary: {
    student_count: number
    completed_count: number
    average_score: number
    pass_rate: number
  }
  ability_summary: Array<{
    key: string
    name: string
    average_score: number
    sample_count: number
  }>
  task_summary: Array<{
    task_code: string
    task_title: string
    average_score: number
    completion_count: number
  }>
  common_errors: Array<{
    question_code: string
    stem: string
    knowledge_point: string
    ability_key: string
    attempts: number
    wrong_count: number
    wrong_rate: number
  }>
  recommended_actions: TeachingPlanAction[]
}

export interface TeachingPlanAction {
  id: string
  priority: 'high' | 'medium' | 'low'
  target: string
  reason: string
  strategy: string
  task_codes: string[]
  completed: boolean
}

export interface TeachingPlanOut {
  id: number
  title: string
  class_name: string
  status: 'draft' | 'active' | 'completed'
  analysis_snapshot: TeacherTrainingAnalysisOut
  actions: TeachingPlanAction[]
  notes: string
  generated_at: string
  updated_at: string
}

// 推荐
export interface RecommendationOut {
  task_id: number
  task_code: string
  task_title: string
  target_ability: string
  target_ability_name: string
  reason_code: string
  reason_text: string
  difficulty: number
  estimated_minutes: number
  current_ability_score: number
}

export interface AdaptiveLearningPathOut {
  student_id: number
  data_boundary: string
  summary: {
    overall_mastery: number
    knowledge_count: number
    weak_count: number
    learning_count: number
    mastered_count: number
    completed_answer_count: number
    path_step_count: number
  }
  ability_state: Array<{
    key: string
    name: string
    score: number
    attempt_count: number
    state: 'weak' | 'learning' | 'mastered'
  }>
  knowledge_mastery: Array<{
    knowledge_point: string
    ability_key: string
    ability_name: string
    mastery_score: number
    attempt_count: number
    wrong_count: number
    recent_scores: number[]
    safety_critical: boolean
    state: 'weak' | 'learning' | 'mastered'
  }>
  learning_path: AdaptiveLearningStep[]
  next_step: AdaptiveLearningStep | null
  refresh_rule: string
}

export interface AdaptiveLearningStep {
  id: string
  step_type: 'knowledge_review' | 'training_retry' | 'diagnostic_training'
  title: string
  reason: string
  priority: string
  knowledge_point: string
  target_ability: string
  task_id?: number
  task_code?: string
  difficulty: number
  estimated_minutes: number
  route: string
  safety_critical: boolean
}

export interface CurriculumCourseOut {
  id: number
  course_code: string
  name: string
  category: string
  total_hours: number
  practice_hours: number
  practice_ratio: number
  ability_weights: Record<string, number>
  knowledge_points: string[]
  position_ids: number[]
  assessment_method: string
  enabled: boolean
  sort_order: number
}

export interface CurriculumProgramOut {
  id: number
  program_code: string
  major: string
  name: string
  version: number
  status: 'draft' | 'published' | 'archived'
  objectives: string
  graduation_requirements: string[]
  source_period_months: number
  change_summary: string
  parent_program_id: number | null
  published_at: string
  courses: CurriculumCourseOut[]
}

export interface ProgramAnalysisOut {
  scope: {
    major: string
    months: number
    cutoff: string
    data_boundary: string
  }
  summary: {
    position_count: number
    job_sample_count: number
    job_sample_month_count: number
    industry_evidence_count: number
    authoritative_evidence_count: number
    total_course_hours: number
    practice_hours: number
    practice_ratio: number
    confidence: 'low' | 'medium' | 'high'
    confidence_basis: string
  }
  positions: Array<{ id: number; name: string; sample_count: number; graph_version: number }>
  ability_gaps: Array<{
    ability_key: string
    ability_name: string
    demand_share: number
    curriculum_share: number
    gap: number
  }>
  top_skills: Array<{ name: string; count: number }>
  uncovered_skills: Array<{ name: string; count: number }>
  industry_themes: Array<{ name: string; count: number }>
  evidence_refs: Array<Record<string, unknown>>
  generated_at: string
}

export interface IndustryEvidenceOut {
  id: number
  major: string
  title: string
  source_name: string
  source_type: string
  source_no: string
  source_url: string
  published_at: string | null
  summary: string
  themes: string[]
  skills: string[]
  confidence: 'low' | 'medium' | 'high'
  enabled: boolean
  created_at: string
}

export interface ProgramAdjustmentAction {
  id: string
  type: string
  priority: 'high' | 'medium' | 'low'
  target: string
  target_ability: string
  reason: string
  suggestion: string
  hours_delta: number
  completed: boolean
}

export interface ProgramProposalOut {
  id: number
  base_program_id: number
  target_version: number
  status: 'draft' | 'reviewed' | 'rejected' | 'published'
  title: string
  analysis_snapshot: ProgramAnalysisOut
  actions: ProgramAdjustmentAction[]
  evidence_refs: Array<Record<string, unknown>>
  generation_method: string
  review_note: string
  reviewed_at: string | null
  published_program_id: number | null
  published_at: string | null
  created_at: string
  updated_at: string
}

// 知识库
export interface KnowledgeItemOut {
  id: number
  knowledge_id: string
  title: string
  ability: string
  /** 文件由已映射分块汇总；普通条目为自身能力维度。 */
  chunk_abilities: string[]
  knowledge_point: string
  difficulty: number
  content: string
  source_type: string
  source_name: string
  source_no: string
  chapter: string
  page: number | null
  safety_level: string
  tags: string[]
  file_name: string
  file_type: string
  file_size: number
  vector_embedded: boolean
  created_at: string | null
}

export interface KnowledgeListOut {
  items: KnowledgeItemOut[]
  total: number
  page: number
  page_size: number
}

export interface KnowledgeChunkDetailOut {
  id: number
  knowledge_item_id: number
  chunk_index: number
  heading: string
  chapter: string
  heading_path: string
  chunk_type: string
  content: string
  page_start: number | null
  page_end: number | null
  enabled: boolean
  item_title: string
  knowledge_id: string
  source_name: string
  source_no: string
  file_name: string
}

export interface KnowledgeChunkOut {
  id: number
  knowledge_item_id: number
  chunk_index: number
  heading: string
  chapter: string
  heading_path?: string
  chunk_type?: string
  content: string
  page_start: number | null
  page_end: number | null
  knowledge_point_id: number | null
  knowledge_point_code: string
  knowledge_point_name: string
  ability: string
  match_score: number
  match_reason: string
  enabled: boolean
  reviewed: boolean
  vector_embedded: boolean
}

export interface KnowledgeChunkListOut {
  items: KnowledgeChunkOut[]
  total: number
  enabled: number
  knowledge_points: Array<{
    id: number
    code: string
    name: string
    ability: string
  }>
}

export interface KnowledgeStatsOut {
  total: number
  embedded: number
  authoritative: number
  by_ability: Record<string, number>
  by_source: Record<string, number>
}

// 岗位能力图谱
export interface AbilityGraphNode {
  id: string
  name: string
  category: number
  code: string
  description: string
  weight?: number
  symbol_size: number
  authority_count?: number
  authority_sources?: Array<{
    knowledge_id: string
    title: string
    source_name: string
    source_no: string
    chapter: string
    page: number | null
  }>
  reviewed_chunk_count?: number
  reviewed_chunks?: Array<{
    chunk_id: number
    heading: string
    source_name: string
    page_start: number | null
    page_end: number | null
  }>
}

export interface AbilityGraphLink {
  source: string
  target: string
  relation: string
  weight?: number
}

export interface PositionAbilityHeatmap {
  positions: Array<{
    id: number
    code: string
    name: string
    description: string
  }>
  abilities: Array<{
    id: number
    key: string
    name: string
  }>
  tasks: Array<{
    id: number
    position_id: number
    code: string
    name: string
  }>
  position_cells: Array<{
    position_id: number
    ability_id: number
    weight: number
  }>
  task_cells: Array<{
    task_id: number
    ability_id: number
    weight: number
  }>
  value_semantics: 'ability_weight'
}

export interface AbilityGraphOut {
  categories: string[]
  nodes: AbilityGraphNode[]
  links: AbilityGraphLink[]
  heatmap: PositionAbilityHeatmap
  stats: {
    positions: number
    tasks: number
    abilities: number
    knowledge_points: number
    skill_points: number
    authority_items: number
    enabled_file_chunks: number
  }
  data_source: 'database'
  evidence_relation_source: 'knowledge_evidence_relations'
}

export interface PositionGraphDraft {
  position_summary: string
  ability_weights: Record<string, number>
  tasks: Array<{
    code: string
    name: string
    description: string
    ability_weights: Record<string, number>
    knowledge_points: Array<{
      code: string
      name: string
      description: string
      ability_key: string
      skills: string[]
    }>
    source_refs: number[]
  }>
  demand_skills: string[]
  review_note: string
}

export interface TeacherPositionAnalysis {
  id: number
  version: number
  status: string
  provider: string
  evidence_count: number
  confidence: number
  result: PositionGraphDraft
  created_at: string
  reviewed_at: string
  published_at: string
}

export interface TeacherPositionOut {
  id: number
  code: string
  name: string
  major: string
  description: string
  aliases: string[]
  status: 'draft' | 'published' | 'archived'
  graph_version: number
  source_summary: string
  task_count: number
  snapshot_count: number
  latest_analysis: TeacherPositionAnalysis | null
  published_at: string
}

export interface JobPostingSnapshotOut {
  id: number
  title: string
  company: string
  region: string
  source_name: string
  source_url: string
  published_at: string
  published_at_raw: string
  published_at_source: string
  date_confidence: 'low' | 'medium' | 'high'
  date_parse_reason: string
  observed_at: string
  skills: string[]
  match_score: number
  snippet: string
}

export interface PositionDiscoveryCandidateOut {
  id: number
  source_name: string
  source_url: string
  title: string
  validation_status: 'accepted' | 'rejected'
  validation_errors: string[]
  confidence: number
}

export interface PositionDiscoveryRunOut {
  run_id: number
  status: 'queued' | 'running' | 'completed' | 'empty' | 'restricted' | 'failed' | 'cancelled'
  mode: 'fast' | 'browser'
  stage: string
  progress: number
  cancel_requested: boolean
  query_terms: string[]
  source_domains: string[]
  found_count: number
  saved_count: number
  lookback_months: number
  stage_stats: Record<string, number>
  official_sources: Array<{
    source: string
    status: string
    available: boolean
    url: string
    detail: string
  }>
  diagnostic: string
  warnings: string[]
  error_summary: string
  created_at: string
  completed_at: string
  candidates?: PositionDiscoveryCandidateOut[]
}

export interface TeacherPositionDetailOut {
  position: Omit<TeacherPositionOut, 'task_count' | 'snapshot_count' | 'latest_analysis' | 'published_at'>
  snapshots: JobPostingSnapshotOut[]
  discovery_runs: PositionDiscoveryRunOut[]
  analyses: TeacherPositionAnalysis[]
}

export interface PositionDemandTrendOut {
  position_id: number
  position_name: string
  range_months: number
  series: Array<{
    period: string
    posting_count: number | null
    employer_count: number | null
    growth_rate: number | null
    moving_average: number | null
    covered: boolean
    date_basis: 'published_at' | 'uncovered'
  }>
  summary: {
    sample_count: number
    total_evidence_count: number
    dated_sample_count: number
    undated_sample_count: number
    excluded_low_confidence_count: number
    outside_range_count: number
    source_count: number
    employer_count: number
    batch_count: number
    covered_months: number
    coverage_ratio: number
    display_mode: 'snapshot' | 'trend'
    latest_period: string | null
    latest_posting_count: number
    latest_growth_rate: number | null
    last_observed_at: string | null
    latest_published_at: string | null
    confidence: 'low' | 'medium' | 'high'
    date_confidence: { high: number; medium: number; low: number }
    data_semantics: string
  }
  top_skills: Array<{ name: string; count: number }>
  sources: Array<{ name: string; count: number }>
  title_categories: Array<{ name: string; count: number }>
  batch_activity: Array<{
    run_id: number
    observed_at: string
    sample_count: number
    new_count: number
  }>
}
