# Roadmap

This document tracks planned work for the MCP Python SDK, organized by priority.

## Tier 1 Compliance (SEP-1730)

Track: achieving and maintaining Tier 1 SDK status per the [SDK Tiering System](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1730).

### Conformance
- [ ] Reach 100% client conformance pass rate (currently 94.7% — `auth/resource-mismatch` scenario fails)
- [ ] Maintain 100% server conformance pass rate

### Documentation
- [ ] Document all non-experimental MCP features with examples
- [ ] Add documentation for roots (listing and change notifications)
- [ ] Add documentation for cancellation
- [ ] Add documentation for protocol version negotiation
- [ ] Add documentation for JSON Schema 2020-12 support
- [ ] Add examples for resource subscribing/unsubscribing
- [ ] Improve elicitation documentation (enum values, complete notification, default values)
- [ ] Document ping, audio content, prompts with embedded resources and images

### Process
- [ ] Audit P0 labels to ensure they represent genuine critical bugs
- [ ] Maintain issue triage SLA (>= 90% within 2 business days)

## Spec Tracking

The SDK tracks the MCP specification and targets a release within 30 days of each new spec version.

| Spec Version | SDK Support | Notes |
|---|---|---|
| 2025-11-25 | v1.26.0 | Current stable spec |
| draft | In progress | Tracking via `main` branch |

### Upcoming Spec Features
- [ ] Structured content (`structuredContent` in tool results)
- [ ] JSON-RPC batching support
- [ ] Additional transport improvements

## SDK Improvements

- [ ] Improve low-level server API ergonomics
- [ ] Expand testing coverage for edge cases
- [ ] Performance improvements for high-throughput servers
