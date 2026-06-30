import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mcp.server import MCPServer
from mcp.server.mcpserver import InvalidRequestState, RequestStateSecurity

PREFIX = "kms1."  # format version; fed to GCM as associated data, so it is bound under the tag


def unwrap_data_key() -> bytes:
    """One KMS call at process start - kms.decrypt(CiphertextBlob=...) - then every token is local crypto."""
    return os.urandom(32)  # stand-in for the unwrapped 32-byte data key


class EnvelopeCodec:
    def __init__(self, data_key: bytes) -> None:
        self._aesgcm = AESGCM(data_key)

    def seal(self, payload: bytes) -> str:
        nonce = os.urandom(12)
        return PREFIX + (nonce + self._aesgcm.encrypt(nonce, payload, PREFIX.encode())).hex()

    def unseal(self, token: str) -> bytes:
        try:
            raw = bytes.fromhex(token.removeprefix(PREFIX))
            return self._aesgcm.decrypt(raw[:12], raw[12:], PREFIX.encode())
        except (ValueError, InvalidTag) as exc:
            raise InvalidRequestState("token failed verification") from exc


mcp = MCPServer("Deployer", request_state_security=RequestStateSecurity(codec=EnvelopeCodec(unwrap_data_key())))
