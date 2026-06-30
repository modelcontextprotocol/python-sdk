"""Integrity protection for the multi-round-trip `requestState` (MCP 2026-07-28).

The spec requires servers to treat the client-echoed `requestState` as
attacker-controlled: `RequestStateBoundary` seals every outgoing value and
verifies every inbound echo, so handlers only ever see plaintext they minted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, NoReturn, Protocol, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS
from mcp_types.methods import INPUT_REQUIRED_METHODS, is_input_required

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError

__all__ = [
    "AESGCMRequestStateCodec",
    "InvalidRequestState",
    "RequestStateBoundary",
    "RequestStateCodec",
    "RequestStateSecurity",
    "authenticated_principal",
]

logger = logging.getLogger(__name__)


class InvalidRequestState(Exception):
    """A sealed `requestState` token failed verification.

    The message is a log-only reason code; the boundary never puts it on the wire.
    """


class RequestStateCodec(Protocol):
    """Authenticated crypto over the framework's request-state envelope.

    The framework stamps and re-verifies every envelope claim (expiry, request
    binding, principal); a codec only provides integrity and, ideally,
    confidentiality (a sign-only codec leaves the payload client-readable).

    Requirements: `unseal(seal(payload))` round-trips, and `unseal` raises
    `InvalidRequestState` for any token it did not mint unmodified; tokens
    never name their algorithm (version with a format prefix bound under the
    authentication tag, RFC 8725); comparisons are constant-time. Both methods
    are synchronous, so cache key material rather than calling a KMS per token.
    """

    def seal(self, payload: bytes) -> str:
        """Return an opaque URL-safe token protecting `payload`."""
        ...

    def unseal(self, token: str) -> bytes:
        """Reverse `seal`.

        Raises:
            InvalidRequestState: Malformed, unauthentic, or unknown-key token.
        """
        ...


def authenticated_principal(ctx: ServerRequestContext[Any, Any]) -> str | None:
    """Default principal binding: the authenticated OAuth client's `client_id`.

    Returns `None` (state not principal-bound) on unauthenticated transports.
    """
    token = get_access_token()
    return token.client_id if token is not None else None


class RequestStateSecurity:
    """Policy for protecting `requestState`: codec, TTL, principal, audience.

    Exactly one of `keys` or `codec`:

        RequestStateSecurity(keys=[secret])      # built-in AES-256-GCM
        RequestStateSecurity(codec=MyKmsCodec()) # bring your own crypto
        RequestStateSecurity.ephemeral()         # process-local key

    `keys` is the rotation ring: `keys[0]` seals, every key unseals.
    Zero-downtime rotation, each phase fully rolled out before the next:
    `keys=[old, new]`, then `keys=[new, old]`, then `keys=[new]` after one TTL.

    The boundary enforces expiry, request binding, audience, and principal for
    every codec, fail-closed in both directions. `audience=None` defers to the
    boundary's `default_audience` (`MCPServer` passes its server name).
    """

    codec: RequestStateCodec
    ttl: float
    bind_principal: Callable[[ServerRequestContext[Any, Any]], str | None] | None
    audience: str | None

    def __init__(
        self,
        *,
        keys: Sequence[bytes | bytearray | str] | None = None,
        codec: RequestStateCodec | None = None,
        ttl: float = 600.0,
        bind_principal: Callable[[ServerRequestContext[Any, Any]], str | None] | None = authenticated_principal,
        audience: str | None = None,
    ) -> None:
        if (keys is None) == (codec is None):
            raise ValueError("RequestStateSecurity takes exactly one of keys= or codec=")
        if not (math.isfinite(ttl) and ttl > 0):
            raise ValueError(f"request-state ttl must be a positive finite number, got {ttl!r}")
        if keys is not None:
            self.codec = AESGCMRequestStateCodec(keys)
        else:
            assert codec is not None
            self.codec = codec
        self.ttl = ttl
        self.bind_principal = bind_principal
        self.audience = audience

    @classmethod
    def ephemeral(cls, *, ttl: float = 600.0, audience: str | None = None) -> RequestStateSecurity:
        """Protection under a key generated now and held only by this process.

        Suits single-process deployments (stdio, one HTTP worker): state minted
        before a restart or by another worker is rejected. Multi-instance
        deployments must share a key via `keys=[...]`.
        """
        return cls(keys=[os.urandom(32)], ttl=ttl, audience=audience)


_KDF_INFO = b"mcp/request-state/v1/aes-256-gcm"
_KID_INFO = b"mcp/request-state/v1/kid:"
_TOKEN_PREFIX = "v1."
_KID_LEN = 4
_NONCE_LEN = 12


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64u_decode(text: str) -> bytes:
    """Strict inverse of `_b64u`: only the canonical unpadded encoding decodes."""
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if _b64u(raw) != text:
        raise ValueError("non-canonical base64url")
    return raw


def _derive_key(secret: bytes) -> bytes:
    """Stretch an operator secret (>= 32 bytes, any format) into the AES-256 key."""
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=_KDF_INFO).derive(secret)


class AESGCMRequestStateCodec:
    """Built-in codec: AES-256-GCM under key(s) derived with HKDF-SHA256.

    Tokens are encrypted, not merely signed, so clients cannot read the state.
    `keys[0]` seals; all keys unseal (rotation, see `RequestStateSecurity`).
    Each token carries a 4-byte non-secret key fingerprint for an O(1) ring
    lookup, and the "v1." prefix and fingerprint are bound into the GCM
    associated data, so a token cannot be replayed into another format version
    or ring slot. Key bytes are copied at construction.
    """

    def __init__(self, keys: Sequence[bytes | bytearray | str]) -> None:
        for i, key in enumerate(cast("Sequence[object]", keys)):
            if not isinstance(key, bytes | bytearray | str):
                # Never coerce: bytes(32) would silently build an all-zero key.
                raise TypeError(
                    f"request-state keys must be bytes, bytearray, or str; keys[{i}] is {type(key).__name__}"
                )
        material = [k.encode() if isinstance(k, str) else bytes(k) for k in keys]
        if not material:
            raise ValueError("AESGCMRequestStateCodec requires at least one key")
        for i, k in enumerate(material):
            if len(k) < 32:
                raise ValueError(
                    f"request-state keys must be at least 32 bytes of secret randomness; "
                    f"keys[{i}] is {len(k)} bytes. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        self._ring: dict[bytes, AESGCM] = {}
        self._mint_kid = b""
        for i, secret in enumerate(material):
            key = _derive_key(secret)
            kid = hashlib.sha256(_KID_INFO + key).digest()[:_KID_LEN]
            if kid in self._ring:
                raise ValueError(f"keys[{i}] duplicates an earlier ring key")
            self._ring[kid] = AESGCM(key)
            if i == 0:
                self._mint_kid = kid

    def seal(self, payload: bytes) -> str:
        kid = self._mint_kid
        nonce = os.urandom(_NONCE_LEN)
        sealed = self._ring[kid].encrypt(nonce, payload, _TOKEN_PREFIX.encode() + kid)
        return _TOKEN_PREFIX + _b64u(kid + nonce + sealed)

    def unseal(self, token: str) -> bytes:
        if not token.startswith(_TOKEN_PREFIX):
            raise InvalidRequestState("malformed")
        try:
            raw = _b64u_decode(token[len(_TOKEN_PREFIX) :])
        except ValueError as exc:
            raise InvalidRequestState("malformed") from exc
        if len(raw) < _KID_LEN + _NONCE_LEN + 16:
            raise InvalidRequestState("malformed")
        kid, nonce, sealed = raw[:_KID_LEN], raw[_KID_LEN : _KID_LEN + _NONCE_LEN], raw[_KID_LEN + _NONCE_LEN :]
        aead = self._ring.get(kid)
        if aead is None:
            raise InvalidRequestState("unknown key")
        try:
            return aead.decrypt(nonce, sealed, _TOKEN_PREFIX.encode() + kid)
        except InvalidTag:
            raise InvalidRequestState("seal") from None


# The multi-round-trip carriers: the only methods whose results may carry `requestState`.
_MRTR_METHODS = INPUT_REQUIRED_METHODS
_ENVELOPE_VERSION = 1
_FUTURE_SKEW = 60.0
_PRINCIPAL_LABEL = b"mcp/request-state/principal:"

_RoundBinding = tuple[str, str, str | None]
"""The (target, args-digest, principal) one round's envelope binds, computed once per round."""


