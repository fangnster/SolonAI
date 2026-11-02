import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { validateWalletIdentities } from '../src/lib/wallet-identity.ts'
import { walletAssetCards } from '../src/lib/wallet-asset-view.ts'
import { LatestWalletRequest, loadLatestWallet } from '../src/lib/latest-wallet-request.ts'

const PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
function wallet(owner = 'wallet-a', slot = '424242') {
  return {
    wallet_address: owner,
    account_identity_version: 1,
    quantity_schema_version: 2,
    token_observed_slot: slot,
    sol_balance_raw: '0',
    sol_decimals: 9,
    sol_balance_exact: '0.000000000',
    sol_value_usd: 0,
    tokens: ['TA_A', 'TA_B'].map((account_address) => ({
      account_address,
      token_owner: owner,
      program_id: PROGRAM,
      observed_slot: slot,
      mint: 'USDC_TEST',
      symbol: 'USDC',
      name: 'USD fixture',
      value_usd: 0,
      balance_raw: '1250000',
      decimals: 6,
      balance_exact: '1.250000',
    })),
  }
}
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
function harness() {
  const state = { value: null, error: null, loading: false }
  const gate = new LatestWalletRequest()
  const callbacks = {
    success: (value) => {
      state.value = value
    },
    error: (error) => {
      state.error = String(error)
    },
    loading: (value) => {
      state.loading = value
    },
  }
  return {
    state,
    gate,
    start: (owner, promise) => loadLatestWallet(gate, owner, () => promise, callbacks),
  }
}

test('same mint uses distinct stable account keys across order and slot changes', () => {
  const source = wallet()
  const keys = walletAssetCards(source)
    .slice(1)
    .map((card) => card.id)
  assert.equal(new Set(keys).size, 2)
  const refreshed = wallet('wallet-a', '424243')
  refreshed.tokens.reverse()
  assert.deepEqual(
    walletAssetCards(refreshed)
      .slice(1)
      .map((card) => card.id)
      .sort(),
    [...keys].sort()
  )
})
test('maximum u64 read slot stays a string', () => {
  assert.doesNotThrow(() => validateWalletIdentities(wallet('wallet-a', '18446744073709551615')))
})
test('missing or invalid identity is rejected', () => {
  for (const field of ['account_address', 'token_owner', 'program_id', 'observed_slot']) {
    const source = wallet()
    delete source.tokens[0][field]
    assert.throws(() => validateWalletIdentities(source), /identity/)
  }
})
test('duplicate API accounts are rejected instead of summed', () => {
  const source = wallet()
  source.tokens.push({ ...source.tokens[0] })
  assert.throws(() => validateWalletIdentities(source), /duplicate/)
})
test('wallet and read context must match', () => {
  assert.throws(() => validateWalletIdentities(wallet(), 'wallet-b'), /mismatched/)
  const source = wallet()
  source.tokens[1].observed_slot = '424243'
  assert.throws(() => validateWalletIdentities(source), /mixed/)
})
test('numeric or noncanonical slots are rejected', () => {
  for (const slot of [424242, true, '-1', '01', '18446744073709551616']) {
    assert.throws(() => validateWalletIdentities(wallet('wallet-a', slot)))
  }
})
test('empty account list has explicit unknown context', () => {
  const source = wallet()
  source.tokens = []
  source.token_observed_slot = null
  assert.doesNotThrow(() => validateWalletIdentities(source))
  source.token_observed_slot = '0'
  assert.throws(() => validateWalletIdentities(source), /unknown/)
})
test('late old success cannot replace latest request even with a higher slot', async () => {
  const h = harness(),
    old = deferred(),
    recent = deferred()
  const first = h.start('wallet-a', old.promise)
  const second = h.start('wallet-a', recent.promise)
  recent.resolve(wallet('wallet-a', '100'))
  await second
  old.resolve(wallet('wallet-a', '200'))
  await first
  assert.equal(h.state.value.token_observed_slot, '100')
})
test('late old failure cannot clear loading or overwrite current success', async () => {
  const h = harness(),
    old = deferred(),
    recent = deferred()
  const first = h.start('wallet-a', old.promise)
  const second = h.start('wallet-a', recent.promise)
  old.reject(new Error('old failed'))
  await first
  assert.equal(h.state.loading, true)
  assert.equal(h.state.error, null)
  recent.resolve(wallet())
  await second
  assert.equal(h.state.loading, false)
})
test('wallet switch and disconnect invalidate previous request', async () => {
  const h = harness(),
    old = deferred(),
    recent = deferred()
  const first = h.start('wallet-a', old.promise)
  const second = h.start('wallet-b', recent.promise)
  recent.resolve(wallet('wallet-b'))
  await second
  old.resolve(wallet('wallet-a'))
  await first
  assert.equal(h.state.value.wallet_address, 'wallet-b')
  const pending = deferred(),
    third = h.start('wallet-b', pending.promise)
  h.gate.invalidate()
  pending.resolve(wallet('wallet-b', '424244'))
  await third
  assert.equal(h.state.value.token_observed_slot, '424242')
})
test('latest empty result replaces old rows and current failure does not resurrect old success', async () => {
  const h = harness()
  await h.start('wallet-a', Promise.resolve(wallet()))
  const empty = wallet()
  empty.tokens = []
  empty.token_observed_slot = null
  await h.start('wallet-a', Promise.resolve(empty))
  assert.equal(h.state.value.tokens.length, 0)
  const old = deferred(),
    recent = deferred()
  const first = h.start('wallet-a', old.promise),
    second = h.start('wallet-a', recent.promise)
  recent.reject(new Error('current failed'))
  await second
  old.resolve(wallet())
  await first
  assert.equal(h.state.value.tokens.length, 0)
  assert.match(h.state.error, /current failed/)
})
test('current response from a different wallet is rejected', async () => {
  const h = harness()
  await h.start('wallet-a', Promise.resolve(wallet('wallet-b')))
  assert.equal(h.state.value, null)
  assert.match(h.state.error, /does not match/)
})

if (process.env.WALLET_FIXTURE) {
  test('actual RPC-to-API JSON keeps identities, unique keys and string slots', () => {
    const source = JSON.parse(readFileSync(process.env.WALLET_FIXTURE, 'utf8'))
    validateWalletIdentities(source, source.wallet_address)
    const cards = walletAssetCards(source)
    assert.equal(new Set(cards.map((card) => card.id)).size, cards.length)
    assert.equal(typeof source.tokens[0].observed_slot, 'string')
  })
}
