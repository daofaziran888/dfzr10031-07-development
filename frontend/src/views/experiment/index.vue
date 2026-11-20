<template>
  <section class="page" data-module="experiment">
    <header class="page-head">
      <div>
        <h2>分析实验管理</h2>
        <p class="page-desc">维护实验方案，围绕方案编号、实验名称、分析数据集、样本范围做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记实验方案</button>
        <button class="btn" type="button" @click="exportRows">导出分析实验清单</button>
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
            <button class="link" type="button" @click="openSample(row)">样本分配</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无分析实验数据，可先登记实验方案</td>
        </tr>
      </tbody>
    </table>

    <section v-if="sample" class="sample-panel" data-module="experiment_sample">
      <header class="sample-head">
        <div>
          <h3>实验样本分配表 · {{ sample.experiment.方案编号 }} {{ sample.experiment.实验名称 }}</h3>
          <p class="page-desc">
            从带参与者编号、观测时间和分组字段的数据归并同一参与者的观测；同一参与者在一次实验中只进入一个实验臂。
          </p>
        </div>
        <button class="btn" type="button" @click="sample = null">收起</button>
      </header>

      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">名单参与者</span>
          <strong class="stat-value">{{ sample.summary.participants }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">对照组 / 实验组</span>
          <strong class="stat-value">
            {{ sample.summary.arm_participants['对照组'] ?? 0 }} / {{ sample.summary.arm_participants['实验组'] ?? 0 }}
          </strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">待归属观测</span>
          <strong class="stat-value">{{ sample.summary.unattributed_observations }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">地区已更正</span>
          <strong class="stat-value">{{ sample.summary.corrected_participants.length }}</strong>
        </article>
      </div>

      <div class="sample-toolbar">
        <button class="btn primary" type="button" @click="syncSample">生成 / 刷新分组名单</button>
        <label class="filter-item">
          <span>地区口径</span>
          <select v-model="queryRegionBasis" @change="onFilterChange">
            <option value="start">启动时地区（复验原分层设计）</option>
            <option value="current">更正后地区（当前地区响应差异）</option>
          </select>
        </label>
        <label class="filter-item">
          <span>分层地区</span>
          <select v-model="queryRegion" @change="onFilterChange">
            <option value="">全部地区</option>
            <option v-for="region in regionOptions" :key="region" :value="region">{{ region }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>实验臂</span>
          <select v-model="queryArm" @change="onFilterChange">
            <option value="">全部实验臂</option>
            <option v-for="arm in armOptions" :key="arm" :value="arm">{{ arm }}</option>
          </select>
        </label>
        <button class="btn ghost" type="button" @click="resetSampleFilters">重置查询范围</button>
      </div>

      <p class="sample-hint">{{ analytics?.scope ?? sample.definitions.population }}</p>

      <h4>分组名单</h4>
      <table class="data-table">
        <thead>
          <tr>
            <th>参与者编号</th>
            <th>实验臂</th>
            <th>启动时地区</th>
            <th>更正后地区</th>
            <th>首次曝光时间</th>
            <th>观测条数</th>
            <th>转化</th>
            <th>核对</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in sample.participants" :key="item.参与者编号">
            <td>{{ item.参与者编号 }}</td>
            <td>{{ item.实验臂 }}</td>
            <td>{{ item.启动时地区 }}</td>
            <td>
              {{ item.更正后地区 }}
              <span v-if="item.地区已更正" class="tag warn">已更正</span>
            </td>
            <td>{{ item.首次曝光时间 ?? '—' }}</td>
            <td>{{ item.观测条数 }}</td>
            <td>{{ item.转化 ? '是' : '否' }}</td>
            <td>
              <button class="link" type="button" @click="reconcile(item.参与者编号)">重新查询曝光</button>
              <span v-if="item.分组冲突" class="tag warn">分组冲突</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="reconciliation" class="reconcile-card">
        <header class="sample-head">
          <h4>曝光核对 · {{ reconciliation.参与者编号 }}</h4>
          <button class="btn ghost" type="button" @click="reconciliation = null">关闭</button>
        </header>
        <ul class="finding-list">
          <li v-for="line in reconciliation.findings" :key="line">{{ line }}</li>
        </ul>
        <table class="data-table">
          <thead>
            <tr>
              <th>地区口径</th>
              <th>筛选所用地区</th>
              <th>实验臂</th>
              <th>所在臂分母</th>
              <th>所在臂分子</th>
              <th>本人是否计入</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in reconciliation.denominator_contribution" :key="item.region_basis">
              <td>{{ item.地区口径 }}</td>
              <td>{{ item.筛选所用地区 }}</td>
              <td>{{ item.实验臂 }}</td>
              <td>{{ item.所在臂分母 }}</td>
              <td>{{ item.所在臂分子 }}</td>
              <td>{{ item.本人是否计入该分母 ? '是，只计 1 次' : '否' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="sample-grid">
        <div>
          <h4>各臂指标（分子 / 分母）</h4>
          <table class="data-table">
            <thead>
              <tr><th>地区</th><th>实验臂</th><th>分母</th><th>分子</th><th>转化率</th></tr>
            </thead>
            <tbody>
              <tr v-for="cell in analytics?.cells ?? []" :key="`${cell.地区}-${cell.实验臂}`">
                <td>{{ cell.地区 }}</td>
                <td>{{ cell.实验臂 }}</td>
                <td>{{ cell.分母 }}</td>
                <td>{{ cell.分子 }}</td>
                <td>{{ cell.转化率 === null ? '—' : `${(cell.转化率 * 100).toFixed(1)}%` }}</td>
              </tr>
              <tr v-if="!(analytics?.cells ?? []).length">
                <td colspan="5" class="empty-state">当前查询范围内没有匹配的名单参与者</td>
              </tr>
            </tbody>
          </table>
          <p class="page-foot">
            <span>
              合计分母 {{ analytics?.totals.分母 ?? 0 }} 人、分子 {{ analytics?.totals.分子 ?? 0 }} 人；
              一次观测不会同时计入两臂
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
              <tr v-for="item in analytics?.pending_observations ?? []" :key="item.观测编号">
                <td>{{ item.观测编号 }}</td>
                <td>{{ item.参与者编号 || '—' }}</td>
                <td>{{ item.地区 }}</td>
                <td>{{ item.转化 ? '是' : '否' }}</td>
              </tr>
              <tr v-if="!(analytics?.pending_observations ?? []).length">
                <td colspan="4" class="empty-state">当前查询范围内没有待归属观测</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <details class="sample-definitions" :open="Boolean(report)">
        <summary>实验报告：人群口径与样本分母</summary>
        <template v-if="report">
          <p>
            <strong>人群口径：</strong>{{ report.population.definition }}
            本次纳入 {{ report.population.included_participants }} 人
            <span v-if="report.population.counts_use_query_scope">
              （全名单 {{ report.population.roster_participants }} 人，已按当前查询范围收窄）
            </span>，
            排除 {{ report.population.excluded_participants }} 人 /
            {{ report.population.excluded_observations }} 条观测（{{ report.population.exclusion_reason }}）。
          </p>
          <p>
            <strong>分母：</strong>{{ report.denominator.definition }}
            当前口径（{{ report.denominator.region_label }}）合计 {{ report.denominator.total }} 人。
          </p>
          <p><strong>分子：</strong>{{ report.numerator.definition }} 合计 {{ report.numerator.total }} 人。</p>
          <p><strong>待归属：</strong>{{ report.pending.definition }}</p>
          <p><strong>曝光归属：</strong>{{ report.exposure_rule }}</p>
          <p class="sample-hint">下面两段分层为全名单口径，用于对照原分层设计与当前地区口径；分子分母合计以本次查询范围为准。</p>
          <table class="data-table">
            <thead>
              <tr><th>地区口径</th><th>地区</th><th>实验臂</th><th>分母</th><th>分子</th><th>转化率</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in report.strata.start.cells" :key="`start-${item.地区}-${item.实验臂}`">
                <td>启动时地区</td>
                <td>{{ item.地区 }}</td>
                <td>{{ item.实验臂 }}</td>
                <td>{{ item.分母 }}</td>
                <td>{{ item.分子 }}</td>
                <td>{{ item.转化率 === null ? '—' : `${(item.转化率 * 100).toFixed(1)}%` }}</td>
              </tr>
              <tr v-for="item in report.strata.current.cells" :key="`current-${item.地区}-${item.实验臂}`">
                <td>更正后地区</td>
                <td>{{ item.地区 }}</td>
                <td>{{ item.实验臂 }}</td>
                <td>{{ item.分母 }}</td>
                <td>{{ item.分子 }}</td>
                <td>{{ item.转化率 === null ? '—' : `${(item.转化率 * 100).toFixed(1)}%` }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <template v-else>
          <p><strong>人群口径：</strong>{{ sample.definitions.population }}</p>
          <p><strong>分母口径：</strong>{{ sample.definitions.denominator }}</p>
          <p><strong>分子口径：</strong>{{ sample.definitions.numerator }}</p>
          <p><strong>待归属：</strong>{{ sample.definitions.pending }}</p>
          <p><strong>曝光归属：</strong>{{ sample.definitions.exposure }}</p>
        </template>
      </details>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条分析实验记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记实验方案</h3>
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

type RosterItem = {
  参与者编号: string
  实验臂: string
  启动时地区: string
  更正后地区: string
  首次曝光时间: string | null
  观测条数: number
  转化: boolean
  地区已更正: boolean
  分组冲突: boolean
}

type RosterSummary = {
  participants: number
  observations: number
  arm_participants: Record<string, number>
  unattributed_observations: number
  corrected_participants: string[]
  conflict_participants: string[]
}

type SamplePayload = {
  experiment: Row
  count: number
  participants: RosterItem[]
  summary: RosterSummary
  definitions: Record<string, string>
}

type AggregateCell = { 地区: string; 实验臂: string; 分母: number; 分子: number; 转化率: number | null }

type PendingObservation = {
  观测编号: string
  参与者编号: string
  观测时间: string
  地区: string
  转化: boolean
}

type AggregatePayload = {
  scope: string
  cells: AggregateCell[]
  arm_totals: AggregateCell[]
  totals: { 分母: number; 分子: number; 待归属观测: number }
  pending_observations: PendingObservation[]
  pending_summary: { 地区: string; 观测数: number; 转化观测数: number }[]
}

type ReportCell = { 地区: string; 实验臂: string; 分母: number; 分子: number; 转化率: number | null }

type ReportPayload = {
  population: {
    definition: string
    included_participants: number
    roster_participants: number
    excluded_participants: number
    excluded_observations: number
    exclusion_reason: string
    counts_use_query_scope: boolean
  }
  denominator: { definition: string; total: number; region_label: string }
  numerator: { definition: string; total: number }
  pending: { definition: string }
  exposure_rule: string
  strata: { start: { cells: ReportCell[] }; current: { cells: ReportCell[] } }
}

type ReconciliationPayload = {
  参与者编号: string
  findings: string[]
  denominator_contribution: {
    region_basis: string
    地区口径: string
    筛选所用地区: string
    实验臂: string
    所在臂分母: number
    所在臂分子: number
    本人是否计入该分母: boolean
  }[]
}

const ENDPOINT = '/api/experiment'
const columns = ["方案编号", "实验名称", "分析数据集", "样本范围", "分组字段", "目标度量", "基准区间", "显著阈值"]
const actions = ["提交设计", "运行实验", "完成实验"]
const statuses = ["草稿", "已设计", "运行中", "已完成"]
const stats = [{"label": "运行中实验", "value": 0}, {"label": "已完成实验", "value": 0}, {"label": "草稿方案", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})

const sample = ref<SamplePayload | null>(null)
const analytics = ref<AggregatePayload | null>(null)
const reconciliation = ref<ReconciliationPayload | null>(null)
const report = ref<ReportPayload | null>(null)
const queryRegion = ref('')
const queryArm = ref('')
const queryRegionBasis = ref<'start' | 'current'>('start')

const regionOptions = computed(() => {
  const values = new Set<string>()
  for (const item of sample.value?.participants ?? []) {
    if (item.启动时地区) values.add(item.启动时地区)
    if (item.更正后地区) values.add(item.更正后地区)
  }
  return [...values].sort()
})

const armOptions = computed(() => {
  const values = new Set<string>(Object.keys(sample.value?.summary.arm_participants ?? {}))
  for (const item of sample.value?.participants ?? []) {
    if (item.实验臂) values.add(item.实验臂)
  }
  return [...values]
})

function sampleQuery(): string {
  const params = new URLSearchParams()
  if (queryRegion.value) params.set('region', queryRegion.value)
  if (queryArm.value) params.set('arm', queryArm.value)
  params.set('region_basis', queryRegionBasis.value)
  return params.toString()
}

async function readJson<T>(path: string): Promise<T> {
  const response = await request(path)
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || '接口返回异常，数据未更新')
  }
  return payload as T
}

function onFilterChange() {
  void loadAnalytics()
}

async function loadAnalytics(entryId = Number(sample.value?.experiment.id ?? 0)) {
  if (!entryId) return
  errorMessage.value = ''
  try {
    const [aggregate, experimentReport] = await Promise.all([
      readJson<AggregatePayload>(`${ENDPOINT}/${entryId}/sample/aggregate?${sampleQuery()}`),
      readJson<ReportPayload>(`${ENDPOINT}/${entryId}/sample/report?${sampleQuery()}`),
    ])
    analytics.value = aggregate
    report.value = experimentReport
  } catch (error) {
    analytics.value = null
    report.value = null
    errorMessage.value = error instanceof Error ? error.message : '实验样本聚合读取失败'
  }
}

async function loadSample(entryId: number) {
  sample.value = await readJson<SamplePayload>(`${ENDPOINT}/${entryId}/sample`)
  reconciliation.value = null
  report.value = null
  queryRegion.value = ''
  queryArm.value = ''
  queryRegionBasis.value = 'start'
  await loadAnalytics(entryId)
}

async function openSample(row: Row) {
  errorMessage.value = ''
  try {
    await loadSample(Number(row.id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '实验样本分配表读取失败'
  }
}

async function syncSample() {
  const entryId = Number(sample.value?.experiment.id ?? 0)
  if (!entryId) return
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${entryId}/sample/sync`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || payload.message || '分组名单生成失败')
    }
    await loadSample(entryId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分组名单生成失败'
  }
}

async function reconcile(participantId: string) {
  const entryId = Number(sample.value?.experiment.id ?? 0)
  if (!entryId) return
  errorMessage.value = ''
  try {
    reconciliation.value = await readJson<ReconciliationPayload>(
      `${ENDPOINT}/${entryId}/sample/participants/${encodeURIComponent(participantId)}/reconcile`,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '曝光核对失败'
  }
}

function resetSampleFilters() {
  queryRegion.value = ''
  queryArm.value = ''
  queryRegionBasis.value = 'start'
  void loadAnalytics()
}

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
      throw new Error('分析实验动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分析实验操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('实验方案列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分析实验列表读取失败'
  }
}

onMounted(reload)
</script>
