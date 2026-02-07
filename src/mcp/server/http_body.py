from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

DEFAULT_MAX_BODY_BYTES = 1_000_000


@dataclass(frozen=True)
class BodyTooLargeError(Exception):
    max_body_bytes: int

    def __str__(self) -> str:
        return f"Request body exceeds max_body_bytes={self.max_body_bytes}"


async def read_request_body(request: Request, *, max_body_bytes: int | None = DEFAULT_MAX_BODY_BYTES) -> bytes:
    """Read an HTTP request body with a hard cap.

    Notes:
    - This avoids unbounded buffering of the request body in Python.
    - If the body exceeds max_body_bytes, this raises BodyTooLargeError as soon
      as possible.
    """
    if max_body_bytes is None:
        return await request.body()

    if max_body_bytes <= 0:
        raise ValueError("max_body_bytes must be positive or None")

    # Fast-path: reject based on Content-Length when provided.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_body_bytes:
                raise BodyTooLargeError(max_body_bytes)
        except ValueError:
            # Ignore invalid Content-Length; we'll enforce while streaming.
            pass

    body = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue

        # Never buffer more than max_body_bytes bytes.
        remaining = max_body_bytes - len(body)
        if remaining <= 0:
            raise BodyTooLargeError(max_body_bytes)
        if len(chunk) > remaining:
            body.extend(chunk[:remaining])
            raise BodyTooLargeError(max_body_bytes)

        body.extend(chunk)

    return bytes(body)
