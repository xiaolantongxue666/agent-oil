import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'

const studentChildren: RouteRecordRaw[] = [
  { path: 'student/dashboard', name: 'student-dashboard', component: () => import('@/views/student/DashboardView.vue'), meta: { roles: ['student'], title: '我的成长' } },
  { path: 'ability-graph', name: 'ability-graph', component: () => import('@/views/AbilityGraphView.vue'), meta: { title: '目标岗位能力图谱' } },
  { path: 'training', name: 'training-center', component: () => import('@/views/student/TrainingCenterView.vue'), meta: { roles: ['student'], title: '岗位情境实训' } },
  { path: 'training/:id', name: 'training-task-detail', component: () => import('@/views/student/TrainingTaskView.vue'), meta: { roles: ['student'], title: '训练任务' } },
  { path: 'training/session/:id', name: 'training-session', component: () => import('@/views/student/AITrainingView.vue'), meta: { roles: ['student'], title: 'AI 实训台' } },
  { path: 'training/result/:id', name: 'training-result', component: () => import('@/views/student/TrainingResultView.vue'), meta: { roles: ['student'], title: '训练结果' } },
  { path: 'profile', name: 'ability-profile', component: () => import('@/views/student/ProfileView.vue'), meta: { roles: ['student'], title: '岗位能力成长档案' } },
  { path: 'adaptive-learning', name: 'adaptive-learning', component: () => import('@/views/student/AdaptiveLearningView.vue'), meta: { roles: ['student'], title: '个性化学习路径' } },
  { path: 'knowledge', name: 'knowledge-qa', component: () => import('@/views/KnowledgeQAView.vue'), meta: { title: '岗位学习助手' } },
  { path: 'knowledge/library', name: 'knowledge-library', component: () => import('@/views/student/KnowledgeLibraryView.vue'), meta: { title: '专业资料库' } },
]

const teacherChildren: RouteRecordRaw[] = [
  { path: 'dashboard', name: 'teacher-dashboard', component: () => import('@/views/teacher/DashboardView.vue'), meta: { title: '教学驾驶舱' } },
  { path: 'industry', name: 'teacher-industry', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'industry', title: '岗位与培养方案' } },
  { path: 'training', name: 'teacher-training', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'training', title: '实训任务与题库' } },
  { path: 'learning', name: 'teacher-learning', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'learning', title: '学情诊断与教学复盘' } },
  { path: 'resources', name: 'teacher-resources', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'resources', title: '知识资源建设' } },
  { path: 'assistant', name: 'teacher-assistant', component: () => import('@/views/KnowledgeQAView.vue'), meta: { title: '智能助手' } },
  { path: 'students', name: 'teacher-students', component: () => import('@/views/teacher/StudentListView.vue'), meta: { title: '学生列表' } },
  { path: 'students/:id', name: 'teacher-student-profile', component: () => import('@/views/teacher/StudentProfileView.vue'), meta: { title: '学生画像' } },
  { path: 'tasks', name: 'teacher-tasks', component: () => import('@/views/teacher/TaskManageView.vue'), meta: { title: '任务管理' } },
  { path: 'tasks/:id/questions', name: 'teacher-question-bank', component: () => import('@/views/teacher/QuestionBankView.vue'), meta: { title: 'AI 题库生成与审核' } },
  { path: 'positions', name: 'teacher-positions', component: () => import('@/views/teacher/PositionManageView.vue'), meta: { title: '岗位图谱配置' } },
  { path: 'ability-graph', name: 'teacher-ability-graph', component: () => import('@/views/AbilityGraphView.vue'), meta: { title: '岗位能力图谱' } },
  { path: 'training-results', name: 'teacher-training-results', component: () => import('@/views/teacher/TrainingResultsView.vue'), meta: { title: '班级教学实施复盘' } },
  { path: 'programs', name: 'teacher-programs', component: () => import('@/views/teacher/ProgramManageView.vue'), meta: { title: '产业岗位与培养方案' } },
  { path: 'knowledge', name: 'teacher-knowledge', component: () => import('@/views/teacher/KnowledgeManageView.vue'), meta: { title: '知识库管理' } },
]

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: '登录 — 高水平专业群教学智能体平台' } },
  { path: '/', component: () => import('@/layouts/DefaultLayout.vue'), redirect: '/student/dashboard', children: studentChildren },
  { path: '/teacher', component: () => import('@/layouts/TeacherLayout.vue'), redirect: '/teacher/dashboard', meta: { roles: ['teacher', 'admin'] }, children: teacherChildren },
  { path: '/admin', component: () => import('@/layouts/AdminLayout.vue'), redirect: '/admin/dashboard', meta: { roles: ['admin'] }, children: [
    { path: 'dashboard', name: 'admin-dashboard', component: () => import('@/views/admin/AdminDashboardView.vue'), meta: { title: '系统总览' } },
    { path: 'users', name: 'admin-users', component: () => import('@/views/admin/AdminUsersView.vue'), meta: { title: '用户组织' } },
    { path: 'ai-system', name: 'admin-ai-system', component: () => import('@/views/admin/AdminFeaturesView.vue'), meta: { title: '功能控制' } },
    { path: 'llm-config', name: 'admin-llm-config', component: () => import('@/views/admin/AdminLlmConfigView.vue'), meta: { title: '教学智能体模型服务' } },
    { path: 'prompts', name: 'admin-prompts', component: () => import('@/views/admin/AdminPromptManageView.vue'), meta: { title: '教学策略工坊' } },
    { path: 'audit', name: 'admin-audit', component: () => import('@/views/admin/AdminAuditView.vue'), meta: { title: '审计运行' } },
    { path: 'assistant', name: 'admin-assistant', component: () => import('@/views/KnowledgeQAView.vue'), meta: { title: '智能助手' } },
    // 已废弃入口：重定向到 dashboard，避免旧书签 404
    { path: 'governance', redirect: '/admin/dashboard' },
    { path: 'review', redirect: '/admin/dashboard' },
  ] },
  { path: '/:pathMatch(.*)*', redirect: '/student/dashboard' },
]
const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.title) document.title = String(to.meta.title)
  if (to.meta.public) return true
  if (!auth.isAuthed) return { name: 'login', query: { redirect: to.fullPath } }
  const roles = to.matched.flatMap((record) => (record.meta.roles as string[] | undefined) || [])
  if (roles.length && (!auth.role || !roles.includes(auth.role))) return auth.isAdmin ? { name: 'admin-dashboard' } : auth.isStaff ? { name: 'teacher-dashboard' } : { name: 'student-dashboard' }
  if (to.meta.feature && auth.isAdmin) { const admin = useAdminStore(); try { await admin.loadFeatures() } catch { return { name: 'admin-dashboard', query: { notice: '功能配置暂不可用' } } }; if (!admin.isEnabled(String(to.meta.feature))) return { name: 'admin-dashboard', query: { notice: '该功能当前已停用' } } }
  return true
})
export default router
