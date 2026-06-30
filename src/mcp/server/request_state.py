"""Integrity protection for the multi-round-trip `requestState` (MCP 2026-07-28).

`requestState` round-trips through the client, so the spec requires servers to
treat the echoed value as attacker-controlled, integrity-protect any state that
influences authorization, resource access, or business logic, and reject state
that fails verification (basic/patterns/mrtr, server requirements 4-5).

This module is the composable tier: `RequestStateBoundary` is a server middleware
that seals every outgoing `requestState` and unseals (verifies) every inbound
echo, so handlers and resolvers only ever see the plaintext state they minted.
`MCPServer` installs it automatically from its `request_state_security=`
parameter; lowlevel `Server` users append it to `Server.middleware` themselves.
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

    Raised by `RequestStateCodec.unseal` implementations for any failure —
    malformed token, failed authentication, unknown key. The message is a short
    reason code for server logs only; the boundary never puts it on the wire.

    (Deliberately not named `InvalidSignature`: that name already exists in
    `mcp.server.mcpserver.exceptions` and means a bad Python callable signature.)
    """


class RequestStateCodec(Protocol):
    """Seals the framework's request-state envelope for its trip through the client.

    Implementations do authenticated crypto over opaque bytes and NOTHING else.
    The framework owns the envelope: it stamps mint time, expiry, the originating
    request's method/target/argument digest, and the principal tag into the
    payload before `seal`, and re-verifies every one of them after `unseal`. A
    codec therefore cannot get TTL, replay-binding, or principal-binding wrong —
    its only obligations are integrity (tamper -> raise) and, ideally,
    confidentiality.

    Requirements:
      - `unseal(seal(payload))` round-trips `payload`; `unseal` MUST raise
        `InvalidRequestState` for any token it did not mint, or that was
        modified in any way.
      - The token MUST NOT name its algorithm; version it with a format prefix
        bound under the authentication tag (RFC 8725 discipline).
      - Comparisons MUST be constant-time (an AEAD primitive satisfies this).
      - Prefer an encrypting construction: the payload carries server state and
        a salted principal digest; a sign-only codec makes both client-readable.
      - Both methods are synchronous; cache key material locally (envelope
        encryption) rather than calling a KMS per token — see the docs example.
    """

    def seal(self, payload: bytes) -> str:
        """Return an opaque URL-safe token protecting `payload`."""
        ...

    def unseal(self, token: str) -> bytes:
        """Reverse `seal`.

        Raises:
            InvalidRequestState: If the token is malformed, fails
                authentication, or was sealed under an unknown key.
        """
        ...


def authenticated_principal(ctx: ServerRequestContext[Any, Any]) -> str | None:
    """Default principal binding: the authenticated OAuth client, when present.

    Reads the access token that `AuthContextMiddleware` stored for this request
    and returns its `client_id`. Returns `None` on unauthenticated transports
    (stdio, auth-less HTTP), in which case state is not principal-bound.
    Replace via `RequestStateSecurity(bind_principal=...)` to bind to a richer
    identity (e.g. an end-user subject from your own auth layer).
    """
    token = get_access_token()
    return token.client_id if token is not None else None


