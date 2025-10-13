"""SQLite-based async operations example server."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import deque
from typing import Any

import anyio
import click
import uvicorn
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.server.session import ServerSession
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.async_operations import (
    AsyncOperationBroker,
    AsyncOperationStore,
    OperationEventQueue,
    PendingAsyncTask,
    ServerAsyncOperation,
    ServerAsyncOperationManager,
)
from mcp.shared.context import RequestContext, SerializableRequestContext
from mcp.types import AsyncOperationStatus, CallToolResult
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SQLiteAsyncOperationStore(AsyncOperationStore):
    """SQLite-based implementation of AsyncOperationStore."""

    def __init__(self, db_path: str = "async_operations.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS operations (
                    token TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    keep_alive INTEGER NOT NULL,
                    resolved_at REAL,
                    session_id TEXT,
                    result TEXT,
                    error TEXT
                )
            """)
            conn.commit()

    async def get_operation(self, token: str) -> ServerAsyncOperation | None:
        """Get operation by token."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM operations WHERE token = ?", (token,))
            row = cursor.fetchone()
            if not row:
                return None

            # Reconstruct CallToolResult from stored JSON
            result = None
            if row["result"]:
                result_data = json.loads(row["result"])
                result = CallToolResult(
                    content=result_data.get("content", []),
                    structuredContent=result_data.get("structuredContent"),
                    isError=result_data.get("isError", False),
                )

            return ServerAsyncOperation(
                token=row["token"],
                tool_name=row["tool_name"],
                arguments=json.loads(row["arguments"]),
                status=row["status"],
                created_at=row["created_at"],
                keep_alive=row["keep_alive"],
                resolved_at=row["resolved_at"],
                session_id=row["session_id"],
                result=result,
                error=row["error"],
            )

    async def store_operation(self, operation: ServerAsyncOperation) -> None:
        """Store an operation."""
        # Serialize result using Pydantic model_dump()
        result_json = None
        if operation.result:
            try:
                result_dict = operation.result.model_dump()
                result_json = json.dumps(result_dict)
            except (TypeError, ValueError):
                # Skip if not serializable
                result_json = None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO operations 
                (token, tool_name, arguments, status, created_at, keep_alive, 
                 resolved_at, session_id, result, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    operation.token,
                    operation.tool_name,
                    json.dumps(operation.arguments),
                    operation.status,
                    operation.created_at,
                    operation.keep_alive,
                    operation.resolved_at,
                    operation.session_id,
                    result_json,
                    operation.error,
                ),
            )
            conn.commit()

    async def update_status(self, token: str, status: AsyncOperationStatus) -> bool:
        """Update operation status."""
        operation = await self.get_operation(token)
        if not operation:
            return False

        # Don't allow transitions from terminal states
        if operation.is_terminal:
            return False

        resolved_at = time.time() if status in ("completed", "failed", "canceled") else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE operations 
                SET status = ?, resolved_at = ?
                WHERE token = ?
            """,
                (status, resolved_at, token),
            )
            conn.commit()

            return cursor.rowcount > 0

    async def complete_operation_with_result(self, token: str, result: CallToolResult) -> bool:
        """Complete operation with result."""
        operation = await self.get_operation(token)
        if not operation or operation.is_terminal:
            return False

        # Serialize result using Pydantic model_dump()
        result_json = None
        try:
            result_dict = result.model_dump()
            result_json = json.dumps(result_dict)
        except (TypeError, ValueError):
            # Skip if not serializable
            result_json = None

        resolved_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE operations 
                SET status = 'completed', result = ?, resolved_at = ?
                WHERE token = ?
            """,
                (result_json, resolved_at, token),
            )
            conn.commit()
            return cursor.rowcount > 0

    async def fail_operation_with_error(self, token: str, error: str) -> bool:
        """Fail operation with error."""
        operation = await self.get_operation(token)
        if not operation or operation.is_terminal:
            return False

        resolved_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE operations 
                SET status = 'failed', error = ?, resolved_at = ?
                WHERE token = ?
            """,
                (error, resolved_at, token),
            )
            conn.commit()
            return cursor.rowcount > 0

    async def cleanup_expired(self) -> int:
        """Remove expired operations and return count."""
        current_time = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM operations 
                WHERE resolved_at IS NOT NULL 
                AND (resolved_at + keep_alive) < ?
            """,
                (current_time,),
            )
            conn.commit()
            return cursor.rowcount


class SQLiteOperationEventQueue(OperationEventQueue):
    """SQLite-based implementation of OperationEventQueue for operation-specific event delivery."""

    def __init__(self, db_path: str = "async_operations.db", table_name: str = "operation_events"):
        self.db_path = db_path
        self.table_name = table_name
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database for operation event queuing."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_token TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_operation_events_token_created 
                ON {self.table_name}(operation_token, created_at)
            """)
            conn.commit()

    async def enqueue_event(self, operation_token: str, message: types.JSONRPCMessage) -> None:
        """Enqueue an event for a specific operation token."""
        message_json = json.dumps(message.model_dump())
        created_at = time.time()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                INSERT INTO {self.table_name} (operation_token, message, created_at)
                VALUES (?, ?, ?)
            """,
                (operation_token, message_json, created_at),
            )
            conn.commit()

    async def dequeue_events(self, operation_token: str) -> list[types.JSONRPCMessage]:
        """Dequeue all pending events for a specific operation token."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get all events for this operation token
            cursor = conn.execute(
                f"""
                SELECT id, message FROM {self.table_name} 
                WHERE operation_token = ?
                ORDER BY created_at
            """,
                (operation_token,),
            )

            events: list[types.JSONRPCMessage] = []
            event_ids: list[int] = []

            for row in cursor:
                event_ids.append(row["id"])
                message_data = json.loads(row["message"])
                message = types.JSONRPCMessage.model_validate(message_data)
                events.append(message)

            # Delete the dequeued events
            if event_ids:
                placeholders = ",".join("?" * len(event_ids))
                conn.execute(f"DELETE FROM {self.table_name} WHERE id IN ({placeholders})", event_ids)
                conn.commit()

            return events


