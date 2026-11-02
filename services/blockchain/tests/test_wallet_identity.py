"""Behavior tests for one read batch, identity preservation and replay safety."""

import asyncio
import copy
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blockchain.cache import get_cache
from blockchain.exceptions import RPCResponseValidationError
from blockchain.services.wallet_service import WalletService

PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def row(address="TA_A", raw=1250000, slot=424242, **updates):
    return {
        "account_address": address,
        "token_owner": "wallet-a",
        "program_id": PROGRAM,
        "observed_slot": slot,
        "mint": "USDC_TEST",
        "balance_raw": raw,
        "decimals": 6,
        "balance": 999.0,
        **updates,
    }


class WalletIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await get_cache().clear()
        self.rpc, self.prices = AsyncMock(), AsyncMock()
        self.rows = [row(), row("TA_B", 750000)]
        self.rpc.get_token_accounts_parsed.return_value = self.rows
        self.rpc.get_balance.return_value = 0
        self.prices.get_token_price.return_value = None
        self.prices.batch_get_token_prices.return_value = {"USDC_TEST": Decimal("2")}
        self.wallet = WalletService(rpc_client=self.rpc, jupiter=self.prices)

    async def asyncTearDown(self):
        await self.wallet.close()
        await get_cache().clear()

    async def fetch(self):
        return await self.wallet.get_token_accounts("wallet-a")

    async def test_same_mint_accounts_keep_separate_identity(self):
        tokens = await self.fetch()
        self.assertEqual([t.account_address for t in tokens], ["TA_A", "TA_B"])
        self.assertEqual([t.balance_raw for t in tokens], [1250000, 750000])
        self.assertEqual([t.observed_slot for t in tokens], [424242, 424242])
        self.assertTrue(
            all(t.token_owner == "wallet-a" and t.program_id == PROGRAM for t in tokens)
        )

    async def test_exact_repeats_do_not_double_count_quantity_or_value(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        portfolio = await self.wallet.get_wallet_portfolio("wallet-a")
        self.assertEqual(len(portfolio.tokens), 2)
        self.assertEqual(sum(t.balance_raw for t in portfolio.tokens), 2000000)
        self.assertEqual(portfolio.total_usd_value, Decimal("4.000000"))
        self.prices.batch_get_token_prices.assert_awaited_once_with(["USDC_TEST"])

    async def test_ui_only_difference_does_not_create_new_account(self):
        self.rows.append({**self.rows[0], "balance": -999.0})
        self.assertEqual(len(await self.fetch()), 2)

    async def test_conflicting_quantity_is_rejected_before_price_lookup(self):
        self.rows.append(row(raw=42))
        with self.assertRaisesRegex(RPCResponseValidationError, "conflicting"):
            await self.fetch()
        self.prices.batch_get_token_prices.assert_not_awaited()

    async def test_same_account_with_different_mint_is_a_conflict(self):
        self.rows.append(row(mint="OTHER"))
        with self.assertRaisesRegex(RPCResponseValidationError, "conflicting"):
            await self.fetch()

    async def test_one_mint_cannot_have_mixed_precision(self):
        self.rows[1]["decimals"] = 9
        with self.assertRaisesRegex(RPCResponseValidationError, "precision"):
            await self.fetch()

    async def test_mixed_read_slots_are_rejected_in_either_order(self):
        self.rows[1]["observed_slot"] = 424243
        for records in (self.rows, list(reversed(self.rows))):
            with self.subTest(records=records):
                self.rpc.get_token_accounts_parsed.return_value = records
                with self.assertRaisesRegex(RPCResponseValidationError, "mixed read contexts"):
                    await self.fetch()

    async def test_wallet_authority_must_match_request(self):
        self.rows[1]["token_owner"] = "wallet-b"
        with self.assertRaises(RPCResponseValidationError):
            await self.fetch()

    async def test_program_must_match_query_scope(self):
        self.rows[1]["program_id"] = "other-program"
        with self.assertRaises(RPCResponseValidationError):
            await self.fetch()

    async def test_missing_identity_is_not_fabricated(self):
        for field in ("account_address", "token_owner", "program_id", "observed_slot"):
            with self.subTest(field=field):
                bad = row()
                del bad[field]
                self.rpc.get_token_accounts_parsed.return_value = [bad]
                with self.assertRaises(KeyError):
                    await self.fetch()

    async def test_slot_range_and_types_are_strict(self):
        for slot in (-1, True, "424242", 2**64):
            with self.subTest(slot=slot):
                self.rpc.get_token_accounts_parsed.return_value = [row(slot=slot)]
                with self.assertRaises(ValueError):
                    await self.fetch()

    async def test_zero_slot_is_known_and_not_none(self):
        self.rpc.get_token_accounts_parsed.return_value = [row(slot=0)]
        portfolio = await self.wallet.get_wallet_portfolio("wallet-a")
        self.assertEqual(portfolio.token_observed_slot, 0)

    async def test_empty_read_has_unknown_slot_without_fabrication(self):
        self.rpc.get_token_accounts_parsed.return_value = []
        portfolio = await self.wallet.get_wallet_portfolio("wallet-a")
        self.assertEqual(portfolio.tokens, [])
        self.assertIsNone(portfolio.token_observed_slot)
        self.prices.batch_get_token_prices.assert_not_awaited()

    async def test_record_order_does_not_change_normalized_output(self):
        first = [t.model_dump() for t in await self.fetch()]
        await get_cache().clear()
        self.rpc.get_token_accounts_parsed.return_value = list(reversed(self.rows))
        self.assertEqual([t.model_dump() for t in await self.fetch()], first)

    async def test_input_rows_are_not_mutated(self):
        before = copy.deepcopy(self.rows)
        await self.fetch()
        self.assertEqual(self.rows, before)

    async def test_bad_batch_is_not_cached_as_partial_success(self):
        self.rows.append(row(raw=42))
        with self.assertRaises(RPCResponseValidationError):
            await self.fetch()
        self.rows.pop()
        self.assertEqual(len(await self.fetch()), 2)
        self.assertEqual(self.rpc.get_token_accounts_parsed.await_count, 2)

    async def test_old_cache_namespace_is_not_reused(self):
        await get_cache().set("token_accounts:wallet-a", ["legacy-without-identity"], 60)
        self.assertEqual(len(await self.fetch()), 2)
        self.rpc.get_token_accounts_parsed.assert_awaited_once()

    async def test_cache_preserves_identity_on_repeat_read(self):
        await self.fetch()
        self.assertEqual((await self.fetch())[0].account_address, "TA_A")
        self.rpc.get_token_accounts_parsed.assert_awaited_once()

    async def test_returned_token_fields_cannot_be_changed_in_place(self):
        token = (await self.fetch())[0]
        with self.assertRaises(ValueError):
            token.balance_raw = 0
        self.assertEqual((await self.fetch())[0].balance_raw, 1250000)

    async def test_max_slot_is_retained_as_internal_integer(self):
        self.rpc.get_token_accounts_parsed.return_value = [row(slot=2**64 - 1)]
        portfolio = await self.wallet.get_wallet_portfolio("wallet-a")
        self.assertEqual(portfolio.token_observed_slot, 2**64 - 1)
        self.assertIs(type(portfolio.tokens[0].observed_slot), int)

    async def test_failed_parallel_read_cleans_up_sibling_before_return(self):
        entered = asyncio.Event()
        cancelled = []

        async def blocked(_wallet):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        async def failed(_wallet):
            await entered.wait()
            raise RuntimeError("fixture token read failed")

        self.rpc.get_balance.side_effect = blocked
        self.rpc.get_token_accounts_parsed.side_effect = failed
        with self.assertRaises(RuntimeError):
            await self.wallet.get_wallet_portfolio("wallet-a", use_cache=False)
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
