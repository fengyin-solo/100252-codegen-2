/**
 * 资质结论的唯一前端口径：状态码、徽标样式、提示语全部与后端 app/rules.py 对齐，
 * 台账页与排班页都从这里取，禁止各写一套判断。
 */
export const QUALIFIED_RESULTS = ['合格', '合格(兼岗)', '合格(兼岗特批)', '类别不符(已说明兼岗)']

export const BLOCKED_RESULTS = ['无证书记录', '已过期', '临期', '类别不符', '临期且类别不符']

export const CERT_STATES = ['合格', '临期', '已过期']

export function isQualified(result: unknown): boolean {
  return QUALIFIED_RESULTS.includes(String(result ?? ''))
}

export function badgeClass(result: unknown): string {
  const value = String(result ?? '')
  if (!value) return 'badge badge-muted'
  if (value === '合格') return 'badge badge-ok'
  if (value.includes('兼岗') || value.includes('已说明')) return 'badge badge-cross'
  if (value === '无证书记录') return 'badge badge-missing'
  if (value === '已过期') return 'badge badge-expired'
  if (value.includes('临期')) return 'badge badge-expiring'
  return 'badge badge-mismatch'
}

export function formatDays(days: unknown): string {
  if (days === null || days === undefined || days === '') return '—'
  const value = Number(days)
  if (Number.isNaN(value)) return '—'
  if (value < 0) return `已过期 ${Math.abs(value)} 天`
  return `${value} 天`
}
