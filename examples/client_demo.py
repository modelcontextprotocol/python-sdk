import asyncio
from typing import AsyncGenerator

from fastapi import FastAPI
from starlette.responses import StreamingResponse
import uvicorn
from threading import Thread
import httpx
from mcp.client.sse import aconnect_sse

# Mock SSE server using FastAPI
app = FastAPI()

@app.get("/sse")
async def sse_endpoint() -> StreamingResponse:
    async def event_stream() -> AsyncGenerator[str, None]:
        for i in range(3):
            yield f"data: Hello {i+1}\n\n"
            await asyncio.sleep(0.1)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

def run_mock_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8012, log_level="warning")

# MCP client demo to connect to the mock SSE server
async def run_demo() -> None:
    server_thread = Thread(target=run_mock_server, daemon=True)
    server_thread.start()
    await asyncio.sleep(1)

    messages = []

    async with httpx.AsyncClient() as client:
        async with aconnect_sse(client, "GET", "http://127.0.0.1:8012/sse") as event_source:
            async for event in event_source.aiter_sse():
                if event.data:
                    print("Event received:", event.data)
                    messages.append(event.data)
                if len(messages) == 3:
                    break

    print("\nClient demo finished. Messages received:", messages)

if __name__ == "__main__":
    asyncio.run(run_demo())