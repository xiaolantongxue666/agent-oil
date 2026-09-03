import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'

const studentChildren: RouteRecordRaw[] = [
  { path: 'student/dashboard', name: 'student-dashboard', component: () => import('@/views/student/DashboardView.vue'), meta: { roles: ['student'], title: '我的成长' } },
  // 比赛导演模式仅保留教师入口 /teacher/competition；旧学生链接兼容 redirect，不 404
  { path: 'competition', redirect: '/student/dashboard' },
  { path: 'ability-graph', name: 'ability-graph', component: () => import('@/views/AbilityGraphView.vue'), meta: { title: '目标岗位能力' } },
  { path: 'training', name: 'training-center', component: () => import('@/views/student/TrainingCenterView.vue'), meta: { roles: ['student'], title: '岗位情境训练' } },
  { path: 'training/:id', name: 'training-task-detail', component: () => import('@/views/student/TrainingTaskView.vue'), meta: { roles: ['student'], title: '训练任务' } },
  { path: 'training/session/:id', name: 'training-session', component: () => import('@/views/student/AITrainingView.vue'), meta: { roles: ['student'], title: '岗位情境训练' } },
  { path: 'training/result/:id', name: 'training-result', component: () => import('@/views/student/TrainingResultView.vue'), meta: { roles: ['student'], title: '训练结果' } },
  { path: 'simulation', name: 'simulation-center', component: () => import('@/views/student/SimulationCenterView.vue'), meta: { roles: ['student'], title: '岗位仿真实训' } },
  { path: 'simulation/:code', name: 'simulation-workbench', component: () => import('@/views/student/SimulationWorkbenchView.vue'), meta: { roles: ['student'], title: '岗位仿真实训' } },
  { path: 'profile', name: 'ability-profile', component: () => import('@/views/student/ProfileView.vue'), meta: { roles: ['student'], title: '技能证据档案' } },
  { path: 'adaptive-learning', name: 'adaptive-learning', component: () => import('@/views/student/AdaptiveLearningView.vue'), meta: { roles: ['student'], title: '个性化学习路径' } },
  { path: 'knowledge', name: 'knowledge-qa', component: () => import('@/views/KnowledgeQAView.vue'), meta: { title: '岗位学习助手' } },
  { path: 'knowledge/library', name: 'knowledge-library', component: () => import('@/views/student/KnowledgeLibraryView.vue'), meta: { title: '专业资料库' } },
]

