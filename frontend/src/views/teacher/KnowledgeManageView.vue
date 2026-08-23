<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeApi } from '@/api'
import MarkdownContent from '@/components/MarkdownContent.vue'
import type { KnowledgeChunkOut, KnowledgeItemOut, KnowledgeStatsOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const items = ref<KnowledgeItemOut[]>([])
const stats = ref<KnowledgeStatsOut | null>(null)
const loading = ref(true)
const keyword = ref('')
const filterAbility = ref('')
const filterSource = ref('authority')
const currentPage = ref(1)
const total = ref(0)
const pageSize = ref(20)

const detailVisible = ref(false)
const detailLoading = ref(false)
const selectedDetail = ref<KnowledgeItemOut | null>(null)
const chunksLoading = ref(false)
const knowledgeChunks = ref<KnowledgeChunkOut[]>([])
const chunkEnabledCount = ref(0)
const chunkKnowledgePoints = ref<Array<{
  id: number; code: string; name: string; ability: string
}>>([])
const savingChunkIds = ref<number[]>([])
const normalizingHtmlTables = ref(false)

// 新增表单（手动输入）
const addVisible = ref(false)
const addForm = ref({
  title: '',
  content: '',
  ability: 'process_understanding',
  source_type: 'teacher_upload',
  source_name: '教师上传',
  difficulty: 1,
})
const submitting = ref(false)

// 文件导入
const uploadVisible = ref(false)
const uploading = ref(false)
const AUTO_ABILITY = '__auto__'
// 默认自动识别；选择具体维度时仅作为同分候选的轻微偏向。
const uploadAbility = ref(AUTO_ABILITY)
const uploadSourceName = ref('')
const uploadDifficulty = ref(1)
const uploadResult = ref<{
  id: number
  file_name: string; file_type: string; file_size: number
  text_length: number; page_count: number; vector_points: number
  chunk_count: number; enabled_chunk_count: number; disabled_chunk_count: number
  chunk_abilities: string[]
} | null>(null)

const abilityOptions = computed(() =>
  Object.entries(ABILITY_LABELS).map(([key, label]) => ({ value: key, label }))
)

const acceptExtensions = '.pdf,.docx,.txt,.md,.markdown'

async function loadItems() {
  loading.value = true
  try {
    const res = await knowledgeApi.list({
      keyword: keyword.value || undefined,
      ability: filterAbility.value || undefined,
      source_type: filterSource.value && filterSource.value !== 'authority'
        ? filterSource.value
        : undefined,
      authority_only: filterSource.value === 'authority' || undefined,
      page: currentPage.value,
      page_size: pageSize.value,
    })
    items.value = res.items
    total.value = res.total
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await knowledgeApi.stats()
  } catch { /* ignore */ }
}

function abilityLabel(key: string) {
  return ABILITY_LABELS[key as AbilityKey] || key || '未分类'
}

function itemAbilities(item: KnowledgeItemOut) {
  return item.chunk_abilities || (item.ability ? [item.ability] : [])
}

function difficultyStars(d: number) {
  return '★'.repeat(d) + '☆'.repeat(Math.max(0, 5 - d))
}

function sourceTypeLabel(sourceType: string) {
  const labels: Record<string, string> = {
    national_occupational_standard: '国家职业标准',
    law: '法律法规',
    national_standard: '国家标准',
    teacher_upload: '教师录入',
    file_import: '文件导入',
    demo: '演示数据',
  }
  return labels[sourceType] || sourceType || '未分类'
}

function onSearch() {
  currentPage.value = 1
  loadItems()
}

function onPageSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1
  loadItems()
}

