#!/usr/bin/env python
# coding: utf-8

# In[1]:


get_ipython().run_line_magic('cd', 'C:/Users/vinis/Documents/python-sdk')


# In[2]:


import os
print(os.getcwd())


# In[3]:


import sys, os
sys.path.append(os.path.abspath("src"))


# In[4]:


pip install fastapi uvicorn httpx httpx-sse sse-starlette anyio


# In[5]:


pip install -e .


# In[6]:


import os

for root, dirs, files in os.walk("C:/Users/vinis/Documents/python-sdk"):
    for file in files:
        if file == "sse.py":
            print(os.path.join(root, file))


# In[7]:


import sys, os
sys.path.append(os.path.abspath("src"))

import mcp.client.sse as sse_module

print("Top-level definitions in mcp.client.sse:")
print(dir(sse_module))


# In[8]:


import inspect
from mcp.client.sse import aconnect_sse

print(inspect.signature(aconnect_sse))


# In[9]:


import asyncio
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




