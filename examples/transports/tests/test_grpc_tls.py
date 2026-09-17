import ipaddress
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from typing import Literal

import anyio
import grpc
import grpc.aio
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from mcp import Client, MCPError
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    CONNECTION_CLOSED,
    PROTOCOL_VERSION_META_KEY,
    CallToolRequestParams,
    CallToolResult,
    Implementation,
)

from mcp_transport_examples.grpc import grpc_client, grpc_server
from mcp_transport_examples.grpc_context import GRPCContext
from mcp_transport_examples.rpc_pb2 import CallEvent, CallRequest


def certificate(
    name: str,
    key: ec.EllipticCurvePrivateKey,
    issuer: x509.Name,
    issuer_key: ec.EllipticCurvePrivateKey,
    *,
    ca: bool = False,
    server: bool = False,
) -> bytes:
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if not ca:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
    if server:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False
        )
    return builder.sign(issuer_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


def private_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


@pytest.mark.anyio
@pytest.mark.parametrize("security", ["insecure", "tls", "mtls", "missing-certificate", "untrusted-certificate"])
async def test_peer_identity_comes_from_tls_not_caller_claims(
    security: Literal["insecure", "tls", "mtls", "missing-certificate", "untrusted-certificate"],
) -> None:
    """SDK-defined: native identity ignores caller claims; rejected TLS peers never reach middleware.

    Steps: 1. Make a typed client call. 2. Check authenticated or anonymous identity.
    3. Inject identity-looking RPC metadata, which the typed client cannot supply, and check identity again.
    """
    root_key = ec.generate_private_key(ec.SECP256R1())
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test root")])
    root_cert = certificate("test root", root_key, root_name, root_key, ca=True)
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_cert = certificate("test server", server_key, root_name, root_key, server=True)
    client_key = ec.generate_private_key(ec.SECP256R1())
    issuer_key = ec.generate_private_key(ec.SECP256R1()) if security == "untrusted-certificate" else root_key
    client_cert = certificate("alice", client_key, root_name, issuer_key)
    client_info = Implementation(name="bob", version="1").model_dump(by_alias=True, exclude_none=True)
    reached: list[str] = []
    claims: list[str | bytes | None] = []

    async def observe(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
        assert isinstance(ctx.transport, GRPCContext)
        assert ctx.params is not None
        assert ctx.params["_meta"][CLIENT_INFO_META_KEY] == client_info
        reached.append(ctx.method)
        claims.append(dict(ctx.transport.metadata).get("x509_common_name"))
        return await call_next(ctx)

    server = MCPServer("TLS", middleware=[observe])

    @server.tool()
    async def identity(ctx: Context) -> dict[str, str | list[str] | None]:
        assert ctx.request_context.method == "tools/call"
        assert isinstance(ctx.transport, GRPCContext)
        return {
            "key": ctx.transport.peer_identity_key,
            "identities": [value.decode("utf-8") for value in ctx.transport.peer_identities],
        }

    with anyio.fail_after(5):
        async with AsyncExitStack() as stack:
            listener = grpc.aio.server()
            credentials = grpc.ssl_server_credentials(
                [(private_bytes(server_key), server_cert)],
                root_certificates=root_cert,
                require_client_auth=security != "tls",
            )
            port = (
                listener.add_insecure_port("127.0.0.1:0")
                if security == "insecure"
                else listener.add_secure_port("127.0.0.1:0", credentials)
            )
            stack.push_async_callback(listener.stop, 0)
            runtime = await stack.enter_async_context(server.serve())
            await runtime.connect(grpc_server(listener))
            await listener.start()
            present_certificate = security in ("mtls", "untrusted-certificate")
            channel_credentials = grpc.ssl_channel_credentials(
                root_certificates=root_cert,
                private_key=private_bytes(client_key) if present_certificate else None,
                certificate_chain=client_cert if present_certificate else None,
            )
            channel = await stack.enter_async_context(
                grpc.aio.insecure_channel(f"127.0.0.1:{port}")
                if security == "insecure"
                else grpc.aio.secure_channel(f"127.0.0.1:{port}", channel_credentials)
            )
            client = await stack.enter_async_context(
                Client(grpc_client(channel), mode="2026-07-28", client_info=Implementation(name="bob", version="1"))
            )
            if security in ("missing-certificate", "untrusted-certificate"):
                with pytest.raises(MCPError) as exc:
                    await client.call_tool("identity")
                assert exc.value.code == CONNECTION_CLOSED
                assert reached == []
            else:
                result = await client.call_tool("identity")
                assert result.structured_content == {
                    "key": "x509_common_name" if security == "mtls" else None,
                    "identities": ["alice"] if security == "mtls" else [],
                }
                assert "tools/call" in reached
                assert all(claim is None for claim in claims)
                rpc = channel.unary_stream(
                    "/mcp.transport.example.MCP/Call",
                    request_serializer=CallRequest.SerializeToString,
                    response_deserializer=CallEvent.FromString,
                )
                params = CallToolRequestParams(
                    name="identity",
                    _meta={
                        PROTOCOL_VERSION_META_KEY: "2026-07-28",
                        CLIENT_CAPABILITIES_META_KEY: {},
                        CLIENT_INFO_META_KEY: client_info,
                    },
                )
                request = CallRequest(
                    method="tools/call",
                    params_json=params.model_dump_json(by_alias=True).encode("utf-8"),
                    request_id_json=b"1",
                )
                events = [event async for event in rpc(request, metadata=(("x509_common_name", "mallory"),))]
                assert len(events) == 1
                forged = CallToolResult.model_validate_json(events[0].result_json)
                assert forged.structured_content == result.structured_content
                assert claims[-1] == "mallory"
