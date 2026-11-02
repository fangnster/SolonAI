import { formatRawAmount } from './exact-amount.ts'

export interface ReportContext {
  schema_version: 1
  freshness_scope: 'account-read-window'
  source: 'rpc_read' | 'report_cache'
  network: string
  commitment: 'confirmed'
  configured_source_id: string
  account_scope: 'native-sol+legacy-token'
  read_started_at_ms: string
  read_completed_at_ms: string
  served_at_ms: string
  age_ms: number
  max_age_ms: number
  joined_refresh: boolean
  publication_status: 'published' | 'cache_hit' | 'skipped' | 'unknown'
}

export function readReportContext(value: unknown): ReportContext {
  if (typeof value !== 'object' || value === null) throw new Error('report context is required')
  const c = value as Record<string, unknown>
  if (
    c.schema_version !== 1 ||
    c.freshness_scope !== 'account-read-window' ||
    !['rpc_read', 'report_cache'].includes(c.source as string) ||
    c.commitment !== 'confirmed' ||
    c.account_scope !== 'native-sol+legacy-token' ||
    typeof c.network !== 'string' ||
    !c.network ||
    typeof c.configured_source_id !== 'string' ||
    !/^[0-9a-f]{64}$/.test(c.configured_source_id) ||
    typeof c.joined_refresh !== 'boolean' ||
    !['published', 'cache_hit', 'skipped', 'unknown'].includes(c.publication_status as string)
  )
    throw new Error('invalid report source context')
  for (const field of ['read_started_at_ms', 'read_completed_at_ms', 'served_at_ms']) {
    if (typeof c[field] !== 'string') throw new Error('report timestamps must be u64 strings')
    formatRawAmount(c[field] as string, 0)
  }
  if (
    !Number.isSafeInteger(c.age_ms) ||
    (c.age_ms as number) < 0 ||
    !Number.isSafeInteger(c.max_age_ms) ||
    (c.max_age_ms as number) <= 0 ||
    (c.age_ms as number) >= (c.max_age_ms as number)
  )
    throw new Error('report read window expired')
  const start = BigInt(c.read_started_at_ms as string),
    complete = BigInt(c.read_completed_at_ms as string)
  const served = BigInt(c.served_at_ms as string)
  if (start > complete || complete > served || served - start !== BigInt(c.age_ms as number)) {
    throw new Error('inconsistent report timeline')
  }
  return c as unknown as ReportContext
}

export function reportAgeLabel(context: ReportContext): string {
  const source = context.source === 'report_cache' ? '报告缓存' : '重新读取'
  return `响应时报告年龄：${(context.age_ms / 1000).toFixed(1)} 秒 · ${source} · ${context.network}`
}
