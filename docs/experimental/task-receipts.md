# Task completion receipts

MCP clients and servers can exchange rich task and tool data, but a task result is not always the same thing as an auditable completion state.

For safety-sensitive workflows, consider adding a small receipt to the end of a task or tool-driven workflow. A receipt separates what the agent or tool claims from the evidence that supports the claim, the next owner, and any human approval boundary.

## Why this matters

A final task message such as:

```text
Done. All tests passed. Ready to publish.
```

contains multiple operational claims:

- the task is complete
- tests passed
- the output is ready for an external action

Those claims may require different evidence, such as tool output, logs, file diffs, test output, trace items, or human approval.

## Minimal receipt shape

```yaml
status_code: 412
status_text: missing_evidence
summary: "The task claimed completion and test success, but did not attach command output."
claims:
  - claim: "Task is complete."
    support_status: unverified
    evidence: []
    required_fix: "Attach the relevant tool result, file diff, log, or trace item."
  - claim: "All tests passed."
    support_status: unsupported
    evidence: []
    required_fix: "Attach the test command and output, or downgrade the claim."
next_owner: ProducingAgent
human_decision_required: false
```

## Safety boundaries

Receipts are useful when a task result may cross a boundary:

- publishing or deploying
- writing to long-term memory
- sending messages or comments
- spending money
- changing external systems
- reporting tests or verification as complete

If a boundary requires approval, the receipt should say so explicitly:

```yaml
human_decision_required: true
required_fix: "Require approval before publishing."
```

## Relationship to MCP data

MCP data can provide evidence for a receipt:

```text
tool result -> evidence item
task state -> status code
client/server trace -> evidence path
approval or user confirmation -> human approval evidence
```

The receipt does not replace MCP protocol messages. It is a final-state summary that helps humans and downstream systems audit whether a completion claim is supported.

Reference protocol:

```text
SACP: https://github.com/aDragon0707/sacp
```
