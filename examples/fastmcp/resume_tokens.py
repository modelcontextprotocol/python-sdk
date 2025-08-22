# resume_tokens.py
"""MCP Server demonstrating resume tokens."""

import logging
import asyncio
import uuid
from typing import Dict, Optional, Any, List
from pydantic import BaseModel

from mcp.server import fastmcp

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OrderData(BaseModel):
    total_amount: float

class OrderResult(BaseModel):
    order_id: str
    total_amount: float

class OrderProgress(BaseModel):
    order_id: str
    status: str
    progress_percentage: int
    current_step: str
    result: Optional[OrderResult] = None
    error: Optional[str] = None

# Global steps definition
ORDER_STEPS: List[OrderProgress] = [
    OrderProgress(order_id="", status="processing", progress_percentage=15, current_step="Validating order data"),
    OrderProgress(order_id="", status="processing", progress_percentage=30, current_step="Checking inventory"),
    OrderProgress(order_id="", status="processing", progress_percentage=50, current_step="Processing payment"),
    OrderProgress(order_id="", status="processing", progress_percentage=70, current_step="Allocating resources"),
    OrderProgress(order_id="", status="processing", progress_percentage=85, current_step="Preparing shipment"),
    OrderProgress(order_id="", status="completed", progress_percentage=100, current_step="Finalizing order")
]

# Global storage for order operations (in production, use proper database/cache)
order_operations: Dict[str, OrderProgress] = {}

# Map resume tokens to order IDs
resume_token_to_order_id: Dict[str, str] = {}
order_id_to_latest_token: Dict[str, str] = {}
# Store original order data for validation
order_id_to_order_data: Dict[str, OrderData] = {}

# --- MCP Server Setup ---
mcp = fastmcp.FastMCP("OrderCreation", port=8090, stateless_http=True)


# --- Async Order Creation Workflow ---
async def fake_order_creation_workflow(order_id: str, order_data: OrderData) -> None:
    """
    Simulated async order creation workflow using global steps.
    Each step takes 10 seconds.
    """
    for step in ORDER_STEPS:
        # Update progress
        order_operations[order_id].status = step.status
        order_operations[order_id].progress_percentage = step.progress_percentage
        order_operations[order_id].current_step = step.current_step
        
        # Set result if this is the completion step
        if step.status == "completed":
            order_operations[order_id].result = OrderResult(
                order_id=order_id,
                total_amount=order_data.total_amount
            )
        
        logger.info(f"Order {order_id}: {step.current_step} ({step.progress_percentage}%)")
        
        # Wait 10 seconds for each step
        await asyncio.sleep(10)


def start_order_creation(order_data: OrderData) -> str:
    """Start a new order creation process and return the order ID."""
    order_id = str(uuid.uuid4())
    
    # Initialize progress tracking
    progress = OrderProgress(
        order_id=order_id,
        status="started",
        progress_percentage=0,
        current_step="Initializing order creation"
    )
    
    # Store in global storage
    order_operations[order_id] = progress
    order_id_to_order_data[order_id] = order_data
    
    # Start the async workflow in a new task
    asyncio.create_task(fake_order_creation_workflow(order_id, order_data))
    
    return order_id


def generate_new_resume_token(order_id: str) -> str:
    """Generate a new resume token for an order and update mappings."""
    new_token = str(uuid.uuid4())
    
    # Clean up old token mapping if exists
    old_token = order_id_to_latest_token.get(order_id)
    if old_token and old_token in resume_token_to_order_id:
        del resume_token_to_order_id[old_token]
    
    # Set up new mapping
    resume_token_to_order_id[new_token] = order_id
    order_id_to_latest_token[order_id] = new_token
    
    return new_token

# --- Tool Definitions ---
@mcp.tool(
    name="create_order",
    description="Create an order in the database. Can start a new order or check status with resume token.",
)
def create_order(order_data: Optional[dict] = None, resume_token: Optional[str] = None) -> dict:
    """
    Create an order in the database or check status of existing order.
    
    Args:
        order_data: Dictionary containing order information (required for new orders)
        resume_token: UUID token to check status of existing order (optional)
    
    Returns:
        Dictionary with order status and optional resume token
    """
    if resume_token:
        # Get order ID from resume token
        order_id = resume_token_to_order_id.get(resume_token)
        
        # Validate order data if provided
        if order_data:
            current_order_data = OrderData(**order_data)
            original_order_data = order_id_to_order_data.get(order_id)
            
            if original_order_data and current_order_data.model_dump_json() != original_order_data.model_dump_json():
                return {
                    "error": "Order data mismatch. The provided order data does not match the original request.",
                    "order_id": order_id,
                }
    
    else:
        # Create new order
        order_data_model = OrderData(**order_data) if order_data else OrderData(total_amount=0.0, items=[])
        order_id = start_order_creation(order_data_model)
        
    # Get progress and convert to dict
    progress = order_operations[order_id]
    result = progress.model_dump()
    
    # Add resume token if still in progress
    if progress.status in ["started", "processing"]:
        result["next_resume_token"] = generate_new_resume_token(order_id)
        
    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
