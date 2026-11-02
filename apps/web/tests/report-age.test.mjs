import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { ReportAgeTracker, liveReportAgeLabel } from '../src/lib/report-age.ts'

const context = () => ({
  schema_version: 1,
  freshness_scope: 'account-read-window',
  source: 'report_cache',
  network: 'devnet',
  commitment: 'confirmed',
  configured_source_id: 'a'.repeat(64),
  account_scope: 'native-sol+legacy-token',
  read_started_at_ms: '1000000',
  read_completed_at_ms: '1001000',
  served_at_ms: '1002500',
  age_ms: 2500,
  max_age_ms: 10000,
  joined_refresh: false,
  publication_status: 'cache_hit',
})
const time = (m, w = 1000000 + m) => ({ mono_ms: m, wall_ms: w })
const tracker = () => new ReportAgeTracker(context(), time(0), time(100))

test('full request duration is conservatively added to server age', () => {
  assert.equal(tracker().observe(time(100)).age_ms, 2600)
})
test('local dwell grows age without resetting the response baseline', () => {
  const t = tracker()
  assert.equal(t.observe(time(1100)).age_ms, 3600)
  assert.equal(t.observe(time(5100)).age_ms, 7600)
  assert.equal(t.observe(time(5100)).age_ms, 7600)
})
test('exact age boundary expires and does not revive on later observations', () => {
  const t = tracker()
  assert.equal(t.observe(time(7499)).expired, false)
  assert.equal(t.observe(time(7500)).expired, true)
  assert.equal(t.observe(time(7501)).expired, true)
})
test('round trip alone can consume the remaining age budget', () => {
  const c = context()
  c.max_age_ms = 3000
  assert.equal(new ReportAgeTracker(c, time(0), time(1000)).observe(time(1000)).expired, true)
})
test('wall elapsed captures a simulated sleep when monotonic elapsed barely moves', () => {
  const state = tracker().observe(time(100, 1120100))
  assert.equal(state.expired, true)
  assert.equal(state.age_ms, 122600)
})
test('clock rollback latches unknown age rather than zero', () => {
  const t = tracker()
  t.observe(time(1100))
  const invalid = t.observe(time(1200, 1001000))
  assert.equal(invalid.age_ms, null)
  assert.equal(invalid.reason, 'clock_changed')
  assert.equal(t.observe(time(3000)).expired, true)
})
test('invalid local clocks conservatively invalidate the report', () => {
  for (const now of [time(NaN), time(-1), time(100, Infinity), time(100, -1)]) {
    assert.equal(tracker().observe(now).reason, 'clock_changed')
  }
})
test('caller mutation cannot reset captured clocks or context', () => {
  const c = context(),
    received = time(100)
  const t = new ReportAgeTracker(c, time(0), received)
  c.age_ms = 0
  received.mono_ms = 5000
  assert.equal(t.observe(time(1100)).age_ms, 3600)
  assert.throws(() => {
    t.context.age_ms = 0
  }, TypeError)
})
test('fractional durations are rounded upward', () => {
  const t = new ReportAgeTracker(context(), time(0), time(0.2, 1000000))
  assert.equal(t.observe(time(0.4, 1000000)).age_ms, 2502)
})
test('live labels distinguish expired and clock changes', () => {
  assert.match(liveReportAgeLabel(tracker().observe(time(7500)), context()), /报告已过期/)
  assert.match(liveReportAgeLabel(tracker().observe(time(-1)), context()), /时间发生变化/)
})
test('unknown displayed age is never formatted as zero', () => {
  assert.match(
    liveReportAgeLabel({ age_ms: null, expired: false, reason: 'fresh' }, context()),
    /时间发生变化/
  )
})

if (process.env.WALLET_FIXTURE) {
  test('actual API context ages locally and reaches expiry', () => {
    const c = JSON.parse(readFileSync(process.env.WALLET_FIXTURE, 'utf8')).report_context
    const t = new ReportAgeTracker(c, time(0), time(0))
    assert.equal(t.observe(time(c.max_age_ms)).expired, true)
  })
}
