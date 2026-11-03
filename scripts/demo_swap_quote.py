"""Offline HTTP quote contract demonstration; no provider calls, keys or orders."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, str(ROOT / "apps/api"))

import httpx  # noqa: E402
from app.api.v1 import assets  # noqa: E402
from fastapi import FastAPI  # noqa: E402

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def demo():
    service = AsyncMock()
    calls = []

    async def quote(**kwargs):
        calls.append(kwargs["amount"])
        return SimpleNamespace(
            provider="jupiter",
            input_mint=kwargs["input_mint"],
            output_mint=kwargs["output_mint"],
            in_amount=kwargs["amount"],
            out_amount=42,
            price_impact_pct=0,
            slippage_bps=kwargs["slippage_bps"],
        )

    service.get_swap_quote.side_effect = quote
    app = FastAPI()
    app.include_router(assets.router, prefix="/api/v1/assets")
    cases = []
    with patch.object(assets, "get_transaction_service", return_value=service):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            for label, mint, raw in [
                ("one USDC at scale 6", USDC, "1000000"),
                ("one SOL base unit", SOL, "1"),
                ("u64 maximum base units", USDC, "18446744073709551615"),
            ]:
                response = await client.post(
                    "/api/v1/assets/swap/quote",
                    json={
                        "input_mint": mint,
                        "output_mint": SOL if mint == USDC else USDC,
                        "amount_raw": raw,
                    },
                )
                assert response.status_code == 200
                assert response.json()["in_amount"] == raw
                assert calls[-1] == int(raw)
                cases.append(
                    {"case": label, "status": 200, "provider_received_raw": str(calls[-1])}
                )
            before = len(calls)
            for label, extra in [
                ("legacy human amount", {"amount": 1.0}),
                ("unsafe numeric JSON", {"amount_raw": 9007199254740995}),
            ]:
                response = await client.post(
                    "/api/v1/assets/swap/quote",
                    json={"input_mint": USDC, "output_mint": SOL, **extra},
                )
                assert response.status_code == 422
                cases.append({"case": label, "status": 422})
            assert len(calls) == before
    return {
        "verified": True,
        "cases": cases,
        "external_provider_calls": 0,
        "orders_submitted": 0,
        "quote_source": "injected fixture, not a market price",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    text = json.dumps(asyncio.run(demo()), indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    print(text, end="")
