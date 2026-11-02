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
from ..models.wallet import SolBalance, TokenAccount, WalletPortfolio
from ..providers.jupiter import JupiterProvider
from ..transport.rpc_client import EnhancedRPCClient

logger = logging.getLogger(__name__)


def _sol_from_lamports(lamports: int) -> Decimal:
    """Construct native SOL exactly without context-rounded arithmetic."""
    if type(lamports) is not int or not 0 <= lamports <= 2**64 - 1:
        raise ValueError("lamports must be a u64 integer")
    return Decimal(f"{lamports}e-9")


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
    async def get_sol_balance(self, address: str) -> SolBalance:
        """
        获取 SOL 余额（缓存 30s）

        Args:
            address: 钱包地址

        Returns:
            SOL 余额 (lamports + sol + usd)
        """
        lamports = await self._rpc.get_balance(address)
        sol = _sol_from_lamports(lamports)

        # 获取 SOL 价格
        usd_value = None
        try:
            sol_price = await self._jupiter.get_token_price(config.WRAPPED_SOL_MINT)
            if sol_price:
                usd_value = sol * sol_price
        except Exception as e:
            logger.warning(f"获取 SOL 价格失败: {e}")

        return SolBalance(lamports=lamports, sol=sol, usd_value=usd_value)

    @cached("token_accounts", ttl=config.CACHE_TTL_TOKENS)
    async def get_token_accounts(self, address: str) -> List[TokenAccount]:
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

        # 收集所有 mint 地址，批量查价格
        mints = [acc["mint"] for acc in raw_accounts]
        prices = {}
        try:
            prices = await self._jupiter.batch_get_token_prices(mints)
        except Exception as e:
            logger.warning(f"批量价格查询失败: {e}")

        # 构建已知代币符号映射
        tokens_map = config.get_tokens()
        symbol_map = {v: k for k, v in tokens_map.items()}

        accounts = []
        for acc in raw_accounts:
            mint = acc["mint"]
            balance = Decimal(str(acc["balance"]))
            price = prices.get(mint)

            accounts.append(
                TokenAccount(
                    mint=mint,
                    symbol=symbol_map.get(mint),
                    decimals=acc["decimals"],
                    balance_raw=acc["balance_raw"],
                    balance=balance,
                    usd_value=balance * price if price else None,
                )
            )

        return accounts

    @cached("wallet_portfolio", ttl=config.CACHE_TTL_BALANCE)
    async def get_wallet_portfolio(self, address: str) -> WalletPortfolio:
        """
        获取钱包资产全景（缓存 30s）

        聚合 SOL + 所有 SPL Token，计算总 USD 价值
        """
        import asyncio

        sol_balance, tokens = await asyncio.gather(
            self.get_sol_balance(address),
            self.get_token_accounts(address),
        )

        # 计算总价值
        total = sol_balance.usd_value or Decimal("0")
        for token in tokens:
            if token.usd_value:
                total += token.usd_value

        return WalletPortfolio(
            wallet_address=address,
            sol_balance=sol_balance,
            tokens=tokens,
            total_usd_value=total,
        )

    async def close(self):
        """关闭所有连接"""
        if self._owns_clients:
            await self._rpc.close()
        await self._jupiter.close()