class SQLiteAsyncOperationBroker(AsyncOperationBroker):
    """SQLite-based implementation of AsyncOperationBroker for persistent task queuing."""

    def __init__(self, db_path: str = "async_operations.db"):
        self.db_path = db_path
        self._task_queue: deque[PendingAsyncTask] = deque()
        self._init_db()
        # Load persisted tasks on startup
        self._load_persisted_tasks_sync()

    def _load_persisted_tasks_sync(self):
        """Load persisted tasks from SQLite on startup (sync version for __init__)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT token, tool_name, arguments, request_id, operation_token, meta, supports_async
                FROM pending_tasks ORDER BY created_at
            """)
            for row in cursor.fetchall():
                # Check if operation is already terminal - don't queue if so
                with sqlite3.connect(self.db_path) as op_conn:
                    op_conn.row_factory = sqlite3.Row
                    op_cursor = op_conn.execute("SELECT status FROM operations WHERE token = ?", (row["token"],))
                    op_row = op_cursor.fetchone()
                    if op_row and op_row["status"] in ("completed", "failed", "canceled"):
                        continue

                # Reconstruct context - the server will hydrate the session
                request_context = SerializableRequestContext(
                    request_id=row["request_id"],
                    operation_token=row["operation_token"],
                    meta=json.loads(row["meta"]) if row["meta"] else None,
                    supports_async=bool(row["supports_async"]),
                )

                task = PendingAsyncTask(
                    token=row["token"],
                    tool_name=row["tool_name"],
                    arguments=json.loads(row["arguments"]),
                    request_context=request_context,
                )
                self._task_queue.append(task)

    def _init_db(self):
        """Initialize the SQLite database for pending tasks."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_tasks (
                    token TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    request_id TEXT,
                    operation_token TEXT,
                    meta TEXT,
                    request_data TEXT,
                    supports_async INTEGER DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            conn.commit()

    async def enqueue_task(
        self,
        token: str,
        tool_name: str,
        arguments: dict[str, Any],
        request_context: RequestContext[ServerSession, Any, Any],
    ) -> None:
        """Enqueue a task for execution and persist to SQLite."""
        # Store in memory queue for immediate processing
        task = PendingAsyncTask(token=token, tool_name=tool_name, arguments=arguments, request_context=request_context)
        self._task_queue.append(task)

        # Extract serializable parts for persistence
        serializable = request_context.to_serializable()
        request_id = serializable.request_id
        operation_token = serializable.operation_token
        supports_async = serializable.supports_async
        meta = json.dumps(serializable.meta.model_dump()) if serializable.meta else None

        # Persist to SQLite for restart recovery
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pending_tasks 
                (token, tool_name, arguments, request_id, operation_token, meta, 
                 supports_async, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    token,
                    tool_name,
                    json.dumps(arguments),
                    request_id,
                    operation_token,
                    meta,
                    int(supports_async),
                    time.time(),
                ),
            )
            conn.commit()

    async def get_pending_tasks(self) -> list[PendingAsyncTask]:
        """Get all pending tasks without clearing them."""
        return list(self._task_queue)

    async def acknowledge_task(self, token: str) -> None:
        """Acknowledge that a task has been dispatched (but keep it in SQLite until completion)."""
        # Remove from memory queue only - keep in SQLite until operation completes
        self._task_queue = deque(task for task in self._task_queue if task.token != token)

    async def complete_task(self, token: str) -> None:
        """Remove a completed task from persistent storage."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM pending_tasks WHERE token = ?", (token,))
            conn.commit()