async function openDetail(item: KnowledgeItemOut) {
  selectedDetail.value = item
  detailVisible.value = true
  detailLoading.value = true
  try {
    selectedDetail.value = await knowledgeApi.detail(item.id)
    if (selectedDetail.value.source_type === 'file_import') {
      await loadChunks(item.id)
    } else {
      knowledgeChunks.value = []
      chunkEnabledCount.value = 0
    }
  } catch {
    ElMessage.error('知识详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function loadChunks(itemId: number) {
  chunksLoading.value = true
  try {
    const result = await knowledgeApi.chunks(itemId)
    knowledgeChunks.value = result.items
    chunkEnabledCount.value = result.enabled
    chunkKnowledgePoints.value = result.knowledge_points
  } catch {
    knowledgeChunks.value = []
    ElMessage.error('章节分块加载失败')
  } finally {
    chunksLoading.value = false
  }
}

async function normalizeHtmlTables() {
  if (!selectedDetail.value || normalizingHtmlTables.value) return
  try {
    await ElMessageBox.confirm(
      '这会将原始 HTML 表格转为 Markdown 表格，并重新生成分块、知识点建议和向量索引。现有分块需要重新审核，是否继续？',
      '修复 MinerU 表格',
      { type: 'warning', confirmButtonText: '重新分块', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  normalizingHtmlTables.value = true
  try {
    const result = await knowledgeApi.normalizeHtmlTables(selectedDetail.value.id)
    if (!result.changed) {
      ElMessage.info(result.message || '未发现需要修复的 HTML 表格')
      return
    }
    selectedDetail.value = await knowledgeApi.detail(selectedDetail.value.id)
    await loadChunks(selectedDetail.value.id)
    ElMessage.success(`已生成 ${result.chunk_count} 个新分块，请审核知识点映射和启用状态`)
  } catch {
    ElMessage.error('HTML 表格修复失败，请稍后重试')
  } finally {
    normalizingHtmlTables.value = false
  }
}

async function updateChunkEnabled(chunk: KnowledgeChunkOut, enabled: boolean) {
  savingChunkIds.value.push(chunk.id)
  try {
    const result = await knowledgeApi.updateChunk(chunk.id, { enabled })
    Object.assign(chunk, result.chunk)
    chunkEnabledCount.value = knowledgeChunks.value.filter((item) => item.enabled).length
    ElMessage.success(enabled ? '该知识块已启用并更新检索索引' : '该知识块已停用并移出检索索引')
  } catch {
    chunk.enabled = !enabled
    ElMessage.error('知识块状态更新失败')
  } finally {
    savingChunkIds.value = savingChunkIds.value.filter((id) => id !== chunk.id)
  }
}

async function updateChunkPoint(chunk: KnowledgeChunkOut, pointId: number | null) {
  savingChunkIds.value.push(chunk.id)
  try {
    const result = await knowledgeApi.updateChunk(chunk.id, { knowledge_point_id: pointId })
    Object.assign(chunk, result.chunk)
    if (selectedDetail.value) {
      selectedDetail.value.chunk_abilities = Array.from(new Set(
        knowledgeChunks.value
          .filter((item) => item.knowledge_point_id && item.ability)
          .map((item) => item.ability),
      )).sort()
    }
    ElMessage.success('知识点映射已更新')
  } catch {
    if (selectedDetail.value) await loadChunks(selectedDetail.value.id)
    ElMessage.error('知识点映射更新失败')
  } finally {
    savingChunkIds.value = savingChunkIds.value.filter((id) => id !== chunk.id)
  }
}

async function reviewUploadedChunks() {
  if (!uploadResult.value) return
  const detail = await knowledgeApi.detail(uploadResult.value.id)
  uploadVisible.value = false
  await openDetail(detail)
}

function openAdd() {
  addForm.value = {
    title: '',
    content: '',
    ability: 'process_understanding',
    source_type: 'teacher_upload',
    source_name: '教师上传',
    difficulty: 1,
  }
  addVisible.value = true
}

async function submitAdd() {
  if (!addForm.value.title.trim() || !addForm.value.content.trim()) {
    ElMessage.warning('标题和内容不能为空')
    return
  }
  submitting.value = true
  try {
    await knowledgeApi.create(addForm.value)
    ElMessage.success('知识条目已添加')
    addVisible.value = false
    loadItems()
    loadStats()
  } catch {
    ElMessage.error('添加失败')
  } finally {
    submitting.value = false
  }
}

// ---- 文件导入 ----

function openUpload() {
  uploadResult.value = null
  uploadAbility.value = AUTO_ABILITY
  uploadSourceName.value = ''
  uploadDifficulty.value = 1
  uploadVisible.value = true
}

async function handleUpload(options: any) {
  const file = options.file as File
  uploading.value = true
  uploadResult.value = null

  const formData = new FormData()
  formData.append('file', file)
  formData.append('ability', uploadAbility.value === AUTO_ABILITY ? '' : uploadAbility.value)
  formData.append('source_name', uploadSourceName.value || file.name)
  formData.append('difficulty', String(uploadDifficulty.value))

  try {
    const res = await knowledgeApi.upload(formData)
    uploadResult.value = res
    ElMessage.success(
      `已识别 ${res.chunk_count} 个章节块，建议启用 ${res.enabled_chunk_count} 个，请继续审核`,
    )
    loadItems()
    loadStats()
  } catch (err: any) {
    const msg = err?.message || err?.detail || '文件导入失败'
    ElMessage.error(msg)
  } finally {
    uploading.value = false
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

async function handleDelete(item: KnowledgeItemOut) {
  try {
    await ElMessageBox.confirm(
      `确定删除知识条目「${item.title}」？此操作不可恢复。`,
      '确认删除',
      { type: 'warning' }
    )
    await knowledgeApi.delete(item.id)
    ElMessage.success('已删除')
    loadItems()
    loadStats()
  } catch { /* cancelled */ }
}

onMounted(() => {
  loadItems()
  loadStats()
})
</script>

<template>
  <div class="ots-page knowledge-page" v-loading="loading">
    <div class="page-header">
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div>
          <h2 style="margin: 0">📚 知识库管理</h2>
          <p class="text-secondary" style="margin: 4px 0 0">管理专业知识文档，支持手动新增和文件导入。</p>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button type="success" @click="openUpload">📁 导入文件</el-button>
          <el-button type="primary" @click="openAdd">+ 添加条目</el-button>
        </div>
      </div>
    </div>

    <!-- 统计概览 -->
    <div v-if="stats" class="stats-row">
      <div class="ots-card stat-card">
        <div class="stat-num">{{ stats.total }}</div>
        <div class="stat-label">知识条目</div>
      </div>
      <div class="ots-card stat-card">
        <div class="stat-num">{{ stats.embedded }}</div>
        <div class="stat-label">已向量化</div>
      </div>
      <div class="ots-card stat-card authority-stat" @click="filterSource = 'authority'; onSearch()">
        <div class="stat-num">{{ stats.authoritative }}</div>
        <div class="stat-label">权威知识（点击查看）</div>
      </div>
      <div class="ots-card stat-card stat-breakdown">
        <div class="breakdown-title">按能力维度</div>
        <div v-for="(count, ability) in stats.by_ability" :key="ability" class="breakdown-item">
          <span>{{ abilityLabel(String(ability)) }}</span>
          <span class="breakdown-count">{{ count }}</span>
        </div>
      </div>
      <div class="ots-card stat-card stat-breakdown">
        <div class="breakdown-title">按来源类型</div>
        <div v-for="(count, source) in stats.by_source" :key="source" class="breakdown-item">
          <span>{{ source }}</span>
          <span class="breakdown-count">{{ count }}</span>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="ots-card filter-bar">
      <el-input
        v-model="keyword"
        placeholder="搜索标题或内容..."
        clearable
        style="width: 280px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      >
        <template #prefix>🔍</template>
      </el-input>
      <el-select v-model="filterAbility" placeholder="按能力维度筛选" clearable @change="onSearch" style="width: 180px">
        <el-option v-for="opt in abilityOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-model="filterSource" placeholder="按来源筛选" clearable @change="onSearch" style="width: 180px">
        <el-option label="全部来源" value="" />
        <el-option label="权威知识" value="authority" />
        <el-option label="国家职业标准" value="national_occupational_standard" />
        <el-option label="法律法规" value="law" />
        <el-option label="国家标准" value="national_standard" />
        <el-option label="教师录入" value="teacher_upload" />
        <el-option label="文件导入" value="file_import" />
        <el-option label="演示数据" value="demo" />
      </el-select>
      <el-button type="primary" @click="onSearch">搜索</el-button>
      <span class="text-secondary" style="margin-left: auto">共 {{ total }} 条</span>
    </div>

    <!-- 知识列表（表格） -->
    <el-table :data="items" stripe style="width: 100%" v-loading="loading">
      <el-table-column prop="knowledge_id" label="编号" width="140" />
      <el-table-column prop="title" label="标题" min-width="200">
        <template #default="{ row }">
          <el-button link type="primary" style="font-weight: 500" @click="openDetail(row)">
            {{ row.title }}
          </el-button>
          <el-tag v-if="row.file_name" size="small" type="warning" style="margin-left: 6px">
            {{ row.file_type?.toUpperCase() }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="能力维度" width="120">
        <template #default="{ row }">
          <template v-if="itemAbilities(row).length">
            <el-tag
              v-for="ability in itemAbilities(row)"
              :key="ability"
              size="small"
              type="info"
              effect="plain"
              style="margin: 2px"
            >{{ abilityLabel(ability) }}</el-tag>
          </template>
          <el-tag v-else size="small" type="warning" effect="plain">待识别</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" min-width="190">
        <template #default="{ row }">
          <div><el-tag size="small" effect="plain">{{ sourceTypeLabel(row.source_type) }}</el-tag></div>
          <div class="text-secondary source-name">{{ row.source_name }}</div>
        </template>
      </el-table-column>
      <el-table-column label="向量化" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.vector_embedded ? 'success' : 'info'" size="small">
            {{ row.vector_embedded ? '✓' : '—' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="难度" width="100" align="center">
        <template #default="{ row }">
          <span style="color: #f5a623">{{ difficultyStars(row.difficulty) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="center">
        <template #default="{ row }">
          <el-button type="primary" size="small" text @click.stop="openDetail(row)">
            查看
          </el-button>
          <el-button type="danger" size="small" text @click.stop="handleDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="pagination">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :page-sizes="[12, 20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="loadItems"
        @size-change="onPageSizeChange"
      />
    </div>

    <el-dialog v-model="detailVisible" title="知识详情与分块审核" width="1100px" top="5vh">
      <div v-loading="detailLoading">
        <el-descriptions v-if="selectedDetail" :column="2" border>
          <el-descriptions-item label="知识编号">{{ selectedDetail.knowledge_id }}</el-descriptions-item>
          <el-descriptions-item label="涉及能力维度">
            <template v-if="itemAbilities(selectedDetail).length">
              <el-tag v-for="ability in itemAbilities(selectedDetail)" :key="ability" size="small" style="margin-right: 4px">
                {{ abilityLabel(ability) }}
              </el-tag>
            </template>
            <el-tag v-else size="small" type="warning">待识别</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedDetail.source_type === 'file_import'" label="首选能力维度">
            {{ selectedDetail.ability ? abilityLabel(selectedDetail.ability) : '未指定（自动识别）' }}
          </el-descriptions-item>
          <el-descriptions-item label="标题" :span="2">{{ selectedDetail.title }}</el-descriptions-item>
          <el-descriptions-item label="来源名称" :span="2">{{ selectedDetail.source_name }}</el-descriptions-item>
          <el-descriptions-item label="来源编号">{{ selectedDetail.source_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="PDF 页码">{{ selectedDetail.page ? `第 ${selectedDetail.page} 页` : '—' }}</el-descriptions-item>
          <el-descriptions-item label="章节" :span="2">{{ selectedDetail.chapter || '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联知识点" :span="2">{{ selectedDetail.knowledge_point || '—' }}</el-descriptions-item>
          <el-descriptions-item v-if="selectedDetail.source_type === 'file_import'" label="文件内容" :span="2">
            已按章节/条款分块，请在下方展开分块查看原文并完成审核。
          </el-descriptions-item>
        </el-descriptions>

        <template v-if="selectedDetail?.source_type === 'file_import'">
          <el-divider content-position="left">章节/条款分块审核</el-divider>
          <div class="chunk-summary">
            <span>共 {{ knowledgeChunks.length }} 块，已启用 {{ chunkEnabledCount }} 块</span>
            <span class="chunk-summary-actions">
              <span class="text-secondary">仅启用块进入专业问答检索；已选择知识点的启用块会关联岗位图谱。</span>
              <el-button
                v-if="selectedDetail?.content.toLowerCase().includes('<table')"
                size="small"
                type="warning"
                plain
                :loading="normalizingHtmlTables"
                @click="normalizeHtmlTables"
              >
                修复 HTML 表格并重新分块
              </el-button>
            </span>
          </div>
          <el-table
            v-loading="chunksLoading"
            :data="knowledgeChunks"
            row-key="id"
            stripe
            max-height="520"
          >
            <el-table-column type="expand" width="42">
              <template #default="{ row }">
                <MarkdownContent class="chunk-full-content" :content="row.content" />
              </template>
            </el-table-column>
            <el-table-column label="#" prop="chunk_index" width="55" />
            <el-table-column label="章节/条款" min-width="210">
              <template #default="{ row }">
                <div class="chunk-heading">{{ row.heading || `分块 ${row.chunk_index + 1}` }}</div>
                <div class="text-secondary chunk-page">
                  <template v-if="row.page_start">
                    第 {{ row.page_start }}<template v-if="row.page_end && row.page_end !== row.page_start">–{{ row.page_end }}</template> 页
                  </template>
                  <template v-else>页码未知</template>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="系统建议" min-width="220">
              <template #default="{ row }">
                <div class="chunk-reason">{{ row.match_reason }}</div>
                <el-tag v-if="row.match_score" size="small" type="info" effect="plain">
                  匹配分 {{ row.match_score }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="图谱知识点" min-width="250">
              <template #default="{ row }">
                <el-select
                  v-model="row.knowledge_point_id"
                  clearable
                  filterable
                  placeholder="未映射"
                  style="width: 100%"
                  :disabled="savingChunkIds.includes(row.id)"
                  @change="(value: number | null) => updateChunkPoint(row, value)"
                >
                  <el-option
                    v-for="point in chunkKnowledgePoints"
                    :key="point.id"
                    :value="point.id"
                    :label="`${point.code} · ${point.name}（${abilityLabel(point.ability)}）`"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90" align="center">
              <template #default="{ row }">
                <el-switch
                  v-model="row.enabled"
                  :loading="savingChunkIds.includes(row.id)"
                  @change="(value: boolean) => updateChunkEnabled(row, value)"
                />
              </template>
            </el-table-column>
            <el-table-column label="索引" width="75" align="center">
              <template #default="{ row }">
                <el-tag :type="row.vector_embedded ? 'success' : 'info'" size="small">
                  {{ row.vector_embedded ? '已建' : '未建' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <template v-else-if="selectedDetail">
          <el-divider content-position="left">知识正文</el-divider>
          <MarkdownContent class="detail-content" :content="selectedDetail.content" />
        </template>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新增弹窗（手动输入） -->
    <el-dialog v-model="addVisible" title="添加知识条目" width="560px">
      <el-form :model="addForm" label-width="80px">
        <el-form-item label="标题" required>
          <el-input v-model="addForm.title" placeholder="知识条目标题" />
        </el-form-item>
        <el-form-item label="内容" required>
          <el-input v-model="addForm.content" type="textarea" :rows="5" placeholder="知识内容..." />
        </el-form-item>
        <el-form-item label="能力维度">
          <el-select v-model="addForm.ability" style="width: 100%">
            <el-option v-for="opt in abilityOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源名称">
          <el-input v-model="addForm.source_name" placeholder="如：教材名称、标准名称" />
        </el-form-item>
        <el-form-item label="难度">
          <el-rate v-model="addForm.difficulty" :max="5" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd">确认添加</el-button>
      </template>
    </el-dialog>

    <!-- 文件导入弹窗 -->
    <el-dialog v-model="uploadVisible" title="📁 导入文件到知识库" width="600px">
      <el-form label-width="140px">
        <el-form-item label="首选能力维度（可选）">
          <el-select v-model="uploadAbility" style="width: 100%">
            <el-option label="自动识别（推荐）" :value="AUTO_ABILITY" />
            <el-option v-for="opt in abilityOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <div class="text-secondary" style="font-size: 12px; line-height: 1.5; margin-top: 4px">
            文件可包含多个能力维度；该选择仅用于识别同分时的优先级，未识别分块仍需教师选择知识点。
          </div>
        </el-form-item>
        <el-form-item label="选择文件">
          <el-upload
            drag
            :auto-upload="false"
            :show-file-list="false"
            :accept="acceptExtensions"
            :on-change="(file: any) => handleUpload({ file: file.raw })"
            :disabled="uploading"
          >
            <div style="padding: 20px 0">
              <div style="font-size: 40px; margin-bottom: 8px">📄</div>
              <div style="color: #606266">将文件拖到此处，或 <em style="color: var(--el-color-primary)">点击上传</em></div>
              <div style="font-size: 12px; color: #909399; margin-top: 8px">
                支持 PDF、DOCX、TXT、MD，按章/节/条优先分块，最大 5MB
              </div>
            </div>
          </el-upload>
        </el-form-item>
        <el-form-item label="来源名称">
          <el-input v-model="uploadSourceName" placeholder="留空则使用文件名" />
        </el-form-item>
        <el-form-item label="难度">
          <el-rate v-model="uploadDifficulty" :max="5" />
        </el-form-item>
      </el-form>

      <!-- 上传中 -->
      <div v-if="uploading" style="text-align: center; padding: 20px">
        <el-icon class="is-loading" style="font-size: 24px; color: var(--el-color-primary)">⏳</el-icon>
        <div style="margin-top: 8px; color: #606266">正在解析文件并向量化...</div>
      </div>

      <!-- 上传结果 -->
      <div v-if="uploadResult" class="upload-result">
        <el-divider content-position="left">导入结果</el-divider>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="文件名">{{ uploadResult.file_name }}</el-descriptions-item>
          <el-descriptions-item label="格式">{{ uploadResult.file_type?.toUpperCase() }}</el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ formatSize(uploadResult.file_size) }}</el-descriptions-item>
          <el-descriptions-item label="提取文本">{{ formatSize(uploadResult.text_length) }}</el-descriptions-item>
          <el-descriptions-item label="页数">{{ uploadResult.page_count }}</el-descriptions-item>
          <el-descriptions-item label="章节块">
            {{ uploadResult.chunk_count }} 个
          </el-descriptions-item>
          <el-descriptions-item label="建议启用">
            <el-tag type="success" size="small">{{ uploadResult.enabled_chunk_count }} 个</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="建议停用">
            <el-tag type="info" size="small">{{ uploadResult.disabled_chunk_count }} 个</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="已建向量">
            <el-tag type="success" size="small">{{ uploadResult.vector_points }} 个</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="涉及维度" :span="2">
            <template v-if="uploadResult.chunk_abilities.length">
              <el-tag v-for="ability in uploadResult.chunk_abilities" :key="ability" size="small" style="margin-right: 4px">
                {{ abilityLabel(ability) }}
              </el-tag>
            </template>
            <el-tag v-else size="small" type="warning">待识别</el-tag>
          </el-descriptions-item>
        </el-descriptions>
        <div style="text-align: center; margin-top: 14px">
          <el-button type="primary" @click="reviewUploadedChunks">立即审核分块</el-button>
        </div>
      </div>

      <template #footer>
        <el-button @click="uploadVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 16px; }

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card { text-align: center; padding: 14px; }
.stat-num {
  font-size: 28px;
  font-weight: 700;
  color: var(--ots-primary);
}
.stat-label {
  font-size: 12px;
  color: var(--ots-text-secondary);
  margin-top: 4px;
}
.authority-stat { cursor: pointer; }
.authority-stat:hover { border-color: var(--ots-primary); }
.stat-breakdown { text-align: left; }
.breakdown-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--ots-text-secondary);
  margin-bottom: 6px;
}
.breakdown-item {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 2px 0;
}
.breakdown-count { font-weight: 600; color: var(--ots-primary); }

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.pagination {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}

.source-name {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.35;
}

.detail-content {
  max-height: 420px;
  min-width: 0;
  max-width: 100%;
  overflow: auto;
  padding-right: 6px;
  box-sizing: border-box;
}

.chunk-summary {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.chunk-summary-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }

.chunk-heading { font-weight: 600; line-height: 1.45; }
.chunk-page { margin-top: 4px; font-size: 12px; }
.chunk-reason { margin-bottom: 5px; font-size: 12px; line-height: 1.5; }
.chunk-full-content {
  padding: 8px 56px;
}

.upload-result {
  margin-top: 12px;
}
</style>
