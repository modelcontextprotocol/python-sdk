from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from mcp.server.session import ServerSession
from mcp.types import (
    CheckpointCreateParams,
    CheckpointCreateResult,
    CheckpointValidateParams,
    CheckpointValidateResult,
    CheckpointResumeParams,
    CheckpointResumeResult,
    CheckpointDeleteParams,
    CheckpointDeleteResult,
)


@runtime_checkable
class CheckpointBackend(Protocol):
    """Backend that actually stores and restores state behind handles."""

    async def create_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointCreateParams,
    ) -> CheckpointCreateResult: ...

    async def validate_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointValidateParams,
    ) -> CheckpointValidateResult: ...

    async def resume_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointResumeParams,
    ) -> CheckpointResumeResult: ...

    async def delete_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointDeleteParams,
    ) -> CheckpointDeleteResult: ...


@dataclass
class InMemoryHandleEntry:
    value: object
    digest: str
    expires_at: float


class InMemoryCheckpointBackend(CheckpointBackend):
    """Simple in-memory backend you can use for tests/POC.

    This is intentionally generic; concrete servers (data, browser, etc.)
    decide *what* `value` is and how to interpret it.
    """

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl = ttl_seconds
        self._handles: dict[str, InMemoryHandleEntry] = {}

    def _now(self) -> float:
        return time.time()

    async def create_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointCreateParams,
    ) -> CheckpointCreateResult:
        # session.fastmcp or session.server can expose some "current state"
        # For now you can override this backend in your server and implement
        # your own snapshot logic.
        raise NotImplementedError(
            "Subclass InMemoryCheckpointBackend and override create_checkpoint "
            "to capture concrete state (e.g. data tables, browser session)."
        )

    async def validate_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointValidateParams,
    ) -> CheckpointValidateResult:
        entry = self._handles.get(params.handle)
        if not entry:
            return CheckpointValidateResult(
                valid=False,
                remainingTtlSeconds=0,
                digestMatch=False,
            )

        now = self._now()
        if now >= entry.expires_at:
            return CheckpointValidateResult(
                valid=False,
                remainingTtlSeconds=0,
                digestMatch=params.expectedDigest == entry.digest,
            )

        remaining = int(entry.expires_at - now)
        return CheckpointValidateResult(
            valid=True,
            remainingTtlSeconds=remaining,
            digestMatch=(
                params.expectedDigest is None
                or params.expectedDigest == entry.digest
            ),
        )

    async def resume_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointResumeParams,
    ) -> CheckpointResumeResult:
        entry = self._handles.get(params.handle)
        if not entry:
            # You’ll map this to HANDLE_NOT_FOUND at JSON-RPC level
            return CheckpointResumeResult(resumed=False, handle=params.handle)

        if self._now() >= entry.expires_at:
            # Map to EXPIRED
            return CheckpointResumeResult(resumed=False, handle=params.handle)

        # Subclasses should take `entry.value` and rehydrate into session state.
        raise NotImplementedError(
            "Subclass InMemoryCheckpointBackend.resume_checkpoint to rehydrate "
            "concrete session state from stored value."
        )

    async def delete_checkpoint(
        self,
        session: ServerSession,
        params: CheckpointDeleteParams,
    ) -> CheckpointDeleteResult:
        deleted = params.handle in self._handles
        self._handles.pop(params.handle, None)
        return CheckpointDeleteResult(deleted=deleted)