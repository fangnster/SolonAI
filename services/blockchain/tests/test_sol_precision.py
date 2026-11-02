"""Offline regressions for native SOL construction against the upstream service API."""

import sys
import unittest
from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blockchain.cache import get_cache
from blockchain.services.wallet_service import WalletService


class WalletSolPrecisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await get_cache().clear()
        self.rpc, self.prices = AsyncMock(), AsyncMock()
        self.prices.get_token_price.return_value = None
        self.wallet = WalletService(rpc_client=self.rpc, jupiter=self.prices)

    async def asyncTearDown(self):
        await self.wallet.close()
        await get_cache().clear()

    async def read(self, lamports):
        # Upstream has no use_cache flag; clear the real cache before each conversion.
        await get_cache().clear()
        self.rpc.get_balance.return_value = lamports
        return await self.wallet.get_sol_balance("fixture-wallet")

    async def test_u64_max_sol_is_exact_under_low_precision(self):
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.clear_flags()
            balance = await self.read(2**64 - 1)
            self.assertEqual(balance.lamports, 2**64 - 1)
            self.assertEqual(balance.sol, Decimal("18446744073.709551615"))
            self.assertFalse(ctx.flags[Inexact])
            self.assertFalse(ctx.flags[Rounded])

    async def test_zero_one_lamport_and_one_sol_plus_one_lamport(self):
        for raw, expected in (
            (0, "0.000000000"),
            (1, "0.000000001"),
            (1_000_000_001, "1.000000001"),
        ):
            with self.subTest(lamports=raw), localcontext() as ctx:
                ctx.prec = 6
                ctx.clear_flags()
                balance = await self.read(raw)
                self.assertEqual(balance.lamports, raw)
                self.assertEqual(balance.sol, Decimal(expected))
                self.assertIsNone(balance.usd_value)
                self.assertFalse(ctx.flags[Inexact])
                self.assertFalse(ctx.flags[Rounded])

    async def test_construction_works_with_rounding_traps_enabled(self):
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            balance = await self.read(2**64 - 1)
        self.assertEqual(balance.sol, Decimal("18446744073.709551615"))

    async def test_invalid_lamports_are_rejected_before_price_lookup(self):
        for raw in (-1, 2**64, True, False, "1000", 1000.0, None):
            with self.subTest(lamports=raw):
                self.prices.get_token_price.reset_mock()
                with self.assertRaisesRegex(ValueError, "lamports must be a u64 integer"):
                    await self.read(raw)
                self.prices.get_token_price.assert_not_awaited()

    async def test_rpc_error_is_not_zero_or_a_cached_success(self):
        self.rpc.get_balance.side_effect = RuntimeError("fixture RPC failure")
        with self.assertRaisesRegex(RuntimeError, "fixture RPC failure"):
            await self.wallet.get_sol_balance("fixture-wallet")
        self.prices.get_token_price.assert_not_awaited()
        self.rpc.get_balance.side_effect = None
        self.rpc.get_balance.return_value = 1
        # Do not clear here: the failed read must not have cached a fabricated zero.
        balance = await self.wallet.get_sol_balance("fixture-wallet")
        self.assertEqual(balance.sol, Decimal("0.000000001"))
        self.assertEqual(self.rpc.get_balance.await_count, 2)

    async def test_model_serializes_the_exact_sol_quantity_as_text(self):
        with localcontext() as ctx:
            ctx.prec = 6
            balance = await self.read(2**64 - 1)
        self.assertEqual(balance.model_dump(mode="json")["sol"], "18446744073.709551615")

    async def test_existing_price_multiplication_is_preserved(self):
        self.prices.get_token_price.return_value = Decimal("150")
        balance = await self.read(1_250_000_000)
        self.assertEqual(balance.sol, Decimal("1.250000000"))
        self.assertEqual(balance.usd_value, Decimal("187.5"))


if __name__ == "__main__":
    unittest.main()
