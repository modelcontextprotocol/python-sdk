from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.inject_ctx import inject_context
from mcp.server.state.transaction.request import (
    prepare_transaction,
    commit_transaction,
    abort_transaction,
)
from mcp.server.state.transaction.types import (
    FastMCPContext,
    TransactionMessagePayload,
    TransactionPayloadProvider,
    TxKey,
)

logger = get_logger(__name__)


class TransactionManager:
    """Registry + execution for per-(state, kind, name) transactions.

    Registry:
      - Multiple providers per TxKey (order-preserving).

    Execution model:
      - For a given TxKey, `prepare_for` resolves each provider → payload (with optional context injection),
        sends transaction/prepare (with a deterministic tx_id derived from TxKey + request_id), and
        pushes the resulting tx_ids as a *batch* on a per-key stack.
      - `commit_for` pops the last batch and commits each tx_id in order.
      - `abort_for` pops the last batch and aborts each tx_id in order (best effort).
    """

    def __init__(self) -> None:
        self._by_key: Dict[TxKey, List[TransactionPayloadProvider]] = {}
        self._active: Dict[TxKey, List[List[str]]] = {}

    ### Registry

    def register(self, *, key: TxKey, provider: TransactionPayloadProvider) -> None:
        """Append a provider to the registry for this key (duplicates allowed)."""
        self._by_key.setdefault(key, []).append(provider)
        logger.debug("Transaction registered for key=%s", key)

    def lookup_all(self, key: TxKey) -> List[TransactionPayloadProvider]:
        """Return a copy of all providers for the key (may be empty)."""
        return list(self._by_key.get(key, []))

    ### Internal helpers

    def _derive_tx_id(self, ctx: FastMCPContext, key: TxKey, ordinal: int) -> str:
        """Stable, compact tx_id: blake2b(request_id|state|kind|name|ordinal)."""
        request_id = getattr(ctx, "request_id", None)
        if request_id is None:
            # Some contexts nest it; try a common fallback
            request_id = getattr(getattr(ctx, "request_context", None), "request_id", "no-rid")

        state, kind, name = key
        raw = f"{request_id}|{state}|{kind}|{name}|{ordinal}"
        h = hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()
        return f"tx_{h}"

    async def _resolve_payload(
        self, ctx: Optional[FastMCPContext], provider: TransactionPayloadProvider
    ) -> TransactionMessagePayload:
        """Provider → concrete payload; inject context if provider is callable."""
        if callable(provider):
            val = inject_context(provider, ctx)
            if hasattr(val, "__await__"):
                return await val  # type: ignore[return-value]
            return val  # type: ignore[return-value]
        return provider

    ### Execution

    async def prepare_for(self, key: TxKey, ctx: FastMCPContext) -> int:
        """Prepare all providers for this key; push tx_id batch on the per-key stack.

        Raises:
            RuntimeError: if any single prepare fails (best-effort abort of already prepared txs).
        """
        providers = self.lookup_all(key)
        if not providers:
            return 0

        batch_ids: List[str] = []
        try:
            for idx, prov in enumerate(providers, start=1):
                payload: TransactionMessagePayload = await self._resolve_payload(ctx, prov)

                # Derive an id deterministically from (ctx.request_id, TxKey, ordinal)
                derived_id = self._derive_tx_id(ctx, key, idx)

                # Ask the client to prepare. If the client returns its own id, prefer it.
                result = await prepare_transaction(ctx=ctx, transaction_id=derived_id, payload=payload)
                if not result.success or not result.transactionId:
                    raise RuntimeError(
                        f"transaction/prepare failed for key={key} (success={result.success}, "
                        f"transactionId={result.transactionId!r})"
                    )

                batch_ids.append(result.transactionId)

        except Exception as e:
            # Cleanup best-effort: abort any txs we already prepared in this batch
            for tx_id in reversed(batch_ids):
                try:
                    await abort_transaction(ctx=ctx, transaction_id=tx_id)
                except Exception as aerr:
                    logger.warning("Abort during prepare cleanup failed for key=%s (tx_id=%s): %s", key, tx_id, aerr)
            raise ValueError(e)

        if batch_ids:
            self._active.setdefault(key, []).append(batch_ids)

        logger.debug("Prepared %d transaction(s) for key=%s", len(batch_ids), key)
        return len(batch_ids)

    async def commit_for(self, key: TxKey, ctx: FastMCPContext) -> None:
        """Commit last batch for this key (LIFO)."""
        stack = self._active.get(key)
        if not stack:
            return
        batch = stack.pop()
        for tx_id in batch:
            result = await commit_transaction(ctx=ctx, transaction_id=tx_id)
            if not result.success:
                raise RuntimeError(f"transaction/commit failed for key={key} (tx_id={tx_id})")
        logger.debug("Committed %d transaction(s) for key=%s", len(batch), key)

    async def abort_for(self, key: TxKey, ctx: FastMCPContext) -> None:
        """Abort last batch for this key (best effort, LIFO)."""
        stack = self._active.get(key)
        if not stack:
            return
        batch = stack.pop()
        for tx_id in batch:
            try:
                result = await abort_transaction(ctx=ctx, transaction_id=tx_id)
                if not result.success:
                    logger.warning("transaction/abort returned success=False for key=%s (tx_id=%s)", key, tx_id)
            except Exception as e:
                logger.warning("Abort failed for key=%s (tx_id=%s): %s", key, tx_id, e)
        logger.debug("Aborted %d transaction(s) for key=%s", len(batch), key)
