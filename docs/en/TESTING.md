# Testing and validation

[English home](../../README.en.md) · [Setup](SETUP.md)

## Wallet regression entry point

```bash
.venv/bin/python scripts/check_wallet_report.py --out .wallet-report-results
```

Use a new output directory for each run. If needed, append `--node /absolute/path/to/node --redis-server /absolute/path/to/redis-server`.

| Suite                                                 |   Cases |
| ----------------------------------------------------- | ------: |
| Python report cache/publication                       |      28 |
| Python API quantities and identity                    |      23 |
| Python wallet identity                                |      21 |
| Python typed RPC parsing                              |      26 |
| Python quantity construction                          |      13 |
| Node exact quantities, with API JSON                  |      15 |
| Node account identity/request ordering, with API JSON |      13 |
| Node report context, with API JSON                    |       9 |
| Node local report age, with API JSON                  |      12 |
| **Total targeted tests**                              | **160** |

The runner also executes real Redis integration outside those test counts. Two independent Python workers use the actual cache coordinator and Lua script. Handshakes ensure A starts first, B reserves and publishes raw 50, then A resumes and its raw 100 is rejected. The check also exercises physical reservation expiry and old-token replay rejection.

An executable-alias regression copies the Redis binary under the name `redis-check-rdb`, creates a `redis-server` symlink to it, and verifies startup through that alias. Ubuntu packages can dispatch Redis modes using the executable name; resolving the symlink before execution incorrectly starts the checker. The harness and runner preserve the server alias.

The SDK/API scenario executes real solana-py/solders decoding, WalletService and FastAPI, with only outbound RPC HTTP and price dependencies replaced. It observes cold read age 0, cached age 2500 with the original read start, and a forced read with a new start. Its generated JSON is passed into all four Node suites. Redis uses a temporary private Unix socket with port 0 and is cleaned up afterwards.

Logs are written per suite; `results.json` is created only after all required checks pass. Read the specific error before changing an expectation. A missing executable or import failure is an environment failure, not evidence that a business-rule mutation was detected.

## Static checks and complete frontend build

```bash
.venv/bin/python -m ruff check apps/api/ services/ scripts/check_wallet_report.py scripts/wallet_report/
.venv/bin/python -m ruff format --check apps/api/ services/ scripts/check_wallet_report.py scripts/wallet_report/
npm run lint --workspace @solon-ai/web
npm run format:check --workspace @solon-ai/web
npm run type-check --workspace @solon-ai/web
npm run build --workspace @solon-ai/web
```

`type-check` covers the dashboard integration and caught an inference issue that the earlier scoped checks did not cover. The call now explicitly carries `WalletAssetsRead` as its generic argument. The full build also performs lint and type validation; it does not execute a real browser or validate live services.

## Local reference results

On 2026-11-03, Python 3.11.15, Node 24.22.2 and Redis 7.2.11 passed the 160 targeted tests and real-Redis scenarios. Frontend lint/format/type checks, the complete Next.js build, and Python Ruff checks passed. Existing warnings in unrelated AI/risk/strategy screens and outdated Browserslist data remain warnings; the checks did not suppress them.

These results are distinct from any GitHub Actions status. The workflow runs on main/develop pushes, course branches and pull requests targeting main/develop, uses Node 24, and uploads wallet regression outputs. CI obtains a Redis executable from the Ubuntu package manager; its version is reported in `results.json`.

## What remains outside this verification

The targeted suite does not run every historical repository test. Some older blockchain/agent scripts require live services and are intentionally not discovered by this runner. No full browser lifecycle or physical sleep test, production load, Redis failover/Cluster, live market/RPC correctness, database migration/restore, real model call or deployed full-stack acceptance is claimed. Two earlier selected mutation experiments detected two specific broken rules; that is not a coverage percentage.
