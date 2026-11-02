"""Read-window freshness, local single-flight and Redis admission-checked publication."""

import asyncio
import copy
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .cache import cache_get_json
from .report_publication import publish_if_current

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
logger = logging.getLogger(__name__)


class ReportFreshnessError(Exception):
    """A report cannot be returned within the configured read-window policy."""


class ReportContext(BaseModel):
    schema_version: Literal[1] = 1
    freshness_scope: Literal["account-read-window"] = "account-read-window"
    source: Literal["rpc_read", "report_cache"]
    network: str
    commitment: Literal["confirmed"] = "confirmed"
    configured_source_id: str
    account_scope: Literal["native-sol+legacy-token"] = "native-sol+legacy-token"
    read_started_at_ms: str
    read_completed_at_ms: str
    served_at_ms: str
    age_ms: int = Field(ge=0, strict=True)
    max_age_ms: int = Field(gt=0, strict=True)
    joined_refresh: bool
    publication_status: Literal["published", "cache_hit", "skipped", "unknown"]


@dataclass(frozen=True)
class ReadScope:
    network: str
    rpc_endpoints: tuple[str, ...]

    @property
    def source_id(self):
        # Fingerprint the configured pool; never expose URLs that may contain credentials.
        value = [
            self.network,
            self.rpc_endpoints,
            "confirmed",
            TOKEN_PROGRAM,
            "native-sol+legacy-token",
            "quantity-v2",
            "identity-v1",
            "report-v1",
            "publication-v1",
        ]
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


