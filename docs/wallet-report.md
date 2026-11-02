# Wallet report: quantities, identity and bounded read age

The wallet endpoint now returns raw integer strings and exact fixed-point quantities, keeps token-account identity, and exposes the age of the account read. The dashboard validates this contract and expires the report while it remains open.

## Quantity and identity contract

`GET /api/v1/assets/{wallet}?refresh=false` includes `quantity_schema_version=2`, `account_identity_version=1`, SOL raw units, and token `balance_raw`, `decimals`, `balance_exact`, `account_address`, `token_owner`, `program_id` and string `observed_slot`.

For example, raw `18446744073709551615` with 18 decimals remains `18.446744073709551615`. Quantity construction starts from validated u64 units and a u8 scale; it never recovers quantities from UI floats. Known zero balances remain records. Missing or invalid required fields fail the read rather than becoming zero. Legacy float and USD fields remain approximate; missing price treatment and later valuation arithmetic are outside this guarantee.

Within one response, identical account records are deduplicated by program/account, conflicting duplicates or mixed read contexts are rejected, and different accounts for one mint remain separate. RPC `context.slot` is a read context, not an account write version. This implementation covers native SOL and the Legacy Token Program; it does not decode Token-2022.

## Cache and publication

`report_context` carries the original read start/end, served time, read-window age, source fingerprint, budget, and publication outcome. Report rebuilds bypass the older in-memory service cache. A cache hit preserves the read start. `refresh=true` skips stored reports and may join an active read in the same API process.

Multiple API workers may still query concurrently. Before a read, a worker registers a fresh UUID reservation in Redis. Lua atomically compares that reservation and writes the report only if it remains current. A superseded or expired reservation produces a retriable 503. A reservation failure skips shared publication; a lost publication reply is `unknown`, without an unconditional SET fallback. Cache keys use v5 and a shared hash tag.

This orders publication reservations on one Redis primary without rollback. It is not an exclusive read lock, a monotonic external fencing counter, a failover guarantee, or proof of the newest chain state. Report freshness also does not certify quote freshness.

The browser adds a conservative request-duration estimate and local dwell time to server age, keeps a high-water mark, and expires on clock anomalies. A request ticket prevents older wallet requests from replacing newer state. Real browser sleep and lifecycle behavior require separate verification.

## Reproduce the checks

Use Python 3.11+, Node 24, Git and Redis on macOS/Linux. Node 24 is required for the regression tests' native TypeScript imports. From the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.txt -r requirements-dev.txt
npm ci --ignore-scripts --no-audit --no-fund
.venv/bin/python scripts/check_wallet_report.py --out .wallet-report-results
npm run lint --workspace @solon-ai/web
npm run format:check --workspace @solon-ai/web
npm run type-check --workspace @solon-ai/web
npm run build --workspace @solon-ai/web
.venv/bin/python -m ruff check apps/api/ services/ scripts/check_wallet_report.py scripts/wallet_report/
.venv/bin/python -m ruff format --check apps/api/ services/ scripts/check_wallet_report.py scripts/wallet_report/
```

Pass `--node /absolute/path/to/node --redis-server /absolute/path/to/redis-server` when needed. Output directories must be new. The runner selects five offline Python suites (112 tests), produces actual SDK/service/API JSON using intercepted RPC HTTP and mock prices, then runs four Node suites against that JSON (49 tests). It also starts a disposable real Redis and two independent Python workers: B reserves later and publishes raw 50; A's late raw 100 must be rejected. The Redis runtime uses only a private temporary Unix socket, TCP port 0, and is cleaned up afterwards. No production Redis, database, wallet key, model endpoint or external RPC is used.

Native SOL quantity construction reuses the validated raw-unit helper with scale 9. The regression checks 0, 1 and maximum-u64 lamports under Decimal precision 6 with prices absent. Exact quantity construction must not signal `Inexact` or `Rounded`; subsequent USD arithmetic still follows the active Decimal context and is outside this guarantee.

`results.json` is written only after success; each suite has a separate log. CI runs the same runner and uploads its output. The real Redis check covers single-primary Lua and physical reservation expiry, not failover or Cluster. The workflow installs the Ubuntu Redis package; local reference verification used Redis 7.2.11. These tests are separate from historical live-network scripts and do not run them implicitly.

This work began as an assistant-provided guided reference. Repository commits describe the resulting implementation and validation; personal learning or authorship claims should state the actual participation separately.
