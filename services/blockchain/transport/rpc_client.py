"""
增强版 Solana RPC 客户端

核心特性：
- 多端点自动切换
- 自动重试 + 指数退避
- 统一的异步接口
- 交易模拟
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from ..config import config
from ..exceptions import (
    InvalidAddressError,
    RPCConnectionError,
    RPCTimeoutError,
    TransactionSendError,
)
from .token_accounts import LEGACY_TOKEN_PROGRAM_ID, parse_token_accounts_response

logger = logging.getLogger(__name__)


def _validate_address(address: str) -> Pubkey:
    """校验并转换 Solana 地址"""
    try:
        return Pubkey.from_string(address)
    except Exception:
        raise InvalidAddressError(address)


class EnhancedRPCClient:
    """增强版 Solana RPC 客户端，支持多端点和自动重试"""

    def __init__(self, rpc_urls: Optional[List[str]] = None):
        self.rpc_urls = rpc_urls or config.RPC_ENDPOINTS
        self._current_index = 0
        self._clients: Dict[str, AsyncClient] = {}
        self._max_retries = config.RPC_MAX_RETRIES
        self._retry_delay = config.RPC_RETRY_DELAY
        self._timeout = config.RPC_TIMEOUT

    def _get_client(self) -> AsyncClient:
        """获取当前 RPC 客户端，惰性创建"""
        url = self.rpc_urls[self._current_index]
        if url not in self._clients:
            self._clients[url] = AsyncClient(url, commitment=Confirmed, timeout=self._timeout)
        return self._clients[url]

    def _switch_endpoint(self):
        """切换到下一个 RPC 端点"""
        if len(self.rpc_urls) > 1:
            old = self.rpc_urls[self._current_index]
            self._current_index = (self._current_index + 1) % len(self.rpc_urls)
            new = self.rpc_urls[self._current_index]
            logger.warning(f"RPC 端点切换: {old} → {new}")

    async def _execute_with_retry(self, operation: str, func, *args, **kwargs) -> Any:
        """带重试的执行封装"""
        last_error = None

        for attempt in range(self._max_retries):
            client = self._get_client()
            try:
                result = await asyncio.wait_for(
                    func(client, *args, **kwargs),
                    timeout=self._timeout,
                )
                return result

            except asyncio.TimeoutError:
                url = self.rpc_urls[self._current_index]
                last_error = RPCTimeoutError(url, self._timeout)
                logger.warning(f"[{operation}] 超时 (尝试 {attempt + 1}/{self._max_retries})")
                self._switch_endpoint()

            except Exception as e:
                url = self.rpc_urls[self._current_index]
                last_error = RPCConnectionError(url, str(e))
                logger.warning(f"[{operation}] 失败 (尝试 {attempt + 1}/{self._max_retries}): {e}")
                if attempt < self._max_retries - 1:
                    self._switch_endpoint()
                    delay = self._retry_delay * (2**attempt)
                    await asyncio.sleep(delay)

        raise last_error

    # ---- 账户查询 ----

    async def get_balance(self, address: str) -> int:
        """
        获取 SOL 余额（lamports）

        Args:
            address: 钱包地址

        Returns:
            余额（lamports）
        """
        pubkey = _validate_address(address)

        async def _call(client: AsyncClient):
            resp = await client.get_balance(pubkey)
            return resp.value

        return await self._execute_with_retry("get_balance", _call)

    async def get_token_accounts_parsed(self, address: str) -> List[Dict[str, Any]]:
        """
        获取Legacy Token Program账户，包括合法零余额账户。

        Returns:
            Raw数量、精度和账户来源信息；非法业务字段使整批失败。
        """
        pubkey = _validate_address(address)
        token_program = Pubkey.from_string(LEGACY_TOKEN_PROGRAM_ID)

        async def _call(client: AsyncClient):
            opts = TokenAccountOpts(program_id=token_program)
            return await client.get_token_accounts_by_owner_json_parsed(
                pubkey,
                opts,
            )

        response = await self._execute_with_retry("get_token_accounts", _call)
        # Business validation happens after transport retries, so bad data is not retried.
        return parse_token_accounts_response(response, str(pubkey))

    async def get_transaction(self, signature_str: str) -> Optional[Dict[str, Any]]:
        """获取交易详情"""
        sig = Signature.from_string(signature_str)

        async def _call(client: AsyncClient):
            resp = await client.get_transaction(
                sig,
                encoding="jsonParsed",
                max_supported_transaction_version=0,
            )
            if resp.value:
                return {
                    "slot": resp.value.slot,
                    "block_time": resp.value.block_time,
                }
            return None

        return await self._execute_with_retry("get_transaction", _call)

    async def get_transaction_history(
        self,
        address: str,
        limit: int = 20,
        before: Optional[str] = None,
        until: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取地址的链上交易签名历史。"""
        pubkey = _validate_address(address)
        before_sig = Signature.from_string(before) if before else None
        until_sig = Signature.from_string(until) if until else None

        async def _call(client: AsyncClient):
            resp = await client.get_signatures_for_address(
                pubkey,
                before=before_sig,
                until=until_sig,
                limit=limit,
            )
            history = []
            for item in resp.value or []:
                history.append(
                    {
                        "signature": str(item.signature),
                        "slot": item.slot,
                        "err": item.err,
                        "memo": item.memo,
                        "block_time": item.block_time,
                        "confirmation_status": str(item.confirmation_status)
                        if item.confirmation_status
                        else None,
                    }
                )
            return history

        return await self._execute_with_retry("get_transaction_history", _call)

    async def get_signature_status(self, signature_str: str) -> Optional[Dict[str, Any]]:
        """查询交易签名状态，支持 pending/confirmed/finalized/failed 判断。"""
        sig = Signature.from_string(signature_str)

        async def _call(client: AsyncClient):
            resp = await client.get_signature_statuses(
                [sig],
                search_transaction_history=True,
            )
            status = resp.value[0] if resp.value else None
            if status is None:
                return None

            return {
                "slot": status.slot,
                "confirmations": status.confirmations,
                "err": status.err,
                "confirmation_status": str(status.confirmation_status)
                if status.confirmation_status
                else None,
            }

        return await self._execute_with_retry("get_signature_status", _call)

    async def get_latest_blockhash(self) -> str:
        """获取最新 blockhash"""

        async def _call(client: AsyncClient):
            resp = await client.get_latest_blockhash(commitment=Finalized)
            return str(resp.value.blockhash)

        return await self._execute_with_retry("get_latest_blockhash", _call)

    async def estimate_fee_for_transaction(self, transaction_base64: str) -> Dict[str, Any]:
        """Estimate network fee for a serialized transaction message."""
        import base64

        tx = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))

        async def _call(client: AsyncClient):
            resp = await client.get_fee_for_message(tx.message, commitment=Confirmed)
            return {
                "fee_lamports": resp.value,
                "fee_sol": (resp.value / 1_000_000_000) if resp.value is not None else None,
            }

        return await self._execute_with_retry("estimate_fee_for_transaction", _call)

    async def simulate_transaction(self, transaction_base64: str) -> Dict[str, Any]:
        """Simulate a serialized transaction without signature verification."""
        import base64

        tx = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))

        async def _call(client: AsyncClient):
            resp = await client.simulate_transaction(tx, sig_verify=False, commitment=Confirmed)
            value = resp.value
            return {
                "err": str(value.err) if value.err is not None else None,
                "logs": value.logs or [],
                "units_consumed": getattr(value, "units_consumed", None),
                "accounts": value.accounts if value.accounts is None else str(value.accounts),
                "return_data": value.return_data
                if value.return_data is None
                else str(value.return_data),
            }

        return await self._execute_with_retry("simulate_transaction", _call)

    async def send_raw_transaction(self, signed_tx: bytes) -> str:
        """
        发送已签名的原始交易

        Args:
            signed_tx: 已签名的交易字节

        Returns:
            交易签名
        """

        async def _call(client: AsyncClient):
            resp = await client.send_raw_transaction(signed_tx)
            return str(resp.value)

        try:
            return await self._execute_with_retry("send_transaction", _call)
        except Exception as e:
            raise TransactionSendError(str(e))

    async def confirm_transaction(self, signature_str: str, timeout_seconds: int = 60) -> bool:
        """等待交易确认"""
        sig = Signature.from_string(signature_str)

        async def _call(client: AsyncClient):
            resp = await client.confirm_transaction(sig, commitment=Confirmed)
            # confirm_transaction 返回 RpcConfirmTransactionResult
            if hasattr(resp, "value") and resp.value:
                if hasattr(resp.value, "err") and resp.value.err:
                    return False
            return True

        return await self._execute_with_retry("confirm_transaction", _call)

    async def request_airdrop(self, address: str, lamports: int = 1_000_000_000) -> str:
        """
        请求 Devnet/Testnet 空投

        Args:
            address: 钱包地址
            lamports: 空投数量（默认 1 SOL）

        Returns:
            空投交易签名
        """
        pubkey = _validate_address(address)

        async def _call(client: AsyncClient):
            resp = await client.request_airdrop(pubkey, lamports)
            # airdrop 可能返回错误对象而非签名
            if hasattr(resp, "value") and resp.value is not None:
                return str(resp.value)
            raise Exception(f"Airdrop 请求失败: {resp}")

        return await self._execute_with_retry("request_airdrop", _call)

    # ---- 生命周期 ----

    async def close(self):
        """关闭所有客户端连接"""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
