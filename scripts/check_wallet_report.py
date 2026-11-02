"""Run offline wallet regression suites and disposable real-Redis integration checks."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def run(args, log, *, env=None):
    result = subprocess.run(
        list(map(str, args)),
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"{log}: exit {result.returncode}\n{result.stderr[-2000:]}")
    return result


def check(out, node, redis_server):
    out.mkdir(parents=True, exist_ok=False)
    version = run([node, "--version"], out / "node-version.log").stdout.strip()
    if not version.startswith("v24."):
        raise ValueError("wallet regression tests require Node 24 for native TypeScript imports")
    counts = {}
    for label, directory, filename, expected in [
        ("publication", "apps/api/tests", "test_wallet_report_cache.py", 28),
        ("api", "apps/api/tests", "test_assets_precision.py", 23),
        ("identity", "services/blockchain/tests", "test_wallet_identity.py", 21),
        ("rpc", "services/blockchain/tests", "test_rpc_token_accounts.py", 26),
        ("amount", "services/blockchain/tests", "test_wallet_precision.py", 13),
    ]:
        result = run(
            [sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", filename, "-v"],
            out / f"python-{label}.log",
        )
        if f"Ran {expected} tests" not in result.stderr:
            raise ValueError(f"unexpected Python test count: {label}")
        counts[f"python_{label}"] = expected

    helper = PROJECT / "scripts/wallet_report"
    alias = json.loads(
        run(
            [sys.executable, helper / "check_executable_alias.py", "--redis-server", redis_server],
            out / "redis-executable-alias.log",
        ).stdout
    )
    if alias.get("verified") is not True:
        raise ValueError("Redis executable alias was not preserved")
    race = json.loads(
        run(
            [sys.executable, helper / "real_redis_demo.py", "--redis-server", redis_server],
            out / "real-redis.log",
        ).stdout
    )
    if not race["verified"] or race["cached_worker"] != "B" or race["cached_raw"] != "50":
        raise ValueError("late publication was not rejected")
    fixture = out / "wallet.json"
    timeline = json.loads(
        run(
            [
                sys.executable,
                helper / "demo.py",
                "--redis-server",
                redis_server,
                "--http-out",
                fixture,
            ],
            out / "rpc-api-timeline.log",
        ).stdout
    )
    history = timeline["history"]
    if [row["source"] for row in history] != ["rpc_read", "report_cache", "rpc_read"]:
        raise ValueError("unexpected cache timeline")
    if (
        history[1]["age_ms"] != 2500
        or history[1]["read_started_at_ms"] != history[0]["read_started_at_ms"]
    ):
        raise ValueError("cache hit changed the original read age")
    env = dict(os.environ, WALLET_FIXTURE=str(fixture))
    for label, filename, expected in [
        ("amount", "exact-amount.test.mjs", 15),
        ("identity", "wallet-identity.test.mjs", 13),
        ("context", "report-context.test.mjs", 9),
        ("age", "report-age.test.mjs", 12),
    ]:
        result = run(
            [node, "--test", PROJECT / "apps/web/tests" / filename],
            out / f"node-{label}.log",
            env=env,
        )
        if not re.search(r"\btests\s+" + str(expected) + r"\b", result.stdout):
            raise ValueError(f"unexpected Node test count: {label}")
        counts[f"node_{label}"] = expected
    report = {
        "verified": True,
        "node": version,
        "tests": counts,
        "total_tests": sum(counts.values()),
        "real_redis_version": race["redis_version"],
        "redis_executable_alias_verified": True,
        "independent_processes": race["independent_python_processes"],
        "cached_worker": race["cached_worker"],
        "cached_raw": race["cached_raw"],
        "external_rpc_calls": timeline["external_rpc_calls"],
        "limits": ["no Redis failover/Cluster", "no live RPC/prices", "no browser lifecycle test"],
    }
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    parser.add_argument("--node", type=Path, default=shutil.which("node"))
    parser.add_argument("--redis-server", type=Path, default=shutil.which("redis-server"))
    args = parser.parse_args()
    if args.node is None or args.redis_server is None:
        parser.error("Node 24 and redis-server must be installed or passed as explicit paths")
    print(
        json.dumps(
            check(args.out.resolve(), args.node.resolve(), args.redis_server.absolute()), indent=2
        )
    )
