# events

The `io.modelcontextprotocol/events` extension: poll, push, and webhook
delivery of server-originated events on top of the `subscriptions/listen`
channel. The story will show a server emitting events and a client consuming
them over each delivery mode.

**Status: not yet implemented.** Depends on both the `subscriptions/listen`
runtime ([#2901](https://github.com/modelcontextprotocol/python-sdk/issues/2901))
and the `extensions` capability map
([#2896](https://github.com/modelcontextprotocol/python-sdk/issues/2896)) —
neither has landed.

## Spec

[Events — extensions](https://modelcontextprotocol.io/specification/draft/extensions/events)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)

## See also

`subscriptions/` (the listen channel this builds on).