def _reject(method: str, reason: str) -> NoReturn:
    """Refuse a round: frozen wire error, real reason to the server log only."""
    logger.warning("requestState rejected on %s: %s", method, reason)
    raise MCPError(
        code=INVALID_PARAMS,
        message="Invalid or expired requestState",
        data={"reason": "invalid_request_state"},
    )


def _request_identity(method: str, params: Mapping[str, Any] | None) -> tuple[str, str]:
    """Salient (target, args-digest) for the request a token binds to.

    Per-method allowlist, never a denylist: a future wire field cannot silently join the digest.
    """
    p: Mapping[str, Any] = params or {}
    args: dict[str, Any] = {}
    if method == "resources/read":
        target = str(p.get("uri", ""))
    else:
        target, args = str(p.get("name", "")), p.get("arguments") or args
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return target, _b64u(hashlib.sha256(canonical.encode()).digest()[:16])


def _principal_claim(principal: str) -> str:
    salt = os.urandom(8)
    tag = hashlib.sha256(_PRINCIPAL_LABEL + salt + principal.encode()).digest()[:16]
    return _b64u(salt + tag)


def _principal_matches(claim: str, principal: str) -> bool:
    try:
        raw = _b64u_decode(claim)
    except ValueError:
        return False
    # A wrong-length claim never matches: compare_digest handles mismatched sizes.
    expected = hashlib.sha256(_PRINCIPAL_LABEL + raw[:8] + principal.encode()).digest()[:16]
    return hmac.compare_digest(raw[8:], expected)


