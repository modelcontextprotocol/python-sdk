"""Asynchronous resource implementation for long-running operations."""

import asyncio
import enum
# import time
from typing import Any, Optional

import pydantic
from pydantic import Field

from mcp.server.fastmcp.resources.base import Resource
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class AsyncStatus(str, enum.Enum):
    """Status of an asynchronous operation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class AsyncResource(Resource):
    """A resource representing an asynchronous operation.
    
    This resource type is used to track long-running operations that are executed
    asynchronously. It provides methods for updating progress, completing with a result,
    failing with an error, and canceling the operation.
    """
    
    status: AsyncStatus = Field(
        default=AsyncStatus.PENDING,
        description="Current status of the asynchronous operation"
    )
    # progress: float = Field(
    #     default=0,
    #     description="Current progress value (0-100 or raw count)"
    # )
    error: Optional[str] = Field(
        default=None,
        description="Error message if the operation failed"
    )
    # created_at: float = Field(
    #     default_factory=time.time,
    #     description="Timestamp when the resource was created"
    # )
    # started_at: Optional[float] = Field(
    #     default=None,
    #     description="Timestamp when the operation started running"
    # )
    # completed_at: Optional[float] = Field(
    #     default=None,
    #     description="Timestamp when the operation completed, failed, or was canceled"
    # )
    
    # Fields not included in serialization
    _task: Optional[asyncio.Task[Any]] = pydantic.PrivateAttr(default=None)
    # _mcp_server = pydantic.PrivateAttr(default=None)
    
    # def set_mcp_server(self, server: Any) -> None:
    #     """Set the MCP server reference.

    #     Args:
    #         server: The MCP server instance
    #     """
    #     self._mcp_server = server
    
    async def read(self) -> str:
        """Read the current state of the resource as JSON.
        
        Returns the current status and progress information.
        """
        # Convert the resource to a dictionary, excluding private fields
        data = self.model_dump(exclude={"_task"})
        
        # Return status info as JSON
        import json
        return json.dumps(data, indent=2)
    
    async def start(self, task: asyncio.Task[Any]) -> None:
        """Mark the resource as running and store the task.
        
        Args:
            task: The asyncio task that is executing the operation
        """
        self._task = task
        self.status = AsyncStatus.RUNNING
        # self.started_at = time.time()
        # await self._notify_changed()
        
        logger.debug(
            "Started async operation",
            extra={
                "uri": self.uri,
            }
        )
    
    # async def update_progress(self, progress: float) -> None:
    #     """Update the progress information.
        
    #     Args:
    #         progress: Current progress value
    #         total: Total expected progress value, if known
    #     """
    #     self.progress = progress
    #     # await self._notify_changed()
        
    #     logger.debug(
    #         "Updated async operation progress",
    #         extra={
    #             "uri": self.uri,
    #             "progress": self.progress,
    #         }
    #     )
    
    async def complete(self) -> None:
        """Mark the resource as completed.
        """
        self.status = AsyncStatus.COMPLETED
        # self.completed_at = time.time()
            
        # await self._notify_changed()
        
        logger.info(
            "Completed async operation",
            extra={
                "uri": self.uri,
                # "duration": self.completed_at - (self.started_at or self.created_at),
            }
        )
    
    async def fail(self, error: str) -> None:
        """Mark the resource as failed and store the error.
        
        Args:
            error: Error message describing why the operation failed
        """
        self.status = AsyncStatus.FAILED
        self.error = error
        # self.completed_at = time.time()
        # await self._notify_changed()
        
        logger.error(
            "Failed async operation",
            extra={
                "uri": self.uri,
                "error": error,
                # "duration": self.completed_at - (self.started_at or self.created_at),
            }
        )
    
    async def cancel(self) -> None:
        """Cancel the operation if it's still running."""
        if self.status in (AsyncStatus.PENDING, AsyncStatus.RUNNING) and self._task:
            self._task.cancel()
            self.status = AsyncStatus.CANCELED
            # self.completed_at = time.time()
            # await self._notify_changed()
            
            logger.info(
                "Canceled async operation",
                extra={
                    "uri": self.uri,
                    # "duration": self.completed_at - (self.started_at or self.created_at),
                }
            )
    
    # async def _notify_changed(self) -> None:
    #     """Notify subscribers that the resource has changed."""
    #     if self._mcp_server:
    #         # This will be implemented in the MCP server to notify clients
    #         # of resource changes via the notification protocol
    #         self._mcp_server.notify_resource_changed(self.uri)