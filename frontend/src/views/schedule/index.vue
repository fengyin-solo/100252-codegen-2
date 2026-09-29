<template>
  <section class="page" data-module="schedule">
    <header class="page-head">
      <div>
        <h2>检修排班</h2>
        <p class="page-desc">
          保存前按「证书类别 + 专业 + 有效期」判定作业资格：资质缺失/类别不符/已过期/临期一律不允许保存；
          超允许兼岗范围须写明理由并留痕。结论与资质台账同源。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reassess">按新口径重算历史</button>
        <button class="btn primary" type="button" @click="openCreate">安排排班</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card"><span class="stat-label">排班总数</span><strong class="stat-value">{{ total }}</strong></article>
      <article class="stat-card"><span class="stat-label">当前合格</span><strong class="stat-value ok-text">{{ countOf('合格') }}</strong></article>
      <article class="stat-card"><span class="stat-label">当前临期</span><strong class="stat-value" style="color:#b54708">{{ countOf('临期') }}</strong></article>
      <article class="stat-card"><span class="stat-label">过期/不符/缺失</span><strong class="stat-value error-text">{{ badCount }}</strong></article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item"><span>编号/姓名/工号</span><input v-model="keyword" placeholder="关键字" /></label>
      <label class="filter-item"><span>审核状态</span>
        <select v-model="status">
          <option value="">全部</option><option>待审核</option><option>已审核</option><option>已驳回</option>
        </select>
      </label>
      <label class="filter-item"><span>资格结论</span>
        <select v-model="qualification">
          <option value="">全部</option>
          <option v-for="q in qualifications" :key="q" :value="q">{{ q }}</option>
        </select>
      </label>
      <label class="filter-item"><span>异常</span>
        <select v-model="onlyAbnormal"><option value="">全部</option><option value="1">仅异常/不合格</option></select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>排班号</th><th>工号</th><th>姓名</th><th>作业日期</th><th>班次</th>
          <th>作业项目</th><th>兼岗范围</th><th>要求/命中证书</th><th>到期天数</th>
          <th>当前资格</th><th>审核状态</th><th>兼岗理由/原因</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :style="row.qualified ? '' : 'background:#fff7f6'">
          <td>{{ row.schedule_no }}</td>
          <td>{{ row.employee_id }}</td>
          <td>{{ row.employee_name }}</td>
          <td>{{ row.work_date }}</td>
          <td>{{ row.shift }}</td>
          <td>{{ row.work_item }}</td>
          <td><span :class="scopeBadge(row.scope)">{{ row.scope }}</span></td>
          <td>{{ row.required_cert }}<div class="muted">{{ row.matched_cert_category || '未命中' }}</div></td>
          <td :class="daysClass(row.days_left)">{{ formatDays(row.days_left) }}</td>
          <td>
            <span :class="badge(row.qualification)">{{ row.qualification }}</span>
            <div v-for="(r, i) in row.reasons" :key="i" class="reason-cell">{{ r }}</div>
          </td>
          <td>{{ row.status }}</td>
          <td style="max-width:220px">
            <div v-if="row.secondary_reason">{{ row.secondary_reason }}</div>
            <div v-else-if="row.secondary_reason_required" class="reason-cell">超范围兼岗，缺理由</div>
            <span v-else class="muted">—</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openAudit(row)">审核记录({{ (row.audits || []).length }})</button>
            <button v-if="row.status === '待审核'" class="link" type="button" @click="approve(row)">通过</button>
            <button v-if="row.status === '待审核'" class="link" type="button" @click="reject(row)">驳回</button>
          </td>
        </tr>
        <tr v-if="!rows.length"><td colspan="13" class="empty-state">暂无排班记录</td></tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条排班；当前结论实时按今天计算，历史审核记录原样保留</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 安排排班 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h3>安排检修排班</h3>
        <div class="form-grid">
          <label>员工</label>
          <select v-model="form.employee_id" @change="runCheck"><option value="">请选择</option>
            <option v-for="e in employees" :key="e.employee_id" :value="e.employee_id">
              {{ e.employee_id }} · {{ e.name }}（{{ e.specialty }}）
            </option>
          </select>
          <label>作业项目</label>
          <select v-model="form.work_item" @change="runCheck"><option value="">请选择</option>
            <option v-for="(cfg, name) in rules?.work_items || {}" :key="name" :value="name">
              {{ name }}（{{ cfg.specialty }} / {{ cfg.cert }}）
            </option>
          </select>
          <label>作业日期</label><input v-model="form.work_date" type="date" />
          <label>班次</label><select v-model="form.shift"><option>白班</option><option>夜班</option></select>
        </div>

        <div v-if="checkResult" style="margin-top:14px; border-top:1px solid var(--border); padding-top:12px">
          <p style="margin:4px 0">
            当前资格：<span :class="badge(checkResult.qualification)">{{ checkResult.qualification }}</span>
            ｜兼岗范围：<span :class="scopeBadge(checkResult.scope)">{{ checkResult.scope }}</span>
            ｜到期天数：<b :class="daysClass(checkResult.days_left)">{{ formatDays(checkResult.days_left) }}</b>
            <span class="muted">（阈值 {{ checkResult.threshold_days }} 天）</span>
          </p>
          <div v-for="(r, i) in checkResult.reasons" :key="i" class="reason-cell">{{ r }}</div>
          <template v-if="checkResult.qualified">
            <label v-if="checkResult.secondary_reason_required" class="form-grid" style="grid-template-columns:120px 1fr; margin-top:8px">
              <span class="reason-cell">兼岗理由（必填）</span>
              <textarea v-model="form.secondary_reason" placeholder="超出允许兼岗范围，须写明理由后方可保存"></textarea>
            </label>
            <p v-else class="ok-text" style="font-size:12px">属于允许兼岗/本专业范围，无需额外理由。</p>
          </template>
          <p v-else class="error-text" style="font-size:12px">资质不合格，排班将被拦截，任何理由均不能放行。</p>
        </div>

        <p v-if="createMessage" :class="createOk ? 'ok-text' : 'error-text'">{{ createMessage }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="button" :disabled="saving" @click="submitCreate">保存排班</button>
        </div>
      </div>
    </div>

    <!-- 审核记录（只追加，证书过期也不删） -->
    <div v-if="auditView" class="modal-mask" @click.self="auditView = null">
      <div class="modal">
        <h3>{{ auditView.schedule_no }} 审核记录</h3>
        <p class="muted" style="font-size:12px">
          审核记录只追加、不覆盖；证书到期或重算后仍完整保留。当前资格：
          <span :class="badge(auditView.qualification)">{{ auditView.qualification }}</span>
        </p>
        <div v-for="(a, i) in auditView.audits" :key="i" class="audit-item">
          <div class="at">{{ (a.at || '').replace('T', ' ') }} · {{ a.reviewer }}</div>
          <div><b>{{ a.action }}</b> ｜当时结论：{{ a.qualification_snapshot }} ｜当时到期天数：{{ a.days_left_snapshot }} ｜范围：{{ a.scope_snapshot }}</div>
          <div>{{ a.note }}</div>
        </div>
        <div v-if="!(auditView.audits || []).length" class="muted">暂无审核记录</div>
        <div class="modal-actions"><button class="btn" type="button" @click="auditView = null">关闭</button></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '@/api/client'

type Row = Record<string, any>
interface Rules {
  threshold_days: Record<string, number>
  work_items: Record<string, { specialty: string; cert: string }>
  qualifications: string[]
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref(''); const status = ref(''); const qualification = ref(''); const onlyAbnormal = ref('')
const employees = ref<Row[]>([])
const rules = ref<Rules | null>(null)

const showCreate = ref(false); const saving = ref(false)
const form = ref({ employee_id: '', work_item: '', work_date: '', shift: '白班', secondary_reason: '' })
const checkResult = ref<Row | null>(null)
const createMessage = ref(''); const createOk = ref(false)
const auditView = ref<Row | null>(null)

const qualifications = computed(() => rules.value?.qualifications ?? ['合格', '临期', '已过期', '类别不符', '资质缺失'])
const countOf = (q: string) => rows.value.filter((r) => r.qualification === q).length
const badCount = computed(() => rows.value.filter((r) => !r.qualified).length)

function formatDays(d: number | null): string {
  return d === null || d === undefined ? '缺失' : d < 0 ? `已过期 ${-d}天` : `${d} 天`
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
  keyword.value = ''; status.value = ''; qualification.value = ''; onlyAbnormal.value = ''
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (status.value) params.set('status', status.value)
  if (qualification.value) params.set('qualification', qualification.value)
  if (onlyAbnormal.value === '1') params.set('only_abnormal', 'true')
  params.set('size', '100')
  try {
    const res = await request(`/api/schedule?${params}`)
    if (!res.ok) throw new Error('排班列表读取失败')
    const data = await res.json()
    rows.value = data.items ?? []
    total.value = data.total ?? 0
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '排班列表读取失败'
  }
}

function openCreate() {
  form.value = { employee_id: '', work_item: '', work_date: '', shift: '白班', secondary_reason: '' }
  checkResult.value = null; createMessage.value = ''
  showCreate.value = true
}
async function runCheck() {
  if (!form.value.employee_id || !form.value.work_item) { checkResult.value = null; return }
  try {
    const res = await request('/api/schedule/check', {
      method: 'POST', body: JSON.stringify({ employee_id: form.value.employee_id, work_item: form.value.work_item }),
    })
    checkResult.value = await res.json()
  } catch {
    checkResult.value = null
  }
}
async function submitCreate() {
  saving.value = true; createMessage.value = ''
  try {
    const res = await request('/api/schedule', { method: 'POST', body: JSON.stringify(form.value) })
    const data = await res.json()
    createOk.value = !!data.ok
    createMessage.value = data.message
    if (data.ok) { showCreate.value = false; await reload() }
  } catch (e) {
    createOk.value = false
    createMessage.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function act(row: Row, action: string, note = '') {
  try {
    const res = await request(`/api/schedule/${row.id}/actions`, {
      method: 'POST', body: JSON.stringify({ values: { action, note } }),
    })
    const data = await res.json()
    if (!data.ok) { errorMessage.value = data.message }
    await reload()
    if (data.ok && auditView.value?.id === row.id) openAudit(data.entry)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '操作失败'
  }
}
const approve = (row: Row) => act(row, '审核通过', '同意')
const reject = (row: Row) => act(row, '驳回', '资质存疑，驳回')
function openAudit(row: Row) { auditView.value = row }

async function reassess() {
  errorMessage.value = ''
  try {
    const res = await request('/api/schedule/reassess', { method: 'POST' })
    const data = await res.json()
    errorMessage.value = ''
    alert(`${data.message}：共 ${data.entry.total} 条，结论变化 ${data.entry.changed} 条；审核记录保持不变`)
    await reload()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '重算失败'
  }
}

onMounted(async () => {
  try {
    const [r, er] = await Promise.all([
      request('/api/schedule/rules').then((x) => x.json()),
      request('/api/qualification/employees').then((x) => x.json()),
    ])
    rules.value = r
    employees.value = er.items ?? []
  } catch { /* 规则缺失时仍可看列表 */ }
  await reload()
})
</script>
