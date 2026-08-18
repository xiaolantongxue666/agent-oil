<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import PositionManageView from './PositionManageView.vue'
import ProgramManageView from './ProgramManageView.vue'
import TaskManageView from './TaskManageView.vue'
import StudentListView from './StudentListView.vue'
import TrainingResultsView from './TrainingResultsView.vue'
import KnowledgeManageView from './KnowledgeManageView.vue'
import KnowledgeLibraryView from '@/views/student/KnowledgeLibraryView.vue'
import AbilityGraphView from '@/views/AbilityGraphView.vue'

const route = useRoute()
const section = computed(() => String(route.meta.workspace || 'industry'))
const groups = {
  industry: [
    { label: '岗位图谱', component: PositionManageView },
    { label: '能力图谱', component: AbilityGraphView },
    { label: '培养方案', component: ProgramManageView },
  ],
  training: [{ label: '实训任务设计', component: TaskManageView }],
  learning: [
    { label: '班级学习画像', component: StudentListView },
    { label: '教学实施复盘', component: TrainingResultsView },
  ],
  resources: [
    { label: '知识资源建设', component: KnowledgeManageView },
    { label: '权威资源浏览', component: KnowledgeLibraryView },
  ],
} as const

const sectionInfo = {
  industry: { eyebrow: '专业群能力建设链', title: '岗位与培养方案', description: '从产业岗位证据出发，形成岗位能力图谱并反向校准人才培养方案。', icon: 'OfficeBuilding', flow: ['产业证据', '岗位能力', '课程体系'] },
  training: { eyebrow: '教学实训设计', title: '实训任务与题库', description: '围绕岗位典型任务设计实训内容，AI 生成仅作草稿，须经教师审核后发布。', icon: 'Document', flow: ['任务设计', '题库审核', '发布实施'] },
  learning: { eyebrow: '学习成效诊断', title: '学情诊断与教学复盘', description: '从班级到个人识别能力薄弱点，将训练数据转化为可执行的教学改进行动。', icon: 'TrendCharts', flow: ['班级观察', '能力诊断', '教学改进'] },
  resources: { eyebrow: '可信教学资源', title: '知识资源建设', description: '建设具有来源、编号、章节和页码的专业教学依据，支撑问答与实训评价。', icon: 'Collection', flow: ['资源入库', '教师审核', '教学应用'] },
} as const

const tabs = computed(() => groups[section.value as keyof typeof groups] || groups.industry)
const info = computed(() => sectionInfo[section.value as keyof typeof sectionInfo] || sectionInfo.industry)
</script>

<template>
  <div class="ots-page workspace-page">
    <section class="workspace-hero">
      <div class="hero-icon"><el-icon><component :is="info.icon" /></el-icon></div>
      <div class="hero-copy"><span>{{ info.eyebrow }}</span><h2>{{ info.title }}</h2><p>{{ info.description }}</p></div>
      <div class="flow-steps"><template v-for="(step, index) in info.flow" :key="step"><span>{{ index + 1 }}</span><strong>{{ step }}</strong><el-icon v-if="index < info.flow.length - 1"><ArrowRight /></el-icon></template></div>
    </section>

    <section class="workspace-panel ots-card">
      <el-tabs :key="section" class="workspace-tabs">
        <el-tab-pane v-for="tab in tabs" :key="tab.label" :label="tab.label" lazy>
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
.workspace-panel { padding: 0 20px 20px; }
.workspace-tabs :deep(.el-tabs__header) { margin-bottom: 4px; }
.workspace-tabs :deep(.el-tabs__item) { height: 52px; padding: 0 22px; font-weight: 600; }
.workspace-tabs :deep(.el-tabs__content) { overflow: visible; }
.workspace-tabs :deep(.ots-page) { padding: 18px 0 0; }

@media (max-width: 1100px) { .workspace-hero { grid-template-columns: 50px 1fr; } .flow-steps { grid-column: 1 / -1; justify-self: start; } }
@media (max-width: 768px) { .workspace-hero { grid-template-columns: 42px 1fr; padding: 16px; } .hero-icon { width: 42px; height: 42px; } .flow-steps { width: 100%; overflow-x: auto; } .workspace-panel { padding: 0 14px 14px; } .workspace-tabs :deep(.el-tabs__item) { padding: 0 13px; } }
</style>