class RequestStateBoundary:
    """Server middleware sealing/unsealing `requestState` at the wire boundary.

    Acts only on the multi-round-trip carriers (tools/call, prompts/get,
    resources/read); every other method passes through untouched.

    Inbound state is verified (codec unseal plus claims check) and replaced
    with the plaintext the server minted before any interceptor or handler
    runs; failure answers -32602 with the frozen message "Invalid or expired
    requestState", the real reason going to the server log only. Outbound, an
    `input_required` result carrying `requestState` is sealed in a fresh
    claims envelope; handlers and resolvers never call the codec.

    `default_audience` seeds the audience claim when the policy sets none
    (`MCPServer` passes its server name). `MCPServer` installs this when
    `request_state_security=` is supplied; lowlevel `Server` users append one
    to `server.middleware` for identical enforcement.
    """

    def __init__(self, security: RequestStateSecurity, *, default_audience: str | None = None) -> None:
        self._security = security
        self._audience = security.audience if security.audience is not None else default_audience

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if ctx.method not in _MRTR_METHODS:
            return await call_next(ctx)
        binding: _RoundBinding | None = None
        if ctx.params is not None and ctx.params.get("requestState") is not None:
            # An explicit JSON null counts as absent: stripping the field is already in any client's power.
            plaintext, binding = self._unseal(ctx)
            ctx = replace(ctx, params={**ctx.params, "requestState": plaintext})
        result = await call_next(ctx)
        return self._seal_result(ctx, result, binding)

    def _unseal(self, ctx: ServerRequestContext[Any, Any]) -> tuple[str, _RoundBinding]:
        assert ctx.params is not None
        wire = ctx.params["requestState"]
        if not isinstance(wire, str):
            _reject(ctx.method, "non-string requestState")
        security = self._security
        try:
            payload = security.codec.unseal(wire)
        except InvalidRequestState as exc:
            _reject(ctx.method, str(exc))
        except Exception:  # deny-on-error: a buggy custom codec must fail closed
            logger.exception("requestState codec raised during unseal on %s", ctx.method)
            _reject(ctx.method, "codec error")
        try:
            claims = json.loads(payload)
            version, iat, exp, inner = claims["v"], claims["iat"], claims["exp"], claims["s"]
        except (ValueError, KeyError, TypeError):
            _reject(ctx.method, "malformed")
        if version != _ENVELOPE_VERSION or not isinstance(inner, str):
            _reject(ctx.method, "malformed")
        now = time.time()
        # Accept-conditions are stated positively so a NaN claim fails the comparison and rejects.
        if not isinstance(iat, int | float) or not (iat <= now + _FUTURE_SKEW):
            _reject(ctx.method, "minted in the future")
        if not isinstance(exp, int | float) or not (now < exp):
            _reject(ctx.method, "expired")
        target, args_digest = _request_identity(ctx.method, ctx.params)
        if claims.get("m") != ctx.method or claims.get("t") != target or claims.get("a") != args_digest:
            _reject(ctx.method, "request binding")
        if claims.get("aud") != self._audience:
            _reject(ctx.method, "audience")
        try:
            principal = security.bind_principal(ctx) if security.bind_principal is not None else None
        except Exception:  # deny-on-error: a raising principal binding must fail closed
            logger.exception("bind_principal raised while verifying requestState on %s", ctx.method)
            _reject(ctx.method, "principal binding error")
        claim = claims.get("p")
        if (claim is None) != (principal is None):
            _reject(ctx.method, "principal drift")
        if claim is not None and principal is not None:
            if not isinstance(claim, str) or not _principal_matches(claim, principal):
                _reject(ctx.method, "principal")
        return inner, (target, args_digest, principal)

    def _seal_result(
        self, ctx: ServerRequestContext[Any, Any], result: HandlerResult, binding: _RoundBinding | None
    ) -> HandlerResult:
        # Spec-path results arrive as wire mappings; a short-circuiting middleware may return a model.
        if not is_input_required(result):
            return result
        state = result.get("requestState") if isinstance(result, Mapping) else result.request_state
        if state is None:
            return result
        if isinstance(result, Mapping):
            if not isinstance(state, str):
                # Only a short-circuiting middleware can put a non-string here; nothing to seal.
                return result
            return {**result, "requestState": self._seal(ctx, state, binding)}
        return result.model_copy(update={"request_state": self._seal(ctx, state, binding)})

    def _seal(self, ctx: ServerRequestContext[Any, Any], state: str, binding: _RoundBinding | None = None) -> str:
        security = self._security
        if binding is None:
            target, args_digest = _request_identity(ctx.method, ctx.params)
            try:
                principal = security.bind_principal(ctx) if security.bind_principal is not None else None
            except Exception:  # deny-on-error: a raising principal binding must not mint unbound state
                logger.exception("bind_principal raised while sealing requestState on %s", ctx.method)
                raise MCPError(code=INTERNAL_ERROR, message="Internal error") from None
            binding = (target, args_digest, principal)
        target, args_digest, principal = binding
        now = int(time.time())
        claims: dict[str, Any] = {
            "v": _ENVELOPE_VERSION,
            "iat": now,
            "exp": now + security.ttl,
            "m": ctx.method,
            "t": target,
            "a": args_digest,
            "s": state,
        }
        if self._audience is not None:
            claims["aud"] = self._audience
        if principal is not None:
            claims["p"] = _principal_claim(principal)
        return security.codec.seal(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode())
