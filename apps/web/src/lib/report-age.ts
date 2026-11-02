import { readReportContext, type ReportContext } from './report-context.ts'

export interface LocalTime {
  readonly mono_ms: number
  readonly wall_ms: number
}
export interface ReportAgeView {
  age_ms: number | null
  expired: boolean
  reason: 'fresh' | 'expired' | 'clock_changed'
}
export function sampleLocalTime(): LocalTime {
  return { mono_ms: performance.now(), wall_ms: Date.now() }
}
function valid(t: LocalTime): boolean {
  return (
    Number.isFinite(t.mono_ms) &&
    t.mono_ms >= 0 &&
    t.mono_ms <= Number.MAX_SAFE_INTEGER &&
    Number.isSafeInteger(t.wall_ms) &&
    t.wall_ms >= 0
  )
}

/** Server age + full round trip + local dwell is conservative; processing can overlap. */
export class ReportAgeTracker {
  readonly context: Readonly<ReportContext>
  private received: LocalTime
  private last: LocalTime
  private baseAge = 0
  private highWater = 0
  private clockChanged = false

  constructor(context: ReportContext, sent: LocalTime, received: LocalTime) {
    this.context = Object.freeze({ ...readReportContext(context) })
    this.received = Object.freeze({ ...received })
    this.last = { ...received }
    this.clockChanged =
      !valid(sent) ||
      !valid(received) ||
      received.mono_ms < sent.mono_ms ||
      received.wall_ms < sent.wall_ms
    if (!this.clockChanged) {
      const rtt = Math.ceil(
        Math.max(received.mono_ms - sent.mono_ms, received.wall_ms - sent.wall_ms)
      )
      this.baseAge = Math.min(Number.MAX_SAFE_INTEGER, context.age_ms + rtt)
      this.highWater = this.baseAge
    }
  }

  observe(now: LocalTime): ReportAgeView {
    if (!valid(now) || now.mono_ms < this.last.mono_ms || now.wall_ms < this.last.wall_ms) {
      this.clockChanged = true
    }
    if (this.clockChanged) return { age_ms: null, expired: true, reason: 'clock_changed' }
    this.last = { ...now }
    const dwell = Math.ceil(
      Math.max(now.mono_ms - this.received.mono_ms, now.wall_ms - this.received.wall_ms)
    )
    this.highWater = Math.max(
      this.highWater,
      Math.min(Number.MAX_SAFE_INTEGER, this.baseAge + dwell)
    )
    const expired = this.highWater >= this.context.max_age_ms
    return { age_ms: this.highWater, expired, reason: expired ? 'expired' : 'fresh' }
  }
}

export function liveReportAgeLabel(view: ReportAgeView, context: ReportContext): string {
  if (view.reason === 'clock_changed' || view.age_ms === null) return '本地时间发生变化，请刷新报告'
  if (view.expired) return '报告已过期，请刷新'
  const source = context.source === 'report_cache' ? '报告缓存' : '重新读取'
  return `报告年龄保守估计：${(view.age_ms / 1000).toFixed(1)} 秒 · ${source} · ${context.network}`
}
