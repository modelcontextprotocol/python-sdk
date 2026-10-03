"""List resources and templates, then read both the static and templated URIs."""

from mcp.client import Client
from mcp.types import TextResourceContents
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        listed = await client.list_resources()
        assert [r.uri for r in listed.resources] == ["config://app"]

        templates = await client.list_resource_templates()
        assert [t.uri_template for t in templates.resource_templates] == ["greeting://{name}"]

        config = await client.read_resource("config://app")
        entry = config.contents[0]
        assert isinstance(entry, TextResourceContents)
        assert entry.text == '{"feature": true}'
        assert entry.mime_type == "application/json"

        hello = await client.read_resource("greeting://world")
        entry = hello.contents[0]
        assert isinstance(entry, TextResourceContents)
        assert entry.text == "Hello, world!"


if __name__ == "__main__":
    run_client(main)
