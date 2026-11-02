import { formatRawAmount } from './exact-amount.ts'

export interface TokenIdentity {
  account_address: string
  token_owner: string
  program_id: string
  observed_slot: string
}

const TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'

export function tokenAccountKey(token: TokenIdentity): string {
  return `spl:${token.program_id}:${token.account_address}`
}

export function validateWalletIdentities(value: unknown, expectedWallet?: string): void {
  if (typeof value !== 'object' || value === null) throw new Error('wallet identity is required')
  const wallet = value as Record<string, unknown>
  if (
    wallet.account_identity_version !== 1 ||
    typeof wallet.wallet_address !== 'string' ||
    !wallet.wallet_address ||
    (expectedWallet !== undefined && wallet.wallet_address !== expectedWallet) ||
    !Array.isArray(wallet.tokens)
  )
    throw new Error('unsupported or mismatched wallet identity')
  if (wallet.tokens.length === 0) {
    if (wallet.token_observed_slot !== null) throw new Error('empty batch has unknown read slot')
    return
  }
  if (typeof wallet.token_observed_slot !== 'string')
    throw new Error('read slot must be a u64 string')
  formatRawAmount(wallet.token_observed_slot, 0)
  const seen = new Set<string>()
  for (const item of wallet.tokens) {
    if (typeof item !== 'object' || item === null) throw new Error('account identity is required')
    const token = item as Record<string, unknown>
    if (
      typeof token.account_address !== 'string' ||
      !token.account_address ||
      token.token_owner !== wallet.wallet_address ||
      token.program_id !== TOKEN_PROGRAM ||
      typeof token.observed_slot !== 'string'
    )
      throw new Error('invalid account identity')
    formatRawAmount(token.observed_slot, 0)
    if (token.observed_slot !== wallet.token_observed_slot) throw new Error('mixed read contexts')
    const key = tokenAccountKey(token as unknown as TokenIdentity)
    if (seen.has(key)) throw new Error('duplicate account in API response')
    seen.add(key)
  }
}
