"""Tests for the model client (i18n/client.py): auth, request assembly, reply and error handling."""

import anthropic
import httpx
import pytest
from anthropic.types import Message as ApiMessage
from anthropic.types import StopReason, TextBlock, ThinkingBlock, Usage

from i18n.client import Message, TranslatorError, api_failure, credentials, message_request, reply_text
from i18n.config import ConfigError

_REQUEST = httpx.Request("POST", "https://api.example/v1/messages")


def _reply(*blocks: TextBlock | ThinkingBlock, stop_reason: StopReason = "end_turn") -> ApiMessage:
    return ApiMessage(
        id="msg",
        content=list(blocks),
        model="model-t",
        role="assistant",
        stop_reason=stop_reason,
        type="message",
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _status_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    return cls("nope", response=httpx.Response(status, request=_REQUEST), body=None)


def test_credentials_pick_the_single_env_var_that_is_set() -> None:
    assert credentials({"ANTHROPIC_API_KEY": "key"}) == {"api_key": "key"}
    assert credentials({"ANTHROPIC_AUTH_TOKEN": "tok"}) == {"auth_token": "tok"}


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({}, "set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN to run a command that calls the model"),
        (
            {"ANTHROPIC_API_KEY": "key", "ANTHROPIC_AUTH_TOKEN": "tok"},
            "both ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are set; set exactly one of them",
        ),
    ],
)
def test_credentials_require_exactly_one_of_the_two_env_vars(environ: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError) as failure:
        credentials(environ)

    assert str(failure.value) == message


def test_message_request_caches_the_system_block_and_sends_no_sampling_parameters() -> None:
    request = message_request(
        model="model-t", system="RULES", messages=[Message("user", "page"), Message("assistant", "ok")], max_tokens=99
    )

    assert request == {
        "model": "model-t",
        "max_tokens": 99,
        "system": [{"type": "text", "text": "RULES", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "page"}, {"role": "assistant", "content": "ok"}],
    }


def test_reply_text_joins_the_text_blocks_and_skips_thinking() -> None:
    reply = _reply(
        ThinkingBlock(type="thinking", thinking="hmm", signature="sig"),
        TextBlock(type="text", text="Hallo"),
        TextBlock(type="text", text=" Welt"),
    )

    assert reply_text(reply, max_tokens=16_000) == "Hallo Welt"


@pytest.mark.parametrize(
    ("stop_reason", "message"),
    [
        ("max_tokens", "reply truncated at the 16000-token output limit"),
        ("refusal", "model declined to answer this request"),
    ],
)
def test_reply_text_truncated_or_declined_reply_is_a_translator_error(stop_reason: StopReason, message: str) -> None:
    with pytest.raises(TranslatorError) as failure:
        reply_text(_reply(TextBlock(type="text", text=""), stop_reason=stop_reason), max_tokens=16_000)

    assert str(failure.value) == message


def test_api_failure_maps_bad_credentials_to_a_config_error() -> None:
    for cls in (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        error = api_failure(_status_error(cls, 401))
        assert isinstance(error, ConfigError) and "check ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN" in str(error)


def test_api_failure_maps_other_api_errors_to_translator_errors() -> None:
    for error in (_status_error(anthropic.InternalServerError, 500), anthropic.APIConnectionError(request=_REQUEST)):
        failure = api_failure(error)
        assert isinstance(failure, TranslatorError) and "API request failed" in str(failure)
