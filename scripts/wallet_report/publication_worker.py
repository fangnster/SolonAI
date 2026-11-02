"""An independent process executing the actual report coordinator against shared Redis."""

import argparse
import asyncio
import json
import sys
from pathlib import Path


async def run(project, socket, role):
    sys.path.insert(0, str(project / "apps/api"))
    from app.core.wallet_report_cache import ReadScope, ReportFreshnessError, WalletReportCache
    from redis.asyncio import Redis

    redis = Redis(unix_socket_path=str(socket), decode_responses=True)
    cache = WalletReportCache(
        ReadScope("fixture-devnet", ("https://fixture.invalid",)), read_timeout=10
    )

    async def load():
        print(json.dumps({"event": "read_started", "role": role}), flush=True)
        if role == "A":
            await asyncio.to_thread(sys.stdin.readline)
        return {
            "wallet_address": "wallet-race",
            "raw": "100" if role == "A" else "50",
            "worker": role,
        }

    try:
        try:
            result = await cache.get(redis, "wallet-race", load, lambda value: value, refresh=True)
            print(
                json.dumps(
                    {"event": "result", "role": role, "status": "published", "raw": result["raw"]}
                ),
                flush=True,
            )
        except ReportFreshnessError as error:
            print(
                json.dumps(
                    {"event": "result", "role": role, "status": "rejected", "reason": str(error)}
                ),
                flush=True,
            )
    finally:
        await cache.aclose()
        await redis.aclose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--project", type=Path, required=True)
    p.add_argument("--socket", type=Path, required=True)
    p.add_argument("--role", choices=["A", "B"], required=True)
    a = p.parse_args()
    asyncio.run(run(a.project.resolve(), a.socket, a.role))
