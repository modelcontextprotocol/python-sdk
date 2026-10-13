const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const cases = [
  ["tutorial", "docs_src/apps/tutorial001.py"],
  ["story", "examples/stories/apps/server.py"],
];

for (const [name, file] of cases) {
  test(`${name} clock shows CallToolResult from notification params per the MCP Apps spec`, () => {
    const source = readFileSync(path.join(root, file), "utf8");
    const html = source.match(/CLOCK_HTML = """([\s\S]*?)"""/)?.[1];
    assert.ok(html);
    const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
    const result = { content: [{ type: "text", text: "2026-06-26T12:00:00Z" }] };
    assert.ok(script);
    const clock = { textContent: "..." };
    const sent = [];
    const parent = { postMessage: (message) => sent.push(message) };
    let onMessage;
    vm.runInNewContext(script, {
      window: {
        parent,
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
    assert.equal(sent[0].method, "ui/initialize");
    assert.equal(sent[0].params.protocolVersion, "2026-01-26");
    assert.equal(sent[0].params.appInfo.name, "clock");

    const notification = { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: result };
    onMessage({ source: parent, data: notification });
    assert.equal(clock.textContent, "...");

    onMessage({ source: parent, data: { jsonrpc: "2.0", id: sent[0].id, result: { protocolVersion: "2026-01-26" } } });
    assert.equal(sent[1].method, "ui/notifications/initialized");
    onMessage({ source: {}, data: notification });
    assert.equal(clock.textContent, "...");
    onMessage({ source: parent, data: { ...notification, method: "ui/notifications/tool-input" } });
    assert.equal(clock.textContent, "...");
    onMessage({ source: parent, data: notification });
    assert.equal(clock.textContent, result.content[0].text);
  });
}
