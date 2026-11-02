# Five-minute technical demo

[English home](../../README.en.md) · [Testing](TESTING.md)

Run the checks before presenting. From the repository root:

```bash
.venv/bin/python scripts/check_wallet_report.py --out .wallet-report-results-demo
```

## 0:00 — State the scope

“This branch improves the wallet read path of an unfinished Solana application. It preserves exact token quantities and account identity, and exposes a bounded read age. The reference was developed with assistant support; I distinguish my own work from the reference and from historical merged contributions.”

## 0:45 — Show a quantity

Open `.wallet-report-results-demo/wallet.json`. Locate raw `18446744073709551615` and scale 18. The exact text is `18.446744073709551615`. Explain why converting through a JavaScript Number or Python float cannot recover lost digits.

Then point to the account address, token owner, program ID and string slot. Several accounts can share a mint; slot is a read context, not an account write version. A known zero account remains present.

## 1:45 — Explain late publication

```bash
.venv/bin/python scripts/wallet_report/real_redis_demo.py \
  --redis-server /absolute/path/to/redis-server
```

“A reserved first and read 100, but completed late. B reserved later and published 50. Redis Lua compares the current reservation and writes atomically, so A is rejected and B remains. The smaller amount is not treated as older.”

Show `real_lua_executed`, `independent_python_processes`, `cached_worker` and `cached_raw`. This is one real Redis primary with two coordinator workers, not two deployed Uvicorn services or a failover test.

## 3:00 — Show the read window

Open `.wallet-report-results-demo/rpc-api-timeline.log`. Explain cold read → cache hit → explicit refresh. Cache age increases without replacing the original read start. The client adds conservative request/dwell time and expires the view; unexpected clocks produce unknown/expired state rather than age zero.

The scenario uses controlled clocks and intercepted RPC HTTP. It is not a demonstration of real chain holdings or real OS sleep.

## 4:00 — Make the limitation concrete

“Exact token quantities do not make all USD estimates exact. Missing quotes and legacy numeric fields still need a separate contract. Redis reservation order is not a globally ordered chain snapshot. I would validate browser lifecycle, quote freshness and Redis recovery as separate work.”

## 4:40 — Ask for focused review

“Please review the raw-amount contract, batch rejection rules and publication failure behavior. The test entry point and expected outcomes are in the repository. My next change should preserve these boundaries and add a concrete regression example.”

If a live command fails, identify the failure and use saved logs explicitly as a previous run; do not present them as current execution.
