import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { readReportContext, reportAgeLabel } from '../src/lib/report-context.ts'

function context(updates = {}) {
  return {
    schema_version: 1,
    freshness_scope: 'account-read-window',
    source: 'rpc_read',
    network: 'devnet',
    commitment: 'confirmed',
    configured_source_id: 'a'.repeat(64),
    account_scope: 'native-sol+legacy-token',
    read_started_at_ms: '1000000',
    read_completed_at_ms: '1001000',
    served_at_ms: '1002500',
    age_ms: 2500,
    max_age_ms: 60000,
    joined_refresh: false,
    publication_status: 'published',
    ...updates,
  }
}

test('valid read and cache contexts keep original timeline', () => {
  const a = readReportContext(context()),
    b = readReportContext(context({ source: 'report_cache' }))
  assert.equal(a.read_started_at_ms, b.read_started_at_ms)
})
test('exact maximum-age boundary is rejected', () => {
  assert.throws(
    () => readReportContext(context({ age_ms: 60000, served_at_ms: '1060000' })),
    /expired/
  )
  assert.doesNotThrow(() => readReportContext(context({ age_ms: 59999, served_at_ms: '1059999' })))
})
test('missing or unsupported context is rejected', () => {
  for (const value of [
    null,
    undefined,
    {},
    context({ schema_version: 0 }),
    context({ source: 'unknown' }),
  ]) {
    assert.throws(() => readReportContext(value))
  }
})
test('timestamps must remain canonical integer strings', () => {
  for (const stamp of [1000000, true, '01', '-1', '18446744073709551616']) {
    assert.throws(() => readReportContext(context({ read_started_at_ms: stamp })))
  }
})
test('claimed age must equal served time minus original start', () => {
  assert.throws(() => readReportContext(context({ age_ms: 0 })), /timeline/)
  assert.throws(() => readReportContext(context({ read_completed_at_ms: '1002501' })), /timeline/)
})
test('age and budget reject floats, booleans and unsafe integers', () => {
  for (const age of [NaN, Infinity, true, '2500', -1, 1.5, 2 ** 53]) {
    assert.throws(() => readReportContext(context({ age_ms: age })))
  }
  assert.throws(() => readReportContext(context({ max_age_ms: 0 })))
})
test('timestamp arithmetic above safe integer range uses BigInt', () => {
  const value = context({
    read_started_at_ms: '18446744073709549115',
    read_completed_at_ms: '18446744073709550115',
    served_at_ms: '18446744073709551615',
  })
  assert.equal(readReportContext(value).age_ms, 2500)
})
test('label describes age at response rather than a live timer', () => {
  assert.match(
    reportAgeLabel(readReportContext(context({ source: 'report_cache' }))),
    /响应时报告年龄：2.5 秒 · 报告缓存 · devnet/
  )
})

if (process.env.WALLET_FIXTURE) {
  test('actual HTTP context passes source, age and timeline validation', () => {
    const body = JSON.parse(readFileSync(process.env.WALLET_FIXTURE, 'utf8'))
    const metadata = readReportContext(body.report_context)
    assert.equal(metadata.freshness_scope, 'account-read-window')
    assert(metadata.age_ms < metadata.max_age_ms)
  })
}
