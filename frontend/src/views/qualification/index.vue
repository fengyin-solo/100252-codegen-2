<template>
  <section class="page" data-module="qualification">
    <header class="page-head">
      <div>
        <h2>人员资质台账</h2>
        <p class="page-desc">
          按证书类别与专业自动判定作业资格。到期天数、临期阈值（分专业）与检修排班共用同一份规则；
          同员工同类别重复证书以最近一次为准；资质信息缺失按不合格处理。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记持证</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card"><span class="stat-label">当前有效证书</span><strong class="stat-value">{{ summary.total }}</strong></article>
      <article class="stat-card"><span class="stat-label">合格</span><strong class="stat-value ok-text">{{ summary.qualified }}</strong></article>
      <article class="stat-card"><span class="stat-label">临期（不足阈值）</span><strong class="stat-value" style="color:#b54708">{{ summary.expiring }}</strong></article>
      <article class="stat-card"><span class="stat-label">已过期</span><strong class="stat-value error-text">{{ summary.expired }}</strong></article>
      <article class="stat-card"><span class="stat-label">信息缺失</span><strong class="stat-value error-text">{{ summary.missing }}</strong></article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item"><span>姓名/工号/证书号</span><input v-model="keyword" placeholder="关键字" /></label>
      <label class="filter-item"><span>证书状态</span>
        <select v-model="certStatus">
          <option value="">全部</option>
          <option v-for="q in qualifications()" :key="q" :value="q">{{ q }}</option>
        </select>
      </label>
      <label class="filter-item"><span>归口专业</span>
        <select v-model="specialty">
          <option value="">全部</option>
          <option v-for="s in specialties()" :key="s" :value="s">{{ s }}（{{ threshold(s) }}天）</option>
        </select>
      </label>
      <label class="filter-item"><span>重复旧证</span>
        <select v-model="includeDup">
          <option value="">只看有效证</option>
          <option value="1">显示已折叠旧证</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>工号</th><th>姓名</th><th>所属专业</th><th>证书类别</th><th>归口专业</th>
          <th>证书编号</th><th>有效期至</th><th>到期天数</th><th>阈值</th><th>证书状态</th><th>登记时间</th><th>作业资格</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :style="row.effect ? '' : 'opacity:.5'">
          <td>{{ row.employee_id }}</td>
          <td>{{ row.employee_name }}</td>
          <td>{{ row.specialty }}</td>
          <td>{{ row.cert_category }}</td>
          <td>{{ row.cert_specialty ?? '—' }}</td>
          <td>{{ row.cert_no || '—' }}</td>
          <td>{{ row.expire_date || '缺失' }}</td>
          <td :class="daysClass(row.days_left)">{{ formatDays(row.days_left) }}</td>
          <td>{{ row.threshold_days }}</td>
          <td><span :class="badge(row.cert_status)">{{ row.cert_status }}</span></td>
          <td class="muted">{{ (row.recorded_at || '').replace('T', ' ').slice(0, 16) }}</td>
          <td><button class="link" type="button" @click="openQualification(row)">查看作业资格</button></td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="12" class="empty-state">暂无符合条件的持证记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条记录（含重复旧证时仅当前有效证参与资格判定）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记持证 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h3>登记持证记录</h3>
        <div class="form-grid">
          <label>员工</label>
          <select v-model="form.employee_id" @change="onPickEmployee">
            <option value="">请选择</option>
            <option v-for="e in employees" :key="e.employee_id" :value="e.employee_id">
              {{ e.employee_id }} · {{ e.name }}（{{ e.specialty }}）
            </option>
          </select>
          <label>证书类别</label>
          <select v-model="form.cert_category">
            <option value="">请选择</option>
            <option v-for="cat in certCategories()" :key="cat" :value="cat">{{ cat }}</option>
          </select>
          <span class="field-hint" v-if="form.cert_category">
            归口专业：{{ certSpecialty()[form.cert_category] }}，临期阈值 {{ threshold(certSpecialty()[form.cert_category]) }} 天
          </span>
          <label>证书编号</label><input v-model="form.cert_no" placeholder="如 SG-2026-001" />
          <label>有效期至</label><input v-model="form.expire_date" type="date" />
          <span class="field-hint">有效期为必填：资质信息缺失按不合格处理，不能留空登记。</span>
          <label>发证机关</label><input v-model="form.issued_by" />
        </div>
        <p v-if="createMessage" :class="createOk ? 'ok-text' : 'error-text'">{{ createMessage }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="button" :disabled="saving" @click="submitCreate">保存</button>
        </div>
      </div>
    </div>

    <!-- 员工作业资格矩阵（与排班同一份结论） -->
    <div v-if="qualView" class="modal-mask" @click.self="qualView = null">
      <div class="modal" style="width:720px">
        <h3>{{ qualView.employee.name }}（{{ qualView.employee.employee_id }} · {{ qualView.employee.specialty }}专业）作业资格</h3>
        <p class="muted" style="font-size:12px">结论与「检修排班」保存校验、/api/schedule/check 完全同源。</p>
        <table class="data-table">
          <thead><tr><th>作业项目</th><th>作业专业</th><th>要求证书</th><th>命中证书</th><th>到期天数</th><th>兼岗范围</th><th>资格结论</th></tr></thead>
          <tbody>
            <tr v-for="w in qualView.work_qualifications" :key="w.work_item">
              <td>{{ w.work_item }}</td>
              <td>{{ w.work_specialty }}</td>
              <td>{{ w.required_cert }}</td>
              <td>{{ w.matched_cert_category || '—' }}</td>
              <td :class="daysClass(w.days_left)">{{ formatDays(w.days_left) }}</td>
              <td><span :class="scopeBadge(w.scope)">{{ w.scope || '—' }}</span></td>
              <td>
                <span :class="badge(w.qualification)">{{ w.qualification }}</span>
                <div v-for="(r, i) in w.reasons" :key="i" class="reason-cell">{{ r }}</div>
                <div v-if="w.secondary_reason_required" class="reason-cell">超范围兼岗，保存排班须写明理由</div>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions"><button class="btn" type="button" @click="qualView = null">关闭</button></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '@/api/client'

type Row = Record<string, any>
interface Rules {
  threshold_days: Record<string, number>
  default_threshold_days: number
  cert_specialty: Record<string, string>
  work_items: Record<string, { specialty: string; cert: string }>
  secondary_scope: Record<string, string[]>
  specialties: string[]
  qualifications: string[]
  scopes: string[]
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const certStatus = ref('')
const specialty = ref('')
const includeDup = ref('')
const employees = ref<Row[]>([])
const rules = ref<Rules | null>(null)

const summary = ref({ total: 0, qualified: 0, expiring: 0, expired: 0, missing: 0 })
const showCreate = ref(false)
const saving = ref(false)
const createMessage = ref('')
const createOk = ref(false)
const form = ref({ employee_id: '', cert_category: '', cert_no: '', expire_date: '', issued_by: '' })
const qualView = ref<Record<string, any> | null>(null)

const threshold = (s?: string | null) => rules.value?.threshold_days[s || ''] ?? rules.value?.default_threshold_days ?? 30
const specialties = () => rules.value?.specialties ?? []
const qualifications = () => rules.value?.qualifications ?? []
const certCategories = () => Object.keys(rules.value?.cert_specialty ?? {})
const certSpecialty = () => rules.value?.cert_specialty ?? {}

function formatDays(d: number | null): string {
  return d === null || d === undefined ? '缺失' : d < 0 ? `已过期 ${-d} 天` : `${d} 天`
}
function daysClass(d: number | null): string {
  if (d === null || d === undefined) return 'error-text'
  if (d < 0) return 'error-text'
  return ''
}
function badge(q: string): string {
  if (q === '合格') return 'badge badge-ok'
  if (q === '临期') return 'badge badge-warn'
  if (q === '已过期' || q === '类别不符' || q === '资质缺失') return 'badge badge-bad'
  return 'badge badge-muted'
}
function scopeBadge(s: string): string {
  if (s === '本专业') return 'badge badge-ok'
  if (s === '允许兼岗') return 'badge badge-info'
  if (s === '超范围兼岗') return 'badge badge-warn'
  return 'badge badge-muted'
}

function resetFilters() {
  keyword.value = ''; certStatus.value = ''; specialty.value = ''; includeDup.value = ''
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (certStatus.value) params.set('cert_status', certStatus.value)
  if (specialty.value) params.set('specialty', specialty.value)
  if (includeDup.value === '1') params.set('include_duplicates', 'true')
  try {
    const res = await request(`/api/qualification/certificates?${params}`)
    if (!res.ok) throw new Error('资质台账读取失败')
    const data = await res.json()
    rows.value = data.items ?? []
    total.value = data.total ?? 0
    summary.value = data.summary ?? summary.value
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '资质台账读取失败'
  }
}

function openCreate() {
  createMessage.value = ''
  form.value = { employee_id: '', cert_category: '', cert_no: '', expire_date: '', issued_by: '' }
  showCreate.value = true
}
function onPickEmployee() {
  const e = employees.value.find((x) => x.employee_id === form.value.employee_id)
  if (e && !form.value.cert_category) {
    // 不强制类别，仅提示；保持用户可选其他类别
  }
  void e
}
async function submitCreate() {
  saving.value = true; createMessage.value = ''
  try {
    const res = await request('/api/qualification/certificates', {
      method: 'POST', body: JSON.stringify(form.value),
    })
    const data = await res.json()
    createOk.value = !!data.ok
    createMessage.value = data.message
    if (data.ok) { showCreate.value = false; await reload() }
  } catch (e) {
    createOk.value = false
    createMessage.value = e instanceof Error ? e.message : '登记失败'
  } finally {
    saving.value = false
  }
}

async function openQualification(row: Row) {
  try {
    const res = await request(`/api/qualification/employees/${row.employee_id}/qualifications`)
    if (!res.ok) throw new Error('作业资格读取失败')
    qualView.value = await res.json()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '作业资格读取失败'
  }
}

onMounted(async () => {
  try {
    const [r, er] = await Promise.all([
      request('/api/qualification/rules').then((x) => x.json()),
      request('/api/qualification/employees').then((x) => x.json()),
    ])
    rules.value = r
    employees.value = er.items ?? []
  } catch {
    /* 规则读取失败时下拉为空，列表仍可加载 */
  }
  await reload()
})
</script>
