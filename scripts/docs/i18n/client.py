"""The model client behind translation and review calls.

The pipeline talks to a `Translator`: one method taking a system prompt, a
message history and a model, returning the reply text. Tests supply a fake;
`AnthropicTranslator` is the real implementation, authenticated from the
environment only and streaming every request so long pages never hit the
non-streaming request timeout. Everything the API can throw becomes a tool
error: an unusable reply is a `TranslatorError` (a per-page failure), bad
credentials are a `ConfigError` (the whole run cannot proceed).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

import anthropic
from anthropic.types import Message as ApiMessage
from anthropic.types import MessageParam, TextBlockParam

from i18n.config import ConfigError

Role = Literal["user", "assistant"]

API_KEY_ENV = "ANTHROPIC_API_KEY"
AUTH_TOKEN_ENV = "ANTHROPIC_AUTH_TOKEN"


@dataclass(frozen=True)
class Message:
    """One turn of the conversation replayed to the model."""

    role: Role
    content: str


class TranslatorError(Exception):
    """The model call did not produce a usable reply (kept out of retries the SDK handles)."""


class Translator(Protocol):
    """Anything that can answer a prompt; the tests inject a scripted fake."""

    def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> str:
        """Return the model's reply text for this conversation."""
        ...


class Credentials(TypedDict, total=False):
    """The single credential a client is built with, keyed as the SDK expects it."""

    api_key: str
    auth_token: str


class MessageRequest(TypedDict):
    """The parameters of one Messages API call."""

    model: str
    max_tokens: int
    system: list[TextBlockParam]
    messages: list[MessageParam]


def credentials(environ: Mapping[str, str]) -> Credentials:
    """The credential to authenticate with, taken from the environment.

    Raises:
        ConfigError: Neither or both of `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are set.
    """
    api_key, auth_token = environ.get(API_KEY_ENV), environ.get(AUTH_TOKEN_ENV)
    if api_key and auth_token:
        raise ConfigError(f"both {API_KEY_ENV} and {AUTH_TOKEN_ENV} are set; set exactly one of them")
    if api_key:
        return {"api_key": api_key}
    if auth_token:
        return {"auth_token": auth_token}
    raise ConfigError(f"set {API_KEY_ENV} or {AUTH_TOKEN_ENV} to run a command that calls the model")


def message_request(*, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> MessageRequest:
    """The parameters of one call: a cached system block and no sampling parameters.

    The system block is byte-identical across a language's pages, so every
    page after the first reads it from the prompt cache. Sampling parameters
    (`temperature` and friends) are never sent — current models reject them,
    and repeatability comes from the pipeline's carry-forward, not the sampler.
    """
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": message.role, "content": message.content} for message in messages],
    }


def reply_text(reply: ApiMessage, *, max_tokens: int) -> str:
    """The reply's text, or the reason there is none.

    Raises:
        TranslatorError: The reply was cut off at `max_tokens`, or the model declined to answer.
    """
    if reply.stop_reason == "max_tokens":
        raise TranslatorError(f"reply truncated at the {max_tokens}-token output limit")
    if reply.stop_reason == "refusal":
        raise TranslatorError("model declined to answer this request")
    return "".join(block.text for block in reply.content if block.type == "text")


def api_failure(error: anthropic.APIError) -> ConfigError | TranslatorError:
    """The tool error an API failure becomes: bad credentials are configuration, the rest are per-call."""
    if isinstance(error, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ConfigError(
            f"the API rejected the credentials ({error.message}); check {API_KEY_ENV} / {AUTH_TOKEN_ENV}"
        )
    return TranslatorError(f"API request failed: {error.message}")


class AnthropicTranslator:
    """`Translator` backed by the Claude Messages API."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        """Authenticate from exactly one of `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`.

        Raises:
            ConfigError: Neither or both credentials are present in the environment.
        """
        self._client = anthropic.Anthropic(**credentials(environ))

    def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> str:
        """Send the conversation and return the reply text.

        Raises:
            ConfigError: The API rejected the credentials.
            TranslatorError: The call failed, the reply was truncated, or the model declined.
        """
        request = message_request(model=model, system=system, messages=messages, max_tokens=max_tokens)
        try:
            with self._client.messages.stream(**request) as stream:
                reply = stream.get_final_message()
        except anthropic.APIError as exc:
            raise api_failure(exc) from exc
        return reply_text(reply, max_tokens=max_tokens)
