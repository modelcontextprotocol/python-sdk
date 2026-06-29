"""HTTP-only SEP-990: `build_auth` presents an IdP-issued ID-JAG (jwt-bearer grant); `whoami` proves the subject."""

import httpx

from mcp.client import Client
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider
from stories._harness import Target, run_client
from stories._shared.auth import MCP_URL, InMemoryTokenStorage

from .idp import issue_id_jag
from .server import DEMO_CLIENT_ID, DEMO_CLIENT_SECRET, DEMO_SCOPE, ISSUER

# The end user the stand-in IdP says is signed in.
DEMO_SUBJECT = "alice@example.com"


async def fetch_id_jag(audience: str, resource: str) -> str:
    """Obtain a fresh ID-JAG from the enterprise IdP — the one step the SDK does not do.

    A real implementation makes an RFC 8693 token-exchange request with the signed-in user's ID
    token; `audience` (the authorization server's issuer) and `resource` (the MCP server's
    identifier) become the ID-JAG's `aud` and `resource` claims. The stand-in IdP signs one
    in-process instead.
    """
    return issue_id_jag(
        subject=DEMO_SUBJECT, client_id=DEMO_CLIENT_ID, audience=audience, resource=resource, scope=DEMO_SCOPE
    )


def build_auth(_http: httpx.AsyncClient) -> httpx.Auth:
    """An `IdentityAssertionOAuthProvider` for the pre-registered confidential client.

    `issuer` is configuration, not discovery — metadata comes from its well-known, never from the
    MCP server — and must match the served `issuer` byte for byte (note the trailing slash).
    `Client(url, auth=...)` doesn't exist yet, so the harness threads this onto the underlying
    `httpx.AsyncClient` and hands `main` a target already routed through it.
    """
    return IdentityAssertionOAuthProvider(
        server_url=MCP_URL,
        storage=InMemoryTokenStorage(),
        client_id=DEMO_CLIENT_ID,
        client_secret=DEMO_CLIENT_SECRET,
        issuer=ISSUER,
        assertion_provider=fetch_id_jag,
        scope=DEMO_SCOPE,
    )


async def main(target: Target, *, mode: str = "auto") -> None:
    # The first request 401s; the provider fetches the authorization server's metadata from the
    # configured issuer, mints an ID-JAG via `fetch_id_jag`, exchanges it at `/token` under the
    # jwt-bearer grant, and retries with the bearer. No `/authorize`, no `/register`, no browser.
    async with Client(target, mode=mode) as client:
        listed = await client.list_tools()
        assert [t.name for t in listed.tools] == ["whoami"]

        result = await client.call_tool("whoami", {})
        assert not result.is_error, result
        assert result.structured_content == {
            "subject": DEMO_SUBJECT,
            "client_id": DEMO_CLIENT_ID,
            "scopes": [DEMO_SCOPE],
        }, result.structured_content


if __name__ == "__main__":
    run_client(main)
