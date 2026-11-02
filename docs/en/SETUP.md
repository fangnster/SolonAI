# Setup and configuration

[English home](../../README.en.md) · [Testing](TESTING.md)

## 1. Choose a scope

The offline wallet checks are the validated starting point. They need no wallet keys, model credentials, external RPC or running database. A full API process additionally starts the existing DeFi refresh scheduler, which can make network requests. Live application startup and provider availability are separate from the offline verification.

Use macOS/Linux, Python 3.11+, Node 24, npm and a Redis executable. The Node tests import TypeScript directly using Node 24. For the local application, Docker Compose can supply PostgreSQL and Redis; the Python API can also use SQLite.

## 2. Install and verify the wallet path

From the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.txt -r requirements-dev.txt
npm ci --ignore-scripts --no-audit --no-fund
.venv/bin/python scripts/check_wallet_report.py --out .wallet-report-results
```

Install Redis using your system's supported package manager, or pass an existing executable with `--redis-server /absolute/path/to/redis-server`. The script owns a temporary Redis process with a private Unix socket and no TCP listener. It never reuses your application Redis. Compilation and dependency installation require normal development tools/network access; the checks themselves intercept external RPC HTTP.

## 3. Configure a local API and frontend

Copy templates only when the destination does not exist:

```bash
test -f apps/api/.env || cp apps/api/.env.example apps/api/.env
test -f apps/web/.env.local || cp apps/web/.env.example apps/web/.env.local
```

In `apps/api/.env`, replace the placeholder RPC endpoint with your chosen devnet endpoint, and keep `SOLANA_NETWORK=devnet` consistent with it. The offline checks do not use this endpoint. API settings read `.env` from the process working directory; run the API from `apps/api` as shown below.

| Variable                             | Purpose / local value                                                                                                                             |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                       | `sqlite+aiosqlite:///./solon_ai.db` for local SQLite; host PostgreSQL can use `postgresql+asyncpg://solon:solon_password@localhost:5432/solon_ai` |
| `REDIS_URL`                          | `redis://localhost:6379` for a host API                                                                                                           |
| `SOLANA_NETWORK`                     | Network label, usually `devnet` for development; it does not verify an endpoint's actual network                                                  |
| `SOLANA_RPC_URLS`                    | Optional comma-separated ordered RPC pool; falls back to `SOLANA_RPC_URL`                                                                         |
| `CACHE_TTL_ASSETS`                   | Report read-age budget in seconds; default 60                                                                                                     |
| `REPORT_READ_TIMEOUT_SECONDS`        | Report load timeout; default 20; cancellation is cooperative                                                                                      |
| `SECRET_KEY`                         | Replace the development placeholder for any shared deployment                                                                                     |
| `NEXT_PUBLIC_API_URL`                | Frontend API base, typically `http://localhost:8000`                                                                                              |
| `NEXT_PUBLIC_SOLANA_RPC_URL`         | Browser wallet RPC endpoint; keep its network consistent with the backend                                                                         |
| `NEXT_PUBLIC_WALLET_ADAPTER_NETWORK` | Frontend wallet network label, typically `devnet`                                                                                                 |

The source fingerprint identifies the configured RPC pool and contract scope; it does not expose endpoint URLs or prove which upstream produced every response. Frontend `NEXT_PUBLIC_*` values are public and are embedded by the Next.js configuration.

## 4. Start infrastructure and development processes

Optional PostgreSQL and the application Redis:

```bash
docker compose up -d db redis
```

The Compose database defaults are for local development. `db` and `redis` are container hostnames; a Python process on the host should use `localhost`. Avoid copying the root Compose `DATABASE_URL` unchanged into a host API configuration.

In one terminal, from the repository root:

```bash
cd apps/api
../../.venv/bin/python -m app.core.init_db
PYTHONPATH=../../services:../../services/ai-agents \
  ../../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

The initializer creates missing tables. Keep `INIT_DB_RESET` unset; its explicit reset mode drops tables. SQLite initialization creates a local database file. Stop this foreground API with Ctrl+C.

In another terminal, from the repository root:

```bash
npm run dev --workspace @solon-ai/web
```

Open `http://localhost:3000`, `http://localhost:8000/docs` and `http://localhost:8000/health`. Health reports Redis connectivity only; a healthy response does not validate PostgreSQL, RPC or model providers. `/openapi.json` is the generated API schema.

## Optional AI and Docker integration

AI imports are lazy; an API can start without the full agent environment, while agent-dependent requests can return 503. The AI manifest currently pins different Pydantic/settings versions from the API manifest. Do not treat sequential installation of both manifests as a validated unified lock. Review `services/ai-agents/requirements.txt` and the existing integration documentation before enabling those workflows.

The existing `docker compose up --build` path includes additional AI dependencies and images. This wallet change set did not run a complete Docker stack or live model request. The web Dockerfile still uses its existing Node 20 image; the wallet regression tests and CI use Node 24. See [architecture status](ARCHITECTURE.md) for follow-up work.
