<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { teacherApi } from '@/api'
import type { TeacherTaskOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const tasks = ref<TeacherTaskOut[]>([])
const router = useRouter()
const loading = ref(true)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)

const form = reactive({
  code: '',
  title: '',
  description: '',
  difficulty: 2,
  target_abilities: [] as string[],
  estimated_minutes: 15,
  max_follow_ups: 3,
  required_points: '' as string,
  reference_points: '' as string,
  scenario_text: '',
  initial_question: '',
})

const ABILITY_OPTIONS = Object.entries(ABILITY_LABELS).map(([key, label]) => ({
  value: key,
  label,
}))

function statusType(s: string) {
  return s === 'published' ? 'success' : s === 'draft' ? 'info' : 'warning'
}

function statusLabel(s: string) {
  const labels: Record<string, string> = { draft: '草稿', published: '已发布', archived: '已停用' }
  return labels[s] || s
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    code: '',
    title: '',
    description: '',
    difficulty: 2,
    target_abilities: [],
    estimated_minutes: 15,
    max_follow_ups: 3,
    required_points: '',
    reference_points: '',
    scenario_text: '',
    initial_question: '',
  })
  dialogVisible.value = true
}

function openEdit(task: TeacherTaskOut) {
  editingId.value = task.id
  Object.assign(form, {
    code: task.code,
    title: task.title,
    description: task.description,
    difficulty: task.difficulty,
    target_abilities: [...task.target_abilities],
    estimated_minutes: task.estimated_minutes,
    max_follow_ups: task.max_follow_ups,
    required_points: task.required_points.join('\n'),
    reference_points: task.reference_points.join('\n'),
    scenario_text: String(task.scenario.scenario_text || ''),
    initial_question: String(task.scenario.initial_question || ''),
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  submitting.value = true
  try {
    const body = {
      code: form.code,
      title: form.title,
      description: form.description,
      difficulty: form.difficulty,
      target_abilities: form.target_abilities,
      estimated_minutes: form.estimated_minutes,
      max_follow_ups: form.max_follow_ups,
      required_points: form.required_points.split('\n').filter(Boolean),
      reference_points: form.reference_points.split('\n').filter(Boolean),
      scenario: {
        scenario_text: form.scenario_text.trim(),
        initial_question: form.initial_question.trim(),
        safety_tip: '教学模拟，非真实生产数据。',
      },
    }
    if (editingId.value) {
      await teacherApi.updateTask(editingId.value, body)
    } else {
      await teacherApi.createTask(body)
    }
    dialogVisible.value = false
    await loadTasks()
  } catch {
    /* interceptor handles toast */
  } finally {
    submitting.value = false
  }
}

async function togglePublish(task: TeacherTaskOut) {
  const newStatus = task.status === 'published' ? 'archived' : 'published'
  try {
    await teacherApi.updateTask(task.id, { status: newStatus })
    await loadTasks()
  } catch {
    /* interceptor */
  }
}

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await teacherApi.tasks()
  } finally {
    loading.value = false
  }
}

onMounted(loadTasks)
</script>

<template>
  <div class="ots-page" v-loading="loading">
    <div class="page-header">
      <h2 style="margin: 0">任务管理</h2>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建任务
      </el-button>
    </div>

    <div class="ots-card">
      <el-table :data="tasks" stripe>
        <el-table-column prop="code" label="编号" width="100" />
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column label="难度" width="80" align="center">
          <template #default="{ row }">
            <el-rate v-model="row.difficulty" disabled :max="5" />
          </template>
        </el-table-column>
        <el-table-column label="目标能力" min-width="200">
          <template #default="{ row }">
            <el-tag
              v-for="ab in row.target_abilities"
              :key="ab"
              size="small"
              effect="plain"
              style="margin: 2px"
            >
              {{ ABILITY_LABELS[ab as AbilityKey] || ab }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="estimated_minutes" label="时长(分)" width="80" align="center" />
        <el-table-column label="选择题" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.question_count ? 'success' : 'info'" size="small">
              {{ row.question_count }} 题
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="225" align="center">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="router.push(`/teacher/tasks/${row.id}/questions`)">题库</el-button>
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button
              text
              :type="row.status === 'published' ? 'danger' : 'success'"
              size="small"
              @click="togglePublish(row)"
            >
              {{ row.status === 'published' ? '停用' : '发布' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑任务' : '新建任务'"
      width="600px"
      destroy-on-close
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="任务编号" required>
          <el-input v-model="form.code" :disabled="!!editingId" placeholder="如 TT-09" />
        </el-form-item>
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="任务标题" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="任务描述" />
        </el-form-item>
        <el-form-item label="难度">
          <el-slider v-model="form.difficulty" :min="1" :max="5" :step="1" show-stops />
        </el-form-item>
        <el-form-item label="目标能力">
          <el-select v-model="form.target_abilities" multiple placeholder="选择能力维度">
            <el-option
              v-for="opt in ABILITY_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="预计时间(分)">
          <el-input-number v-model="form.estimated_minutes" :min="5" :max="120" :step="5" />
        </el-form-item>
        <el-form-item label="兼容轮次">
          <el-input-number v-model="form.max_follow_ups" :min="1" :max="5" />
        </el-form-item>
        <el-form-item label="必答要点">
          <el-input
            v-model="form.required_points"
            type="textarea"
            :rows="3"
            placeholder="每行一个必答要点"
          />
        </el-form-item>
        <el-form-item label="参考答案">
          <el-input
            v-model="form.reference_points"
            type="textarea"
            :rows="3"
            placeholder="每行一个参考答案要点"
          />
        </el-form-item>
        <el-form-item label="实训情境" required>
          <el-input
            v-model="form.scenario_text"
            type="textarea"
            :rows="4"
            placeholder="面向学生展示的脱敏教学情境"
          />
        </el-form-item>
        <el-form-item label="旧版问题">
          <el-input
            v-model="form.initial_question"
            type="textarea"
            :rows="2"
            placeholder="仅兼容历史文本任务；当前学生实训读取数据库选择题"
          />
        </el-form-item>
        <el-alert
          title="当前学生端只展示已配置数据库选择题的已发布任务；题量以任务列表中的“选择题”列为准。"
          type="info"
          :closable="false"
          show-icon
        />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingId ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
</style>
