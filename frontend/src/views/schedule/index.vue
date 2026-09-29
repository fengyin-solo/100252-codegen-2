<template>
  <section class="page" data-module="schedule">
    <header class="page-head">
      <div>
        <h2>检修排班</h2>
        <p class="page-desc">保存排班时强制校验资质：缺失、过期、临期、类别不符一律不允许保存；超出兼岗范围须写明理由。当前资格与资质台账同口径，审核记录独立留存。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记排班</button>
        <button class="btn" type="button" @click="exportRows">导出排班清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.cls">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="排班编号 / 工号 / 姓名" />
      </label>
      <label class="filter-item">
        <span>审核状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>当前资格结论</span>
        <select v-model="filters.result">
          <option value="">全部</option>
          <option v-for="result in resultOptions" :key="result" :value="result">{{ result }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>排班编号</th><th>排班日期</th><th>作业项目</th><th>人员</th>
          <th>作业地点/时段</th><th>兼岗理由</th>
          <th>当前作业资格</th><th>到期天数</th>
          <th>审核记录</th><th>保存时结论</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['排班编号'] }}</td>
          <td>{{ row['排班日期'] }}</td>
          <td>{{ row['作业项目'] }}</td>
          <td>{{ row['员工工号'] }}<br /><small>{{ row['员工姓名'] }}</small></td>
          <td>{{ row['作业地点'] }}<br /><small>{{ row['作业时段'] }}</small></td>
          <td class="reason-cell">{{ row['兼岗理由'] || '—' }}</td>
          <td>
            <span :class="badgeClass(row['作业资格结论'])">{{ row['作业资格结论'] }}</span>
            <p v-if="row['判定理由']" class="cell-reason">{{ row['判定理由'] }}</p>
          </td>
          <td :class="row.qualified ? '' : 'cell-danger'">{{ formatDays(row['到期天数']) }}</td>
          <td>
            <template v-if="row['审核人']">
              {{ row['审核人'] }}<br />
              <small>{{ row['审核意见'] }}</small><br />
              <small>{{ row['审核时间'] }}</small>
            </template>
            <span v-else class="muted-text">待审核（记录留空）</span>
          </td>
          <td>
            <span v-if="row['snapshot_result']" class="snapshot-text">{{ row['snapshot_result'] }}</span>
            <span v-else class="muted-text">—</span>
          </td>
          <td>
            <button v-if="row.status === '待审核'" class="link" type="button" @click="openAudit(row)">审核</button>
            <span v-else class="muted-text">{{ row.status }}</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="11" class="empty-state">暂无排班记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条排班记录；证书到期后刷新页面，当前结论按新口径重算，审核记录仍保留</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 登记排班 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <form class="modal modal-wide" @submit.prevent="submitCreate">
        <h3>登记检修排班</h3>
        <div class="form-grid">
          <label><span>排班日期 *</span><input v-model="form['排班日期']" type="date" required /></label>
          <label>
            <span>作业项目 *</span>
            <select v-model="form['作业项目']" required @change="onJobChange">
              <option value="" disabled>请选择作业项目</option>
              <option v-for="job in jobItems" :key="job" :value="job">{{ job }}</option>
            </select>
          </label>
          <label>
            <span>检修人员 *</span>
            <select v-model="form['员工工号']" required @change="onWorkerChange">
              <option value="" disabled>请先选择作业项目</option>
              <option v-for="item in eligibilityRows" :key="item.worker_id" :value="item.worker_id">
                {{ item.worker_id }} {{ item.worker_name }}（{{ item.specialty }}）— {{ item.result }}
              </option>
            </select>
          </label>
          <label><span>作业地点</span><input v-model="form['作业地点']" /></label>
          <label><span>作业时段</span><input v-model="form['作业时段']" placeholder="如 00:30-03:30" /></label>
        </div>
        <div v-if="selectedVerdict" class="verdict-panel" :class="selectedVerdict.qualified ? 'verdict-ok' : 'verdict-block'">
          <div>
            <span :class="badgeClass(selectedVerdict.result)">{{ selectedVerdict.result }}</span>
            <small>到期天数：{{ formatDays(selectedVerdict.days_to_expiry) }}（{{ selectedVerdict.specialty }}专业阈值 {{ selectedVerdict.threshold_days }} 天）</small>
          </div>
          <p v-for="(reason, idx) in selectedVerdict.reasons" :key="idx" class="cell-reason">{{ reason }}</p>
          <label v-if="!selectedVerdict.qualified || selectedVerdict.result.includes('兼岗')" class="reason-input">
            <span>超范围兼岗理由（不写明理由不允许保存）</span>
            <textarea v-model="form['兼岗理由']" rows="2" placeholder="请写明安排该员工超出允许兼岗范围的理由"></textarea>
          </label>
        </div>
        <p v-else-if="form['作业项目']" class="muted-text">选择人员后即时展示与后端一致的资格判定。</p>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="submit">校验并保存排班</button>
        </footer>
      </form>
    </div>

    <!-- 审核弹窗 -->
    <div v-if="auditTarget" class="modal-mask" @click.self="auditTarget = null">
      <form class="modal" @submit.prevent="submitAudit">
        <h3>审核排班 {{ auditTarget['排班编号'] }}</h3>
        <p class="page-desc">
          当前资质：
          <span :class="badgeClass(auditTarget['作业资格结论'])">{{ auditTarget['作业资格结论'] }}</span>
          ；{{ auditTarget['判定理由'] }}
        </p>
        <div class="form-grid">
          <label><span>审核人 *</span><input v-model="auditForm['审核人']" required /></label>
          <label class="full-span"><span>审核意见 *</span><textarea v-model="auditForm['审核意见']" rows="3" required></textarea></label>
        </div>
        <p class="page-desc">审核通过后审核人、意见与时间作为历史记录长期保留，后续证书到期不影响记录展示。</p>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="auditTarget = null">取消</button>
          <button class="btn primary" type="submit">提交审核</button>
        </footer>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { badgeClass, formatDays } from '@/api/qualification'

