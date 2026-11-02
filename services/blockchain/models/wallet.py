"""
钱包资产数据模型
"""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SolBalance(BaseModel):
    """SOL 余额"""

    lamports: int = Field(description="Lamports 单位余额")
    sol: Decimal = Field(description="SOL 单位余额")
    usd_value: Optional[Decimal] = Field(default=None, description="USD 估值")


class TokenAccount(BaseModel):
    """SPL Token 账户"""

    model_config = ConfigDict(frozen=True)

    account_address: str = Field(strict=True, min_length=1)
    token_owner: str = Field(strict=True, min_length=1)
    program_id: str = Field(strict=True, min_length=1)
    observed_slot: int = Field(strict=True, ge=0, le=2**64 - 1)
    mint: str = Field(description="Token Mint 地址")
    symbol: Optional[str] = Field(default=None, description="Token 符号")
    name: Optional[str] = Field(default=None, description="Token 名称")
    decimals: int = Field(description="小数位数")
    balance_raw: int = Field(description="原始余额（最小单位）")
    balance: Decimal = Field(description="人类可读余额")
    usd_value: Optional[Decimal] = Field(default=None, description="USD 估值")


class WalletPortfolio(BaseModel):
    """钱包资产全景"""

    wallet_address: str = Field(description="钱包地址")
    sol_balance: SolBalance = Field(description="SOL 余额")
    tokens: list[TokenAccount] = Field(default_factory=list, description="Token 持仓列表")
    token_observed_slot: Optional[int] = Field(
        default=None, description="Token读取slot；空列表未知"
    )
    total_usd_value: Decimal = Field(default=Decimal("0"), description="总 USD 价值")
