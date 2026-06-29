"""A stand-in enterprise identity provider: it signs the ID-JAGs the demo authorization server trusts.

A real IdP (Okta, Microsoft Entra ID, ...) issues the ID-JAG via an RFC 8693 token exchange;
`issue_id_jag` collapses that step into one in-process signing call so the story runs unattended.
"""

import time
import uuid

import jwt

IDP_ISSUER = "https://idp.example.com"
# Demo only: a real IdP signs with its private key, verified against its published JWKS.
IDP_SIGNING_KEY = "demo-idp-signing-key"


def issue_id_jag(*, subject: str, client_id: str, audience: str, resource: str, scope: str) -> str:
    """The IdP's short-lived, signed statement that `subject`, via `client_id`, may reach `resource`.

    Enterprise policy is enforced here: an unauthorized combination never gets an ID-JAG. The `typ`
    header and claim set are fixed by the Identity Assertion JWT Authorization Grant profile.
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
