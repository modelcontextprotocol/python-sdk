import asyncio
import aiohttp
import json

# In a real application, these functions would interact with databases,
# external APIs, web pages, etc. For this project, they are mocks.

async def query_database(sql_query: str) -> str:
    """
    Mock function to simulate querying a database.
    In a real implementation, this would connect to a DB and execute the query.
    """
    print(f"TOOL_EXECUTOR: Executing 'query_database' with query: {sql_query}")
    await asyncio.sleep(0.5) # Simulate I/O latency
    # Simulate a simple result based on the query
    if "users" in sql_query.lower():
        return json.dumps([
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": "bob@example.com"}
        ])
    elif "products" in sql_query.lower():
        return json.dumps([
            {"sku": "ITEM001", "name": "Laptop", "price": 1200.00},
            {"sku": "ITEM002", "name": "Mouse", "price": 25.00}
        ])
    else:
        return json.dumps({"status": "success", "message": f"Mock query '{sql_query}' executed."})

async def call_rest_api(url: str, method: str, headers: dict = None, body: dict = None) -> dict:
    """
    Mock function to simulate calling a REST API.
    Uses aiohttp to demonstrate async HTTP requests.
    """
    print(f"TOOL_EXECUTOR: Executing 'call_rest_api' to {method} {url}")
    if headers:
        print(f"TOOL_EXECUTOR: Headers: {headers}")
    if body:
        print(f"TOOL_EXECUTOR: Body: {body}")

    # For this mock, we won't actually make a call but simulate a response.
    # A real implementation would use self._session.request(...)
    await asyncio.sleep(0.5) # Simulate network latency

    # Simulate different responses based on URL or method
    if "example.com/api/data" in url and method == "GET":
        return {"status": "success", "data": {"key": "value", "message": "Mock data from example.com"}}
    elif method == "POST":
        return {"status": "success", "id": "mock_id_123", "data_received": body}
    else:
        return {"status": "error", "message": "Mock API endpoint not found or method not supported."}

async def scrape_web(url: str) -> str:
    """
    Mock function to simulate scraping a webpage.
    Uses aiohttp to demonstrate async HTTP requests.
    """
    print(f"TOOL_EXECUTOR: Executing 'scrape_web' for URL: {url}")

    # For this mock, we won't actually make a call but simulate a response.
    # A real implementation would use:
    # async with aiohttp.ClientSession() as session:
    #     async with session.get(url) as response:
    #         response.raise_for_status()
    #         return await response.text() # or parse HTML, etc.
    await asyncio.sleep(0.7) # Simulate network latency and parsing

    if "example.com" in url:
        return "Mocked HTML content for example.com: This is a sample page with some text."
    elif "another-site.com" in url:
        return "Mocked content from another-site.com: Important information here."
    else:
        return f"Mock scrape successful for {url}. Content: Lorem ipsum dolor sit amet."

# Example of how one might set up a shared aiohttp session if tools need it
# This would typically be managed by the application lifecycle, not globally like this.
# For now, individual tools can create sessions if needed, or we can pass one.
# _shared_aiohttp_session = None

# async def get_shared_aiohttp_session():
#     global _shared_aiohttp_session
#     if _shared_aiohttp_session is None or _shared_aiohttp_session.closed:
#         _shared_aiohttp_session = aiohttp.ClientSession()
#     return _shared_aiohttp_session

# async def close_shared_aiohttp_session():
#     global _shared_aiohttp_session
#     if _shared_aiohttp_session and not _shared_aiohttp_session.closed:
#         await _shared_aiohttp_session.close()
#     _shared_aiohttp_session = None
