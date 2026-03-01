"""Companion examples for src/mcp/shared/_httpx_utils.py docstrings."""

from __future__ import annotations

import httpx

from mcp.shared._httpx_utils import create_mcp_http_client


async def create_mcp_http_client_basic() -> None:
    # region create_mcp_http_client_basic
    async with create_mcp_http_client() as client:
        response = await client.get("https://api.example.com")
    # endregion create_mcp_http_client_basic


async def create_mcp_http_client_headers() -> None:
    # region create_mcp_http_client_headers
    headers = {"Authorization": "Bearer token"}
    async with create_mcp_http_client(headers) as client:
        response = await client.get("/endpoint")
    # endregion create_mcp_http_client_headers


async def create_mcp_http_client_timeout(headers: dict[str, str]) -> None:
    # region create_mcp_http_client_timeout
    timeout = httpx.Timeout(60.0, read=300.0)
    async with create_mcp_http_client(headers, timeout) as client:
        response = await client.get("/long-request")
    # endregion create_mcp_http_client_timeout


async def create_mcp_http_client_auth(headers: dict[str, str], timeout: httpx.Timeout) -> None:
    # region create_mcp_http_client_auth
    from httpx import BasicAuth

    auth = BasicAuth(username="user", password="pass")
    async with create_mcp_http_client(headers, timeout, auth) as client:
        response = await client.get("/protected-endpoint")
    # endregion create_mcp_http_client_auth
