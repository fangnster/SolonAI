"""Exercise the HTTP quote boundary with a provider double and no external calls."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.api.v1 import assets
from fastapi import FastAPI

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class SwapQuoteUnitsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = AsyncMock()

        async def quote(**kwargs):
            return SimpleNamespace(
                provider="jupiter" if kwargs["provider"] == "auto" else kwargs["provider"],
                input_mint=kwargs["input_mint"],
                output_mint=kwargs["output_mint"],
                in_amount=kwargs["amount"],
                out_amount=42,
                price_impact_pct=0,
                slippage_bps=kwargs["slippage_bps"],
            )

        self.service.get_swap_quote.side_effect = quote
        self.factory = patch.object(assets, "get_transaction_service", return_value=self.service)
        self.mock_factory = self.factory.start()
        app = FastAPI()
        app.include_router(assets.router, prefix="/api/v1/assets")
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://fixture",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.factory.stop()

    async def post(self, **changes):
        body = {"input_mint": USDC, "output_mint": SOL, "amount_raw": "1000000"}
        body.update(changes)
        return await self.client.post("/api/v1/assets/swap/quote", json=body)

    async def test_usdc_raw_units_are_not_scaled_as_nine_decimals(self):
        response = await self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["in_amount"], "1000000")
        self.service.get_swap_quote.assert_awaited_once_with(
            input_mint=USDC,
            output_mint=SOL,
            amount=1_000_000,
            slippage_bps=50,
            provider="auto",
        )

    async def test_legacy_human_amount_is_rejected_instead_of_guessed(self):
        response = await self.client.post(
            "/api/v1/assets/swap/quote",
            json={"input_mint": USDC, "output_mint": SOL, "amount": 1.0},
        )
        self.assertEqual(response.status_code, 422)
        self.mock_factory.assert_not_called()

    async def test_u64_max_survives_http_and_provider_call(self):
        response = await self.post(amount_raw="18446744073709551615")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["in_amount"], "18446744073709551615")
        self.assertEqual(self.service.get_swap_quote.call_args.kwargs["amount"], 2**64 - 1)

    async def test_one_raw_unit_is_not_rounded_to_zero(self):
        response = await self.post(input_mint=SOL, output_mint=USDC, amount_raw="1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["in_amount"], "1")

    async def test_noncanonical_amounts_fail_before_provider_creation(self):
        for value in [
            "0",
            "01",
            "+1",
            "-1",
            "1.0",
            "1e6",
            " 1",
            "1\n",
            "１",
            "",
            "18446744073709551616",
            "9" * 1000,
        ]:
            with self.subTest(value=str(value)[:30]):
                self.assertEqual((await self.post(amount_raw=value)).status_code, 422)
        self.mock_factory.assert_not_called()

    async def test_json_numbers_and_booleans_are_not_raw_strings(self):
        for value in [1, 1.0, 9_007_199_254_740_995, True, None]:
            with self.subTest(value=value):
                self.assertEqual((await self.post(amount_raw=value)).status_code, 422)
        self.mock_factory.assert_not_called()

    async def test_slippage_bounds_are_explicit_and_strict(self):
        for value in [-1, 10001, 1.5, True, "50"]:
            with self.subTest(value=value):
                self.assertEqual((await self.post(slippage_bps=value)).status_code, 422)
        self.mock_factory.assert_not_called()

    async def test_valid_slippage_and_provider_are_forwarded(self):
        for value in [0, 10000]:
            response = await self.post(slippage_bps=value, provider="raydium")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["slippage_bps"], value)
            self.assertEqual(self.service.get_swap_quote.call_args.kwargs["provider"], "raydium")

    async def test_unknown_provider_and_extra_human_amount_are_rejected(self):
        self.assertEqual((await self.post(provider="unknown")).status_code, 422)
        self.assertEqual((await self.post(amount=1)).status_code, 422)
        self.mock_factory.assert_not_called()

    async def test_provider_is_closed_on_success_and_failure(self):
        self.assertEqual((await self.post()).status_code, 200)
        self.service.close.assert_awaited_once()
        self.service.close.reset_mock()
        self.service.get_swap_quote.side_effect = RuntimeError("fixture provider failed")
        self.assertEqual((await self.post()).status_code, 500)
        self.service.close.assert_awaited_once()

    async def test_mismatched_provider_quote_is_rejected(self):
        base = {
            "provider": "jupiter",
            "input_mint": USDC,
            "output_mint": SOL,
            "in_amount": 1_000_000,
            "out_amount": 42,
            "price_impact_pct": 0,
            "slippage_bps": 50,
        }
        for mutation in [
            {"in_amount": 1_000_000_000},
            {"input_mint": SOL},
            {"output_mint": USDC},
            {"slippage_bps": 100},
            {"provider": "unknown"},
        ]:
            with self.subTest(mutation=mutation):
                self.service.get_swap_quote.side_effect = None
                self.service.get_swap_quote.return_value = SimpleNamespace(**(base | mutation))
                self.assertEqual((await self.post()).status_code, 502)

    async def test_explicit_provider_must_match_returned_provider(self):
        self.service.get_swap_quote.side_effect = None
        self.service.get_swap_quote.return_value = SimpleNamespace(
            provider="raydium",
            input_mint=USDC,
            output_mint=SOL,
            in_amount=1_000_000,
            out_amount=42,
            price_impact_pct=0,
            slippage_bps=50,
        )
        self.assertEqual((await self.post(provider="jupiter")).status_code, 502)

    async def test_invalid_output_quantity_is_not_a_valid_quote(self):
        for value in [-1, 2**64, True, "42"]:
            self.service.get_swap_quote.side_effect = None
            self.service.get_swap_quote.return_value = SimpleNamespace(
                provider="jupiter",
                input_mint=USDC,
                output_mint=SOL,
                in_amount=1_000_000,
                out_amount=value,
                price_impact_pct=0,
                slippage_bps=50,
            )
            with self.subTest(value=value):
                self.assertEqual((await self.post()).status_code, 502)

    async def test_openapi_declares_raw_string_and_forbids_extra_fields(self):
        schema = (await self.client.get("/openapi.json")).json()["components"]["schemas"][
            "SwapQuoteRequest"
        ]
        self.assertEqual(schema["properties"]["amount_raw"]["type"], "string")
        self.assertNotIn("amount", schema["properties"])
        self.assertIs(schema["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
