"""
资产诊断 API

提供资产查询、诊断、盈亏分析等接口
"""

import os
import sys
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 添加区块链服务路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", "..", "..", "..", ".."))
services_path = os.path.join(project_root, "services")
sys.path.insert(0, services_path)

from app.core.database import get_db  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.wallet_report_cache import (
    ReportContext,
    ReportFreshnessError,
    get_wallet_report_cache,
)  # noqa: E402
from app.models import User  # noqa: E402

router = APIRouter()


def _exact_amount(raw: int, decimals: int) -> str:
    """Format validated integer units without float or Decimal arithmetic."""
    if type(raw) is not int or not 0 <= raw <= 2**64 - 1:
        raise ValueError("raw amount must be a u64 integer")
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("decimals must be a u8 integer")
    digits = str(raw)
    if decimals == 0:
        return digits
    digits = digits.zfill(decimals + 1)
    return f"{digits[:-decimals]}.{digits[-decimals:]}"


def get_wallet_service():
    """Import WalletService lazily so the whole API can still boot."""
    try:
        from blockchain.services.wallet_service import WalletService  # noqa: WPS433, E402

        return WalletService()
    except ModuleNotFoundError as exc:
        missing_package = exc.name or "unknown dependency"
        raise HTTPException(
            status_code=503,
            detail=(
                f"区块链资产服务依赖未安装，当前无法查询链上资产。 缺少依赖: {missing_package}"
            ),
        ) from exc


def get_transaction_service():
    """Import TransactionService lazily."""
    try:
        from blockchain.services.transaction_service import TransactionService  # noqa: WPS433

        return TransactionService()
    except ModuleNotFoundError as exc:
        missing_package = exc.name or "unknown dependency"
        raise HTTPException(
            status_code=503,
            detail=f"区块链交易服务依赖未安装。缺少: {missing_package}",
        ) from exc


# ===== 响应模型 =====


class TokenAsset(BaseModel):
    """Token 资产"""

    symbol: str  # Token 符号
    name: str  # Token 名称
    mint: Optional[str] = None  # Mint 地址
    account_address: str
    token_owner: str
    program_id: str
    observed_slot: str  # u64 read context encoded as text for JavaScript
    balance: float  # Legacy approximate field; new clients use balance_exact
    balance_raw: str  # Integer units encoded as a JSON string
    decimals: int
    balance_exact: str  # Fixed-point text, derived only from raw and decimals
    price_usd: float  # 美元价格
    value_usd: float  # 美元价值


class WalletAssetsPayload(BaseModel):
    """钱包资产"""

    wallet_address: str
    quantity_schema_version: Literal[2] = 2
    account_identity_version: Literal[1] = 1
    token_observed_slot: Optional[str]
    sol_balance_raw: str
    sol_decimals: Literal[9] = 9
    sol_balance_exact: str
    sol_balance: float  # SOL 余额
    sol_price_usd: float  # SOL 价格
    sol_value_usd: float  # SOL 价值
    tokens: List[TokenAsset]  # Token 列表
    total_value_usd: float  # 总价值


class WalletAssets(WalletAssetsPayload):
    report_context: ReportContext


class SwapQuoteRequest(BaseModel):
    """Exact-in quote request; raw units belong to the input mint, never a guessed scale."""

    model_config = ConfigDict(extra="forbid")

    input_mint: str = Field(strict=True, min_length=1, max_length=64)
    output_mint: str = Field(strict=True, min_length=1, max_length=64)
    amount_raw: str = Field(
        strict=True,
        min_length=1,
        max_length=20,
        description="Canonical positive u64 integer text in input-mint base units",
    )
    slippage_bps: int = Field(default=50, strict=True, ge=0, le=10000)
    provider: Literal["auto", "jupiter", "raydium"] = "auto"

    @field_validator("amount_raw")
    @classmethod
    def validate_amount_raw(cls, value: str) -> str:
        if not value.isascii() or not value.isdigit() or value.startswith("0"):
            raise ValueError("amount_raw must be canonical positive ASCII integer text")
        if int(value) > 2**64 - 1:
            raise ValueError("amount_raw exceeds u64")
        return value


class SwapQuoteResponse(BaseModel):
    """Swap 报价响应"""

    provider: str
    input_mint: str
    output_mint: str
    in_amount: str
    out_amount: str
    price_impact_pct: str
    slippage_bps: int


class PnLAnalysis(BaseModel):
    """盈亏分析"""

    total_profit: float  # 总盈利
    total_loss: float  # 总亏损
    net_profit: float  # 净盈利
    roi: float  # 投资回报率
    win_rate: float  # 胜率


class RiskFactor(BaseModel):
    """风险因素"""

    category: str  # 风险类别
    severity: str  # 严重程度：low/medium/high
    description: str  # 描述
    suggestion: str  # 建议


class AssetDiagnosis(BaseModel):
    """资产诊断"""

    wallet_address: str
    overall_risk: str  # 总体风险：low/medium/high
    risk_score: float  # 风险评分 0-100
    risk_factors: List[RiskFactor]  # 风险因素列表
    suggestions: List[str]  # 优化建议


# ===== API 接口 =====


