"""Verify atomic Lua with two Python processes and a disposable real Redis primary."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from redis_harness import isolated_redis

ROOT = Path(__file__).resolve().parent


async def run(project, binary, log_output):
    sys.path.insert(0, str(project / "apps/api"))
    from app.core.wallet_report_cache import ReadScope, WalletReportCache

    async with isolated_redis(binary, log_output) as (redis, socket):
        processes = []

        async def worker(role):
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(ROOT / "publication_worker.py"),
                "--project",
                str(project),
                "--socket",
                str(socket),
                "--role",
                role,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            processes.append(proc)
            started = json.loads(await asyncio.wait_for(proc.stdout.readline(), 5))
            assert started["event"] == "read_started"
            return proc, started

        try:
            a, start_a = await worker("A")
            b, start_b = await worker("B")
            result_b = json.loads(await asyncio.wait_for(b.stdout.readline(), 5))
            await asyncio.wait_for(b.wait(), 5)
            assert result_b["status"] == "published" and b.returncode == 0
            a.stdin.write(b"release\n")
            await a.stdin.drain()
            result_a = json.loads(await asyncio.wait_for(a.stdout.readline(), 5))
            await asyncio.wait_for(a.wait(), 5)
            assert a.returncode == 0
            cache = WalletReportCache(ReadScope("fixture-devnet", ("https://fixture.invalid",)))
            entry = json.loads(await redis.get(cache.cache_key("wallet-race")))
            if result_a["status"] != "rejected" or entry["payload"]["raw"] != "50":
                return {
                    "verified": False,
                    "independent_python_processes": 2,
                    "events": [start_a, start_b, result_b, result_a],
                    "cached_worker": entry["payload"]["worker"],
                    "cached_raw": entry["payload"]["raw"],
                    "reason": "late older read overwrote the newer report",
                }
            from app.core.report_publication import publish_if_current

            report_pttl = await redis.pttl(cache.cache_key("wallet-race"))
            assert 0 < report_pttl <= 60000

            # Real TTL expiration: an expired reservation never admits an old result.
            reservation, report = cache.reservation_key("ttl-test"), cache.cache_key("ttl-test")
            await redis.set(reservation, "old-token", px=25)
            await asyncio.sleep(0.05)
            expired_result = await publish_if_current(
                redis, reservation, report, "old-token", "old", 1000
            )
            assert expired_result == 0 and await redis.get(report) is None

            # Replays with the current token are allowed; another reservation revokes the old token.
            await redis.set(reservation, "one", px=1000)
            assert await publish_if_current(redis, reservation, report, "one", "one", 1000) == 1
            assert await publish_if_current(redis, reservation, report, "one", "one", 1000) == 1
            await redis.set(reservation, "two", px=1000)
            assert await publish_if_current(redis, reservation, report, "one", "old", 1000) == 0
            assert await redis.get(report) == "one"
            version = (await redis.info("server"))["redis_version"]
            return {
                "verified": True,
                "redis_version": version,
                "independent_python_processes": 2,
                "events": [start_a, start_b, result_b, result_a],
                "cached_worker": entry["payload"]["worker"],
                "cached_raw": entry["payload"]["raw"],
                "real_lua_executed": True,
                "expired_reservation_rejected": True,
                "old_token_replay_rejected": True,
                "report_pttl_ms": report_pttl,
                "tcp_port": 0,
                "external_rpc_calls": 0,
                "scope": "one Redis primary without failover or rollback",
            }
        finally:
            for proc in processes:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    default = ROOT.parents[1]
    p.add_argument("--project", type=Path, default=default)
    p.add_argument("--redis-server", type=Path, required=True)
    p.add_argument("--redis-log", type=Path)
    a = p.parse_args()
    body = asyncio.run(run(a.project.resolve(), a.redis_server.resolve(), a.redis_log))
    print(json.dumps(body, indent=2))
    sys.exit(0 if body["verified"] else 1)
