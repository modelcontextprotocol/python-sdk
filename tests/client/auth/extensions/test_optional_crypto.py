"""Optional JWT crypto packaging must preserve asymmetric OAuth semantics."""

import subprocess
import sys
from pathlib import Path

import jwt
import pytest
import tomllib

from mcp.client.auth.extensions.client_credentials import JWTParameters, SignedJWTParameters


def test_crypto_is_an_explicit_extra() -> None:
    project = tomllib.loads((Path(__file__).resolve().parents[4] / "pyproject.toml").read_text())["project"]
    assert "pyjwt>=2.10.1" in project["dependencies"]
    assert not any("[crypto]" in requirement for requirement in project["dependencies"])
    assert project["optional-dependencies"]["oauth"] == ["pyjwt[crypto]>=2.10.1"]


def test_stdio_and_asymmetric_failure_without_crypto() -> None:
    # Exercise PyJWT's real no-backend behavior in a clean subprocess, without
    # altering its algorithms or replacing signing/verification implementations.
    script = r"""
import anyio
import importlib.abc
import sys
class NoCrypto(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'cryptography' or fullname.startswith('cryptography.'):
            raise ModuleNotFoundError('crypto unavailable in this fixture', name=fullname)
sys.meta_path.insert(0, NoCrypto())
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.client.auth.extensions.client_credentials import JWTParameters, SignedJWTParameters
import jwt
assert not jwt.algorithms.has_crypto
params = SignedJWTParameters(issuer='client', subject='client', signing_key='fixture-only')
try:
    anyio.run(params.create_assertion_provider(), 'https://auth.example/')
except NotImplementedError as error:
    assert 'RS256' in str(error)
else:
    raise AssertionError('missing backend did not reject default RS256')
params = JWTParameters(issuer='client', subject='client', audience='https://auth.example/',
                       jwt_signing_key='fixture-only')
try:
    params.to_assertion()
except NotImplementedError as error:
    assert 'RS256' in str(error)
else:
    raise AssertionError('legacy default RS256 silently fell back')
assert JWTParameters(assertion='opaque-prebuilt-fixture').to_assertion() == 'opaque-prebuilt-fixture'
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=30)


@pytest.mark.anyio
@pytest.mark.parametrize("legacy", [False, True])
async def test_rs256_assertions_verify_and_reject_tampering(legacy: bool) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.utils import base64url_decode, base64url_encode

    # Ephemeral fixture key; never written to disk or included in logs.
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    audience = "https://auth.example/"
    if legacy:
        token = JWTParameters(issuer="client", subject="client", audience=audience, jwt_signing_key=pem).to_assertion()
    else:
        params = SignedJWTParameters(issuer="client", subject="client", signing_key=pem)
        token = await params.create_assertion_provider()(audience)
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    options = {"require": ["iss", "sub", "aud", "exp", "iat", "jti"]}
    claims = jwt.decode(
        token, private.public_key(), algorithms=["RS256"], issuer="client", audience=audience, options=options
    )
    assert claims["sub"] == "client"
    assert claims["exp"] - claims["iat"] == 300
    assert claims["jti"]
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(
            token,
            private.public_key(),
            algorithms=["RS256"],
            issuer="client",
            audience="https://other.example/",
            options=options,
        )
    header, payload, signature = token.split(".")
    corrupted = bytearray(base64url_decode(signature))
    corrupted[0] ^= 1
    forged = ".".join((header, payload, base64url_encode(bytes(corrupted)).decode()))
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            forged, private.public_key(), algorithms=["RS256"], issuer="client", audience=audience, options=options
        )
    with pytest.raises(jwt.InvalidAlgorithmError):
        jwt.decode(token, "fixture-only", algorithms=["HS256"])
