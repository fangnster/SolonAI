"""Deterministic age, publication and cancellation tests of the actual report coordinator."""

import asyncio
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.wallet_report_cache import ReadScope, ReportFreshnessError, WalletReportCache
from report_cache_fixtures import PublicationRedis


class Clock:
    now = 1_000_000

    def __call__(self):
        return self.now


class RedisFixture(PublicationRedis):
    """JSON/protocol double; real Redis integration is covered separately."""


def validate(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("wallet_address"), str):
        raise ValueError("bad payload")
    return copy.deepcopy(payload)


class ReportCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.redis = RedisFixture()
        self.cache = WalletReportCache(
            ReadScope("devnet", ("https://fixture.invalid",)), max_age_ms=10000, clock_ms=self.clock
        )
        self.loads = 0

    async def asyncTearDown(self):
        await self.cache.aclose()

    async def load(self):
        self.loads += 1
        self.clock.now += 1000
        return {"wallet_address": "wallet-a", "raw": str(self.loads), "items": ["original"]}

    async def get(self, *, refresh=False, load=None):
        return await self.cache.get(
            self.redis, "wallet-a", load or self.load, validate, refresh=refresh
        )

    def stored(self):
        return json.loads(self.redis.data[self.cache.cache_key("wallet-a")])

    async def test_cache_age_keeps_original_read_start(self):
        cold = await self.get()
        self.clock.now += 2500
        warm = await self.get()
        self.assertEqual(cold["report_context"]["source"], "rpc_read")
        self.assertEqual(warm["report_context"]["source"], "report_cache")
        self.assertEqual(warm["report_context"]["age_ms"], 3500)
        self.assertEqual(
            cold["report_context"]["read_started_at_ms"],
            warm["report_context"]["read_started_at_ms"],
        )
        self.assertEqual(self.loads, 1)

    async def test_storage_ttl_does_not_restart_full_age_budget(self):
        await self.get()
        self.assertEqual(self.redis.writes[0][1], 9)

    async def test_age_just_below_limit_is_accepted(self):
        await self.get()
        self.clock.now = 1_009_999
        self.assertEqual((await self.get())["report_context"]["age_ms"], 9999)
        self.assertEqual(self.loads, 1)

    async def test_exact_age_limit_requires_a_new_read(self):
        await self.get()
        self.clock.now = 1_010_000
        self.assertEqual((await self.get())["raw"], "2")
        self.assertEqual(self.loads, 2)

    async def test_refresh_skips_stored_report(self):
        await self.get()
        self.assertEqual((await self.get(refresh=True))["raw"], "2")

    async def test_failed_force_refresh_has_no_silent_fallback(self):
        await self.get()

        async def fail():
            raise RuntimeError("fixture read failed")

        with self.assertRaises(RuntimeError):
            await self.get(refresh=True, load=fail)
        self.assertEqual((await self.get())["raw"], "1")
        self.assertEqual(len(self.redis.writes), 1)

    async def test_one_read_for_many_concurrent_refreshes(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked():
            self.loads += 1
            entered.set()
            await release.wait()
            return {"wallet_address": "wallet-a", "raw": "42"}

        first = asyncio.create_task(self.get(refresh=True, load=blocked))
        await entered.wait()
        followers = [asyncio.create_task(self.get(refresh=True, load=blocked)) for _ in range(4)]
        # These calls see the existing task before awaiting; release after all are scheduled.
        await asyncio.sleep(0)
        release.set()
        responses = await asyncio.gather(first, *followers)
        self.assertEqual(self.loads, 1)
        self.assertEqual(len(self.redis.writes), 1)
        self.assertEqual(sum(r["report_context"]["joined_refresh"] for r in responses), 4)

    async def test_waiter_cancellation_does_not_cancel_shared_read(self):
        entered, release = asyncio.Event(), asyncio.Event()
        cancelled = []

        async def blocked():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            return {"wallet_address": "wallet-a"}

        first = asyncio.create_task(self.get(refresh=True, load=blocked))
        await entered.wait()
        second = asyncio.create_task(self.get(refresh=True, load=blocked))
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        release.set()
        self.assertEqual((await second)["wallet_address"], "wallet-a")
        self.assertEqual(cancelled, [])

    async def test_failed_read_clears_flight_for_retry(self):
        async def fail():
            raise RuntimeError("failure")

        with self.assertRaises(RuntimeError):
            await self.get(load=fail)
        self.assertEqual((await self.get())["raw"], "1")

    async def test_responses_do_not_share_mutable_payload(self):
        first = await self.get()
        first["items"].append("caller mutation")
        self.assertEqual((await self.get())["items"], ["original"])

    async def test_network_endpoint_and_age_policy_partition_keys(self):
        a = self.cache.cache_key("wallet-a")
        for scope, age in [
            (ReadScope("mainnet", ("https://fixture.invalid",)), 10000),
            (ReadScope("devnet", ("https://another.invalid",)), 10000),
            (self.cache.scope, 20000),
        ]:
            other = WalletReportCache(scope, max_age_ms=age)
            self.assertNotEqual(a, other.cache_key("wallet-a"))
        self.assertNotIn("https://", a)

    async def test_malformed_scope_schema_or_payload_is_a_miss(self):
        await self.get()
        original = self.stored()
        for field, value in [
            ("cache_schema", 3),
            ("source_id", "other"),
            ("payload", {"wallet_address": "wallet-b"}),
            ("read_started_at_ms", True),
        ]:
            entry = copy.deepcopy(original)
            entry[field] = value
            self.redis.data[self.cache.cache_key("wallet-a")] = json.dumps(entry)
            previous_loads = self.loads
            self.assertEqual((await self.get())["report_context"]["source"], "rpc_read")
            self.assertEqual(self.loads, previous_loads + 1)

    async def test_future_cache_time_is_not_reported_as_zero_age(self):
        await self.get()
        entry = self.stored()
        entry["read_completed_at_ms"] = self.clock.now + 1
        self.redis.data[self.cache.cache_key("wallet-a")] = json.dumps(entry)
        self.assertEqual((await self.get())["report_context"]["source"], "rpc_read")

    async def test_clock_backwards_during_new_read_is_rejected(self):
        async def backwards():
            self.clock.now -= 1
            return {"wallet_address": "wallet-a"}

        with self.assertRaises(ReportFreshnessError):
            await self.get(load=backwards)
        self.assertEqual(self.redis.writes, [])

    async def test_already_expired_new_read_is_not_published(self):
        async def slow():
            self.clock.now += 10000
            return {"wallet_address": "wallet-a"}

        with self.assertRaises(ReportFreshnessError):
            await self.get(load=slow)
        self.assertEqual(self.redis.writes, [])

    async def test_wrong_wallet_from_builder_is_not_published(self):
        async def wrong():
            return {"wallet_address": "wallet-b"}

        with self.assertRaises(ReportFreshnessError):
            await self.get(load=wrong)
        self.assertEqual(self.redis.writes, [])

    async def test_read_timeout_is_not_cached_as_success(self):
        self.cache.read_timeout = 0.01

        async def never():
            await asyncio.Event().wait()

        with self.assertRaisesRegex(ReportFreshnessError, "budget"):
            await self.get(load=never)
        self.assertEqual(self.redis.writes, [])

    async def test_redis_read_failure_degrades_to_new_read(self):
        async def bad_get(_key):
            raise RuntimeError("fixture Redis down")

        self.redis.get = bad_get
        self.assertEqual((await self.get())["report_context"]["source"], "rpc_read")

    async def test_redis_write_failure_does_not_invent_a_cache_hit(self):
        async def bad_set(*_args):
            raise RuntimeError("fixture Redis down")

        self.redis.setex = bad_set
        self.assertEqual((await self.get())["report_context"]["source"], "rpc_read")
        self.assertEqual((await self.get())["report_context"]["source"], "rpc_read")
        self.assertEqual(self.loads, 2)

    async def test_redis_io_timeouts_are_bounded(self):
        self.cache.cache_io_timeout = 0.01

        async def never(*_args):
            await asyncio.Event().wait()

        self.redis.get = never
        self.redis.setex = never
        self.assertEqual((await self.get())["report_context"]["source"], "rpc_read")

    async def test_publication_delay_cannot_return_overage_report(self):
        original = self.redis.setex

        async def delayed(*args):
            await original(*args)
            self.clock.now += 10000

        self.redis.setex = delayed
        with self.assertRaises(ReportFreshnessError):
            await self.get()

    async def test_close_cancels_owned_background_tasks(self):
        entered = asyncio.Event()

        async def never():
            entered.set()
            await asyncio.Event().wait()

        waiter = asyncio.create_task(self.get(refresh=True, load=never))
        await entered.wait()
        await self.cache.aclose()
        result = await asyncio.gather(waiter, return_exceptions=True)
        self.assertIsInstance(result[0], asyncio.CancelledError)

    async def test_late_older_coordinator_cannot_overwrite_new_reservation(self):
        other = WalletReportCache(self.cache.scope, max_age_ms=10000, clock_ms=self.clock)
        entered, release = asyncio.Event(), asyncio.Event()

        async def old():
            entered.set()
            await release.wait()
            return {"wallet_address": "wallet-a", "raw": "old"}

        async def recent():
            return {"wallet_address": "wallet-a", "raw": "new"}

        first = asyncio.create_task(self.get(refresh=True, load=old))
        await entered.wait()
        try:
            await other.get(self.redis, "wallet-a", recent, validate, refresh=True)
            release.set()
            with self.assertRaisesRegex(ReportFreshnessError, "superseded"):
                await first
            self.assertEqual(self.stored()["payload"]["raw"], "new")
            self.assertEqual(len(self.redis.writes), 1)
        finally:
            release.set()
            await other.aclose()

    async def test_newest_failed_reservation_does_not_reenable_old_publisher(self):
        other = WalletReportCache(self.cache.scope, max_age_ms=10000, clock_ms=self.clock)
        entered, release = asyncio.Event(), asyncio.Event()

        async def old():
            entered.set()
            await release.wait()
            return {"wallet_address": "wallet-a"}

        async def fail():
            raise RuntimeError("newest failed")

        first = asyncio.create_task(self.get(refresh=True, load=old))
        await entered.wait()
        try:
            with self.assertRaises(RuntimeError):
                await other.get(self.redis, "wallet-a", fail, validate, refresh=True)
            release.set()
            with self.assertRaises(ReportFreshnessError):
                await first
            self.assertEqual(self.redis.writes, [])
        finally:
            release.set()
            await other.aclose()

    async def test_expired_reservation_is_not_recreated_by_old_result(self):
        async def expired():
            self.redis.data.pop(self.cache.reservation_key("wallet-a"))
            return {"wallet_address": "wallet-a"}

        with self.assertRaisesRegex(ReportFreshnessError, "reservation expired"):
            await self.get(load=expired)
        self.assertEqual(self.redis.writes, [])

    async def test_reservation_failure_skips_publication_without_unconditional_write(self):
        async def bad_set(*args, **kwargs):
            raise RuntimeError("reservation down")

        self.redis.set = bad_set
        body = await self.get()
        self.assertEqual(body["report_context"]["publication_status"], "skipped")
        self.assertEqual(self.redis.writes, [])

    async def test_lost_publish_reply_is_reported_unknown_and_cache_can_still_exist(self):
        original = self.redis.eval

        async def lost(*args):
            await original(*args)
            raise ConnectionError("reply lost")

        self.redis.eval = lost
        body = await self.get()
        self.assertEqual(body["report_context"]["publication_status"], "unknown")
        self.assertEqual((await self.get())["report_context"]["publication_status"], "cache_hit")
        self.assertEqual(len(self.redis.writes), 1)

    async def test_successful_publication_reports_status_and_token(self):
        body = await self.get()
        self.assertEqual(body["report_context"]["publication_status"], "published")
        self.assertEqual(len(self.stored()["publication_token"]), 32)


if __name__ == "__main__":
    unittest.main()