class RequestStateSecurity:
    """Policy for protecting `requestState`: which codec, what TTL, which principal.

    Exactly one of `keys` or `codec`:

        RequestStateSecurity(keys=[secret])      # built-in AES-256-GCM, shared key(s)
        RequestStateSecurity(codec=MyKmsCodec()) # bring your own crypto
        RequestStateSecurity.ephemeral()         # process-local key; single process only
        RequestStateSecurity.unprotected()       # explicit opt-out (read its docstring)

    `keys` is the rotation ring: `keys[0]` seals new state; every key may
    unseal. Zero-downtime rotation is three phases (each fully rolled out
    before the next): `keys=[old, new]` (every instance learns to verify the
    new key; old still mints) -> `keys=[new, old]` (new mints; in-flight old
    state keeps verifying) -> after one TTL, `keys=[new]`.

    The sealed envelope carries mint time, a short expiry, the originating
    request's method + target + argument digest, and a salted digest of
    `bind_principal(ctx)` — the spec's three recommended replay bounds, on by
    default and enforced by the boundary for EVERY codec, including custom
    ones. Principal binding applies when the SDK authenticates the request (the
    default binding derives no principal on unauthenticated transports) and is
    fail-closed in both directions: state sealed with a principal is rejected
    by a verifier that derives none, and vice versa.

    `audience` distinguishes services that share — or accidentally reuse — a
    secret: it is stamped into the envelope and verified fail-closed in both
    directions. `None` leaves state audience-unbound unless the server tier
    supplies a default (`MCPServer` passes its server name as the boundary's
    `default_audience`).
    """

    codec: RequestStateCodec | None
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
        _unprotected: bool = False,
    ) -> None:
        if _unprotected:
            # `unprotected()`'s spelling: no codec, no binding, no audience; `ttl` is never read.
            self.codec = None
            self.ttl = ttl
            self.bind_principal = None
            self.audience = None
            return
        if (keys is None) == (codec is None):
            raise ValueError("RequestStateSecurity takes exactly one of keys= or codec=")
        if not (math.isfinite(ttl) and ttl > 0):
            raise ValueError(f"request-state ttl must be a positive finite number, got {ttl!r}")
        self.codec = AESGCMRequestStateCodec(keys) if keys is not None else codec
        self.ttl = ttl
        self.bind_principal = bind_principal
        self.audience = audience

    @classmethod
    def ephemeral(cls, *, ttl: float = 600.0, audience: str | None = None) -> RequestStateSecurity:
        """Protection under a key generated now and held only by this process.

        Valid for single-process deployments (stdio, a single HTTP worker): the
        one process that mints state is the one that receives the retry. It
        FAILS across instances and restarts — state minted before a restart, or
        by another worker behind a load balancer, is rejected with the standard
        "Invalid or expired requestState" error and the client must start the
        flow over. Multi-instance deployments must share a key:
        `RequestStateSecurity(keys=[...])`. `ttl` and `audience` carry the same
        meaning as on the main constructor.
        """
        return cls(keys=[os.urandom(32)], ttl=ttl, audience=audience)

    @classmethod
    def unprotected(cls) -> RequestStateSecurity:
        """No protection: `requestState` crosses the wire exactly as handlers wrote it.

        The spec permits this ONLY "when tampering can cause nothing worse than
        request failure" (basic/patterns/mrtr). A client can then read, forge,
        and replay your state at will — never put data that influences
        authorization, resource access, or business logic in it. A server
        configured this way fails the `input-required-result-tampered-state`
        conformance scenario by design. Resolver-driven tools
        (`Resolve(...)` parameters) refuse this mode at registration: their
        state carries elicited answers, which are business inputs.
        """
        return cls(_unprotected=True)

    @property
    def is_unprotected(self) -> bool:
        return self.codec is None


_KDF_INFO = b"mcp/request-state/v1/aes-256-gcm"
_KID_INFO = b"mcp/request-state/v1/kid:"
_TOKEN_PREFIX = "v1."
_KID_LEN = 4
_NONCE_LEN = 12


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64u_decode(text: str) -> bytes:
    """Strict inverse of `_b64u`: only the canonical unpadded encoding decodes.

    The round-trip check rejects every malleable variant a lax decoder admits —
    non-zero trailing don't-care bits, injected non-alphabet characters, and
    appended padding — raising ValueError for all of them.
    """
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if _b64u(raw) != text:
        raise ValueError("non-canonical base64url")
    return raw


def _derive_key(secret: bytes) -> bytes:
    """Stretch an operator secret (>= 32 bytes, any format) into the AES-256 key."""
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=_KDF_INFO).derive(secret)


