"""List prompts, autocomplete an argument, then render both prompts."""

from mcp.client import Client
from mcp.types import PromptReference, TextContent
from stories._harness import connect_from_args, run_client


async def scenario(client: Client) -> None:
    listed = await client.list_prompts()
    by_name = {p.name: p for p in listed.prompts}
    assert set(by_name) == {"greet", "code_review"}
    assert by_name["greet"].arguments is not None
    assert [a.name for a in by_name["greet"].arguments] == ["name"]
    assert by_name["greet"].arguments[0].required is True
    assert by_name["code_review"].title == "Code Review"

    completion = await client.complete(
        PromptReference(name="code_review"),
        argument={"name": "language", "value": "py"},
    )
    assert completion.completion.values == ["python", "pytorch"], completion

    greeted = await client.get_prompt("greet", {"name": "Ada"})
    assert len(greeted.messages) == 1
    assert greeted.messages[0].role == "user"
    assert isinstance(greeted.messages[0].content, TextContent)
    assert "Ada" in greeted.messages[0].content.text

    reviewed = await client.get_prompt("code_review", {"language": "rust", "code": "fn main() {}"})
    assert [m.role for m in reviewed.messages] == ["user", "assistant"]
    first = reviewed.messages[0].content
    assert isinstance(first, TextContent)
    assert "rust" in first.text and "fn main() {}" in first.text


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
