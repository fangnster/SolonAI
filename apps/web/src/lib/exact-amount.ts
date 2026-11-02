/** The quantity contract only; USD valuation has a separate policy. */
export interface ExactQuantity {
  balance_raw: string
  decimals: number
  balance_exact: string
}

const U64_MAX = 18446744073709551615n

export function formatRawAmount(raw: string, decimals: number): string {
  if (
    typeof raw !== 'string' ||
    raw.length === 0 ||
    raw.length > 20 ||
    /[^0-9]/.test(raw) ||
    (raw.length > 1 && raw.startsWith('0')) ||
    BigInt(raw) > U64_MAX
  ) {
    throw new Error('balance_raw must be a canonical u64 string')
  }
  if (!Number.isInteger(decimals) || decimals < 0 || decimals > 255) {
    throw new Error('decimals must be a u8 integer')
  }
  if (decimals === 0) return raw
  const digits = raw.padStart(decimals + 1, '0')
  return `${digits.slice(0, -decimals)}.${digits.slice(-decimals)}`
}

export function readExactQuantity(value: unknown): ExactQuantity {
  if (typeof value !== 'object' || value === null) throw new Error('quantity must be an object')
  const record = value as Record<string, unknown>
  if (typeof record.balance_raw !== 'string' || typeof record.decimals !== 'number') {
    throw new Error('raw string and integer decimals are required')
  }
  const expected = formatRawAmount(record.balance_raw, record.decimals)
  if (record.balance_exact !== expected) throw new Error('balance_exact disagrees with raw amount')
  return { balance_raw: record.balance_raw, decimals: record.decimals, balance_exact: expected }
}

export function formatExactQuantity(value: unknown): string {
  const quantity = readExactQuantity(value)
  const [whole, fraction] = quantity.balance_exact.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return fraction === undefined ? grouped : `${grouped}.${fraction}`
}

export function validateWalletQuantities(value: unknown): void {
  if (typeof value !== 'object' || value === null) throw new Error('wallet must be an object')
  const wallet = value as Record<string, unknown>
  if (wallet.quantity_schema_version !== 2 || wallet.sol_decimals !== 9) {
    throw new Error('unsupported quantity schema')
  }
  readExactQuantity({
    balance_raw: wallet.sol_balance_raw,
    decimals: wallet.sol_decimals,
    balance_exact: wallet.sol_balance_exact,
  })
  if (!Array.isArray(wallet.tokens)) throw new Error('tokens must be an array')
  wallet.tokens.forEach(readExactQuantity)
}
