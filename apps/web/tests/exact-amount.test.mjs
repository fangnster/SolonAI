import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  formatExactQuantity,
  formatRawAmount,
  readExactQuantity,
  validateWalletQuantities,
} from '../src/lib/exact-amount.ts'

const quantity = (raw, decimals) => ({
  balance_raw: raw,
  decimals,
  balance_exact: formatRawAmount(raw, decimals),
})

test('u64 maximum retains every decimal digit', () => {
  assert.equal(formatRawAmount('18446744073709551615', 18), '18.446744073709551615')
})
test('JSON string roundtrip retains every integer digit', () => {
  const token = JSON.parse(JSON.stringify(quantity('18446744073709551615', 18)))
  assert.equal(readExactQuantity(token).balance_raw, '18446744073709551615')
})
test('unsafe JSON number demonstrates the old failure', () => {
  const old = JSON.parse('{"raw":18446744073709551615}')
  assert.notEqual(BigInt(old.raw), 18446744073709551615n)
})
test('zero decimals formats an integer without a dot', () => {
  assert.equal(formatRawAmount('18446744073709551615', 0), '18446744073709551615')
})
test('zero retains the requested decimal places', () => {
  assert.equal(formatRawAmount('0', 6), '0.000000')
})
test('u8 maximum decimals remains representable as text', () => {
  assert.equal(formatRawAmount('42', 255), '0.' + '0'.repeat(253) + '42')
})
test('grouping preserves all fractional digits', () => {
  assert.equal(formatExactQuantity(quantity('9007199254740995', 9)), '9,007,199.254740995')
})
test('reject noncanonical raw strings and out of range values', () => {
  for (const raw of [
    '',
    '01',
    '+1',
    '-1',
    '1e3',
    '1.0',
    '１',
    '1\n',
    '1\r',
    '1\u2028',
    ' 1',
    '18446744073709551616',
  ]) {
    assert.throws(() => formatRawAmount(raw, 6), /canonical u64/)
  }
})
test('reject numeric raw values even when small', () => {
  for (const raw of [1, true, null, 18446744073709551615n]) {
    assert.throws(() => formatRawAmount(raw, 6), /canonical u64/)
  }
})
test('reject invalid decimal types and range', () => {
  for (const decimals of [-1, 256, 1.5, true, '6', null, NaN, Infinity]) {
    assert.throws(() => formatRawAmount('1', decimals), /u8/)
  }
})
test('reject exact text inconsistent with raw units', () => {
  assert.throws(
    () => readExactQuantity({ ...quantity('1250000', 6), balance_exact: '1.25' }),
    /disagrees/
  )
})
test('missing fields do not fall back to a legacy float or zero', () => {
  assert.throws(() => readExactQuantity({ balance: 1.25 }), /required/)
})
test('valid wallet contract passes and old version is rejected', () => {
  const wallet = {
    quantity_schema_version: 2,
    sol_balance_raw: '0',
    sol_decimals: 9,
    sol_balance_exact: '0.000000000',
    tokens: [quantity('1250000', 6)],
  }
  assert.doesNotThrow(() => validateWalletQuantities(wallet))
  assert.throws(
    () => validateWalletQuantities({ ...wallet, quantity_schema_version: 1 }),
    /unsupported/
  )
  assert.throws(() => validateWalletQuantities({ ...wallet, tokens: null }), /array/)
})
test('JSON serialization requires converting BigInt back to a string', () => {
  assert.throws(() => JSON.stringify({ raw: 1n }), TypeError)
  assert.equal(JSON.parse(JSON.stringify({ raw: String(1n) })).raw, '1')
})

if (process.env.WALLET_FIXTURE) {
  test('actual Python HTTP JSON is accepted without number conversion', () => {
    const wallet = JSON.parse(readFileSync(process.env.WALLET_FIXTURE, 'utf8'))
    validateWalletQuantities(wallet)
    assert.equal(formatExactQuantity(wallet.tokens[0]), '18.446744073709551615')
    assert.equal(wallet.sol_balance_raw, '18446744073709551615')
  })
}
