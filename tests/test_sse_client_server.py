import asyncio
from typing import AsyncGenerator, List

from fastapi import FastAPI
from starlette.responses import StreamingResponse
import uvicorn
from threading import Thread
import httpx
from mcp.client.sse import aconnect_sse

app = FastAPI()

@app.get("/sse")
async def sse_endpoint():
    async def event_stream():
        for i in range(3):
            yield f"data: Hello {i+1}\n\n"
            await asyncio.sleep(0.1)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

def run_mock_server():
    uvicorn.run(app, host="127.0.0.1", port=8012, log_level="warning")

async def main():
    server_thread = Thread(target=run_mock_server, daemon=True)
    server_thread.start()
    await asyncio.sleep(1)

    messages = []

    async with httpx.AsyncClient() as client:
        async with aconnect_sse(client, "GET", "http://127.0.0.1:8012/sse") as event_source:
            async for event in event_source.aiter_sse():
                if event.data:
                    print(" Event received:", event.data)
                    messages.append(event.data)
                if len(messages) == 3:
                    break

    assert messages == ["Hello 1", "Hello 2", "Hello 3"]
    print("\n Test passed! SSE connection via aconnect_sse worked correctly.")

await main()


# In[ ]:




