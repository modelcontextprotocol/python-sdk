"""Idempotency demo client.

Demonstrates how the MCP SDK's built-in retry mechanism (max_timeout_retries)
combined with automatic idempotency keys protects against double-charging.

Flow:
  1. Get initial balance.
  2. Call make_payment with a 2 s timeout and max_timeout_retries=1.
     - The server processes the payment then sleeps 5 s, causing the client to
       time out. The SDK retries automatically with the *same* idempotency key.
     - The server detects the duplicate and returns "already_processed".
  3. Get final balance and transactions — only a single debit is recorded.

Run with:
    uv run client.py
"""

from __future__ import annotations

import asyncio
import json

from mcp.client.client import Client

SERVER_URL = "http://127.0.0.1:8000/mcp"
ACCOUNT_UID = "b4d8ada9-74a1-4c64-9ba3-a1af8c8307eb"


def _print_result(label: str, text: str) -> None:
    try:
        parsed = json.loads(text)
        formatted = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, TypeError):
        formatted = text
    print(f"\n{label}:\n{formatted}")


async def main() -> None:
    async with Client(SERVER_URL) as client:
        # 1. Initial balance.
        result = await client.call_tool("get_balance", {"account_uid": ACCOUNT_UID})
        _print_result("Initial balance", result.content[0].text)  # type: ignore[union-attr]

    print("\nCalling make_payment (2 s timeout, 1 retry)...")
    print("The server will process the payment then sleep 5 s.")
    print("The SDK will time out, then retry with the same idempotency key.\n")

    async with Client(SERVER_URL) as client:
        # 2. make_payment — SDK generates one idempotency key and reuses it on retry.
        #
        # First attempt: server processes payment, sleeps 5 s → client times out.
        # Retry:         server detects duplicate key → returns "already_processed".
        #
        # The caller does not need to manage the key; max_timeout_retries signals
        # that the tool is safe to retry and the SDK handles deduplication.
        result = await client.call_tool(
            "make_payment",
            {
                "account_uid": ACCOUNT_UID,
                "iban": "DE89370400440532013000",
                "bic": "COBADEFFXXX",
                "amount_in_minor_units": 25_00,
                "currency": "EUR",
            },
            read_timeout_seconds=2.0,
            max_timeout_retries=1,
        )
        _print_result("make_payment result (after retry)", result.content[0].text)  # type: ignore[union-attr]

    async with Client(SERVER_URL) as client:
        # 3. Final state — should show a single 25.00 EUR debit.
        balance = await client.call_tool("get_balance", {"account_uid": ACCOUNT_UID})
        _print_result("Final balance", balance.content[0].text)  # type: ignore[union-attr]

        transactions = await client.call_tool("get_transactions", {"account_uid": ACCOUNT_UID})
        _print_result("Final transactions", transactions.content[0].text)  # type: ignore[union-attr]


if __name__ == "__main__":
    asyncio.run(main())
