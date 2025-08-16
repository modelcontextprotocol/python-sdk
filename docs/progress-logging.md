# Progress & logging

Learn how to implement comprehensive logging and progress reporting in your MCP servers to provide users with real-time feedback and debugging information.

## Logging basics

### Log levels and usage

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Logging Example")

@mcp.tool()
async def demonstrate_logging(operation: str, ctx: Context[ServerSession, None]) -> str:
    """Demonstrate different logging levels."""
    
    # Debug: Detailed information for debugging
    await ctx.debug(f"Starting operation: {operation}")
    await ctx.debug("Initializing operation parameters")
    
    # Info: General information about operation progress
    await ctx.info(f"Processing operation: {operation}")
    
    # Warning: Something unexpected but not critical
    if operation == "risky_operation":
        await ctx.warning("This operation has known limitations")
    
    # Error: Something went wrong
    if operation == "failing_operation":
        await ctx.error("Operation failed due to invalid input")
        raise ValueError("Operation not supported")
    
    await ctx.info(f"Operation '{operation}' completed successfully")
    return f"Completed: {operation}"

@mcp.tool()
async def structured_logging(
    data: dict,
    ctx: Context[ServerSession, None]
) -> dict:
    """Example of structured logging with context."""
    
    operation_id = f"op_{hash(str(data)) % 10000:04d}"
    
    await ctx.info(f"[{operation_id}] Starting data processing")
    await ctx.debug(f"[{operation_id}] Input data: {len(data)} fields")
    
    try:
        # Simulate processing
        processed_count = 0
        for key, value in data.items():
            await ctx.debug(f"[{operation_id}] Processing field: {key}")
            processed_count += 1
        
        await ctx.info(f"[{operation_id}] Processed {processed_count} fields successfully")
        
        return {
            "operation_id": operation_id,
            "status": "success",
            "processed_fields": processed_count
        }
        
    except Exception as e:
        await ctx.error(f"[{operation_id}] Processing failed: {e}")
        raise
```

## Progress reporting

### Basic progress updates

```python
import asyncio

@mcp.tool()
async def long_running_task(
    total_steps: int,
    ctx: Context[ServerSession, None]
) -> str:
    """Demonstrate basic progress reporting."""
    
    await ctx.info(f"Starting task with {total_steps} steps")
    
    for i in range(total_steps):
        # Simulate work
        await asyncio.sleep(0.1)
        
        # Calculate progress
        progress = (i + 1) / total_steps
        
        # Report progress
        await ctx.report_progress(
            progress=progress,
            total=1.0,
            message=f"Completed step {i + 1} of {total_steps}"
        )
        
        await ctx.debug(f"Step {i + 1} completed")
    
    await ctx.info("All steps completed")
    return f"Successfully completed {total_steps} steps"

@mcp.tool()
async def detailed_progress_task(
    phases: list[str],
    ctx: Context[ServerSession, None]
) -> dict:
    """Multi-phase task with detailed progress reporting."""
    
    total_phases = len(phases)
    await ctx.info(f"Starting multi-phase task: {total_phases} phases")
    
    results = {}
    
    for phase_idx, phase_name in enumerate(phases):
        await ctx.info(f"Starting phase {phase_idx + 1}/{total_phases}: {phase_name}")
        
        # Simulate phase work with sub-progress
        phase_steps = 5  # Each phase has 5 steps
        
        for step in range(phase_steps):
            # Simulate step work
            await asyncio.sleep(0.05)
            
            # Calculate overall progress
            completed_phases = phase_idx
            phase_progress = (step + 1) / phase_steps
            overall_progress = (completed_phases + phase_progress) / total_phases
            
            # Report progress with detailed message
            await ctx.report_progress(
                progress=overall_progress,
                total=1.0,
                message=f"Phase {phase_idx + 1}/{total_phases} ({phase_name}): Step {step + 1}/{phase_steps}"
            )
            
            await ctx.debug(f"Phase '{phase_name}' step {step + 1} completed")
        
        results[phase_name] = f"Completed in {phase_steps} steps"
        await ctx.info(f"Phase '{phase_name}' completed")
    
    await ctx.info("All phases completed successfully")
    
    return {
        "status": "completed",
        "phases": results,
        "total_phases": total_phases
    }
```

### Advanced progress patterns

```python
from typing import Callable, Awaitable

