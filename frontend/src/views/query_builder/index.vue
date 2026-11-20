<template>
  <section class="page" data-module="query_builder">
    <header class="page-head">
      <div>
        <h2>OLAP查询管理</h2>
        <p class="page-desc">维护查询模板，围绕模板编号、模板名称、查询语句、参数定义做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记查询模板</button>
        <button class="btn" type="button" @click="exportRows">导出OLAP查询清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无OLAP查询数据，可先登记查询模板</td>
        </tr>
      </tbody>
    </table>


    <section class="sample-panel" data-module="query_builder_sample">
      <header class="sample-head">
        <div>
          <h3>按实验样本分配表聚合</h3>
          <p class="page-desc">
            以分组名单为分母聚合各臂指标；未加入名单的观测单列。筛选后的分子、分母和待归属记录使用同一次查询的人群范围。
          </p>
        </div>
      </header>
      <div class="sample-toolbar">
        <label class="filter-item">
          <span>实验方案</span>
          <select v-model.number="sampleEntryId" @change="loadSampleMetrics">
            <option v-for="item in sampleOptions" :key="item.id" :value="item.id">
              {{ item.方案编号 }} · {{ item.实验名称 }}
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>分层地区</span>
          <select v-model="sampleRegion" @change="loadSampleMetrics">
            <option value="">全部地区</option>
            <option v-for="region in regionOptions" :key="region" :value="region">{{ region }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>实验臂</span>
          <select v-model="sampleArm" @change="loadSampleMetrics">
            <option value="">全部实验臂</option>
            <option v-for="arm in armOptions" :key="arm" :value="arm">{{ arm }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>地区口径</span>
          <select v-model="sampleRegionBasis" @change="loadSampleMetrics">
            <option value="start">启动时地区</option>
            <option value="current">更正后地区</option>
          </select>
        </label>
      </div>
      <p class="sample-hint">{{ sampleMetrics?.scope ?? '选择实验方案后按分组名单聚合。' }}</p>
      <div class="sample-grid">
        <div>
          <h4>各臂指标</h4>
          <table class="data-table">
            <thead>
              <tr><th>地区</th><th>实验臂</th><th>分母</th><th>分子</th><th>转化率</th></tr>
            </thead>
            <tbody>
              <tr v-for="cell in sampleMetrics?.cells ?? []" :key="`${cell.地区}-${cell.实验臂}`">
                <td>{{ cell.地区 }}</td>
                <td>{{ cell.实验臂 }}</td>
                <td>{{ cell.分母 }}</td>
                <td>{{ cell.分子 }}</td>
                <td>{{ cell.转化率 === null ? '—' : `${(cell.转化率 * 100).toFixed(1)}%` }}</td>
              </tr>
              <tr v-if="!(sampleMetrics?.cells ?? []).length">
                <td colspan="5" class="empty-state">当前查询范围内没有名单参与者</td>
              </tr>
            </tbody>
          </table>
          <p class="page-foot">
            <span>
              合计分母 {{ sampleMetrics?.totals.分母 ?? 0 }} 人、分子 {{ sampleMetrics?.totals.分子 ?? 0 }} 人
            </span>
          </p>
        </div>
        <div>
          <h4>未加入名单的观测（单列）</h4>
          <table class="data-table">
            <thead>
              <tr><th>观测编号</th><th>参与者编号</th><th>地区</th><th>转化</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in sampleMetrics?.pending_observations ?? []" :key="item.观测编号">
                <td>{{ item.观测编号 }}</td>
                <td>{{ item.参与者编号 || '—' }}</td>
                <td>{{ item.地区 }}</td>
                <td>{{ item.转化 ? '是' : '否' }}</td>
              </tr>
              <tr v-if="!(sampleMetrics?.pending_observations ?? []).length">
                <td colspan="4" class="empty-state">当前查询范围内没有待归属观测</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条OLAP查询记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记查询模板</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label v-for="field in columns.slice(0, 3)" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="createFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/query_builder'
const columns = ["模板编号", "模板名称", "查询语句", "参数定义", "数据集范围", "超时秒数", "缓存策略", "模板状态"]
const actions = ["保存模板", "发布模板", "停用模板"]
const statuses = ["草稿", "已保存", "已发布", "已停用"]
const stats = [{"label": "已发布模板", "value": 0}, {"label": "草稿模板", "value": 0}, {"label": "停用模板", "value": 0}]

type SampleMetricCell = { 地区: string; 实验臂: string; 分母: number; 分子: number; 转化率: number | null }

type SampleMetrics = {
  scope: string
  cells: SampleMetricCell[]
  totals: { 分母: number; 分子: number; 待归属观测: number }
  pending_observations: { 观测编号: string; 参与者编号: string; 地区: string; 转化: boolean }[]
}

const knownRegions = ref<string[]>([])
const knownArms = ref<string[]>([])
const regionOptions = computed(() => knownRegions.value)
const armOptions = computed(() => knownArms.value)
const sampleOptions = ref<{ id: number; 方案编号: string; 实验名称: string }[]>([])
const sampleEntryId = ref<number | null>(null)
const sampleRegion = ref('')
const sampleArm = ref('')
const sampleRegionBasis = ref<'start' | 'current'>('start')
const sampleMetrics = ref<SampleMetrics | null>(null)

async function loadSampleMetrics() {
  if (!sampleEntryId.value) {
    sampleMetrics.value = null
    return
  }
  const params = new URLSearchParams()
  if (sampleRegion.value) params.set('region', sampleRegion.value)
  if (sampleArm.value) params.set('arm', sampleArm.value)
  params.set('region_basis', sampleRegionBasis.value)
  try {
    const response = await request(
      `${ENDPOINT}/experiment/${sampleEntryId.value}/sample_metrics?${params.toString()}`,
    )
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || '实验样本聚合读取失败')
    }
    const metrics = payload as SampleMetrics
    sampleMetrics.value = metrics
    knownRegions.value = [
      ...new Set([
        ...knownRegions.value,
        ...metrics.cells.map((cell) => cell.地区),
        ...metrics.pending_observations.map((item) => item.地区),
      ]),
    ].sort()
    knownArms.value = [
      ...new Set([...knownArms.value, ...metrics.cells.map((cell) => cell.实验臂)]),
    ]
  } catch (error) {
    sampleMetrics.value = null
    errorMessage.value = error instanceof Error ? error.message : '实验样本聚合读取失败'
  }
}

