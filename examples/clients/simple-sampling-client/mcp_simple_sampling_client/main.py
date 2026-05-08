"""MCP client that fulfils server-initiated sampling via a real LLM.

Answers the questions raised in issue
https://github.com/modelcontextprotocol/python-sdk/issues/1205 by wiring
an actual LLM call into the ClientSession `sampling_callback` and
showing how each advisory field in `CreateMessageRequestParams` should
be interpreted.

The LLM backend is deliberately provider-agnostic: we speak the
OpenAI-compatible `/chat/completions` schema over httpx, so the example
runs against OpenAI, Groq, OpenRouter, Ollama, vLLM, or any other
gateway that honours the same contract. Users swap providers by
changing environment variables rather than code — maintainer feedback
on earlier attempts flagged provider-specific SDKs as a no-go for the
examples directory.
"""

from __future__ import annotations

import logging
import os
import shlex
from typing import Any

import anyio
import click
import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.context import ClientRequestContext
from mcp.client.stdio import stdio_client

logger = logging.getLogger("mcp-simple-sampling-client")

# Defaults point at Groq because it has a generous free tier and speaks the
# OpenAI-compatible schema. Override via env vars to target any other
# provider without editing this file.
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Minimal mapping from OpenAI's `finish_reason` to MCP's `stop_reason`.
# Both are advisory strings, so missing entries round-trip unchanged
# rather than raising.
_FINISH_REASON_TO_STOP_REASON: dict[str, str] = {
    "stop": "endTurn",
    "length": "maxTokens",
    "content_filter": "endTurn",
}


class LLMClient:
    """Thin async wrapper over an OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, *, api_key: str, base_url: str, default_model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    def pick_model(self, preferences: types.ModelPreferences | None) -> str:
        # modelPreferences are advisory per spec: "The client MAY ignore
        # them." We treat the first usable hint as a soft override and
        # fall back to LLM_MODEL. Numeric priorities are not used to
        # pick a model here — that would require a catalogue of available
        # models, which is provider-specific — but we log them so the
        # user can see what the server asked for.
        if preferences is None:
            return self.default_model
        if (
            preferences.cost_priority is not None
            or preferences.speed_priority is not None
            or (preferences.intelligence_priority is not None)
        ):
            logger.info(
                "Server model priorities — cost=%s speed=%s intelligence=%s",
                preferences.cost_priority,
                preferences.speed_priority,
                preferences.intelligence_priority,
            )
        if preferences.hints:
            for hint in preferences.hints:
                if hint.name:
                    return hint.name
        return self.default_model

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float | None,
        stop_sequences: list[str] | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if stop_sequences:
            payload["stop"] = stop_sequences
        if metadata:
            # OpenAI's schema accepts arbitrary metadata for provider-side
            # logging. Non-OpenAI gateways typically ignore unknown keys
            # rather than rejecting them, so a raw passthrough is safe.
            payload["metadata"] = metadata

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60.0) as http:
            response = await http.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()


def _sampling_messages_to_openai(messages: list[types.SamplingMessage]) -> list[dict[str, Any]]:
    """Flatten MCP SamplingMessages into OpenAI-style chat messages.

    MCP allows a message `content` to be either a single block or a list
    of mixed blocks (text/image/audio). This example only forwards text;
    other block types are surfaced to the LLM as a placeholder so the
    conversation stays coherent without silently dropping content. A
    production client would either forward image URLs/base64 directly or
    refuse the request with an ErrorData response.
    """
    converted: list[dict[str, Any]] = []
    for message in messages:
        parts: list[str] = []
        for block in message.content_as_list:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(f"[{block.type} content omitted]")
        converted.append({"role": message.role, "content": "\n".join(parts)})
    return converted


class SamplingHandler:
    """Implements the ClientSession `sampling_callback` protocol."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def __call__(
        self,
        context: ClientRequestContext,
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        # includeContext asks the client to attach context from its other
        # active sessions. A real multi-server client would query its
        # session registry here and prepend the relevant context to the
        # prompt. We only log the request so the example stays a single
        # file, but the hook point is this branch.
        if params.include_context and params.include_context != "none":
            logger.info(
                "Server requested includeContext=%s — real clients would inject session context here",
                params.include_context,
            )

        model = self.llm.pick_model(params.model_preferences)
        try:
            raw = await self.llm.chat(
                messages=_sampling_messages_to_openai(params.messages),
                model=model,
                system_prompt=params.system_prompt,
                max_tokens=params.max_tokens,
                temperature=params.temperature,
                stop_sequences=params.stop_sequences,
                metadata=params.metadata,
            )
        except httpx.HTTPError:
            # Callback contracts require returning ErrorData on failure
            # rather than raising — the session turns an exception into a
            # transport-level error, which is less useful to the server.
            logger.exception("LLM provider call failed")
            return types.ErrorData(code=types.INTERNAL_ERROR, message="LLM provider call failed")

        choice = raw["choices"][0]
        finish_reason = choice.get("finish_reason")
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=choice["message"]["content"]),
            model=raw.get("model", model),
            stop_reason=_FINISH_REASON_TO_STOP_REASON.get(finish_reason, finish_reason),
        )


async def _run(server_command: str, server_args: list[str], tool_arguments: dict[str, Any]) -> None:
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise click.UsageError("LLM_API_KEY is required; see README for provider setup.")
    base_url = os.environ.get("LLM_API_BASE_URL", DEFAULT_BASE_URL)
    default_model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    sampling = SamplingHandler(LLMClient(api_key=api_key, base_url=base_url, default_model=default_model))
    params = StdioServerParameters(command=server_command, args=server_args)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, sampling_callback=sampling) as session:
            await session.initialize()
            tools = await session.list_tools()
            if not tools.tools:
                click.echo("Server exposes no tools; nothing to demo.")
                return
            tool = tools.tools[0]
            click.echo(f"Calling tool '{tool.name}' with {tool_arguments}")
            result = await session.call_tool(tool.name, tool_arguments)
            for block in result.content:
                if isinstance(block, types.TextContent):
                    click.echo(block.text)


@click.command()
@click.option(
    "--server-command",
    default="uv",
    show_default=True,
    help="Executable that launches the MCP server over stdio.",
)
@click.option(
    "--server-args",
    default="run mcp-simple-sampling",
    show_default=True,
    help="Arguments for server-command; split with POSIX shell rules.",
)
@click.option(
    "--topic",
    default="a lighthouse keeper",
    show_default=True,
    help="Story topic forwarded to the server's write_story tool.",
)
def main(server_command: str, server_args: str, topic: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    anyio.run(_run, server_command, shlex.split(server_args), {"topic": topic})
    return 0


if __name__ == "__main__":
    main()