type Row = Record<string, string | number | boolean | null>
type Verdict = {
  worker_id: string
  worker_name: string
  specialty: string
  cert_category: string | null
  cert_no: string | null
  days_to_expiry: number | null
  result: string
  qualified: boolean
  blocked: boolean
  threshold_days: number
  reasons: string[]
}

const ENDPOINT = '/api/schedule'
const statuses = ['待审核', '已审核', '已驳回']
const resultOptions = ['合格', '合格(兼岗)', '类别不符(已说明兼岗)', '临期', '已过期', '临期且类别不符', '类别不符', '无证书记录']

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(true)
const filters = reactive({ keyword: '', status: '', result: '' })

const statCards = ref([
  { label: '排班总数', value: 0, cls: '' },
  { label: '待审核', value: 0, cls: '' },
  { label: '当前资格合格', value: 0, cls: 'ok-text' },
  { label: '当前资格不合格', value: 0, cls: 'danger-text' },
])

const jobItems = ref<string[]>([])
const createOpen = ref(false)
const form = reactive<Record<string, string>>({
  排班日期: '', 作业项目: '', 员工工号: '', 作业地点: '', 作业时段: '', 兼岗理由: '',
})
const eligibilityRows = ref<Verdict[]>([])

const selectedVerdict = computed<Verdict | null>(() => {
  if (!form['员工工号']) return null
  return eligibilityRows.value.find((item) => item.worker_id === form['员工工号']) ?? null
})

const auditTarget = ref<Row | null>(null)
const auditForm = reactive({ 审核人: '', 审核意见: '' })

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.result = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export/all`, '_blank')
}

function openCreate() {
  Object.keys(form).forEach((key) => { form[key] = '' })
  eligibilityRows.value = []
  createOpen.value = true
}

async function onJobChange() {
  form['员工工号'] = ''
  eligibilityRows.value = []
  if (!form['作业项目']) return
  const query = new URLSearchParams({ job_item: form['作业项目'] })
  const response = await request(`/api/qualification/eligibility?${query.toString()}`)
  if (response.ok) {
    const payload = await response.json()
    eligibilityRows.value = payload.items ?? []
  }
}

function onWorkerChange() {
  // 切换人员时若人员已合格则清空旧理由；不合格且需要理由时保留输入
  const verdict = selectedVerdict.value
  if (verdict?.qualified && !verdict.result.includes('兼岗')) form['兼岗理由'] = ''
}

async function submitCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...form } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '排班未保存')
    createOpen.value = false
    flash(payload.message || '排班已保存')
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '排班未保存', false)
  }
}

function openAudit(row: Row) {
  auditTarget.value = row
  auditForm['审核人'] = ''
  auditForm['审核意见'] = ''
}

async function submitAudit() {
  if (!auditTarget.value) return
  try {
    const response = await request(`${ENDPOINT}/${auditTarget.value.id}/audit`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...auditForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '审核未提交')
    auditTarget.value = null
    flash(payload.message || '审核完成')
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '审核未提交', false)
  }
}

async function reload() {
  message.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.result) query.set('result', filters.result)
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('排班列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
    statCards.value[0].value = total.value
    statCards.value[1].value = rows.value.filter((r) => r.status === '待审核').length
    statCards.value[2].value = rows.value.filter((r) => r.qualified).length
    statCards.value[3].value = rows.value.filter((r) => !r.qualified).length
  } catch (error) {
    flash(error instanceof Error ? error.message : '排班列表读取失败', false)
  }
}

onMounted(async () => {
  const response = await request(`${ENDPOINT}/options`)
  if (response.ok) {
    const payload = await response.json()
    jobItems.value = payload.job_items ?? []
  }
  await reload()
})
</script>