const teacherChildren: RouteRecordRaw[] = [
  { path: 'dashboard', name: 'teacher-dashboard', component: () => import('@/views/teacher/DashboardView.vue'), meta: { title: '教学驾驶舱' } },
  // 导演模式 teacher-only：全局守卫对父子 roles 取并集（flatMap），meta.roles 无法单独收紧子路由，
  // 故用 beforeEnter 做等价最小限制；admin 直访被送回 admin home，student 已在父路由守卫被拦
  { path: 'competition', name: 'teacher-competition', component: () => import('@/views/CompetitionView.vue'), meta: { title: '竞赛展示' }, beforeEnter: () => { const auth = useAuthStore(); return auth.role === 'teacher' ? true : auth.isAdmin ? { path: '/admin/users' } : auth.isStaff ? { name: 'teacher-dashboard' } : { name: 'student-dashboard' } } },
  { path: 'industry', name: 'teacher-industry', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'industry', title: '专业群建设' } },
  { path: 'training', name: 'teacher-training', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'training', title: '教学实训' } },
  { path: 'learning', name: 'teacher-learning', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'learning', title: '学情与评价' } },
  { path: 'resources', name: 'teacher-resources', component: () => import('@/views/teacher/TeacherWorkspaceView.vue'), meta: { workspace: 'resources', title: '教学资源' } },
  // Phase 3：旧独立入口收敛为 Workspace Tab（redirect 保留原 query，如岗位图谱下钻 ?position=）
  { path: 'professional-group', redirect: (to) => ({ path: '/teacher/industry', query: { ...to.query, tab: 'group' } }) },
  { path: 'positions', redirect: (to) => ({ path: '/teacher/industry', query: { ...to.query, tab: 'positions' } }) },
  { path: 'ability-graph', redirect: (to) => ({ path: '/teacher/industry', query: { ...to.query, tab: 'ability' } }) },
  { path: 'programs', redirect: (to) => ({ path: '/teacher/industry', query: { ...to.query, tab: 'program' } }) },
  { path: 'training-results', redirect: (to) => ({ path: '/teacher/learning', query: { ...to.query, tab: 'review' } }) },
  { path: 'assistant', name: 'teacher-assistant', component: () => import('@/views/KnowledgeQAView.vue'), meta: { title: '智能助手' } },
  { path: 'students', name: 'teacher-students', component: () => import('@/views/teacher/StudentListView.vue'), meta: { title: '班级学情诊断' } },
  { path: 'students/:id', name: 'teacher-student-profile', component: () => import('@/views/teacher/StudentProfileView.vue'), meta: { title: '学生技能档案' } },
  { path: 'tasks', name: 'teacher-tasks', component: () => import('@/views/teacher/TaskManageView.vue'), meta: { title: '实训任务设计' } },
  { path: 'tasks/:id/questions', name: 'teacher-question-bank', component: () => import('@/views/teacher/QuestionBankView.vue'), meta: { title: 'AI 题库生成与审核' } },
  { path: 'knowledge', name: 'teacher-knowledge', component: () => import('@/views/teacher/KnowledgeManageView.vue'), meta: { title: '知识资源建设' } },
]

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: '登录 — 高水平专业群教学智能体平台' } },
  { path: '/', component: () => import('@/layouts/DefaultLayout.vue'), redirect: '/student/dashboard', meta: { roles: ['student'] }, children: studentChildren },
  { path: '/teacher', component: () => import('@/layouts/TeacherLayout.vue'), redirect: '/teacher/dashboard', meta: { roles: ['teacher', 'admin'] }, children: teacherChildren },
  { path: '/admin', component: () => import('@/layouts/AdminLayout.vue'), redirect: '/admin/users', meta: { roles: ['admin'] }, children: [
    { path: 'users', name: 'admin-users', component: () => import('@/views/admin/AdminUsersView.vue'), meta: { title: '组织与用户' } },
    // 管理员不参与比赛主演示：导演模式唯一入口在教师端 /teacher/competition
    { path: 'competition', redirect: '/admin/users' },
    { path: 'ai-system', name: 'admin-ai-system', component: () => import('@/views/admin/AdminFeaturesView.vue'), meta: { title: '功能控制' } },
    { path: 'llm-config', name: 'admin-llm-config', component: () => import('@/views/admin/AdminLlmConfigView.vue'), meta: { title: '教学智能体模型服务' } },
    { path: 'prompts', name: 'admin-prompts', component: () => import('@/views/admin/AdminPromptManageView.vue'), meta: { title: '教学策略工坊' } },
    { path: 'assistant', name: 'admin-assistant', component: () => import('@/views/KnowledgeQAView.vue'), meta: { title: '智能助手' } },
    // 已废弃入口：重定向到组织与用户，避免旧书签 404
    { path: 'governance', redirect: '/admin/users' },
    { path: 'review', redirect: '/admin/users' },
    { path: 'dashboard', redirect: '/admin/users' },
    { path: 'audit', redirect: '/admin/users' },
  ] },
  { path: '/:pathMatch(.*)*', redirect: roleHome },
]

// 未匹配路径不再统一踢到学生首页，按当前角色回各自工作台
function roleHome() {
  const auth = useAuthStore()
  if (auth.isAdmin) return { path: '/admin/users' }
  if (auth.role === 'teacher') return { name: 'teacher-dashboard' }
  if (auth.isAuthed) return { name: 'student-dashboard' }
  return { name: 'login' }
}

const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.title) document.title = String(to.meta.title)
  if (to.meta.public) return true
  if (!auth.isAuthed) return { name: 'login', query: { redirect: to.fullPath } }
  const roles = to.matched.flatMap((record) => (record.meta.roles as string[] | undefined) || [])
  if (roles.length && (!auth.role || !roles.includes(auth.role))) return auth.isAdmin ? { path: '/admin/users' } : auth.isStaff ? { name: 'teacher-dashboard' } : { name: 'student-dashboard' }
  if (to.meta.feature && auth.isAdmin) { const admin = useAdminStore(); try { await admin.loadFeatures() } catch { return { path: '/admin/users', query: { notice: '功能配置暂不可用' } } }; if (!admin.isEnabled(String(to.meta.feature))) return { path: '/admin/users', query: { notice: '该功能当前已停用' } } }
  return true
})
export default router
