"""
区块链服务层缓存中间件

提供基于内存的 LRU 缓存 (进程内) + 可选 Redis 缓存 (跨进程)
设计原则：
- blockchain 服务层不直接依赖 Redis（保持独立性）
- 使用内存缓存作为默认，Redis 作为可选增强
- 自动 TTL 过期
"""

import asyncio
import functools
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class MemoryCache:
    """
    线程安全的内存 LRU 缓存

    特性：
    - TTL 自动过期
    - LRU 淘汰策略
    - 最大容量限制
    """

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值，过期返回 None"""
        async with self._lock:
            if key in self._cache:
                value, expires_at = self._cache[key]
                if time.time() < expires_at:
                    # 移到末尾 (最近使用)
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return value
                else:
                    # 过期，删除
                    del self._cache[key]

            self._misses += 1
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值"""
        async with self._lock:
            expires_at = time.time() + ttl
            self._cache[key] = (value, expires_at)
            self._cache.move_to_end(key)

            # LRU 淘汰
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    async def delete(self, key: str) -> None:
        """删除缓存"""
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """清空所有缓存"""
        async with self._lock:
            self._cache.clear()

    @property
    def stats(self) -> dict:
        """缓存统计"""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self._hits / total * 100:.1f}%" if total > 0 else "N/A",
        }


# 全局缓存实例
_global_cache = MemoryCache(max_size=2000)


def get_cache() -> MemoryCache:
    """获取全局缓存实例"""
    return _global_cache


def _make_cache_key(prefix: str, *args, **kwargs) -> str:
    """生成缓存 key"""
    key_parts = [prefix]
    for arg in args:
        key_parts.append(str(arg))
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")
    raw = ":".join(key_parts)
    # 太长的 key 用 hash
    if len(raw) > 200:
        return f"{prefix}:{hashlib.md5(raw.encode()).hexdigest()}"
    return raw


def cached(prefix: str, ttl: int):
    """
    异步方法缓存装饰器

    用法：
        @cached("balance", ttl=30)
        async def get_balance(self, address: str) -> SolBalance:
            ...

    Args:
        prefix: 缓存 key 前缀
        ttl: 过期时间（秒）
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Wallet methods explicitly accept use_cache; a fresh API report bypasses every layer.
            use_cache = kwargs.get("use_cache", True)
            if type(use_cache) is not bool:
                raise TypeError("use_cache must be a bool")
            if not use_cache:
                return await func(*args, **kwargs)
            # 跳过 self 参数生成 key
            cache_args = args[1:] if args else args
            cache_kwargs = {k: v for k, v in kwargs.items() if k != "use_cache"}
            key = _make_cache_key(prefix, *cache_args, **cache_kwargs)

            cache = get_cache()
            result = await cache.get(key)
            if result is not None:
                logger.debug(f"缓存命中: {key}")
                return result

            result = await func(*args, **kwargs)

            if result is not None:
                await cache.set(key, result, ttl)

            return result

        # 暴露缓存清理方法
        wrapper.invalidate = lambda *a, **kw: get_cache().delete(
            _make_cache_key(prefix, *a, **{k: v for k, v in kw.items() if k != "use_cache"})
        )

        return wrapper

    return decorator
