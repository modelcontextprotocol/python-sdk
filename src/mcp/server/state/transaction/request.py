from mcp.shared.message import ServerMessageMetadata
import mcp.types as types

from starlette.requests import Request
from mcp.server.fastmcp import Context
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.session import ServerSession

# Short Context alias (no dependency back to state-machine internals)
FastMCPContext = Context[ServerSession, LifespanResultT, Request]

async def prepare_transaction(
        ctx: FastMCPContext,
        transaction_id: str,
        payload: types.TransactionMessagePayload,
    ) -> types.TransactionResult:
        """Send a transaction/prepare request and return the result."""
        return await ctx.session.send_request(
            request=types.ServerRequest(
                types.TransactionPrepareRequest(
                    method="transaction/prepare",
                    params=types.TransactionPrepareRequestParams(
                                transactionId=transaction_id,
                                payload=payload
                            ),
                )
            ),
            result_type=types.TransactionResult,
            metadata=ServerMessageMetadata(related_request_id=ctx.request_id),
        )

async def commit_transaction(
        ctx: FastMCPContext,
        transaction_id: str,
    ) -> types.TransactionResult:
        """Send a transaction/commit request and return the result."""
        return await ctx.session.send_request(
            request=types.ServerRequest(
                types.TransactionCommitRequest(
                    method="transaction/commit",
                    params=types.TransactionCommitRequestParams(transactionId=transaction_id),
                )
            ),
            result_type=types.TransactionResult,
            metadata=ServerMessageMetadata(related_request_id=ctx.request_id),
        )    

async def abort_transaction(
        ctx: FastMCPContext,
        transaction_id: str,
    ) -> types.TransactionResult:
        """Send a transaction/abort request and return the result."""
        return await ctx.session.send_request(
            request=types.ServerRequest(
                types.TransactionAbortRequest(
                    method="transaction/abort",
                    params=types.TransactionAbortRequestParams(transactionId=transaction_id),
                )
            ),
            result_type=types.TransactionResult,
            metadata=ServerMessageMetadata(related_request_id=ctx.request_id),
        )    