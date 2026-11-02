"""Strict parsing for Legacy Token Program jsonParsed account responses."""

from typing import Any, Dict, List

from solders.pubkey import Pubkey

from ..exceptions import RPCResponseValidationError

LEGACY_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
U64_MAX = 2**64 - 1


def _pubkey(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise RPCResponseValidationError(path, "expected a public key string")
    try:
        return str(Pubkey.from_string(value))
    except ValueError as error:
        raise RPCResponseValidationError(path, "expected a valid public key") from error


def _raw_amount(value: Any, path: str) -> int:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 20
        or not value.isascii()
        or not value.isdigit()
        or (len(value) > 1 and value[0] == "0")
    ):
        raise RPCResponseValidationError(path, "expected a canonical ASCII u64 string")
    amount = int(value)
    if amount > U64_MAX:
        raise RPCResponseValidationError(path, "amount exceeds u64")
    return amount


def parse_token_accounts_response(response: Any, owner: str) -> List[Dict[str, Any]]:
    """Return every valid account, including zero; reject an invalid batch atomically.

    uiAmount and uiAmountString are presentation fields and are deliberately ignored.
    response is the real solana-py/solders typed response, not raw JSON.
    """
    slot = response.context.slot
    if type(slot) is not int or not 0 <= slot <= U64_MAX:
        raise RPCResponseValidationError("context.slot", "expected a u64 integer")
    if not isinstance(response.value, list):
        raise RPCResponseValidationError("value", "expected an account array")
    accounts = []
    for index, entry in enumerate(response.value):
        path = f"value[{index}]"
        address = str(entry.pubkey)
        program_id = str(entry.account.owner)
        if program_id != LEGACY_TOKEN_PROGRAM_ID:
            raise RPCResponseValidationError(f"{path}.account.owner", "unexpected token program")
        data = entry.account.data
        parsed = getattr(data, "parsed", None)
        if getattr(data, "program", None) != "spl-token" or not isinstance(parsed, dict):
            raise RPCResponseValidationError(
                f"{path}.account.data", "expected spl-token jsonParsed data"
            )
        parsed_path = f"{path}.account.data.parsed"
        if parsed.get("type") != "account":
            raise RPCResponseValidationError(f"{parsed_path}.type", "expected token account")
        info = parsed.get("info")
        if not isinstance(info, dict):
            raise RPCResponseValidationError(f"{parsed_path}.info", "expected an object")
        info_path = f"{parsed_path}.info"
        mint = _pubkey(info.get("mint"), f"{info_path}.mint")
        token_owner = _pubkey(info.get("owner"), f"{info_path}.owner")
        if token_owner != owner:
            raise RPCResponseValidationError(f"{info_path}.owner", "does not match queried wallet")
        token_amount = info.get("tokenAmount")
        amount_path = f"{info_path}.tokenAmount"
        if not isinstance(token_amount, dict):
            raise RPCResponseValidationError(amount_path, "expected an object")
        raw = _raw_amount(token_amount.get("amount"), f"{amount_path}.amount")
        decimals = token_amount.get("decimals")
        if type(decimals) is not int or not 0 <= decimals <= 255:
            raise RPCResponseValidationError(f"{amount_path}.decimals", "expected a u8 integer")
        accounts.append(
            {
                "account_address": address,
                "token_owner": token_owner,
                "program_id": program_id,
                "observed_slot": slot,
                "mint": mint,
                "balance_raw": raw,
                "decimals": decimals,
                "balance": float(f"{raw}e-{decimals}"),  # legacy approximation only
            }
        )
    return accounts
