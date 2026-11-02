"""Actual assets router and cache JSON, with local RPC/price/Redis dependencies."""

import asyncio
import copy
import json
import os
import sys
import unittest
from decimal import localcontext
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services"))

import httpx
from app.api.v1 import assets
from app.core.wallet_report_cache import WalletReportCache
from blockchain.cache import get_cache
from blockchain.services.wallet_service import WalletService
from fastapi import FastAPI
from report_cache_fixtures import PublicationRedis


class MemoryRedis(PublicationRedis):
    """JSON/protocol double; real Redis integration is covered separately."""


def without_report_context(body):
    return {key: value for key, value in body.items() if key != "report_context"}


class AssetsPrecisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await get_cache().clear()
        self.redis = MemoryRedis()
        self.rpc, self.prices = AsyncMock(), AsyncMock()
        self.rpc.get_balance.return_value = 2**64 - 1
        self.rpc.get_token_accounts_parsed.return_value = [
            {
                "mint": "MAX18",
                "balance_raw": 2**64 - 1,
                "decimals": 18,
                "balance": 18.446744073709553,
            },
            {"mint": "ABOVE53", "balance_raw": 9007199254740995, "decimals": 9, "balance": 0.0},
            {"mint": "ZERO", "balance_raw": 0, "decimals": 6, "balance": 0.0},
        ]
        for index, row in enumerate(self.rpc.get_token_accounts_parsed.return_value):
            row.update(
                {
                    "account_address": f"TA_{index:03d}",
                    "token_owner": "fixture-wallet",
                    "program_id": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "observed_slot": 424242,
                }
            )
        self.prices.get_token_price.return_value = None
        self.prices.batch_get_token_prices.return_value = {}
        self.wallet = WalletService(rpc_client=self.rpc, jupiter=self.prices)
        self.factory = patch.object(assets, "get_wallet_service", return_value=self.wallet)
        self.factory.start()
        self.app = FastAPI()
        self.app.include_router(assets.router, prefix="/api/v1/assets")

        async def local_redis():
            return self.redis

        self.app.dependency_overrides[assets.get_redis] = local_redis
        self.reports = WalletReportCache(assets.get_wallet_report_cache().scope)
        self.app.dependency_overrides[assets.get_wallet_report_cache] = lambda: self.reports
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://fixture",
        )

    async def asyncTearDown(self):
        await self.reports.aclose()
        await self.client.aclose()
        self.factory.stop()
        await get_cache().clear()

    async def fetch(self):
        return await self.client.get("/api/v1/assets/fixture-wallet")

    async def test_exact_http_payload_uses_strings(self):
        response = await self.fetch()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body.get("quantity_schema_version"), 2)
        self.assertEqual(body["sol_balance_raw"], "18446744073709551615")
        self.assertEqual(body["sol_decimals"], 9)
        self.assertEqual(body["sol_balance_exact"], "18446744073.709551615")
        token = body["tokens"][0]
        self.assertEqual(token["balance_raw"], "18446744073709551615")
        self.assertIs(type(token["balance_raw"]), str)
        self.assertEqual(token["decimals"], 18)
        self.assertEqual(token["balance_exact"], "18.446744073709551615")

    async def test_above_safe_integer_retains_all_digits(self):
        body = (await self.fetch()).json()
        self.assertEqual(body["tokens"][1]["balance_raw"], "9007199254740995")
        self.assertEqual(body["tokens"][1]["balance_exact"], "9007199.254740995")

    async def test_known_zero_is_preserved(self):
        body = (await self.fetch()).json()
        self.assertEqual(body["tokens"][2]["balance_raw"], "0")
        self.assertEqual(body["tokens"][2]["balance_exact"], "0.000000")

    async def test_warm_cache_matches_cold_response(self):
        cold = await self.fetch()
        warm = await self.fetch()
        self.assertEqual(without_report_context(warm.json()), without_report_context(cold.json()))
        self.rpc.get_token_accounts_parsed.assert_awaited_once()
        key = assets.get_wallet_report_cache().cache_key("fixture-wallet")
        stored = json.loads(self.redis.data[key])["payload"]
        self.assertIs(type(stored["tokens"][0]["balance_raw"]), str)
        self.assertEqual(stored["tokens"][0]["balance_exact"], "18.446744073709551615")
        self.assertEqual(self.redis.writes, [(key, 60)])
        self.assertEqual(cold.json()["report_context"]["source"], "rpc_read")
        self.assertEqual(warm.json()["report_context"]["source"], "report_cache")

    async def test_old_cache_key_is_not_read_as_new_contract(self):
        self.redis.data["assets:wallet:fixture-wallet"] = json.dumps({"sol_balance": 999})
        self.redis.data["assets:wallet:v2:fixture-wallet"] = json.dumps({"sol_balance": 888})
        self.redis.data["assets:wallet:v3:fixture-wallet"] = json.dumps({"sol_balance": 777})
        body = (await self.fetch()).json()
        self.assertEqual(body["sol_balance_raw"], "18446744073709551615")
        self.rpc.get_balance.assert_awaited_once()

    async def test_legacy_fields_remain_for_existing_consumers(self):
        body = (await self.fetch()).json()
        self.assertIs(type(body["sol_balance"]), float)
        self.assertIs(type(body["tokens"][0]["balance"]), float)
        self.assertIn("value_usd", body["tokens"][0])

    async def test_openapi_declares_quantity_strings(self):
        schemas = (await self.client.get("/openapi.json")).json()["components"]["schemas"]
        self.assertEqual(schemas["TokenAsset"]["properties"]["balance_raw"]["type"], "string")
        self.assertEqual(schemas["TokenAsset"]["properties"]["balance_exact"]["type"], "string")
        self.assertEqual(schemas["WalletAssets"]["properties"]["sol_balance_raw"]["type"], "string")

    async def test_rpc_failure_is_not_a_zero_success(self):
        self.rpc.get_token_accounts_parsed.side_effect = RuntimeError("fixture RPC failed")
        response = await self.fetch()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("tokens", response.json())
        self.assertEqual(self.redis.writes, [])

    async def test_zero_and_u8_max_decimals(self):
        self.assertEqual(assets._exact_amount(42, 0), "42")
        self.assertEqual(assets._exact_amount(42, 255), "0." + "0" * 253 + "42")

    async def test_invalid_raw_and_decimals_do_not_become_zero(self):
        for raw in (-1, 2**64, True, "1", None):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                assets._exact_amount(raw, 6)
        for decimals in (-1, 256, True, "6", 6.0):
            with self.subTest(decimals=decimals), self.assertRaises(ValueError):
                assets._exact_amount(1, decimals)

    async def test_formatting_ignores_decimal_context(self):
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(assets._exact_amount(2**64 - 1, 18), "18.446744073709551615")

    async def test_identity_and_max_slot_survive_http_and_cache(self):
        for row in self.rpc.get_token_accounts_parsed.return_value:
            row["observed_slot"] = 2**64 - 1
        cold = await self.fetch()
        warm = await self.fetch()
        body = cold.json()
        self.assertEqual(without_report_context(body), without_report_context(warm.json()))
        self.assertEqual(body["account_identity_version"], 1)
        self.assertEqual(body["token_observed_slot"], "18446744073709551615")
        self.assertEqual(body["tokens"][0]["account_address"], "TA_000")
        self.assertEqual(body["tokens"][0]["token_owner"], "fixture-wallet")
        self.assertEqual(body["tokens"][0]["observed_slot"], "18446744073709551615")
        self.assertIs(type(body["tokens"][0]["observed_slot"]), str)

    async def test_empty_token_read_has_null_context(self):
        self.rpc.get_token_accounts_parsed.return_value = []
        body = (await self.fetch()).json()
        self.assertEqual(body["tokens"], [])
        self.assertIsNone(body["token_observed_slot"])

    async def test_exact_repeat_does_not_duplicate_api_rows(self):
        rows = self.rpc.get_token_accounts_parsed.return_value
        rows.append(copy.deepcopy(rows[0]))
        self.assertEqual(len((await self.fetch()).json()["tokens"]), 3)

    async def test_conflicting_account_does_not_write_partial_cache(self):
        rows = self.rpc.get_token_accounts_parsed.return_value
        rows.append({**rows[0], "balance_raw": 42})
        response = await self.fetch()
        self.assertEqual(response.status_code, 500)
        self.assertIn("conflicting", response.json()["detail"])
        self.assertEqual(self.redis.writes, [])

    async def test_mixed_slots_do_not_write_partial_cache(self):
        self.rpc.get_token_accounts_parsed.return_value[1]["observed_slot"] += 1
        self.assertEqual((await self.fetch()).status_code, 500)
        self.assertEqual(self.redis.writes, [])

    async def test_openapi_declares_identity_and_slot_strings(self):
        properties = self.app.openapi()["components"]["schemas"]["TokenAsset"]["properties"]
        self.assertEqual(properties["observed_slot"]["type"], "string")
        self.assertEqual(properties["account_address"]["type"], "string")

    async def test_missing_identity_is_not_returned_as_zero(self):
        del self.rpc.get_token_accounts_parsed.return_value[0]["account_address"]
        self.assertEqual((await self.fetch()).status_code, 500)
        self.assertEqual(self.redis.writes, [])

    async def test_report_rebuild_bypasses_all_wallet_memory_layers(self):
        await self.wallet.get_wallet_portfolio("fixture-wallet")
        self.rpc.get_token_accounts_parsed.return_value[0]["balance_raw"] = 42
        self.assertEqual((await self.fetch()).json()["tokens"][0]["balance_raw"], "42")
        self.rpc.get_token_accounts_parsed.return_value[0]["balance_raw"] = 43
        forced = await self.client.get("/api/v1/assets/fixture-wallet?refresh=true")
        self.assertEqual(forced.json()["tokens"][0]["balance_raw"], "43")
        self.assertEqual(self.rpc.get_token_accounts_parsed.await_count, 3)
        self.assertEqual(self.rpc.get_balance.await_count, 3)

    async def test_actual_router_coalesces_concurrent_force_reads(self):
        entered, release, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()
        rows = copy.deepcopy(self.rpc.get_token_accounts_parsed.return_value)

        async def blocked(_wallet):
            entered.set()
            await release.wait()
            return rows

        self.rpc.get_token_accounts_parsed.side_effect = blocked
        original = self.reports.get
        calls = 0

        async def observed(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                joined.set()
            return await original(*args, **kwargs)

        self.reports.get = observed
        first = asyncio.create_task(self.client.get("/api/v1/assets/fixture-wallet?refresh=true"))
        await entered.wait()
        second = asyncio.create_task(self.client.get("/api/v1/assets/fixture-wallet?refresh=true"))
        await joined.wait()
        release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertTrue(b.json()["report_context"]["joined_refresh"])
        self.assertEqual(without_report_context(a.json()), without_report_context(b.json()))
        self.assertEqual(self.rpc.get_token_accounts_parsed.await_count, 1)
        self.assertEqual(len(self.redis.writes), 1)

    async def test_failed_force_read_does_not_silently_return_cached_success(self):
        await self.fetch()
        self.rpc.get_token_accounts_parsed.side_effect = RuntimeError("fixture force failed")
        forced = await self.client.get("/api/v1/assets/fixture-wallet?refresh=true")
        self.assertEqual(forced.status_code, 500)
        self.assertEqual(len(self.redis.writes), 1)
        normal = await self.fetch()
        self.assertEqual(normal.json()["report_context"]["source"], "report_cache")

    async def test_report_budget_returns_503_without_partial_cache(self):
        self.reports.read_timeout = 0.01

        async def never(_wallet):
            await asyncio.Event().wait()

        self.rpc.get_token_accounts_parsed.side_effect = never
        response = await self.fetch()
        self.assertEqual(response.status_code, 503)
        self.assertIn("budget", response.json()["detail"])
        self.assertEqual(self.redis.writes, [])

    async def test_two_api_coordinators_reject_superseded_publication(self):
        other = WalletReportCache(self.reports.scope)
        managers = iter([self.reports, other])
        self.app.dependency_overrides[assets.get_wallet_report_cache] = lambda: next(managers)
        entered, release = asyncio.Event(), asyncio.Event()
        old_rows = copy.deepcopy(self.rpc.get_token_accounts_parsed.return_value)
        new_rows = copy.deepcopy(old_rows)
        new_rows[0]["balance_raw"] = 42
        calls = 0

        async def response(_wallet):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
                return old_rows
            return new_rows

        self.rpc.get_token_accounts_parsed.side_effect = response
        first = asyncio.create_task(self.client.get("/api/v1/assets/fixture-wallet?refresh=true"))
        await entered.wait()
        try:
            recent = await self.client.get("/api/v1/assets/fixture-wallet?refresh=true")
            self.assertEqual(recent.status_code, 200)
            release.set()
            self.assertEqual((await first).status_code, 503)
            key = self.reports.cache_key("fixture-wallet")
            self.assertEqual(
                json.loads(self.redis.data[key])["payload"]["tokens"][0]["balance_raw"], "42"
            )
        finally:
            release.set()
            await other.aclose()


if __name__ == "__main__":
    unittest.main()
