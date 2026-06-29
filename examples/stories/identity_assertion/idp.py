"""A stand-in enterprise identity provider: it signs the ID-JAGs the demo authorization server trusts.

In production the IdP is a separate service (Okta, Microsoft Entra ID, ...) and the client obtains
the ID-JAG from it with an RFC 8693 token-exchange request, presenting the signed-in user's ID
token. `issue_id_jag` collapses that whole step into one in-process signing call so the story runs
unattended; the README's caveats spell out what a real deployment changes.
"""

import time
import uuid

import jwt

IDP_ISSUER = "https://idp.example.com"
# Demo only: a real IdP signs with its private key and the authorization server verifies the
# signature against the IdP's published JWKS. A shared HMAC secret keeps this story self-contained.
IDP_SIGNING_KEY = "demo-idp-signing-key"


def issue_id_jag(*, subject: str, client_id: str, audience: str, resource: str, scope: str) -> str:
    """The IdP's short-lived, signed statement that `subject`, via `client_id`, may reach `resource`.

    This is where the enterprise enforces policy: an IdP that does not authorize the combination
    simply never issues the ID-JAG, and there is nothing for the client to present. The `typ`
    header and the claim set are fixed by the Identity Assertion JWT Authorization Grant profile.
    """
    now = int(time.time())
    return jwt.encode(
        {
            "iss": IDP_ISSUER,
            "sub": subject,
            "aud": audience,
            "client_id": client_id,
            "resource": resource,
            "scope": scope,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 300,
        },
        IDP_SIGNING_KEY,
        algorithm="HS256",
        headers={"typ": "oauth-id-jag+jwt"},
    )