async def progress_wrapper(
    tasks: list[Callable[[], Awaitable[any]]],
    task_names: list[str],
    ctx: Context[ServerSession, None]
) -> list[any]:
    """Execute multiple tasks with combined progress reporting."""
    
    if len(tasks) != len(task_names):
        raise ValueError("Tasks and names lists must have same length")
    
    await ctx.info(f"Executing {len(tasks)} tasks with progress tracking")
    
    results = []
    total_tasks = len(tasks)
    
    for i, (task, name) in enumerate(zip(tasks, task_names)):
        await ctx.info(f"Starting task {i + 1}/{total_tasks}: {name}")
        
        try:
            # Execute task
            result = await task()
            results.append(result)
            
            # Report completion
            progress = (i + 1) / total_tasks
            await ctx.report_progress(
                progress=progress,
                total=1.0,
                message=f"Completed {i + 1}/{total_tasks}: {name}"
            )
            
            await ctx.info(f"Task '{name}' completed successfully")
            
        except Exception as e:
            await ctx.error(f"Task '{name}' failed: {e}")
            results.append(None)
            
            # Continue with next task
            progress = (i + 1) / total_tasks
            await ctx.report_progress(
                progress=progress,
                total=1.0,
                message=f"Failed {i + 1}/{total_tasks}: {name} (continuing...)"
            )
    
    successful_tasks = sum(1 for r in results if r is not None)
    await ctx.info(f"Completed {successful_tasks}/{total_tasks} tasks successfully")
    
    return results

