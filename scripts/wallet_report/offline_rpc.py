"""Real SDK and typed decoding; replace only the outbound HTTP boundary."""

import copy
import json
import sys
from pathlib import Path


async def open_client(project: Path, payload: dict, before_request=None):
    sys.path.insert(0, str(project / "services"))
    import httpx
    from blockchain.transport.rpc_client import EnhancedRPCClient

    requests = []
    client = EnhancedRPCClient(rpc_urls=["https://fixture.invalid"])
    client._retry_delay = 0
    client._max_retries = 3
    sdk = client._get_client()
    await sdk._provider.session.aclose()

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if before_request is not None:
            await before_request(body)
        if body["method"] == "getTokenAccountsByOwner":
            response = copy.deepcopy(payload)
        elif body["method"] == "getBalance":
            response = {
                "jsonrpc": "2.0",
                "result": {"context": {"slot": 424242}, "value": 2**64 - 1},
            }
        else:
            raise AssertionError("unexpected fixture method: " + body["method"])
        response["id"] = body["id"]
        return httpx.Response(200, json=response)

    sdk._provider.session = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    )
    return client, requests
