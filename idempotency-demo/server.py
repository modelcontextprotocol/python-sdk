"""Idempotency demo server.

Demonstrates idempotent tool calls using MCPServer and ctx.idempotency_key.

Run with:
    uv run server.py
"""

from __future__ import annotations

import anyio
import uvicorn

from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, ToolAnnotations

server = MCPServer("idempotency-demo")

# In-memory account store — reset on each server restart.
accounts: dict[str, dict[str, int | list[dict[str, str | int]]]] = {
    "b4d8ada9-74a1-4c64-9ba3-a1af8c8307eb": {
        "balance_minor_units": 100_00,
        "transactions": [],
    },
    "1a57e024-09db-4402-801b-4f75b1a05a8d": {
        "balance_minor_units": 200_00,
        "transactions": [],
    },
}

# Idempotency key store — tracks processed payment keys.
processed_keys: set[str] = set()

# Call counter — used to trigger a slow response on every other call.
num_calls: int = 0


@server.tool()
def get_balance(account_uid: str) -> str:
    """Return the current balance in minor units for the specified account."""
    account = accounts.get(account_uid)
    if account is None:
        raise MCPError(INVALID_PARAMS, f"Account {account_uid} not found")
    balance = account["balance_minor_units"]
    return f'{{"balanceMinorUnits": {balance}}}'


@server.tool()
def get_transactions(account_uid: str) -> str:
    """Return the list of processed transactions for the specified account."""
    import json

    account = accounts.get(account_uid)
    if account is None:
        raise MCPError(INVALID_PARAMS, f"Account {account_uid} not found")
    return json.dumps({"transactions": account["transactions"]}, indent=2)


@server.tool(annotations=ToolAnnotations(idempotentHint=True))
async def make_payment(
    account_uid: str,
    iban: str,
    bic: str,
    amount_in_minor_units: int,
    currency: str,
    ctx: Context,
) -> str:
    """Idempotent payment tool.

    Uses ctx.idempotency_key to deduplicate retries. A retry carrying the same
    key returns "already_processed" without charging the account again.

    The first call deliberately sleeps for 5 seconds after processing, simulating
    a slow response that causes the client to time out. When the client retries
    with the same idempotency key the request is recognised as a duplicate and
    returns immediately.
    """
    global num_calls

    key = ctx.idempotency_key
    if not key:
        raise MCPError(INVALID_PARAMS, "idempotency_key is required for make_payment")

    # Duplicate request — return cached result without side effects.
    if key in processed_keys:
        print(f"[server] Duplicate payment detected (key={key}) — returning cached result")
        return '{"status": "already_processed", "message": "Payment already applied. Returning cached result."}'

    account = accounts.get(account_uid)
    if account is None:
        raise MCPError(INVALID_PARAMS, f"Account {account_uid} not found")

    balance = int(account["balance_minor_units"])
    if balance < amount_in_minor_units:
        raise MCPError(INVALID_PARAMS, f"Insufficient funds: balance {balance} < {amount_in_minor_units}")

    # Apply payment and record the idempotency key *before* sleeping so that a
    # retry arriving while we are still sleeping gets the "already_processed" path.
    account["balance_minor_units"] = balance - amount_in_minor_units
    account["transactions"].append(  # type: ignore[union-attr]
        {"IBAN": iban, "BIC": bic, "amountMinorUnits": amount_in_minor_units, "currency": currency}
    )
    processed_keys.add(key)

    call_number = num_calls
    num_calls += 1

    print(f"[server] Payment processed (key={key}, call={call_number})")

    if call_number % 2 == 0:
        # Simulate a slow response on even-numbered calls. The client times out
        # after 2 s and retries with the same idempotency key; this sleep means
        # the retry will always arrive after processing is committed.
        print("[server] Sleeping 5 s to trigger client timeout...")
        await anyio.sleep(5)

    return '{"status": "processed", "message": "Payment applied."}'


if __name__ == "__main__":
    app = server.streamable_http_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)
