"""Offline tests of the real WalletService with injected RPC and price providers."""

import copy
import sys
import unittest
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blockchain.cache import get_cache  # noqa: E402
from blockchain.services.wallet_service import WalletService  # noqa: E402

IDENTITY = {
    "account_address": "test-account",
    "token_owner": "test-wallet",
    "program_id": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "observed_slot": 424242,
}


class WalletPrecisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await get_cache().clear()
        self.rpc = AsyncMock()
        self.prices = AsyncMock()
        self.prices.batch_get_token_prices.return_value = {}
        self.wallet = WalletService(rpc_client=self.rpc, jupiter=self.prices)

    async def balance(self, raw, decimals, ui_balance=0.0):
        self.rpc.get_token_accounts_parsed.return_value = [
            {
                **IDENTITY,
                "mint": "TEST_MINT",
                "balance_raw": raw,
                "decimals": decimals,
                "balance": ui_balance,
            }
        ]
        return (await self.wallet.get_token_accounts("test-wallet"))[0]

    async def test_preserves_raw_amount_above_binary64_integer_boundary(self):
        token = await self.balance(9_007_199_254_740_995, 9, float(9_007_199_254_740_995) / 10**9)
        self.assertEqual(token.balance, Decimal("9007199.254740995"))
        self.assertEqual(token.balance_raw, 9_007_199_254_740_995)

    async def test_u64_max_with_eighteen_decimals(self):
        token = await self.balance(2**64 - 1, 18, 18.446744073709552)
        self.assertEqual(token.balance, Decimal("18.446744073709551615"))

    async def test_raw_amount_is_authoritative_when_ui_balance_disagrees(self):
        token = await self.balance(1_250_000, 6, 999.0)
        self.assertEqual(token.balance, Decimal("1.250000"))
        self.assertIsNone(token.usd_value)

    async def test_zero_raw_amount_is_a_known_zero(self):
        token = await self.balance(0, 6, 999.0)
        self.assertEqual(token.balance, Decimal("0.000000"))

    async def test_zero_decimals_does_not_add_a_scale(self):
        token = await self.balance(42, 0, 0.0)
        self.assertEqual(token.balance, Decimal("42"))

    async def test_construction_is_exact_under_low_decimal_context_precision(self):
        with localcontext() as ctx:
            ctx.prec = 6
            token = await self.balance(2**64 - 1, 18, 18.446744073709552)
        self.assertEqual(token.balance, Decimal("18.446744073709551615"))

    async def test_mint_decimals_u8_upper_boundary_is_accepted(self):
        token = await self.balance(42, 255, 0.0)
        self.assertEqual(token.balance, Decimal("42e-255"))

    async def test_invalid_raw_types_and_range_are_rejected(self):
        for raw in (-1, 2**64, True, "1250000", 1250000.0, None):
            with self.subTest(raw=raw):
                await get_cache().clear()
                with self.assertRaises(ValueError):
                    await self.balance(raw, 6, 1.25)

    async def test_invalid_decimals_are_rejected(self):
        for decimals in (-1, 256, True, "6", 6.0):
            with self.subTest(decimals=decimals):
                await get_cache().clear()
                with self.assertRaises(ValueError):
                    await self.balance(1_250_000, decimals, 1.25)

    async def test_missing_raw_amount_does_not_become_zero(self):
        self.rpc.get_token_accounts_parsed.return_value = [
            {**IDENTITY, "mint": "TEST_MINT", "decimals": 6, "balance": 1.25}
        ]
        with self.assertRaises(KeyError):
            await self.wallet.get_token_accounts("test-wallet")

    async def test_rpc_error_is_not_an_empty_or_zero_balance(self):
        self.rpc.get_token_accounts_parsed.side_effect = RuntimeError("fixture RPC failure")
        with self.assertRaisesRegex(RuntimeError, "fixture RPC failure"):
            await self.wallet.get_token_accounts("test-wallet")

    async def test_real_model_serializes_exact_decimal_as_a_string(self):
        token = await self.balance(2**64 - 1, 18, 18.446744073709552)
        self.assertEqual(token.model_dump(mode="json")["balance"], "18.446744073709551615")

    async def test_rpc_rows_are_not_modified_and_dependencies_are_injected(self):
        rows = [{**IDENTITY, "mint": "TEST_MINT", "balance_raw": 1, "decimals": 9, "balance": 0.0}]
        before = copy.deepcopy(rows)
        self.rpc.get_token_accounts_parsed.return_value = rows
        token = (await self.wallet.get_token_accounts("test-wallet"))[0]
        self.assertEqual(token.balance, Decimal("0.000000001"))
        self.assertEqual(rows, before)
        self.rpc.get_token_accounts_parsed.assert_awaited_once_with("test-wallet")
        self.prices.batch_get_token_prices.assert_awaited_once_with(["TEST_MINT"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
