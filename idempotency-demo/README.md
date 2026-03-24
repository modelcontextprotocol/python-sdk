# MCP Idempotency Demo

A minimal example showing how `ctx.idempotency_key` on the server side, combined
with `max_timeout_retries` on the client side, prevents duplicate side-effects when
a tool call is retried after a timeout.

## What it demonstrates

`Client.call_tool` automatically generates a UUID idempotency key and attaches it
to every `tools/call` request. When `max_timeout_retries` is set and a call times
out, the SDK retries with the **same** key — no key management needed in user code.

On the server side, `ctx.idempotency_key` exposes the key to any `@server.tool()`
handler that accepts a `Context` parameter. The `make_payment` tool stores processed
keys and returns `"already_processed"` when it sees a key it has handled before,
ensuring the account is only debited once.

```text
Client                              Server
  |                                   |
  |-- make_payment (key=abc, 2s) ---->|
  |                                   |-- debit account
  |                                   |-- store key=abc
  |                                   |-- sleep 5s ...
  |<-- timeout (2s elapsed) ----------|
  |                                   |
  |-- make_payment (key=abc, retry) ->|  ← same key
  |                                   |-- key=abc already seen → skip debit
  |<-- {"status":"already_processed"}-|
```

## Setup

```bash
cd idempotency-demo
uv sync
```

## Running

In one terminal, start the server:

```bash
uv run server.py
```

In another terminal, run the client:

```bash
uv run client.py
```

## Expected output

**Server terminal:**

```text
[server] Payment processed (key=<uuid>, call=0)
[server] Sleeping 5 s to trigger client timeout...
[server] Duplicate payment detected (key=<uuid>) — returning cached result
```

**Client terminal:**

```text
Initial balance:
{
  "balanceMinorUnits": 10000
}

Calling make_payment (2 s timeout, 1 retry)...
The server will process the payment then sleep 5 s.
The SDK will time out, then retry with the same idempotency key.

make_payment result (after retry):
{
  "status": "already_processed",
  "message": "Payment already applied. Returning cached result."
}

Final balance:
{
  "balanceMinorUnits": 7500
}

Final transactions:
{
  "transactions": [
    {
      "IBAN": "DE89370400440532013000",
      "BIC": "COBADEFFXXX",
      "amountMinorUnits": 2500,
      "currency": "EUR"
    }
  ]
}
```

The final balance shows a single 25.00 EUR debit (10000 → 7500 minor units) and a
single transaction, even though the tool was called twice. Without idempotency the
account would be debited twice.
