<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { knowledgeApi } from '@/api'
import MarkdownContent from '@/components/MarkdownContent.vue'
import type { KnowledgeChunkOut, KnowledgeItemOut, KnowledgeStatsOut } from '@/types'
import { ABILITY_LABELS, type AbilityKey } from '@/types'

const items = ref<KnowledgeItemOut[]>([])
const stats = ref<KnowledgeStatsOut | null>(null)
const loading = ref(true)
const keyword = ref('')
const filterAbility = ref('')
const currentPage = ref(1)
const total = ref(0)
const pageSize = 12

const selectedDetail = ref<KnowledgeItemOut | null>(null)
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const knowledgeChunks = ref<KnowledgeChunkOut[]>([])
const selectedChunkId = ref<number | null>(null)

const selectedChunk = computed(() =>
  knowledgeChunks.value.find((chunk) => chunk.id === selectedChunkId.value) || knowledgeChunks.value[0] || null,
)

const abilityOptions = computed(() =>
  Object.entries(ABILITY_LABELS).map(([key, label]) => ({ value: key, label }))
)

async function loadItems() {
  loading.value = true
  try {
    const res = await knowledgeApi.list({
      keyword: keyword.value || undefined,
      ability: filterAbility.value || undefined,
      page: currentPage.value,
      page_size: pageSize,
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

async function openDetail(item: KnowledgeItemOut) {
  selectedDetail.value = item
  detailVisible.value = true
  detailLoading.value = true
  detailError.value = ''
  knowledgeChunks.value = []
  selectedChunkId.value = null
  try {
    const detail = await knowledgeApi.detail(item.id)
    selectedDetail.value = detail
    if (detail.source_type === 'file_import') {
      const chunks = await knowledgeApi.chunks(detail.id)
      knowledgeChunks.value = chunks.items
      selectedChunkId.value = chunks.items[0]?.id ?? null
    }
  } catch {
    detailError.value = '知识详情加载失败，请稍后重试。'
  } finally {
    detailLoading.value = false
  }
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

function onSearch() {
  currentPage.value = 1
  loadItems()
}

onMounted(() => {
  loadItems()
  loadStats()
})
</script>

<template>
  <div class="ots-page knowledge-page" v-loading="loading">
    <div class="page-header">
      <h2>📚 专业知识库</h2>
      <p class="text-secondary">浏览油气储运工程专业知识文档，支持按能力维度和关键词筛选。</p>
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
      <div class="ots-card stat-card">
        <div class="stat-num">{{ Object.keys(stats.by_ability).length }}</div>
        <div class="stat-label">能力维度</div>
      </div>
      <div class="ots-card stat-card">
        <div class="stat-num">{{ Object.keys(stats.by_source).length }}</div>
        <div class="stat-label">来源类型</div>
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
      <el-button type="primary" @click="onSearch">搜索</el-button>
      <span class="text-secondary" style="margin-left: auto">共 {{ total }} 条</span>
    </div>

    <!-- 知识列表 -->
    <el-empty v-if="!loading && !items.length" description="暂无知识条目" />

    <div v-else class="knowledge-grid">
      <div
        v-for="item in items"
        :key="item.id"
        class="ots-card knowledge-card"
        @click="openDetail(item)"
      >
        <div class="card-header">
          <el-tag size="small" :type="item.vector_embedded ? 'success' : 'info'" effect="plain">
            {{ item.vector_embedded ? '已向量化' : '未向量化' }}
          </el-tag>
          <span class="knowledge-id text-secondary">{{ item.knowledge_id }}</span>
        </div>
        <div class="card-title">{{ item.title }}</div>
        <div class="card-content">{{ item.content }}</div>
        <div class="card-footer">
          <template v-if="itemAbilities(item).length">
            <el-tag
              v-for="ability in itemAbilities(item)"
              :key="ability"
              size="small"
              effect="plain"
              type="info"
            >{{ abilityLabel(ability) }}</el-tag>
          </template>
          <el-tag v-else size="small" type="warning" effect="plain">待识别</el-tag>
          <span class="difficulty text-secondary">{{ difficultyStars(item.difficulty) }}</span>
          <span class="text-secondary" style="font-size: 11px">{{ item.source_name }}</span>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="pagination">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
        @current-change="loadItems"
      />
    </div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="selectedDetail?.title" width="min(1080px, 94vw)" top="5vh">
      <div v-loading="detailLoading">
        <template v-if="selectedDetail && !detailError">
        <div class="detail-meta">
          <template v-if="itemAbilities(selectedDetail).length">
            <el-tag v-for="ability in itemAbilities(selectedDetail)" :key="ability" size="small">
              {{ abilityLabel(ability) }}
            </el-tag>
          </template>
          <el-tag v-else size="small" type="warning">待识别</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ selectedDetail.source_type }}</el-tag>
          <span class="text-secondary">{{ selectedDetail.knowledge_id }}</span>
        </div>
        <template v-if="selectedDetail.source_type === 'file_import' && knowledgeChunks.length">
          <div class="file-viewer">
            <aside class="chunk-nav" aria-label="文档分块导航">
              <div class="chunk-nav-title">章节 / 条款（{{ knowledgeChunks.length }}）</div>
              <button
                v-for="chunk in knowledgeChunks"
                :key="chunk.id"
                class="chunk-nav-item"
                :class="{ active: chunk.id === selectedChunk?.id }"
                type="button"
                @click="selectedChunkId = chunk.id"
              >
                <span class="chunk-nav-index">{{ chunk.chunk_index + 1 }}</span>
                <span class="chunk-nav-label">{{ chunk.heading || `分块 ${chunk.chunk_index + 1}` }}</span>
                <span v-if="chunk.chunk_type === 'table'" class="chunk-nav-type">表格</span>
              </button>
            </aside>
            <section v-if="selectedChunk" class="chunk-preview">
              <div class="chunk-preview-meta text-secondary">
                <span>{{ selectedChunk.heading_path || selectedChunk.chapter || selectedChunk.heading }}</span>
                <span v-if="selectedChunk.page_start">
                  · P{{ selectedChunk.page_start }}<template v-if="selectedChunk.page_end && selectedChunk.page_end !== selectedChunk.page_start">–{{ selectedChunk.page_end }}</template>
                </span>
              </div>
              <MarkdownContent class="detail-content" :content="selectedChunk.content" />
            </section>
          </div>
        </template>
        <MarkdownContent v-else class="detail-content" :content="selectedDetail.content" />
        <el-descriptions :column="2" border size="small" style="margin-top: 16px">
          <el-descriptions-item label="来源">{{ selectedDetail.source_name }}</el-descriptions-item>
          <el-descriptions-item label="编号">{{ selectedDetail.source_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="章节">{{ selectedDetail.chapter || '—' }}</el-descriptions-item>
          <el-descriptions-item label="页码">{{ selectedDetail.page ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="安全等级">{{ selectedDetail.safety_level || '—' }}</el-descriptions-item>
          <el-descriptions-item label="难度">{{ difficultyStars(selectedDetail.difficulty) }}</el-descriptions-item>
        </el-descriptions>
        </template>
        <el-empty v-else-if="!detailLoading && detailError" :description="detailError" :image-size="80" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0 0 6px; }

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
  padding: 14px;
}
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

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
}
.knowledge-card {
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}
.knowledge-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(11, 95, 107, 0.14);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.knowledge-id { font-size: 11px; font-family: monospace; }
.card-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 8px;
}
.card-content {
  color: var(--ots-text-secondary);
  font-size: 13px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 10px;
}
.card-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  border-top: 1px solid var(--ots-border);
  padding-top: 8px;
}
.difficulty { font-size: 12px; color: #f5a623; }

.pagination {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.detail-content {
  line-height: 1.7;
  background: var(--ots-bg);
  padding: 12px;
  border-radius: 8px;
}
.file-viewer {
  display: grid;
  grid-template-columns: minmax(210px, 28%) minmax(0, 1fr);
  min-height: 430px;
  border: 1px solid var(--ots-border);
  border-radius: 8px;
  overflow: hidden;
}
.chunk-nav {
  overflow-y: auto;
  max-height: 58vh;
  padding: 10px;
  border-right: 1px solid var(--ots-border);
  background: #fafcfd;
}
.chunk-nav-title { margin: 2px 4px 10px; font-size: 13px; font-weight: 600; }
.chunk-nav-item {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 7px;
  padding: 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--ots-text-primary);
  cursor: pointer;
  text-align: left;
}
.chunk-nav-item:hover, .chunk-nav-item.active { background: #e8f4f5; color: var(--ots-primary); }
.chunk-nav-index { flex: 0 0 22px; color: var(--ots-text-secondary); font-size: 12px; }
.chunk-nav-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.chunk-nav-type { margin-left: auto; color: #ad6800; font-size: 11px; }
.chunk-preview { min-width: 0; max-height: 58vh; overflow: auto; padding: 14px; }
.chunk-preview-meta { margin-bottom: 10px; font-size: 12px; line-height: 1.5; }
@media (max-width: 700px) {
  .file-viewer { grid-template-columns: 1fr; }
  .chunk-nav { max-height: 170px; border-right: 0; border-bottom: 1px solid var(--ots-border); }
  .chunk-preview { max-height: 45vh; }
}
</style>
