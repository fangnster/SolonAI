# Solon AI

[简体中文](README.md) | English

Solon AI is a work-in-progress Solana application that combines a Next.js interface, a FastAPI backend, blockchain data services, and an optional agent workflow. The repository contains wallet reporting, DeFi provider integration, database/cache infrastructure, and agent/RAG code. Availability of a route or UI screen does not imply that the corresponding production workflow is complete.

The wallet-report changes focus on a concrete problem: preserve token quantities and account identity across RPC, API, cache and UI boundaries, and stop displaying a report as fresh indefinitely.

## Start here

- [Setup and configuration](docs/en/SETUP.md): reproduce the offline checks first, then start a local API and frontend.
- [Architecture and current status](docs/en/ARCHITECTURE.md): component responsibilities, data flow and remaining work.
- [Wallet API reference](docs/en/API.md): quantity, identity, freshness and error contracts.
- [Testing and validation](docs/en/TESTING.md): commands, expected results and verification limits.
- [Five-minute technical demo](docs/en/DEMO.md): a reviewer-oriented walkthrough.
- [Contributing](docs/en/CONTRIBUTING.md): review scope, tests and commit conventions.
- [Wallet implementation notes](docs/wallet-report.md): detailed quantity and publication semantics.

## What is implemented in the wallet path

- Validate raw u64 amounts and u8 decimal scales; carry raw units and exact fixed-point text as JSON strings.
- Preserve Legacy Token Program account addresses, owners, program IDs and read-context slots, including known zero balances.
- Reject malformed batches, conflicting duplicate accounts and mixed token read contexts.
- Cache reports with their original read window, a bounded age and explicit source metadata.
- Use atomic Redis reservation checks to reject a superseded task's late publication on one primary.
- Validate the client contract, guard against stale wallet responses, and expire displayed balances as local time passes.

USD values and legacy float fields remain approximate. Quote freshness, Token-2022, Redis failover, complete authentication and production hardening remain separate work. See the status table in the architecture guide.

## Reproduce the wallet checks

Requirements: Python 3.11+, Node 24, npm and a Redis executable on macOS/Linux. The regression runner starts its own temporary Redis; no existing Redis instance or provider credentials are required.

```bash
git clone https://github.com/fangnster/SolonAI.git
cd SolonAI
git switch course/w1d1-review
python3.11 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.txt -r requirements-dev.txt
npm ci --ignore-scripts --no-audit --no-fund
.venv/bin/python scripts/check_wallet_report.py --out .wallet-report-results
```

Expected summary: `verified: true`, `total_tests: 160`, `cached_worker: B`, `cached_raw: "50"`, and `external_rpc_calls: 0`. Use a new output directory for each run. Explicit `--node` and `--redis-server` executable paths are supported.

## Repository map

```text
apps/web/                 Next.js UI and client-side report validation
apps/api/                 FastAPI routes, SQLAlchemy models and Redis report cache
services/blockchain/      Solana RPC parsing, wallet service and DeFi providers
services/ai-agents/       Agent graph, prompts and RAG implementation
scripts/wallet_report/    Controlled SDK/API and real-Redis integration scenarios
docs/en/                  English setup, architecture, API and review material
```

The local reference run on 2026-11-03 passed the 160 targeted tests, real-Redis integration, frontend lint/format/type checks, a complete Next.js build, and Python Ruff checks. Existing frontend lint warnings remain. This does not certify live provider availability, full browser behavior or production deployment. Remote CI status belongs to the individual GitHub run.

This change set began as an assistant-provided guided reference. Historical merged contributions and the author's own learning participation should be described separately from the implementation and checks in this branch.
