"""
Solana RPC 模块 — 自定义异常体系

按照开发文档定义的异常分类：
- RPC 连接 / 超时 / 限流
- 交易构建 / 发送 / 模拟
- 协议交互
- 业务逻辑（余额不足 / 无效地址）
"""

from typing import List, Optional


class SolanaRPCError(Exception):
    """RPC 模块基础异常"""

    def __init__(self, message: str = "Solana RPC 操作失败", detail: str = ""):
        self.message = message
        self.detail = detail
        super().__init__(f"{message}: {detail}" if detail else message)


# ---- RPC 连接相关 ----


class RPCConnectionError(SolanaRPCError):
    """RPC 连接失败（网络问题、端点不可用）"""

    def __init__(self, endpoint: str = "", detail: str = ""):
        super().__init__(f"RPC 连接失败 [{endpoint}]", detail)
        self.endpoint = endpoint


class RPCTimeoutError(SolanaRPCError):
    """RPC 请求超时"""

    def __init__(self, endpoint: str = "", timeout: float = 0):
        super().__init__(f"RPC 请求超时 [{endpoint}]", f"超时时间: {timeout}s")
        self.endpoint = endpoint
        self.timeout = timeout


class RPCRateLimitError(SolanaRPCError):
    """RPC 调用频率超限"""

    def __init__(self, endpoint: str = "", retry_after: float = 0):
        super().__init__(f"RPC 频率限制 [{endpoint}]", f"建议等待: {retry_after}s")
        self.endpoint = endpoint
        self.retry_after = retry_after


class RPCResponseValidationError(SolanaRPCError):
    """A received response violates the parsed account contract; do not retry it."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__("RPC response validation failed", f"{path}: {reason}")


# ---- 交易相关 ----


class TransactionBuildError(SolanaRPCError):
    """交易构建失败（参数错误、余额不足等）"""

    def __init__(self, detail: str = ""):
        super().__init__("交易构建失败", detail)


class TransactionSendError(SolanaRPCError):
    """交易发送失败"""

    def __init__(self, detail: str = ""):
        super().__init__("交易发送失败", detail)


class TransactionSimulationError(SolanaRPCError):
    """交易模拟失败（预执行不通过）"""

    def __init__(self, detail: str = "", logs: Optional[List[str]] = None):
        super().__init__("交易模拟失败", detail)
        self.logs = logs or []


# ---- 协议相关 ----


class ProviderError(SolanaRPCError):
    """DeFi 协议交互失败"""

    def __init__(self, provider: str = "", detail: str = ""):
        super().__init__(f"协议交互失败 [{provider}]", detail)
        self.provider = provider


class QuoteError(ProviderError):
    """报价获取失败"""

    def __init__(self, provider: str = "", detail: str = ""):
        super().__init__(provider, f"获取报价失败: {detail}")


# ---- 业务逻辑相关 ----


class InsufficientBalanceError(SolanaRPCError):
    """余额不足"""

    def __init__(self, required: float = 0, available: float = 0, token: str = "SOL"):
        super().__init__(
            "余额不足",
            f"需要 {required} {token}，当前余额 {available} {token}",
        )
        self.required = required
        self.available = available
        self.token = token


class InvalidAddressError(SolanaRPCError):
    """无效的 Solana 地址"""

    def __init__(self, address: str = ""):
        super().__init__("无效的 Solana 地址", address)
        self.address = address
