"""Example: MCP client with a pre-execution authorization callback.

This example shows how to build a tool-execution loop that evaluates
every tool call against an authorization policy before execution.
This pattern is essential when connecting agents to MCP servers at
scale, where some tools are safe to run freely and others require
approval or should be blocked entirely.

Run from the repository root:
    uv run examples/snippets/clients/client_with_authorization.py
"""

import asyncio
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Authorization layer
# ---------------------------------------------------------------------------


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


@dataclass
class AuthRequest:
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class AuthResult:
    decision: Decision
    reason: str


def default_policy(request: AuthRequest) -> AuthResult:
    """A simple policy function that decides whether a tool call should
    be allowed, denied, or held for approval.

    Replace or extend this function with your own logic — for example,
    reading from a policy file, checking roles, or calling an external
    authorization service.
    """
    # Safe tools (e.g. arithmetic, reading data) are always allowed
    if request.tool_name in ["add", "calculator", "get_weather"] or request.tool_name.startswith(("read_", "list_")):
        return AuthResult(Decision.ALLOW, "safe tool, allowed by default")

    # Destructive tools are always blocked
    if request.tool_name.startswith(("delete_", "drop_", "destroy_", "execute_script")):
        return AuthResult(Decision.DENY, "destructive tool, blocked by policy")

    # Everything else needs a human to approve
    return AuthResult(
        Decision.APPROVAL_REQUIRED,
        "tool has unknown side effects, requires approval before execution",
    )


async def authorized_call_tool(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
    policy: Callable[[AuthRequest], AuthResult] = default_policy,
) -> Any:
    """Evaluate the authorization policy before calling a tool.
    Only executes the tool if the decision is ALLOW.
    """
    request = AuthRequest(tool_name=tool_name, arguments=arguments)
    result = policy(request)

    print(f"\n  Tool     : {tool_name}")
    print(f"  Decision : {result.decision.value.upper()}")
    print(f"  Reason   : {result.reason}")

    if result.decision == Decision.ALLOW:
        try:
            tool_result = await session.call_tool(tool_name, arguments)

            # Safely extract text output if present
            output = str(tool_result)
            if hasattr(tool_result, "content") and tool_result.content:
                first_content = tool_result.content[0]
                if isinstance(first_content, types.TextContent):
                    output = first_content.text
            print(f"  Result   : {output}")
            return tool_result
        except Exception as e:
            print(f"  Error    : {e}")
            return None

    if result.decision == Decision.APPROVAL_REQUIRED:
        # In a real system this would create a checkpoint and notify a
        # human approver. Here we simply surface the requirement.
        print("  Action   : execution paused — waiting for human approval")
        return None

    # Decision.DENY
    print("  Action   : execution blocked")
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# We use mcpserver_quickstart to have a reliable server to connect to
server_params = StdioServerParameters(
    command="uv",
    args=["--directory", "examples/snippets", "run", "server", "mcpserver_quickstart", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Discover available tools
            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description}")

            print("\n--- Running authorization checks ---")

            # Demonstrate: safe tool -> allowed (add is from mcpserver_quickstart)
            await authorized_call_tool(
                session,
                tool_name="add",
                arguments={"a": 5, "b": 3},
            )

            # Demonstrate: unknown tool -> approval required
            await authorized_call_tool(
                session,
                tool_name="write_file",
                arguments={"path": "/tmp/example.txt", "content": "hello"},
            )

            # Demonstrate: delete tool -> denied
            await authorized_call_tool(
                session,
                tool_name="delete_file",
                arguments={"path": "/tmp/example.txt"},
            )


if __name__ == "__main__":
    asyncio.run(run())