class WalletReportCache:
    """Per-worker single-flight and conditional writes on one shared Redis primary."""

    def __init__(
        self,
        scope: ReadScope,
        max_age_ms=60000,
        read_timeout=20.0,
        clock_ms=None,
        cache_io_timeout=2.0,
    ):
        if type(max_age_ms) is not int or not 0 < max_age_ms <= 2**53 - 1:
            raise ValueError("max_age_ms must be a positive safe integer")
        if read_timeout <= 0 or cache_io_timeout <= 0:
            raise ValueError("read_timeout must be positive")
        self.scope = scope
        self.max_age_ms = max_age_ms
        self.read_timeout = read_timeout
        self.cache_io_timeout = cache_io_timeout
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._inflight = {}

    def cache_key(self, wallet):
        # Both script keys share a Redis Cluster hash tag.
        return f"assets:wallet:v5:{{{self.scope.source_id}:{self.max_age_ms}:{wallet}}}:report"

    def reservation_key(self, wallet):
        return self.cache_key(wallet).removesuffix(":report") + ":reservation"

    def _now(self):
        now = self.clock_ms()
        if type(now) is not int or not 0 <= now <= 2**64 - 1:
            raise ReportFreshnessError("clock is outside supported milliseconds")
        return now

    def _view(self, entry, source, joined=False):
        now = self._now()
        start, complete = entry["read_started_at_ms"], entry["read_completed_at_ms"]
        if not 0 <= start <= complete <= now or now - start >= self.max_age_ms:
            raise ReportFreshnessError("account read window expired or clock moved backwards")
        context = ReportContext(
            source=source,
            network=self.scope.network,
            configured_source_id=self.scope.source_id,
            read_started_at_ms=str(start),
            read_completed_at_ms=str(complete),
            served_at_ms=str(now),
            age_ms=now - start,
            max_age_ms=self.max_age_ms,
            joined_refresh=joined,
            publication_status=(
                "cache_hit"
                if source == "report_cache"
                else entry.get("_publication_status", "skipped")
            ),
        )
        return {**copy.deepcopy(entry["payload"]), "report_context": context.model_dump()}

    def _cached_entry(self, value, wallet, validate):
        try:
            if not isinstance(value, dict) or value.get("cache_schema") != 5:
                return None
            token = value.get("publication_token")
            if (
                not isinstance(token, str)
                or len(token) != 32
                or any(c not in "0123456789abcdef" for c in token)
            ):
                return None
            if (
                value.get("source_id") != self.scope.source_id
                or value.get("max_age_ms") != self.max_age_ms
            ):
                return None
            for name in ("read_started_at_ms", "read_completed_at_ms"):
                if type(value.get(name)) is not int or not 0 <= value[name] <= 2**64 - 1:
                    return None
            payload = validate(value["payload"])
            if payload["wallet_address"] != wallet:
                return None
            entry = {**value, "payload": payload}
            self._view(entry, "report_cache")
            return entry
        except (KeyError, TypeError, ValueError, ReportFreshnessError):
            return None

    async def _rebuild(self, redis, key, wallet, load, validate):
        token = uuid.uuid4().hex
        reservation_key = self.reservation_key(wallet)
        reserved = False
        try:
            reserved = bool(
                await asyncio.wait_for(
                    redis.set(reservation_key, token, px=self.max_age_ms + 1000),
                    timeout=self.cache_io_timeout,
                )
            )
        except Exception:
            # Without confirmed admission, return a read but never write a shared report.
            logger.warning("Report publication reservation unavailable")
        started = self._now()
        try:
            payload = await asyncio.wait_for(load(), timeout=self.read_timeout)
        except asyncio.TimeoutError as error:
            raise ReportFreshnessError("report read budget exceeded") from error
        completed = self._now()
        payload = validate(payload)
        if payload["wallet_address"] != wallet:
            raise ReportFreshnessError("report wallet does not match request")
        entry = {
            "cache_schema": 5,
            "publication_token": token if reserved else None,
            "source_id": self.scope.source_id,
            "max_age_ms": self.max_age_ms,
            "read_started_at_ms": started,
            "read_completed_at_ms": completed,
            "payload": copy.deepcopy(payload),
        }
        self._view(entry, "rpc_read")  # reject already-expired reads before publication
        remaining_ms = self.max_age_ms - (self._now() - started)
        if remaining_ms <= 0:
            raise ReportFreshnessError("report expired before publication")
        entry["_publication_status"] = "skipped"
        if reserved:
            payload_json = json.dumps(
                {k: v for k, v in entry.items() if not k.startswith("_")},
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            try:
                published = await asyncio.wait_for(
                    publish_if_current(
                        redis, reservation_key, key, token, payload_json, remaining_ms
                    ),
                    timeout=self.cache_io_timeout,
                )
            except Exception:
                # The script may have executed before a timeout/disconnect; do not claim success.
                logger.warning("Report publication outcome unknown")
                entry["_publication_status"] = "unknown"
            else:
                if published != 1:
                    raise ReportFreshnessError(
                        "report publication superseded or reservation expired; retry"
                    )
                entry["_publication_status"] = "published"
        return entry

    async def get(self, redis, wallet, load, validate, *, refresh=False):
        key = self.cache_key(wallet)
        task = self._inflight.get(key)
        cached = None
        if task is None and not refresh:
            try:
                stored = await asyncio.wait_for(
                    cache_get_json(redis, key), timeout=self.cache_io_timeout
                )
            except asyncio.TimeoutError:
                logger.warning("Report cache read timed out")
                stored = None
            cached = self._cached_entry(stored, wallet, validate)
            # A refresh may have begun while the Redis read was awaiting IO.
            task = self._inflight.get(key)
            if task is None and cached is not None:
                return self._view(cached, "report_cache")
        joined = task is not None
        if task is None:
            task = asyncio.create_task(self._rebuild(redis, key, wallet, load, validate))
            self._inflight[key] = task

            def finished(done):
                if self._inflight.get(key) is done:
                    self._inflight.pop(key)
                if not done.cancelled():
                    done.exception()  # consume unobserved failures if every waiter disconnected

            task.add_done_callback(finished)
        entry = await asyncio.shield(task)
        return self._view(entry, "rpc_read", joined)

    async def aclose(self):
        tasks = list(self._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()


_report_cache = None


def get_wallet_report_cache():
    global _report_cache
    if _report_cache is None:
        from blockchain.config import config

        from .config import settings

        _report_cache = WalletReportCache(
            ReadScope(config.NETWORK, tuple(config.RPC_ENDPOINTS)),
            max_age_ms=settings.CACHE_TTL_ASSETS * 1000,
            read_timeout=settings.REPORT_READ_TIMEOUT_SECONDS,
        )
    return _report_cache
