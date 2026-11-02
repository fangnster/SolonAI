"""Actual SDK -> WalletService -> API -> report-cache scenarios with controlled time/IO."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from offline_rpc import open_client
from redis_harness import isolated_redis

ROOT = Path(__file__).resolve().parent


async def run(project, case, output, real_redis):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    payload = json.loads((ROOT / "inputs/valid.json").read_text())
    owner = payload["result"]["value"][0]["account"]["data"]["parsed"]["info"]["owner"]
    entered, release, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()
    mode = {"block": False, "fail": False}

    async def before_rpc(body):
        if body["method"] == "getTokenAccountsByOwner":
            if mode["fail"]:
                raise RuntimeError("fixture RPC unavailable")
            if mode["block"]:
                entered.set()
                await release.wait()

    rpc, requests = await open_client(project, payload, before_rpc)
    sys.path.insert(0, str(project / "apps/api"))
    import httpx
    from app.api.v1 import assets
    from app.core.wallet_report_cache import ReadScope, WalletReportCache
    from blockchain.cache import get_cache
    from blockchain.services.wallet_service import WalletService
    from fastapi import FastAPI

    class Clock:
        now = 1_000_000

        def __call__(self):
            return self.now

    class RedisFixture:
        def __init__(self):
            self.writes = []

        async def get(self, key):
            return await real_redis.get(key)

        async def set(self, key, value, **kwargs):
            return await real_redis.set(key, value, **kwargs)

        async def eval(self, *args):
            result = await real_redis.eval(*args)
            if result == 1:
                self.writes.append(args)
            return result

    clock, redis = Clock(), RedisFixture()
    reports = WalletReportCache(
        ReadScope("fixture-devnet", ("https://fixture.invalid",)), clock_ms=clock
    )
    prices = AsyncMock()
    prices.get_token_price.return_value = None
    prices.batch_get_token_prices.return_value = {}
    assets.get_wallet_service = lambda: WalletService(rpc_client=rpc, jupiter=prices)
    app = FastAPI()
    app.include_router(assets.router, prefix="/api/v1/assets")

    async def local_redis():
        return redis

    app.dependency_overrides[assets.get_redis] = local_redis
    app.dependency_overrides[assets.get_wallet_report_cache] = lambda: reports
    await get_cache().clear()
    history = []
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:

            async def fetch(refresh=False):
                response = await client.get(f"/api/v1/assets/{owner}", params={"refresh": refresh})
                body = response.json()
                context = body.get("report_context", {})
                history.append(
                    {
                        "status": response.status_code,
                        "source": context.get("source"),
                        "age_ms": context.get("age_ms"),
                        "read_started_at_ms": context.get("read_started_at_ms"),
                        "joined_refresh": context.get("joined_refresh"),
                        "fixture_http_requests_so_far": len(requests),
                    }
                )
                return response, body

            if case == "concurrent":
                mode["block"] = True
                original = reports.get
                count = 0

                async def observed(*args, **kwargs):
                    nonlocal count
                    count += 1
                    if count == 2:
                        joined.set()
                    return await original(*args, **kwargs)

                reports.get = observed
                first = asyncio.create_task(fetch(True))
                await entered.wait()
                second = asyncio.create_task(fetch(True))
                await joined.wait()
                release.set()
                results = await asyncio.gather(first, second)
                body = results[0][1]
                assert len(requests) == 2 and len(redis.writes) == 1
            else:
                response, body = await fetch()
                response.raise_for_status()
                if case == "timeline":
                    clock.now += 2500
                    _, body = await fetch()
                    cached_body = body
                    payload["result"]["value"][2]["account"]["data"]["parsed"]["info"][
                        "tokenAmount"
                    ]["amount"] = "1500000"
                    clock.now += 1000
                    _, forced = await fetch(True)
                    assert forced["tokens"][2]["balance_raw"] == "1500000"
                    body = cached_body
                elif case == "expired":
                    clock.now += 60000
                    _, body = await fetch()
                    assert body["report_context"]["source"] == "rpc_read"
                elif case == "refresh-error":
                    mode["fail"] = True
                    failed, error = await fetch(True)
                    assert failed.status_code == 500
                    _, body = await fetch()
                    assert body["report_context"]["source"] == "report_cache"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(body, indent=2) + "\n")
        return {
            "case": case,
            "history": history,
            "real_redis": True,
            "cache_writes": len(redis.writes),
            "fixture_http_requests": len(requests),
            "external_rpc_calls": 0,
            "http_json": str(output),
            "publication_scope": "Lua admission check on one Redis primary; single-flight is per API event loop",
        }
    finally:
        await reports.aclose()
        await rpc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    project = ROOT.parents[1]
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument(
        "--case", choices=["timeline", "concurrent", "expired", "refresh-error"], default="timeline"
    )
    parser.add_argument("--http-out", type=Path)
    parser.add_argument("--redis-server", type=Path, required=True)
    args = parser.parse_args()
    out = args.http_out.resolve() if args.http_out else ROOT / "runs" / (args.case + "-wallet.json")

    async def main():
        async with isolated_redis(args.redis_server) as (client, socket):
            return await run(args.project.resolve(), args.case, out, client)

    print(json.dumps(asyncio.run(main()), indent=2))