@mcp.tool()
async def batch_processing(
    items: list[str],
    ctx: Context[ServerSession, None]
) -> dict:
    """Process items in batches with progress reporting."""
    
    batch_size = 3
    total_items = len(items)
    batches = [items[i:i + batch_size] for i in range(0, total_items, batch_size)]
    total_batches = len(batches)
    
    await ctx.info(f"Processing {total_items} items in {total_batches} batches")
    
    processed_items = []
    failed_items = []
    
    for batch_idx, batch in enumerate(batches):
        await ctx.info(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch)} items)\")\n        \n        for item_idx, item in enumerate(batch):\n            try:\n                # Simulate item processing\n                await asyncio.sleep(0.1)\n                processed_items.append(f\"processed_{item}\")\n                \n                # Calculate detailed progress\n                items_completed = len(processed_items) + len(failed_items)\n                progress = items_completed / total_items\n                \n                await ctx.report_progress(\n                    progress=progress,\n                    total=1.0,\n                    message=f\"Batch {batch_idx + 1}/{total_batches}, Item {item_idx + 1}/{len(batch)}: {item}\"\n                )\n                \n                await ctx.debug(f\"Successfully processed item: {item}\")\n                \n            except Exception as e:\n                await ctx.warning(f\"Failed to process item '{item}': {e}\")\n                failed_items.append(item)\n        \n        await ctx.info(f\"Batch {batch_idx + 1} completed\")\n    \n    await ctx.info(f\"Processing complete: {len(processed_items)} successful, {len(failed_items)} failed\")\n    \n    return {\n        \"total_items\": total_items,\n        \"processed_count\": len(processed_items),\n        \"failed_count\": len(failed_items),\n        \"processed_items\": processed_items,\n        \"failed_items\": failed_items\n    }\n```\n\n## Custom logging patterns\n\n### Contextual logging\n\n```python\nfrom dataclasses import dataclass\nfrom datetime import datetime\n\n@dataclass\nclass LogContext:\n    \"\"\"Context information for enhanced logging.\"\"\"\n    user_id: str | None = None\n    session_id: str | None = None\n    operation_id: str | None = None\n    timestamp: datetime | None = None\n\nclass EnhancedLogger:\n    \"\"\"Enhanced logger with context management.\"\"\"\n    \n    def __init__(self, ctx: Context):\n        self.ctx = ctx\n        self.log_context = LogContext()\n    \n    def set_context(self, **kwargs):\n        \"\"\"Update logging context.\"\"\"\n        for key, value in kwargs.items():\n            if hasattr(self.log_context, key):\n                setattr(self.log_context, key, value)\n    \n    async def log_with_context(self, level: str, message: str):\n        \"\"\"Log message with context information.\"\"\"\n        context_parts = []\n        \n        if self.log_context.user_id:\n            context_parts.append(f\"user:{self.log_context.user_id}\")\n        if self.log_context.session_id:\n            context_parts.append(f\"session:{self.log_context.session_id}\")\n        if self.log_context.operation_id:\n            context_parts.append(f\"op:{self.log_context.operation_id}\")\n        \n        context_str = \"[\" + \",\".join(context_parts) + \"]\" if context_parts else \"\"\n        full_message = f\"{context_str} {message}\" if context_str else message\n        \n        # Use appropriate log level\n        if level == \"debug\":\n            await self.ctx.debug(full_message)\n        elif level == \"info\":\n            await self.ctx.info(full_message)\n        elif level == \"warning\":\n            await self.ctx.warning(full_message)\n        elif level == \"error\":\n            await self.ctx.error(full_message)\n        else:\n            await self.ctx.log(level, full_message)\n\n@mcp.tool()\nasync def contextual_operation(\n    user_id: str,\n    data: dict,\n    ctx: Context[ServerSession, None]\n) -> dict:\n    \"\"\"Operation with contextual logging.\"\"\"\n    \n    # Set up enhanced logger\n    logger = EnhancedLogger(ctx)\n    logger.set_context(\n        user_id=user_id,\n        session_id=ctx.request_id[:8],\n        operation_id=f\"ctx_op_{hash(user_id) % 1000:03d}\",\n        timestamp=datetime.now()\n    )\n    \n    await logger.log_with_context(\"info\", \"Starting contextual operation\")\n    \n    try:\n        # Process data with contextual logging\n        await logger.log_with_context(\"debug\", f\"Processing {len(data)} data fields\")\n        \n        processed_data = {}\n        for key, value in data.items():\n            await logger.log_with_context(\"debug\", f\"Processing field: {key}\")\n            processed_data[key] = f\"processed_{value}\"\n        \n        await logger.log_with_context(\"info\", \"Operation completed successfully\")\n        \n        return {\n            \"status\": \"success\",\n            \"user_id\": user_id,\n            \"processed_fields\": len(processed_data),\n            \"operation_id\": logger.log_context.operation_id\n        }\n        \n    except Exception as e:\n        await logger.log_with_context(\"error\", f\"Operation failed: {e}\")\n        raise\n```\n\n### Performance logging\n\n```python\nimport time\nfrom functools import wraps\n\ndef performance_logged(func):\n    \"\"\"Decorator to add performance logging to tools.\"\"\"\n    \n    @wraps(func)\n    async def wrapper(*args, **kwargs):\n        # Find context in arguments\n        ctx = None\n        for arg in args:\n            if isinstance(arg, Context):\n                ctx = arg\n                break\n        \n        if not ctx:\n            return await func(*args, **kwargs)\n        \n        # Start timing\n        start_time = time.time()\n        function_name = func.__name__\n        \n        await ctx.info(f\"[PERF] Starting {function_name}\")\n        await ctx.debug(f\"[PERF] {function_name} called with {len(args)} args\")\n        \n        try:\n            result = await func(*args, **kwargs)\n            \n            # Log success with timing\n            duration = time.time() - start_time\n            await ctx.info(f\"[PERF] {function_name} completed in {duration:.3f}s\")\n            \n            if duration > 5.0:  # Warn about slow operations\n                await ctx.warning(f\"[PERF] Slow operation detected: {function_name} took {duration:.3f}s\")\n            \n            return result\n            \n        except Exception as e:\n            # Log failure with timing\n            duration = time.time() - start_time\n            await ctx.error(f\"[PERF] {function_name} failed after {duration:.3f}s: {e}\")\n            raise\n    \n    return wrapper\n\n@mcp.tool()\n@performance_logged\nasync def performance_monitored_task(\n    complexity: str,\n    ctx: Context[ServerSession, None]\n) -> dict:\n    \"\"\"Task with automatic performance monitoring.\"\"\"\n    \n    # Simulate different complexity levels\n    if complexity == \"light\":\n        await asyncio.sleep(0.1)\n        operations = 10\n    elif complexity == \"medium\":\n        await asyncio.sleep(1.0)\n        operations = 100\n    elif complexity == \"heavy\":\n        await asyncio.sleep(3.0)\n        operations = 1000\n    else:\n        await asyncio.sleep(0.05)\n        operations = 5\n    \n    return {\n        \"complexity\": complexity,\n        \"operations_performed\": operations,\n        \"status\": \"completed\"\n    }\n```\n\n## Error logging and debugging\n\n### Comprehensive error handling\n\n```python\nimport traceback\nfrom typing import Any\n\n@mcp.tool()\nasync def robust_operation(\n    operation_type: str,\n    parameters: dict[str, Any],\n    ctx: Context[ServerSession, None]\n) -> dict:\n    \"\"\"Operation with comprehensive error logging.\"\"\"\n    \n    operation_id = f\"rob_{hash(operation_type) % 1000:03d}\"\n    \n    await ctx.info(f\"[{operation_id}] Starting robust operation: {operation_type}\")\n    await ctx.debug(f\"[{operation_id}] Parameters: {parameters}\")\n    \n    try:\n        # Validate parameters\n        if not isinstance(parameters, dict):\n            raise ValueError(\"Parameters must be a dictionary\")\n        \n        await ctx.debug(f\"[{operation_id}] Parameter validation passed\")\n        \n        # Simulate operation based on type\n        if operation_type == \"process_data\":\n            if \"data\" not in parameters:\n                raise KeyError(\"Missing required parameter: data\")\n            \n            data = parameters[\"data\"]\n            await ctx.info(f\"[{operation_id}] Processing {len(data) if hasattr(data, '__len__') else 'unknown size'} data\")\n            \n            # Simulate processing with potential failures\n            if data == \"invalid_data\":\n                raise ValueError(\"Invalid data format detected\")\n            \n            result = f\"Processed: {data}\"\n            \n        elif operation_type == \"network_call\":\n            url = parameters.get(\"url\")\n            if not url:\n                raise ValueError(\"URL parameter required for network_call\")\n            \n            await ctx.info(f\"[{operation_id}] Making network call to: {url}\")\n            \n            # Simulate network issues\n            if \"error\" in url:\n                raise ConnectionError(f\"Failed to connect to {url}\")\n            \n            result = f\"Response from {url}\"\n            \n        else:\n            raise NotImplementedError(f\"Operation type '{operation_type}' not supported\")\n        \n        await ctx.info(f\"[{operation_id}] Operation completed successfully\")\n        \n        return {\n            \"operation_id\": operation_id,\n            \"status\": \"success\",\n            \"result\": result,\n            \"operation_type\": operation_type\n        }\n        \n    except KeyError as e:\n        await ctx.error(f\"[{operation_id}] Missing parameter: {e}\")\n        await ctx.debug(f\"[{operation_id}] Available parameters: {list(parameters.keys())}\")\n        \n        return {\n            \"operation_id\": operation_id,\n            \"status\": \"error\",\n            \"error_type\": \"missing_parameter\",\n            \"error_message\": str(e)\n        }\n        \n    except ValueError as e:\n        await ctx.error(f\"[{operation_id}] Invalid parameter value: {e}\")\n        await ctx.debug(f\"[{operation_id}] Parameter validation failed\")\n        \n        return {\n            \"operation_id\": operation_id,\n            \"status\": \"error\",\n            \"error_type\": \"invalid_parameter\",\n            \"error_message\": str(e)\n        }\n        \n    except Exception as e:\n        # Log full exception details\n        await ctx.error(f\"[{operation_id}] Unexpected error: {e}\")\n        await ctx.debug(f\"[{operation_id}] Full traceback: {traceback.format_exc()}\")\n        \n        return {\n            \"operation_id\": operation_id,\n            \"status\": \"error\",\n            \"error_type\": \"unexpected_error\",\n            \"error_message\": str(e)\n        }\n```\n\n## Notifications and resource updates\n\n### Resource change notifications\n\n```python\n@mcp.resource(\"status://{service}\")\ndef get_service_status(service: str) -> str:\n    \"\"\"Get status of a service.\"\"\"\n    # Simulate service status\n    statuses = {\n        \"database\": \"operational\",\n        \"api\": \"degraded\",\n        \"cache\": \"maintenance\"\n    }\n    return f\"Service '{service}' status: {statuses.get(service, 'unknown')}\"\n\n@mcp.tool()\nasync def update_service_status(\n    service: str,\n    new_status: str,\n    ctx: Context[ServerSession, None]\n) -> dict:\n    \"\"\"Update service status and notify clients.\"\"\"\n    \n    await ctx.info(f\"Updating {service} status to: {new_status}\")\n    \n    # Update status (in a real app, this would update a database)\n    # statuses[service] = new_status\n    \n    # Notify clients about the resource change\n    resource_uri = f\"status://{service}\"\n    await ctx.session.send_resource_updated(resource_uri)\n    \n    await ctx.info(f\"Status update notification sent for {service}\")\n    \n    return {\n        \"service\": service,\n        \"new_status\": new_status,\n        \"notification_sent\": True\n    }\n\n@mcp.tool()\nasync def bulk_status_update(\n    updates: dict[str, str],\n    ctx: Context[ServerSession, None]\n) -> dict:\n    \"\"\"Update multiple service statuses.\"\"\"\n    \n    await ctx.info(f\"Starting bulk update for {len(updates)} services\")\n    \n    updated_services = []\n    \n    for service, status in updates.items():\n        try:\n            await ctx.debug(f\"Updating {service} to {status}\")\n            \n            # Update status\n            # statuses[service] = status\n            \n            # Send individual resource update\n            await ctx.session.send_resource_updated(f\"status://{service}\")\n            \n            updated_services.append(service)\n            \n        except Exception as e:\n            await ctx.warning(f\"Failed to update {service}: {e}\")\n    \n    # Notify that the overall resource list may have changed\n    await ctx.session.send_resource_list_changed()\n    \n    await ctx.info(f\"Bulk update completed: {len(updated_services)} services updated\")\n    \n    return {\n        \"total_updates\": len(updates),\n        \"successful_updates\": len(updated_services),\n        \"updated_services\": updated_services\n    }\n```\n\n## Testing logging and progress\n\n### Unit testing with log verification\n\n```python\nimport pytest\nfrom unittest.mock import AsyncMock, Mock\n\n@pytest.mark.asyncio\nasync def test_logging_functionality():\n    \"\"\"Test that logging works correctly.\"\"\"\n    \n    # Mock context with logging methods\n    mock_ctx = Mock()\n    mock_ctx.info = AsyncMock()\n    mock_ctx.debug = AsyncMock()\n    mock_ctx.warning = AsyncMock()\n    mock_ctx.error = AsyncMock()\n    \n    # Test the logging function\n    result = await demonstrate_logging(\"test_operation\", mock_ctx)\n    \n    # Verify logging calls were made\n    mock_ctx.debug.assert_called()\n    mock_ctx.info.assert_called()\n    assert \"test_operation\" in str(result)\n\n@pytest.mark.asyncio\nasync def test_progress_reporting():\n    \"\"\"Test progress reporting functionality.\"\"\"\n    \n    mock_ctx = Mock()\n    mock_ctx.info = AsyncMock()\n    mock_ctx.debug = AsyncMock()\n    mock_ctx.report_progress = AsyncMock()\n    \n    # Test progress function\n    result = await long_running_task(3, mock_ctx)\n    \n    # Verify progress was reported\n    assert mock_ctx.report_progress.call_count == 3\n    \n    # Check progress values\n    calls = mock_ctx.report_progress.call_args_list\n    assert calls[0][1]['progress'] == 1/3  # First progress report\n    assert calls[1][1]['progress'] == 2/3  # Second progress report\n    assert calls[2][1]['progress'] == 1.0  # Final progress report\n```\n\n## Best practices\n\n### Logging guidelines\n\n- **Appropriate levels** - Use debug for detailed info, info for general progress, warning for issues, error for failures\n- **Structured messages** - Include operation IDs and context information\n- **Performance awareness** - Log timing information for slow operations\n- **Error details** - Include full error context without exposing sensitive data\n\n### Progress reporting best practices\n\n- **Frequent updates** - Update progress regularly but not excessively\n- **Meaningful messages** - Provide clear descriptions of current activity\n- **Accurate percentages** - Ensure progress values are accurate and monotonic\n- **Error handling** - Continue reporting progress even when some operations fail\n\n### Performance considerations\n\n- **Async logging** - Use async logging methods to avoid blocking\n- **Log levels** - Filter logs appropriately in production\n- **Batch operations** - Group related log messages when possible\n- **Resource cleanup** - Clean up progress tracking resources\n\n## Next steps\n\n- **[Context patterns](context.md)** - Advanced context usage for logging\n- **[Authentication](authentication.md)** - Security logging and audit trails\n- **[Error handling](tools.md#error-handling-and-validation)** - Comprehensive error handling patterns\n- **[Performance optimization](servers.md#performance-considerations)** - Server performance monitoring