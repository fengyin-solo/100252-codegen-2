<template>
  <section class="page" data-module="qualification">
    <header class="page-head">
      <div>
        <h2>资质台账</h2>
        <p class="page-desc">按证书类别与专业自动判定作业资格；到期预警阈值按专业区分，资质缺失按不合格处理。判定口径与检修排班完全一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCertForm">登记证书</button>
        <button class="btn" type="button" :disabled="reassessing" @click="reassess">按新口径重标历史数据</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.cls">{{ item.value }}</strong>
      </article>
    </div>

    <div class="rule-panel">
      <strong>判定规则（与排班保存共用）：</strong>
      <span v-for="(days, spec) in rules.warn_days_by_specialty" :key="spec" class="rule-chip">
        {{ spec }}专业临期阈值 {{ days }} 天
      </span>
      <span class="rule-chip rule-chip-warn">资质缺失 / 已过期 / 临期 / 类别不符 一律不合格</span>
      <span class="rule-chip">同一人重复录入同一张证书以最近一次为准</span>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="工号 / 姓名 / 证书编号" />
      </label>
      <label class="filter-item">
        <span>专业</span>
        <select v-model="filters.specialty">
          <option value="">全部专业</option>
          <option v-for="spec in rules.specialties" :key="spec" :value="spec">{{ spec }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>证书状态</span>
        <select v-model="filters.state">
          <option value="">全部状态</option>
          <option v-for="state in certStates" :key="state" :value="state">{{ state }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>工号</th><th>姓名</th><th>专业</th><th>证书编号</th><th>证书类别</th>
          <th>有效期至</th><th>到期天数</th><th>证书状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['员工工号'] }}</td>
          <td>{{ row['员工姓名'] }}</td>
          <td>{{ row['专业'] }}</td>
          <td>{{ row['证书编号'] }}</td>
          <td>{{ row['证书类别'] }}</td>
          <td>{{ row['有效期至'] }}</td>
          <td :class="row.blocked ? 'cell-danger' : ''">{{ formatDays(row['到期天数']) }}<small v-if="row.blocked">（阈值 {{ row['预警阈值'] }} 天）</small></td>
          <td><span :class="badgeClass(row['证书状态'])">{{ row['证书状态'] }}</span></td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="8" class="empty-state">暂无符合条件的持证记录</td>
        </tr>
      </tbody>
    </table>

    <header class="sub-head">
      <h3>作业资格矩阵</h3>
      <p class="page-desc">选择作业项目后逐人给出资格结论，与检修排班保存时调用的是同一份后端判定。</p>
    </header>
    <div class="filter-bar">
      <label class="filter-item">
        <span>作业项目</span>
        <select v-model="matrixJob" @change="loadMatrix">
          <option value="" disabled>请选择作业项目</option>
          <option v-for="job in jobItems" :key="job" :value="job">{{ job }}</option>
        </select>
      </label>
      <span v-if="matrixJob" class="rule-hint">
        要求 {{ rules.job_primary_cert[matrixJob] }}；允许兼岗：{{ (rules.cross_post_rules[matrixJob] ?? []).join('、') || '无' }}
      </span>
    </div>
    <table v-if="matrix.length" class="data-table">
      <thead>
        <tr><th>工号</th><th>姓名</th><th>专业</th><th>命中证书</th><th>到期天数</th><th>作业资格结论</th><th>判定理由</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in matrix" :key="item.worker_id">
          <td>{{ item.worker_id }}</td>
          <td>{{ item.worker_name }}</td>
          <td>{{ item.specialty }}</td>
          <td>{{ item.cert_category ? `${item.cert_category}（${item.cert_no}）` : '—' }}</td>
          <td :class="item.blocked ? 'cell-danger' : ''">{{ formatDays(item.days_to_expiry) }}</td>
          <td><span :class="badgeClass(item.result)">{{ item.result }}</span></td>
          <td class="reason-cell">{{ item.reasons.join('；') }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条持证记录（同一证书重复录入仅展示最近一次）</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <div v-if="certFormOpen" class="modal-mask" @click.self="certFormOpen = false">
      <form class="modal" @submit.prevent="submitCert">
        <h3>登记证书</h3>
        <p class="page-desc">同一员工重复录入同一证书编号时，本次录入自动成为生效记录，历史录入置为失效。</p>
        <div class="form-grid">
          <label><span>员工工号 *</span><input v-model="certForm['员工工号']" required /></label>
          <label><span>员工姓名（新档案必填）</span><input v-model="certForm['员工姓名']" /></label>
          <label>
            <span>专业（新档案必填）</span>
            <select v-model="certForm['专业']">
              <option value="">请选择</option>
              <option v-for="spec in rules.specialties" :key="spec" :value="spec">{{ spec }}</option>
            </select>
          </label>
          <label>
            <span>证书类别 *</span>
            <select v-model="certForm['证书类别']" required>
              <option value="" disabled>请选择</option>
              <option v-for="cat in rules.cert_categories" :key="cat" :value="cat">{{ cat }}</option>
            </select>
          </label>
          <label><span>证书编号 *</span><input v-model="certForm['证书编号']" required /></label>
          <label><span>发证机关</span><input v-model="certForm['发证机关']" /></label>
          <label><span>发证日期</span><input v-model="certForm['发证日期']" type="date" /></label>
          <label><span>有效期至 *</span><input v-model="certForm['有效期至']" type="date" required /></label>
        </div>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="certFormOpen = false">取消</button>
          <button class="btn primary" type="submit">保存登记</button>
        </footer>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { CERT_STATES, badgeClass, formatDays } from '@/api/qualification'

type CertRow = Record<string, string | number | boolean | null>
type EligibilityItem = {
  worker_id: string
  worker_name: string
  specialty: string
  cert_category: string | null
  cert_no: string | null
  days_to_expiry: number | null
  result: string
  blocked: boolean
  reasons: string[]
}
type Rules = {
  specialties: string[]
  cert_categories: string[]
  warn_days_by_specialty: Record<string, number>
  job_primary_cert: Record<string, string>
  cross_post_rules: Record<string, string[]>
}

const ENDPOINT = '/api/qualification'

const rows = ref<CertRow[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(true)
const reassessing = ref(false)
const certStates = CERT_STATES
const filters = reactive({ keyword: '', specialty: '', state: '' })

const rules = ref<Rules>({
  specialties: [],
  cert_categories: [],
  warn_days_by_specialty: {},
  job_primary_cert: {},
  cross_post_rules: {},
})
const jobItems = ref<string[]>([])
const matrixJob = ref('')
const matrix = ref<EligibilityItem[]>([])

const stats = ref<Record<string, number>>({ 持证记录: 0, 有效: 0, 临期: 0, 已过期: 0 })
const statCards = ref([
  { label: '持证记录', value: 0, cls: '' },
  { label: '有效证书', value: 0, cls: 'ok-text' },
  { label: '30 天内临期（按各专业阈值）', value: 0, cls: 'warn-text' },
  { label: '已过期', value: 0, cls: 'danger-text' },
])

const certFormOpen = ref(false)
const certForm = reactive<Record<string, string>>({
  员工工号: '', 员工姓名: '', 专业: '', 证书类别: '',
  证书编号: '', 发证机关: '', 发证日期: '', 有效期至: '',
})

function openCertForm() {
  Object.keys(certForm).forEach((key) => { certForm[key] = '' })
  certFormOpen.value = true
}

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function resetFilters() {
  filters.keyword = ''
  filters.specialty = ''
  filters.state = ''
  void reload()
}

async function reload() {
  message.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.specialty) query.set('specialty', filters.specialty)
  if (filters.state) query.set('state', filters.state)
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}/certificates?${query.toString()}`)
    if (!response.ok) throw new Error('资质台账读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
    await loadStats()
  } catch (error) {
    flash(error instanceof Error ? error.message : '资质台账读取失败', false)
  }
}

async function loadStats() {
  const response = await request(`${ENDPOINT}/stats`)
  if (response.ok) {
    const payload = await response.json()
    stats.value = payload.stats
    statCards.value[0].value = payload.stats['持证记录'] ?? 0
    statCards.value[1].value = payload.stats['有效'] ?? 0
    statCards.value[2].value = payload.stats['临期'] ?? 0
    statCards.value[3].value = payload.stats['已过期'] ?? 0
  }
}

async function loadMatrix() {
  if (!matrixJob.value) return
  const query = new URLSearchParams({ job_item: matrixJob.value })
  const response = await request(`${ENDPOINT}/eligibility?${query.toString()}`)
  if (!response.ok) {
    matrix.value = []
    return
  }
  const payload = await response.json()
  matrix.value = payload.items ?? []
}

async function submitCert() {
  try {
    const response = await request(`${ENDPOINT}/certificates`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...certForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '证书登记失败')
    certFormOpen.value = false
    flash(payload.message || '证书已登记')
    await reload()
    if (matrixJob.value) await loadMatrix()
  } catch (error) {
    flash(error instanceof Error ? error.message : '证书登记失败', false)
  }
}

async function reassess() {
  reassessing.value = true
  try {
    const response = await request(`${ENDPOINT}/reassess`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '重标失败')
    const info = payload.entry
    flash(`历史数据已按新口径重标：证书 ${info.certificates.total} 条、排班 ${info.schedules.total} 条，审核记录保留 ${info.audit_records_preserved} 条`)
    await reload()
    if (matrixJob.value) await loadMatrix()
  } catch (error) {
    flash(error instanceof Error ? error.message : '重标失败', false)
  } finally {
    reassessing.value = false
  }
}

onMounted(async () => {
  const [rulesResp, optionsResp] = await Promise.all([
    request(`${ENDPOINT}/rules`),
    request('/api/schedule/options'),
  ])
  if (rulesResp.ok) rules.value = await rulesResp.json()
  if (optionsResp.ok) {
    const options = await optionsResp.json()
    jobItems.value = options.job_items ?? []
  }
  await reload()
})
</script>
