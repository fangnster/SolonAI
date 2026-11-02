"""
钱包资产查询服务

提供 SOL 余额、SPL Token 持仓、资产全景等高级查询
自带缓存：避免高频重复请求链上数据
"""

import logging
from decimal import Decimal
from typing import List, Optional

from ..cache import cached
from ..config import config
from ..exceptions import RPCResponseValidationError
from ..models.wallet import SolBalance, TokenAccount, WalletPortfolio
from ..providers.jupiter import JupiterProvider
from ..transport.rpc_client import EnhancedRPCClient
from ..transport.token_accounts import LEGACY_TOKEN_PROGRAM_ID

logger = logging.getLogger(__name__)


def _token_balance_from_raw(balance_raw: int, decimals: int) -> Decimal:
    """Build an exact token quantity without a float or context-rounded division."""
    if type(balance_raw) is not int or not 0 <= balance_raw <= 2**64 - 1:
        raise ValueError("balance_raw must be a u64 integer")
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("decimals must be a u8 integer")
    return Decimal(f"{balance_raw}e-{decimals}")


def _normalize_accounts(rows, owner: str) -> List[TokenAccount]:
    """Normalize one read batch; collapse exact repeats and reject conflicting identities."""
    seen = {}
    expected_slot = None
    mint_decimals = {}
    for index, row in enumerate(rows):
        balance = _token_balance_from_raw(row["balance_raw"], row["decimals"])
        token = TokenAccount(
            account_address=row["account_address"],
            token_owner=row["token_owner"],
            program_id=row["program_id"],
            observed_slot=row["observed_slot"],
            mint=row["mint"],
            balance_raw=row["balance_raw"],
            decimals=row["decimals"],
            balance=balance,
        )
        path = f"accounts[{index}]"
        if token.token_owner != owner or token.program_id != LEGACY_TOKEN_PROGRAM_ID:
            raise RPCResponseValidationError(
                path, "account owner or program does not match read scope"
            )
        if expected_slot is not None and token.observed_slot != expected_slot:
            raise RPCResponseValidationError(
                path + ".observed_slot", "mixed read contexts in one batch"
            )
        expected_slot = token.observed_slot
        key = (token.program_id, token.account_address)
        previous = seen.get(key)
        if previous is not None:
            if previous != token:
                raise RPCResponseValidationError(path, "conflicting records for one account")
            continue
        if token.mint in mint_decimals and token.decimals != mint_decimals[token.mint]:
            raise RPCResponseValidationError(
                path + ".decimals", "inconsistent precision for one mint"
            )
        mint_decimals[token.mint] = token.decimals
        seen[key] = token
    return [seen[key] for key in sorted(seen)]


class WalletService:
    """钱包资产查询服务"""

    def __init__(
        self,
        rpc_client: Optional[EnhancedRPCClient] = None,
        jupiter: Optional[JupiterProvider] = None,
    ):
        self._rpc = rpc_client or EnhancedRPCClient()
        self._jupiter = jupiter or JupiterProvider()
        self._owns_clients = rpc_client is None

    @cached("sol_balance", ttl=config.CACHE_TTL_BALANCE)
    async def get_sol_balance(self, address: str, *, use_cache: bool = True) -> SolBalance:
        """
        获取 SOL 余额（缓存 30s）

        Args:
            address: 钱包地址

        Returns:
            SOL 余额 (lamports + sol + usd)
        """
        lamports = await self._rpc.get_balance(address)
        sol = Decimal(str(lamports)) / Decimal("1000000000")

        # 获取 SOL 价格
        usd_value = None
        try:
            sol_price = await self._jupiter.get_token_price(config.WRAPPED_SOL_MINT)
            if sol_price:
                usd_value = sol * sol_price
        except Exception as e:
            logger.warning(f"获取 SOL 价格失败: {e}")

        return SolBalance(lamports=lamports, sol=sol, usd_value=usd_value)

    @cached("token_accounts:identity_v1", ttl=config.CACHE_TTL_TOKENS)
    async def get_token_accounts(
        self, address: str, *, use_cache: bool = True
    ) -> List[TokenAccount]:
        """
        获取所有 SPL Token 持仓（缓存 60s）

        Args:
            address: 钱包地址

        Returns:
            Token 账户列表（含余额和 USD 估值）
        """
        raw_accounts = await self._rpc.get_token_accounts_parsed(address)

        if not raw_accounts:
            return []

        normalized = _normalize_accounts(raw_accounts, address)
        # 收集所有 mint 地址，批量查价格
        mints = list(dict.fromkeys(token.mint for token in normalized))
        prices = {}
        try:
            prices = await self._jupiter.batch_get_token_prices(mints)
        except Exception as e:
            logger.warning(f"批量价格查询失败: {e}")

        # 构建已知代币符号映射
        tokens_map = config.get_tokens()
        symbol_map = {v: k for k, v in tokens_map.items()}

        accounts = []
        for token in normalized:
            mint = token.mint
            price = prices.get(mint)

            accounts.append(
                token.model_copy(
                    update={
                        "symbol": symbol_map.get(mint),
                        "usd_value": token.balance * price if price else None,
                    }
                )
            )

        return accounts

    @cached("wallet_portfolio:identity_v1", ttl=config.CACHE_TTL_BALANCE)
    async def get_wallet_portfolio(
        self, address: str, *, use_cache: bool = True
    ) -> WalletPortfolio:
        """
        获取钱包资产全景（缓存 30s）

        聚合 SOL + 所有 SPL Token，计算总 USD 价值
        """
        import asyncio

        reads = [
            asyncio.create_task(self.get_sol_balance(address, use_cache=use_cache)),
            asyncio.create_task(self.get_token_accounts(address, use_cache=use_cache)),
        ]
        try:
            sol_balance, tokens = await asyncio.gather(*reads)
        except BaseException:
            # Finish sibling cleanup before the API closes owned clients or exits its budget.
            for read in reads:
                read.cancel()
            await asyncio.gather(*reads, return_exceptions=True)
            raise

        # 计算总价值
        total = sol_balance.usd_value or Decimal("0")
        for token in tokens:
            if token.usd_value:
                total += token.usd_value

        return WalletPortfolio(
            wallet_address=address,
            sol_balance=sol_balance,
            tokens=tokens,
            token_observed_slot=tokens[0].observed_slot if tokens else None,
            total_usd_value=total,
        )

    async def close(self):
        """关闭所有连接"""
        if self._owns_clients:
            await self._rpc.close()
        await self._jupiter.close()
