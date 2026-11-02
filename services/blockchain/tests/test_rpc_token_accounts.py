"""Offline HTTP boundary tests with real solana-py and solders response decoding."""

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from solders.pubkey import Pubkey

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blockchain.cache import get_cache
from blockchain.exceptions import InvalidAddressError, RPCResponseValidationError
from blockchain.services.wallet_service import WalletService
from blockchain.transport.rpc_client import EnhancedRPCClient

PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
OWNER = str(Pubkey.from_bytes(bytes([1]) * 32))
MINT = str(Pubkey.from_bytes(bytes([3]) * 32))


def account(raw="1250000", decimals=6, ui=1.25, seed=2, mint=MINT):
    return {
        "pubkey": str(Pubkey.from_bytes(bytes([seed]) * 32)),
        "account": {
            "owner": PROGRAM,
            "lamports": 2039280,
            "executable": False,
            "rentEpoch": 0,
            "data": {
                "program": "spl-token",
                "space": 165,
                "parsed": {
                    "type": "account",
                    "info": {
                        "mint": mint,
                        "owner": OWNER,
                        "state": "initialized",
                        "isNative": False,
                        "tokenAmount": {"amount": raw, "decimals": decimals, "uiAmount": ui},
                    },
                },
            },
        },
    }


def token_amount(row):
    return row["account"]["data"]["parsed"]["info"]["tokenAmount"]


class RPCTokenAccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await get_cache().clear()
        self.rows = [account()]
        self.requests = []
        self.fail_first = False
        self.client = EnhancedRPCClient(rpc_urls=["https://fixture.invalid"])
        self.client._retry_delay = 0
        self.client._max_retries = 3
        sdk = self.client._get_client()
        await sdk._provider.session.aclose()

        def handler(request):
            body = json.loads(request.content)
            self.requests.append(body)
            if self.fail_first and len(self.requests) == 1:
                return httpx.Response(503, json={"error": "fixture unavailable"})
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"context": {"slot": 424242}, "value": copy.deepcopy(self.rows)},
                },
            )

        # Version-pinned test seam: replace HTTP transport, not SDK classes or typed responses.
        sdk._provider.session = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        )

    async def asyncTearDown(self):
        await self.client.close()
        await get_cache().clear()

    async def fetch(self):
        return await self.client.get_token_accounts_parsed(OWNER)

    async def assert_invalid(self, path_suffix):
        with self.assertRaises(RPCResponseValidationError) as caught:
            await self.fetch()
        self.assertTrue(caught.exception.path.endswith(path_suffix), caught.exception.path)
        return caught.exception

    async def test_keeps_nonzero_raw_when_ui_is_null(self):
        self.rows = [account(ui=None)]
        rows = await self.fetch()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance_raw"], 1250000)

    async def test_keeps_nonzero_raw_when_ui_is_missing(self):
        del token_amount(self.rows[0])["uiAmount"]
        self.assertEqual((await self.fetch())[0]["balance_raw"], 1250000)

    async def test_keeps_known_zero_account(self):
        self.rows = [account(raw="0", ui=0)]
        rows = await self.fetch()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance_raw"], 0)

    async def test_frozen_account_quantity_is_still_a_balance(self):
        self.rows[0]["account"]["data"]["parsed"]["info"]["state"] = "frozen"
        self.assertEqual((await self.fetch())[0]["balance_raw"], 1250000)

    async def test_raw_is_authoritative_when_ui_disagrees(self):
        token_amount(self.rows[0])["uiAmount"] = 999.0
        self.assertEqual((await self.fetch())[0]["balance"], 1.25)

    async def test_presentation_fields_are_not_required_or_trusted(self):
        for ui in ("broken", {}, False, -100):
            with self.subTest(ui=ui):
                token_amount(self.rows[0])["uiAmount"] = ui
                token_amount(self.rows[0])["uiAmountString"] = "not authoritative"
                self.assertEqual((await self.fetch())[0]["balance_raw"], 1250000)

    async def test_u64_max_is_preserved(self):
        self.rows = [account(raw=str(2**64 - 1), decimals=18, ui=None)]
        self.assertEqual((await self.fetch())[0]["balance_raw"], 2**64 - 1)

    async def test_zero_and_max_decimals(self):
        for decimals in (0, 255):
            with self.subTest(decimals=decimals):
                self.rows = [account(raw="42", decimals=decimals, ui=None)]
                self.assertEqual((await self.fetch())[0]["decimals"], decimals)

    async def test_rejects_noncanonical_and_out_of_range_raw(self):
        for raw in ("", "01", "+1", "-1", "1e3", "1.0", "１", "1\n", " 1", str(2**64), "9" * 5000):
            with self.subTest(raw=raw[:24]):
                token_amount(self.rows[0])["amount"] = raw
                await self.assert_invalid("tokenAmount.amount")

    async def test_rejects_non_string_raw(self):
        for raw in (1, 1.5, True, None, {}):
            with self.subTest(raw=raw):
                token_amount(self.rows[0])["amount"] = raw
                await self.assert_invalid("tokenAmount.amount")

    async def test_missing_raw_is_not_default_zero(self):
        del token_amount(self.rows[0])["amount"]
        await self.assert_invalid("tokenAmount.amount")

    async def test_invalid_decimals_are_not_coerced(self):
        for decimals in (-1, 256, True, "6", 6.0, None):
            with self.subTest(decimals=decimals):
                token_amount(self.rows[0])["decimals"] = decimals
                await self.assert_invalid("tokenAmount.decimals")

    async def test_missing_decimals_is_not_default_zero(self):
        del token_amount(self.rows[0])["decimals"]
        await self.assert_invalid("tokenAmount.decimals")

    async def test_invalid_second_row_fails_whole_batch_without_retry(self):
        self.rows.append(account(raw="750000", ui=None, seed=4))
        del token_amount(self.rows[1])["amount"]
        error = await self.assert_invalid("tokenAmount.amount")
        self.assertTrue(error.path.startswith("value[1]."))
        self.assertEqual(len(self.requests), 1)

    async def test_sdk_request_uses_owner_program_and_jsonparsed(self):
        await self.fetch()
        request = self.requests[0]
        self.assertEqual(request["method"], "getTokenAccountsByOwner")
        self.assertEqual(request["params"][0], OWNER)
        self.assertEqual(request["params"][1], {"programId": PROGRAM})
        self.assertEqual(request["params"][2]["encoding"], "jsonParsed")

    async def test_token_owner_must_match_wallet(self):
        for owner in (MINT, None, "bad-owner"):
            with self.subTest(owner=owner):
                self.rows[0]["account"]["data"]["parsed"]["info"]["owner"] = owner
                await self.assert_invalid("info.owner")

    async def test_mint_must_be_public_key(self):
        self.rows[0]["account"]["data"]["parsed"]["info"]["mint"] = "not-a-mint"
        await self.assert_invalid("info.mint")

    async def test_program_owner_is_not_token_authority(self):
        self.rows[0]["account"]["owner"] = OWNER
        await self.assert_invalid("account.owner")

    async def test_parsed_type_must_be_token_account(self):
        self.rows[0]["account"]["data"]["parsed"]["type"] = "mint"
        await self.assert_invalid("parsed.type")

    async def test_required_info_and_amount_objects(self):
        original = copy.deepcopy(self.rows[0])
        for part in ("info", "tokenAmount"):
            with self.subTest(part=part):
                self.rows = [copy.deepcopy(original)]
                parsed = self.rows[0]["account"]["data"]["parsed"]
                if part == "info":
                    parsed["info"] = None
                else:
                    parsed["info"]["tokenAmount"] = None
                await self.assert_invalid(part)

    async def test_same_mint_accounts_retain_distinct_identity_and_slot(self):
        self.rows.append(account(raw="750000", ui=None, seed=4))
        rows = await self.fetch()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["mint"], rows[1]["mint"])
        self.assertNotEqual(rows[0]["account_address"], rows[1]["account_address"])
        self.assertEqual([row["balance_raw"] for row in rows], [1250000, 750000])
        self.assertEqual([row["observed_slot"] for row in rows], [424242, 424242])
        self.assertEqual(rows[0]["token_owner"], OWNER)
        self.assertEqual(rows[0]["program_id"], PROGRAM)

    async def test_empty_valid_response_returns_empty_list(self):
        self.rows = []
        self.assertEqual(await self.fetch(), [])

    async def test_transport_failure_still_retries(self):
        self.fail_first = True
        self.assertEqual((await self.fetch())[0]["balance_raw"], 1250000)
        self.assertEqual(len(self.requests), 2)

    async def test_invalid_wallet_is_rejected_before_http(self):
        with self.assertRaises(InvalidAddressError):
            await self.client.get_token_accounts_parsed("not-a-wallet")
        self.assertEqual(self.requests, [])

    async def test_real_wallet_service_receives_null_ui_and_zero(self):
        self.rows = [
            account(raw=str(2**64 - 1), decimals=18, ui=None),
            account(raw="0", ui=0, seed=4, mint=str(Pubkey.from_bytes(bytes([5]) * 32))),
        ]
        prices = AsyncMock()
        prices.batch_get_token_prices.return_value = {}
        wallet = WalletService(rpc_client=self.client, jupiter=prices)
        tokens = await wallet.get_token_accounts(OWNER)
        self.assertEqual([token.balance_raw for token in tokens], [2**64 - 1, 0])
        self.assertEqual(format(tokens[0].balance, "f"), "18.446744073709551615")
        self.assertEqual(format(tokens[1].balance, "f"), "0.000000")
        self.assertIsNone(tokens[0].usd_value)
        await wallet.close()

    async def test_invalid_batch_is_not_cached_as_partial_or_zero(self):
        self.rows.append(account(seed=4))
        del token_amount(self.rows[1])["amount"]
        prices = AsyncMock()
        prices.batch_get_token_prices.return_value = {}
        wallet = WalletService(rpc_client=self.client, jupiter=prices)
        with self.assertRaises(RPCResponseValidationError):
            await wallet.get_token_accounts(OWNER)
        prices.batch_get_token_prices.assert_not_awaited()
        token_amount(self.rows[1])["amount"] = "42"
        tokens = await wallet.get_token_accounts(OWNER)
        self.assertEqual([token.balance_raw for token in tokens], [1250000, 42])
        self.assertEqual(len(self.requests), 2)
        await wallet.close()


if __name__ == "__main__":
    unittest.main()
