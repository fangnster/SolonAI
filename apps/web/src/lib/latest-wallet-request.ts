export interface WalletRequest {
  readonly sequence: number
  readonly wallet: string
}

/** UI request order only. Read slots are not account write versions. */
export class LatestWalletRequest {
  private sequence = 0
  private active: WalletRequest | null = null

  begin(wallet: string): WalletRequest {
    this.active = Object.freeze({ sequence: ++this.sequence, wallet })
    return this.active
  }

  isCurrent(request: WalletRequest): boolean {
    return request === this.active
  }

  invalidate(): void {
    this.active = null
  }
}

export async function loadLatestWallet<T extends { wallet_address: string }>(
  gate: LatestWalletRequest,
  wallet: string,
  load: (wallet: string) => Promise<T>,
  callbacks: {
    success: (value: T) => void
    error: (error: unknown) => void
    loading: (active: boolean) => void
  }
): Promise<void> {
  const request = gate.begin(wallet)
  callbacks.loading(true)
  try {
    const result = await load(wallet)
    if (!gate.isCurrent(request)) return
    if (result.wallet_address !== wallet) throw new Error('response wallet does not match request')
    callbacks.success(result)
  } catch (error) {
    if (gate.isCurrent(request)) callbacks.error(error)
  } finally {
    if (gate.isCurrent(request)) callbacks.loading(false)
  }
}