class UserPreferences(BaseModel):
    continue_processing: bool = Field(description="Should we continue with the operation?")


@click.command()
@click.option("--port", default=8000, help="Port to listen on for HTTP")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="Transport type",
)
@click.option("--db-path", default="async_operations.db", help="SQLite database path")
def main(port: int, transport: str, db_path: str):
    """Run the SQLite async operations example server."""
    # Create components with specified database path
    operation_request_queue = SQLiteOperationEventQueue(db_path, "operation_requests")
    operation_response_queue = SQLiteOperationEventQueue(db_path, "operation_responses")
    broker = SQLiteAsyncOperationBroker(db_path)
    store = SQLiteAsyncOperationStore(db_path)
    manager = ServerAsyncOperationManager(
        store=store,
        broker=broker,
        operation_request_queue=operation_request_queue,
        operation_response_queue=operation_response_queue,
    )
    mcp = FastMCP(
        "SQLite Async Operations Demo",
        async_operations=manager,
    )

    @mcp.tool(invocation_modes=["async"])
    async def fetch_website(
        url: str,
        ctx: Context[ServerSession, None],
    ) -> list[types.ContentBlock]:
        headers = {"User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"}
        async with create_mcp_http_client(headers=headers) as client:
            logger.info("Entered fetch_website")

            # Simulate delay
            await anyio.sleep(10)

            # Request approval from user
            logger.info("Sending elicitation to confirm")
            result = await ctx.elicit(
                message=f"Please confirm that you would like to fetch from {url}.",
                schema=UserPreferences,
            )
            logger.info(f"Elicitation result: {result}")

            if result.action != "accept" or not result.data.continue_processing:
                return [types.TextContent(type="text", text="Operation cancelled by user")]

            logger.info(f"Fetching {url}")
            response = await client.get(url)
            response.raise_for_status()
            logger.info("Returning fetch result")
            return [types.TextContent(type="text", text=response.text)]

    logger.info(f"Starting server with SQLite database: {db_path}")
    logger.info("Pending tasks will be automatically restarted on server restart!")

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        app = mcp.streamable_http_app()
        server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="error"))
        logger.info(f"Starting {transport} server on port {port}")
        server.run()
    else:
        raise ValueError(f"Invalid transport for test server: {transport}")