class AESGCMRequestStateCodec:
    """Built-in codec: AES-256-GCM under key(s) derived with HKDF-SHA256.

    The token is opaque: contents are encrypted, not merely signed, so clients
    (and anything that logs the wire) cannot read resolver keys, elicited
    answers, or whatever a manual flow put in its state. `keys[0]` seals; all
    keys unseal (rotation, see `RequestStateSecurity`). Each token carries a
    4-byte non-secret fingerprint of its key, so verification is an O(1) ring
    lookup — never trial decryption. Key bytes are copied at construction, so
    later mutation of a caller-held bytearray has no effect.

    The "v1." prefix and the key fingerprint are fed into the GCM associated
    data, so both are bound under the authentication tag: a v1 token cannot be
    replayed into a future "v2." format, nor transplanted across ring slots
    (RFC 8725 discipline — the token never names an algorithm; the version
    prefix pins the whole construction server-side). Authentication failure is
    constant-time inside the AEAD primitive, and every failure raises
    `InvalidRequestState` with a log-only reason code.
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


# The multi-round-trip carriers — the only methods whose results may carry
# `requestState`. Single source: the monolith result map in `mcp_types.methods`.
_MRTR_METHODS = INPUT_REQUIRED_METHODS
_ENVELOPE_VERSION = 1
_FUTURE_SKEW = 60.0
_PRINCIPAL_LABEL = b"mcp/request-state/principal:"

_RoundBinding = tuple[str, str, str | None]
"""(target, args-digest, principal) one round's envelope binds — computed once per round."""


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

    Explicit per-method allowlist (never a denylist): tools/call and
    prompts/get bind name + arguments; resources/read binds the uri. Retry-only
    fields (inputResponses, requestState, _meta) are structurally excluded, and
    a future wire field cannot silently join the digest.
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
    # A wrong-length claim cannot match: the recomputed 16-byte tag never
    # equals a differently-sized remainder (compare_digest handles the sizes).
    expected = hashlib.sha256(_PRINCIPAL_LABEL + raw[:8] + principal.encode()).digest()[:16]
    return hmac.compare_digest(raw[8:], expected)


