"""Trace synthetic RPC fields through real SDK decoding, WalletService and the assets API."""

import argparse
import asyncio
import copy
import importlib.metadata
import json
import os
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import AsyncMock, patch

PROJECT = Path(__file__).resolve().parents[1]
CASES = (
    "baseline",
    "ui-disagrees",
    "raw-invalid",
    "decimals-string",
    "native-overflow",
    "account-lamports-overflow",
    "decimals-conflict",
    "different-decimals",
)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


async def trace(case, out):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    for directory in ("services", "apps/api", "apps/api/tests"):
        sys.path.insert(0, str(PROJECT / directory))
    import httpx
    from app.api.v1 import assets
    from app.core.wallet_report_cache import ReadScope, WalletReportCache
    from blockchain.cache import get_cache
    from blockchain.services.wallet_service import WalletService
    from blockchain.transport.rpc_client import EnhancedRPCClient
    from fastapi import FastAPI
    from report_cache_fixtures import PublicationRedis
    from solders.pubkey import Pubkey

    out.mkdir()
    fixtures = PROJECT / "scripts/wallet_report/inputs"
    native = json.loads((fixtures / "provenance-native.json").read_text())
    tokens = json.loads((fixtures / "provenance-tokens.json").read_text())
    row = tokens["result"]["value"][0]
    amount = row["account"]["data"]["parsed"]["info"]["tokenAmount"]
    owner = row["account"]["data"]["parsed"]["info"]["owner"]
    if case == "ui-disagrees":
        amount.update(uiAmount=999.0, uiAmountString="999")
    elif case == "raw-invalid":
        amount["amount"] = "+1"
    elif case == "decimals-string":
        amount["decimals"] = "6"
    elif case == "native-overflow":
        native["result"]["value"] = 2**64
    elif case == "account-lamports-overflow":
        row["account"]["lamports"] = 2**64
    elif case == "decimals-conflict":
        second = copy.deepcopy(row)
        second["pubkey"] = str(Pubkey.from_bytes(bytes([4]) * 32))
        second["account"]["data"]["parsed"]["info"]["tokenAmount"].update(
            amount="750000", decimals=9
        )
        tokens["result"]["value"].append(second)
    elif case == "different-decimals":
        amount["decimals"] = 9
    write_json(out / "rpc-native.json", native)
    write_json(out / "rpc-tokens.json", tokens)
    requests, sdk_stages, observed = [], [], {}
    rpc = EnhancedRPCClient(rpc_urls=["https://fixture.invalid"])
    rpc._retry_delay = 0
    rpc._max_retries = 3
    sdk = rpc._get_client()
    await sdk._provider.session.aclose()

    def http_boundary(request):
        body = json.loads(request.content)
        requests.append(body)
        response = {"getBalance": native, "getTokenAccountsByOwner": tokens}.get(body["method"])
        if response is None:
            raise AssertionError("unexpected RPC method: " + body["method"])
        response = copy.deepcopy(response)
        response["id"] = body["id"]
        return httpx.Response(200, json=response)

    sdk._provider.session = httpx.AsyncClient(
        transport=httpx.MockTransport(http_boundary), trust_env=False
    )
    make_request = sdk._provider.make_request

    async def observe_sdk(body, parser):
        method = json.loads(body.to_json())["method"]
        try:
            decoded = await make_request(body, parser)
        except Exception as error:
            sdk_stages.append({"method": method, "error_type": type(error).__name__})
            raise
        stage = {
            "method": method,
            "response_type": type(decoded).__name__,
            "value_type": type(decoded.value).__name__,
            "context_slot": decoded.context.slot,
        }
        if method == "getBalance":
            stage["lamports"] = decoded.value
        else:
            account = decoded.value[0].account
            parsed_amount = account.data.parsed["info"]["tokenAmount"]
            stage.update(
                account_lamports=account.lamports,
                amount_type=type(parsed_amount["amount"]).__name__,
                decimals_type=type(parsed_amount["decimals"]).__name__,
            )
        sdk_stages.append(stage)
        return decoded

    sdk._provider.make_request = observe_sdk
    get_balance, get_tokens = rpc.get_balance, rpc.get_token_accounts_parsed

    async def observe_balance(address):
        value = await get_balance(address)
        observed["transport_native"] = {
            "lamports": value,
            "python_type": type(value).__name__,
            "context_slot_retained": False,
        }
        return value

    async def observe_tokens(address):
        records = await get_tokens(address)
        observed["parser_records"] = copy.deepcopy(records)
        return records

    rpc.get_balance, rpc.get_token_accounts_parsed = observe_balance, observe_tokens
    prices = AsyncMock()
    prices.get_token_price.return_value = None
    prices.batch_get_token_prices.return_value = {}
    wallet = WalletService(rpc_client=rpc, jupiter=prices)
    portfolio = wallet.get_wallet_portfolio

    async def observe_portfolio(*args, **kwargs):
        model = await portfolio(*args, **kwargs)
        observed["wallet_model"] = model.model_dump(mode="json")
        return model

    wallet.get_wallet_portfolio = observe_portfolio
    reports = WalletReportCache(
        ReadScope("fixture-devnet", ("https://fixture.invalid",)), clock_ms=lambda: 1000000
    )
    redis = PublicationRedis()  # Protocol double; this script does not prove Redis Lua semantics.
    app = FastAPI()
    app.include_router(assets.router, prefix="/api/v1/assets")
    app.dependency_overrides[assets.get_redis] = lambda: redis
    app.dependency_overrides[assets.get_wallet_report_cache] = lambda: reports
    await get_cache().clear()
    try:
        with patch.object(assets, "get_wallet_service", return_value=wallet):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://fixture"
            ) as client:
                response = await client.get(f"/api/v1/assets/{owner}", params={"refresh": True})
                api = response.json()
    finally:
        await reports.aclose()
        await rpc.close()
        await get_cache().clear()

    counts = dict(Counter(request["method"] for request in requests))
    expected_status = 200 if case in ("baseline", "ui-disagrees", "different-decimals") else 500
    assert response.status_code == expected_status, api
    assert not (set(counts) - {"getBalance", "getTokenAccountsByOwner"})
    for request in requests:
        assert request["params"][0] == owner
        if request["method"] == "getTokenAccountsByOwner":
            assert request["params"][1] == {"programId": row["account"]["owner"]}
            assert request["params"][2]["encoding"] == "jsonParsed"
    if expected_status == 200:
        assert api["sol_balance_raw"] == "1000000001"
        assert api["sol_balance_exact"] == "1.000000001"
        assert api["tokens"][0]["balance_raw"] == "1250000"
        assert api["tokens"][0]["balance_exact"] == (
            "0.001250000" if case == "different-decimals" else "1.250000"
        )
        assert counts == {"getBalance": 1, "getTokenAccountsByOwner": 1}
        boundary = "accepted"
    elif case in ("native-overflow", "account-lamports-overflow"):
        method = "getBalance" if case == "native-overflow" else "getTokenAccountsByOwner"
        assert counts[method] == 3
        assert any("error_type" in stage for stage in sdk_stages)
        boundary = "sdk_decode_inside_retry"
    elif case == "decimals-conflict":
        assert (
            len(observed["parser_records"]) == 2 and prices.batch_get_token_prices.await_count == 0
        )
        assert counts["getTokenAccountsByOwner"] == 1
        boundary = "wallet_service_batch_validation"
    else:
        assert "parser_records" not in observed
        assert counts["getTokenAccountsByOwner"] == 1
        path = "tokenAmount.amount" if case == "raw-invalid" else "tokenAmount.decimals"
        assert path in api["detail"]
        boundary = "business_parser_after_retry"
    if expected_status != 200:
        assert "tokens" not in api
    result = {
        "case": case,
        "verified": True,
        "status": response.status_code,
        "boundary": boundary,
        "request_counts": counts,
        "requests": requests,
        "sdk_stages": sdk_stages,
        **observed,
        "api": api,
        "price_batch_calls": prices.batch_get_token_prices.await_count,
        "external_rpc_calls": 0,
        "mint_account_independently_read": False,
        "redis": "protocol double, not a real Redis server",
        "native_and_token_slots_form_atomic_snapshot": False,
    }
    write_json(out / "trace.json", result)
    return {
        key: result[key] for key in ("case", "verified", "status", "boundary", "request_counts")
    }


async def main(args):
    if sys.flags.optimize:
        raise RuntimeError("run this assertion-based diagnostic without Python -O")
    versions = {name: importlib.metadata.version(name) for name in ("solana", "solders", "httpx")}
    if versions["solana"] != "0.30.2" or versions["solders"] != "0.18.1":
        raise ValueError("private SDK observation seam requires solana 0.30.2 and solders 0.18.1")
    args.out.mkdir(parents=True, exist_ok=False)
    cases = CASES if args.case == "all" else (args.case,)
    results = [await trace(case, args.out / case) for case in cases]
    summary = {"verified": True, "versions": versions, "cases": results, "external_rpc_calls": 0}
    write_json(args.out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("all", *CASES), default="baseline")
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args()
    args.out = args.out.resolve()
    print(json.dumps(asyncio.run(main(args)), indent=2))
