"""Companion examples for src/mcp/client/auth/extensions/client_credentials.py docstrings."""

from __future__ import annotations

from mcp.client.auth import TokenStorage
from mcp.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider,
    PrivateKeyJWTOAuthProvider,
    SignedJWTParameters,
    static_assertion_provider,
)


async def fetch_token_from_identity_provider(*, audience: str) -> str: ...


def ClientCredentialsOAuthProvider_init(my_token_storage: TokenStorage) -> None:
    # region ClientCredentialsOAuthProvider_init
    provider = ClientCredentialsOAuthProvider(
        server_url="https://api.example.com",
        storage=my_token_storage,
        client_id="my-client-id",
        client_secret="my-client-secret",
    )
    # endregion ClientCredentialsOAuthProvider_init


def static_assertion_provider_usage(my_token_storage: TokenStorage, my_prebuilt_jwt: str) -> None:
    # region static_assertion_provider_usage
    provider = PrivateKeyJWTOAuthProvider(
        server_url="https://api.example.com",
        storage=my_token_storage,
        client_id="my-client-id",
        assertion_provider=static_assertion_provider(my_prebuilt_jwt),
    )
    # endregion static_assertion_provider_usage


def SignedJWTParameters_usage(my_token_storage: TokenStorage, private_key_pem: str) -> None:
    # region SignedJWTParameters_usage
    jwt_params = SignedJWTParameters(
        issuer="my-client-id",
        subject="my-client-id",
        signing_key=private_key_pem,
    )
    provider = PrivateKeyJWTOAuthProvider(
        server_url="https://api.example.com",
        storage=my_token_storage,
        client_id="my-client-id",
        assertion_provider=jwt_params.create_assertion_provider(),
    )
    # endregion SignedJWTParameters_usage


def PrivateKeyJWTOAuthProvider_workloadIdentity(my_token_storage: TokenStorage) -> None:
    # region PrivateKeyJWTOAuthProvider_workloadIdentity
    async def get_workload_identity_token(audience: str) -> str:
        # Fetch JWT from your identity provider
        # The JWT's audience must match the provided audience parameter
        return await fetch_token_from_identity_provider(audience=audience)

    provider = PrivateKeyJWTOAuthProvider(
        server_url="https://api.example.com",
        storage=my_token_storage,
        client_id="my-client-id",
        assertion_provider=get_workload_identity_token,
    )
    # endregion PrivateKeyJWTOAuthProvider_workloadIdentity


def PrivateKeyJWTOAuthProvider_staticJWT(my_token_storage: TokenStorage, my_prebuilt_jwt: str) -> None:
    # region PrivateKeyJWTOAuthProvider_staticJWT
    provider = PrivateKeyJWTOAuthProvider(
        server_url="https://api.example.com",
        storage=my_token_storage,
        client_id="my-client-id",
        assertion_provider=static_assertion_provider(my_prebuilt_jwt),
    )
    # endregion PrivateKeyJWTOAuthProvider_staticJWT


def PrivateKeyJWTOAuthProvider_sdkSigned(my_token_storage: TokenStorage, private_key_pem: str) -> None:
    # region PrivateKeyJWTOAuthProvider_sdkSigned
    jwt_params = SignedJWTParameters(
        issuer="my-client-id",
        subject="my-client-id",
        signing_key=private_key_pem,
    )
    provider = PrivateKeyJWTOAuthProvider(
        server_url="https://api.example.com",
        storage=my_token_storage,
        client_id="my-client-id",
        assertion_provider=jwt_params.create_assertion_provider(),
    )
    # endregion PrivateKeyJWTOAuthProvider_sdkSigned
