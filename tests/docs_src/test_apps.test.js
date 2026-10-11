const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const python = `
import json

import anyio

from docs_src.apps import tutorial001
from mcp import Client
from mcp.client import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.types import TextResourceContents
from stories.apps.server import RESOURCE_URI, build_server


async def main() -> None:
    cases = []
    for name, server, uri in (
        ("tutorial", tutorial001.mcp, "ui://clock/app.html"),
        ("story", build_server(), RESOURCE_URI),
    ):
        async with Client(server, extensions=[advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})]) as client:
            resource = await client.read_resource(uri)
            result = await client.call_tool("get_time", {})
        content = resource.contents[0]
        assert isinstance(content, TextResourceContents)
        assert content.mime_type == APP_MIME_TYPE
        cases.append({"name": name, "html": content.text, "result": result.model_dump(mode="json", by_alias=True)})
    print(json.dumps(cases))


anyio.run(main)
`;

const cases = JSON.parse(
  execFileSync("uv", ["run", "--frozen", "--no-sync", "python", "-c", python], {
    cwd: root,
    encoding: "utf8",
    env: {
      ...process.env,
      PYTHONPATH: [root, path.join(root, "examples"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  }),
);

for (const { name, html, result } of cases) {
  test(`${name} clock shows the tool-result notification`, () => {
    const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
    assert.ok(script);
    const clock = { textContent: "..." };
    let onMessage;
    vm.runInNewContext(script, {
      window: {
        addEventListener(type, handler) {
          assert.equal(type, "message");
          onMessage = handler;
        },
      },
      document: {
        getElementById(id) {
          assert.equal(id, "now");
          return clock;
        },
      },
    });

    assert.equal(typeof onMessage, "function");
    onMessage({ data: { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: result } });
    assert.equal(clock.textContent, result.content[0].text);
  });
}