async def _build_assets_payload(wallet_address: str):
    # 使用新的 WalletService 获取资产
    wallet_service = get_wallet_service()
    try:
        portfolio = await wallet_service.get_wallet_portfolio(wallet_address, use_cache=False)
    finally:
        await wallet_service.close()

    # 转换为 API 响应格式
    tokens = [
        TokenAsset(
            symbol=t.symbol or "UNKNOWN",
            name=t.name or t.mint[:8] + "...",
            mint=t.mint,
            account_address=t.account_address,
            token_owner=t.token_owner,
            program_id=t.program_id,
            observed_slot=str(t.observed_slot),
            balance=float(t.balance),
            balance_raw=str(t.balance_raw),
            decimals=t.decimals,
            balance_exact=_exact_amount(t.balance_raw, t.decimals),
            price_usd=float(t.usd_value / t.balance) if t.usd_value and t.balance else 0.0,
            value_usd=float(t.usd_value) if t.usd_value else 0.0,
        )
        for t in portfolio.tokens
    ]

    sol_price = 0.0
    sol_value = 0.0
    if portfolio.sol_balance.usd_value and portfolio.sol_balance.sol:
        sol_price = float(portfolio.sol_balance.usd_value / portfolio.sol_balance.sol)
        sol_value = float(portfolio.sol_balance.usd_value)

    response = WalletAssetsPayload(
        wallet_address=wallet_address,
        token_observed_slot=(
            str(portfolio.token_observed_slot)
            if portfolio.token_observed_slot is not None
            else None
        ),
        sol_balance_raw=str(portfolio.sol_balance.lamports),
        sol_balance_exact=_exact_amount(portfolio.sol_balance.lamports, 9),
        sol_balance=float(portfolio.sol_balance.sol),
        sol_price_usd=sol_price,
        sol_value_usd=sol_value,
        tokens=tokens,
        total_value_usd=float(portfolio.total_usd_value),
    )
    return response.model_dump()


@router.get("/{wallet_address}", response_model=WalletAssets)
async def get_assets(
    wallet_address: str,
    refresh: bool = False,
    redis=Depends(get_redis),
    reports=Depends(get_wallet_report_cache),
):
    """Return a bounded-age account read; refresh skips stored reports and may join an active read."""
    try:
        return await reports.get(
            redis,
            wallet_address,
            lambda: _build_assets_payload(wallet_address),
            lambda payload: WalletAssetsPayload.model_validate(payload).model_dump(),
            refresh=refresh,
        )
    except ReportFreshnessError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"获取资产失败: {str(error)}") from error


@router.get("/{wallet_address}/diagnosis", response_model=AssetDiagnosis)
async def diagnose_assets(wallet_address: str):
    """
    资产诊断

    分析资产风险、提供优化建议
    """
    try:
        # TODO: 实现真实的风险诊断逻辑
        # 这里返回 mock 数据

        risk_factors = [
            RiskFactor(
                category="授权风险",
                severity="low",
                description="检测到 2 个活跃的代币授权",
                suggestion="定期检查并撤销不再使用的授权",
            ),
            RiskFactor(
                category="资产集中度",
                severity="medium",
                description="90% 的资产集中在 SOL",
                suggestion="考虑适当分散投资，降低单一资产风险",
            ),
        ]

        suggestions = [
            "您的闲置 SOL 可以存入 MarginFi 赚取 4.2% 年化收益",
            "建议将部分资产配置到稳定币，降低波动风险",
            "定期检查并撤销不再使用的代币授权",
        ]

        return AssetDiagnosis(
            wallet_address=wallet_address,
            overall_risk="low",
            risk_score=25.5,
            risk_factors=risk_factors,
            suggestions=suggestions,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"资产诊断失败: {str(e)}")


@router.post("/swap/quote", response_model=SwapQuoteResponse)
async def get_swap_quote(request: SwapQuoteRequest):
    """
    获取 Swap 报价

    聚合 Jupiter + Raydium 获取最优报价
    """
    try:
        tx_service = get_transaction_service()
        try:
            amount_raw = int(request.amount_raw)

            quote = await tx_service.get_swap_quote(
                input_mint=request.input_mint,
                output_mint=request.output_mint,
                amount=amount_raw,
                slippage_bps=request.slippage_bps,
                provider=request.provider,
            )
        finally:
            await tx_service.close()

        # This endpoint requests ExactIn. Never return a quote for another request's units.
        if (
            type(quote.in_amount) is not int
            or quote.in_amount != amount_raw
            or type(quote.out_amount) is not int
            or not 0 <= quote.out_amount <= 2**64 - 1
            or quote.input_mint != request.input_mint
            or quote.output_mint != request.output_mint
            or quote.provider not in ("jupiter", "raydium")
            or (request.provider != "auto" and quote.provider != request.provider)
            or type(quote.slippage_bps) is not int
            or quote.slippage_bps != request.slippage_bps
        ):
            raise HTTPException(status_code=502, detail="Quote does not match the request contract")

        return SwapQuoteResponse(
            provider=quote.provider,
            input_mint=quote.input_mint,
            output_mint=quote.output_mint,
            in_amount=str(quote.in_amount),
            out_amount=str(quote.out_amount),
            price_impact_pct=str(quote.price_impact_pct or 0),
            slippage_bps=quote.slippage_bps,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取报价失败: {str(e)}")


@router.get("/{wallet_address}/pnl", response_model=PnLAnalysis)
async def get_pnl(
    wallet_address: str,
    db: AsyncSession = Depends(get_db),
):
    """
    盈亏分析

    分析用户的历史交易盈亏
    """
    try:
        # 查找用户
        result = await db.execute(select(User).where(User.wallet_address == wallet_address))
        user = result.scalar_one_or_none()

        if not user:
            # 新用户，返回空数据
            return PnLAnalysis(
                total_profit=0.0,
                total_loss=0.0,
                net_profit=0.0,
                roi=0.0,
                win_rate=0.0,
            )

        # TODO: 查询用户的交易记录，计算盈亏
        # 这里返回 mock 数据

        return PnLAnalysis(
            total_profit=1250.50,
            total_loss=320.80,
            net_profit=929.70,
            roi=15.6,
            win_rate=68.5,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"盈亏分析失败: {str(e)}")
