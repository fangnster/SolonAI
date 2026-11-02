import { formatExactQuantity, type ExactQuantity } from './exact-amount.ts'
import { tokenAccountKey, validateWalletIdentities, type TokenIdentity } from './wallet-identity.ts'

/** Only the fields consumed by the asset cards. */
export interface WalletQuantityView {
  wallet_address: string
  account_identity_version: 1
  token_observed_slot: string | null
  sol_balance_raw: string
  sol_decimals: 9
  sol_balance_exact: string
  sol_value_usd: number
  tokens: Array<
    ExactQuantity &
      TokenIdentity & { mint: string; symbol: string; name: string; value_usd: number }
  >
}

export function walletAssetCards(wallet: WalletQuantityView) {
  validateWalletIdentities(wallet)
  return [
    {
      id: `native:sol:${wallet.wallet_address}`,
      icon: 'S',
      symbol: 'SOL',
      name: 'Solana',
      amountExact: formatExactQuantity({
        balance_raw: wallet.sol_balance_raw,
        decimals: wallet.sol_decimals,
        balance_exact: wallet.sol_balance_exact,
      }),
      value: wallet.sol_value_usd,
      change24h: 0,
    },
    ...wallet.tokens.map((token) => ({
      id: tokenAccountKey(token),
      icon: token.symbol.charAt(0),
      symbol: token.symbol,
      name: token.name,
      amountExact: formatExactQuantity(token),
      value: token.value_usd,
      change24h: 0,
    })),
  ]
}
