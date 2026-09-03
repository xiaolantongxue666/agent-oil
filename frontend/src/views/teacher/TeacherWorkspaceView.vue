<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Component } from 'vue'
import PositionManageView from './PositionManageView.vue'
import ProgramManageView from './ProgramManageView.vue'
import ProfessionalGroupView from './ProfessionalGroupView.vue'
import TaskManageView from './TaskManageView.vue'
import StudentListView from './StudentListView.vue'
import TrainingResultsView from './TrainingResultsView.vue'
import KnowledgeManageView from './KnowledgeManageView.vue'
import KnowledgeLibraryView from '@/views/student/KnowledgeLibraryView.vue'
import AbilityGraphView from '@/views/AbilityGraphView.vue'

const route = useRoute()
const router = useRouter()
const section = computed(() => String(route.meta.workspace || 'industry'))

interface WorkspaceTab {
  key: string
  label: string
  component: Component
}

const groups: Record<string, WorkspaceTab[]> = {
  industry: [
    { key: 'group', label: '专业群驾驶舱', component: ProfessionalGroupView },
    { key: 'positions', label: '产业岗位洞察', component: PositionManageView },
    { key: 'ability', label: '岗位能力图谱', component: AbilityGraphView },
    { key: 'program', label: '培养方案与调整', component: ProgramManageView },
  ],
  training: [
    { key: 'tasks', label: '实训任务设计', component: TaskManageView },
  ],
  learning: [
    { key: 'class', label: '班级学情诊断', component: StudentListView },
    { key: 'review', label: '教学实施复盘', component: TrainingResultsView },
  ],
  resources: [
    { key: 'knowledge', label: '知识资源建设', component: KnowledgeManageView },
    { key: 'authoritative', label: '权威教学依据', component: KnowledgeLibraryView },
  ],
}

const sectionInfo: Record<string, { eyebrow: string; title: string; description: string; icon: string; flow: string[] }> = {
  industry: { eyebrow: '产业需求传导首站', title: '专业群建设', description: '从产业岗位证据出发，识别专业群能力需求，分析课程供给差距，并形成可审核的培养方案调整依据。', icon: 'OfficeBuilding', flow: ['产业岗位证据', '能力缺口 Gap', '调整草案', '教师审核'] },
  training: { eyebrow: '教学实训设计', title: '教学实训', description: '围绕岗位典型任务设计实训内容，AI 生成仅作草稿，须经教师审核后发布。', icon: 'Document', flow: ['任务设计', '题库审核', '发布实施'] },
  learning: { eyebrow: '学习成效诊断', title: '学情与评价', description: '从班级学情到个人技能档案，定位薄弱能力并形成可执行的教学改进行动。', icon: 'TrendCharts', flow: ['班级诊断', '学生技能档案', '教学改进'] },
  resources: { eyebrow: '可信教学资源', title: '教学资源', description: '建设具有来源、编号、章节和页码的专业教学依据，支撑问答与实训评价。', icon: 'Collection', flow: ['资源入库', '教师审核', '教学应用'] },
}

const tabs = computed(() => groups[section.value] ?? groups.industry)
const info = computed(() => sectionInfo[section.value] ?? sectionInfo.industry)

// tab 状态进 URL：刷新/前进后退可恢复；非法 tab 回退首个；默认不带 tab 即首项
const activeTab = computed(() => {
  const q = String(route.query.tab || '')
  return tabs.value.some((tab) => tab.key === q) ? q : tabs.value[0].key
})

function onTabChange(key: string | number) {
  router.push({ query: { ...route.query, tab: String(key) } })
}

watch(
  () => [section.value, route.query.tab] as const,
  () => {
    const q = String(route.query.tab || '')
    if (q && !tabs.value.some((tab) => tab.key === q)) {
      router.replace({ query: { ...route.query, tab: tabs.value[0].key } })
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="ots-page workspace-page">
    <section class="workspace-hero">
      <div class="hero-icon"><el-icon><component :is="info.icon" /></el-icon></div>
      <div class="hero-copy"><span>{{ info.eyebrow }}</span><h2>{{ info.title }}</h2><p>{{ info.description }}</p></div>
      <div class="flow-steps"><template v-for="(step, index) in info.flow" :key="step"><span>{{ index + 1 }}</span><strong>{{ step }}</strong><el-icon v-if="index < info.flow.length - 1"><ArrowRight /></el-icon></template></div>
    </section>

    <!-- Phase 8：内容区扁平化——业务 View 自带卡片，外层不再套重边框大卡（消除双层卡片感） -->
    <section class="workspace-panel">
      <el-tabs :key="section" class="workspace-tabs" :model-value="activeTab" @tab-change="onTabChange">
        <el-tab-pane v-for="tab in tabs" :key="tab.key" :name="tab.key" :label="tab.label" lazy>
          <component :is="tab.component" />
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<style scoped>
.workspace-page { padding-top: 20px; }
.workspace-hero { display: grid; grid-template-columns: 54px minmax(260px, 1fr) auto; align-items: center; gap: 15px; margin-bottom: 16px; padding: 20px 22px; border: 1px solid #dce8ef; border-radius: var(--ots-radius); background: linear-gradient(115deg, #f4f8fc, #fff 62%); }
.hero-icon { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 14px; background: var(--ots-education-soft); color: var(--ots-education); font-size: 24px; }
.hero-copy > span { color: var(--ots-education); font-size: 11px; font-weight: 600; letter-spacing: .7px; }
.hero-copy h2 { margin: 4px 0 5px; color: #123f5d; font-size: 22px; }
.hero-copy p { margin: 0; color: var(--ots-text-secondary); font-size: 12px; }
.flow-steps { display: flex; align-items: center; gap: 7px; padding: 9px 11px; border: 1px solid var(--ots-border); border-radius: 9px; background: #fff; }
.flow-steps span { display: grid; place-items: center; width: 21px; height: 21px; border-radius: 50%; background: #e9f3f6; color: var(--ots-primary); font-size: 9px; }
.flow-steps strong { font-size: 10px; white-space: nowrap; }
.flow-steps .el-icon { color: var(--ots-text-secondary); font-size: 12px; }
.workspace-panel { padding: 0; }
.workspace-tabs :deep(.el-tabs__header) { margin-bottom: 4px; }
.workspace-tabs :deep(.el-tabs__item) { height: 52px; padding: 0 22px; font-weight: 600; }
.workspace-tabs :deep(.el-tabs__content) { overflow: visible; }
.workspace-tabs :deep(.ots-page) { padding: 18px 0 0; }

@media (max-width: 1280px) { .workspace-tabs :deep(.el-tabs__item) { padding: 0 16px; } }
@media (max-width: 1100px) { .workspace-hero { grid-template-columns: 50px 1fr; } .flow-steps { grid-column: 1 / -1; justify-self: start; } }
@media (max-width: 768px) { .workspace-hero { grid-template-columns: 42px 1fr; padding: 16px; } .hero-icon { width: 42px; height: 42px; } .flow-steps { width: 100%; overflow-x: auto; } .workspace-tabs :deep(.el-tabs__item) { padding: 0 13px; font-size: 13px; } .workspace-tabs :deep(.el-tabs__nav-wrap) { overflow-x: auto; } }
</style>