async function loadSampleOptions() {
  try {
    const response = await request('/api/experiment?size=200')
    const payload = await response.json()
    sampleOptions.value = (payload.items ?? []).map((item: Row) => ({
      id: Number(item.id),
      方案编号: String(item.方案编号 ?? ''),
      实验名称: String(item.实验名称 ?? ''),
    }))
    const running = (payload.items ?? []).find((item: Row) => item.status === '运行中')
    sampleEntryId.value = Number(running?.id ?? sampleOptions.value[0]?.id ?? 0) || null
    await loadSampleMetrics()
  } catch {
    sampleOptions.value = []
  }
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})

function updateStats() {
  const data = rows.value
  stats.length > 0 && (stats[0].value = data.filter((r: Row) => r.status === statuses[1] || r.pending).length)
  stats.length > 1 && (stats[1].value = data.filter((r: Row) => r.status && !r.pending && !r.abnormal).length)
  stats.length > 2 && (stats[2].value = data.filter((r: Row) => r.abnormal).length)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = ''
  createFields.value = {}
  showCreateModal.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createFields.value }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || '登记失败')
    }
    showCreateModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('OLAP查询动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'OLAP查询操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('查询模板列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'OLAP查询列表读取失败'
  }
}

onMounted(async () => {
  await reload()
  await loadSampleOptions()
})
</script>