class RequestStateBoundary:
    """Server middleware sealing/unsealing `requestState` at the wire boundary.

    Inbound: a request presenting `requestState` (any non-null value, on any
    method) is handled before any extension interceptor or handler runs. On the
    multi-round-trip carriers (tools/call, prompts/get, resources/read) the
    value is verified (codec unseal + claims check: version, mint-time skew,
    expiry, method, target, argument digest, audience, principal) and replaced
    with the plaintext the server originally minted. Every other method has no
    legal carrier for the field, so the request is rejected outright.
    Verification failure answers a wire-level -32602 with the frozen message
    "Invalid or expired requestState"; the underlying reason goes to the server
    log only.

    Outbound: an `input_required` result carrying `requestState` on a
    multi-round-trip carrier has it sealed inside a fresh claims envelope; on
    any other method an emission is a server bug answered as an internal error,
    never silent plaintext. Handlers and resolvers write plaintext and never
    call the codec themselves.

    `default_audience` seeds the envelope's audience claim when the policy does
    not set its own `audience`. `MCPServer` passes its server name, so two
    services sharing (or accidentally reusing) a key reject each other's state
    by default.

    `ctx.params` is the raw, unvalidated wire mapping (no model validation has
    happened yet), so the field is the camelCase wire key "requestState"; the
    inbound rewrite replaces that key on a copy of the params and forwards it
    with `dataclasses.replace(ctx, params=...)` — the rewrite contract
    `ServerMiddleware` sanctions.

    `MCPServer` installs this automatically from `request_state_security=`.
    Lowlevel `Server` users append one to `server.middleware` — they get the
    identical claims enforcement; nothing is private to MCPServer.

    With `security=None` (an `MCPServer` that has no MRTR registrations and no
    configuration) the boundary fails safe at runtime: inbound `requestState`
    is rejected — this server never minted one — and an outbound emission is a
    server bug answered as an internal error, never silent plaintext. Declared
    MRTR surfaces never reach that branch — registration already failed at
    construction (see the startup gate) — while statically-undetectable cases
    (unannotated returns, TYPE_CHECKING-only annotations, wrapped functions)
    land on the loud runtime error instead.
    """

    def __init__(self, security: RequestStateSecurity | None, *, default_audience: str | None = None) -> None:
        self._security = security
        self._audience = (
            security.audience if security is not None and security.audience is not None else default_audience
        )

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        binding: _RoundBinding | None = None
        if ctx.params is not None and ctx.params.get("requestState") is not None:
            # An explicit JSON null is the field's absence (a fresh flow): only
            # presented state is verified, and stripping the field is already
            # in any client's power.
            if ctx.method not in _MRTR_METHODS:
                _reject(ctx.method, "requestState on a non-MRTR method")
            plaintext, binding = self._unseal(ctx)
            ctx = replace(ctx, params={**ctx.params, "requestState": plaintext})
        result = await call_next(ctx)
        return self._seal_result(ctx, result, binding)

    # -- inbound ------------------------------------------------------------

    def _unseal(self, ctx: ServerRequestContext[Any, Any]) -> tuple[str, _RoundBinding | None]:
        assert ctx.params is not None
        wire = ctx.params["requestState"]
        if not isinstance(wire, str):
            _reject(ctx.method, "non-string requestState")
        security = self._security
        if security is None:
            _reject(ctx.method, "requestState received but no request_state_security is configured")
        if security.is_unprotected:
            return wire, None
        assert security.codec is not None
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
        # Accept-conditions are stated positively so a claim that defeats
        # comparison (a NaN smuggled through a weak custom codec) reads as
        # unproven and rejects.
        if not isinstance(iat, int | float) or not (iat <= now + _FUTURE_SKEW):
            _reject(ctx.method, "minted in the future")
        if not isinstance(exp, int | float) or not (now < exp):
            _reject(ctx.method, "expired")
        target, args_digest = _request_identity(ctx.method, ctx.params)
        if claims.get("m") != ctx.method or claims.get("t") != target or claims.get("a") != args_digest:
            _reject(ctx.method, "request binding")
        if claims.get("aud") != self._audience:
            _reject(ctx.method, "audience")  # fail closed in BOTH directions
        try:
            principal = security.bind_principal(ctx) if security.bind_principal is not None else None
        except Exception:  # deny-on-error: a raising principal binding must fail closed
            logger.exception("bind_principal raised while verifying requestState on %s", ctx.method)
            _reject(ctx.method, "principal binding error")
        claim = claims.get("p")
        if (claim is None) != (principal is None):
            _reject(ctx.method, "principal drift")  # fail closed in BOTH directions
        if claim is not None and principal is not None:
            if not isinstance(claim, str) or not _principal_matches(claim, principal):
                _reject(ctx.method, "principal")
        return inner, (target, args_digest, principal)

    # -- outbound -----------------------------------------------------------

    def _seal_result(
        self, ctx: ServerRequestContext[Any, Any], result: HandlerResult, binding: _RoundBinding | None
    ) -> HandlerResult:
        # Results arrive as wire mappings on the spec path (serialization runs
        # inside the chain); a middleware short-circuiting below the boundary
        # may return a model. Both shapes are sealed.
        if not is_input_required(result):
            return result
        state = result.get("requestState") if isinstance(result, Mapping) else result.request_state
        if state is None:
            return result
        if ctx.method not in _MRTR_METHODS:
            logger.error(
                "handler for %s returned an input_required result carrying requestState, but the spec "
                "restricts InputRequiredResult to tools/call, prompts/get, and resources/read; extension "
                "and custom methods must not mint requestState. Refusing to send it.",
                ctx.method,
            )
            raise MCPError(code=INTERNAL_ERROR, message="Internal error")
        if isinstance(result, Mapping):
            if not isinstance(state, str):
                # Only a short-circuiting middleware can put a non-string here
                # (the spec path validated the field as a string); there is no
                # state for this module to seal.
                return result
            return {**result, "requestState": self._seal(ctx, state, binding)}
        return result.model_copy(update={"request_state": self._seal(ctx, state, binding)})

    def _seal(self, ctx: ServerRequestContext[Any, Any], state: str, binding: _RoundBinding | None = None) -> str:
        security = self._security
        if security is None:
            # Reachable only by an *undeclared* dynamic InputRequiredResult
            # return (declared surfaces already failed at construction). Never
            # emit unprotected state silently; tell the operator exactly what
            # to do, in the log, and fail the request.
            logger.error(
                "handler for %s returned an InputRequiredResult with requestState, but no "
                "request_state_security is configured on this server; refusing to send unprotected "
                "state. Pass request_state_security=RequestStateSecurity(...) to MCPServer "
                "(or .ephemeral() for single-process, or .unprotected() to accept the risk).",
                ctx.method,
            )
            raise MCPError(code=INTERNAL_ERROR, message="Internal error")
        if security.is_unprotected:
            return state
        assert security.codec is not None
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
