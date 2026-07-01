"""The "todos" demo application — a Python port of the TypeScript SDK's reference todos-server.

It is a small but believable application (a project todo board) where every MCP feature has
a job: CRUD tools the model calls from chat, the board and each task exposed as resources,
planning/seeding prompts, a sampling-backed `prioritize` tool that borrows the *host's*
model, elicitation-confirmed `clear_done` and `brainstorm_tasks`, and logging/progress while
it works. State is in-memory and per-process; the point is the wiring, not the persistence.
The transport entry point that serves this over stdio / Streamable HTTP is server.py.

The server speaks both protocol revisions from the same handlers: on 2026-07-28 connections
the interactive tools return `InputRequiredResult` rounds; on pre-2026 connections the same
rounds are fulfilled as push-style elicitation/sampling requests (see `run_interactive`).
"""

import itertools
import json
import math
import os
import re
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import anyio
from mcp import MCPDeprecationWarning
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions
from mcp.server.mcpserver import Context, MCPServer, RequestStateSecurity
from mcp.server.mcpserver.prompts.base import AssistantMessage, Message, UserMessage
from mcp.server.stdio import stdio_server
from mcp_types import (
    LOG_LEVEL_META_KEY,
    CallToolResult,
    Completion,
    CompletionArgument,
    CompletionContext,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequest,
    ElicitRequestedSchema,
    ElicitRequestFormParams,
    ElicitResult,
    EmptyResult,
    InputRequiredResult,
    InputResponse,
    InputResponses,
    ListResourcesResult,
    PaginatedRequestParams,
    PromptReference,
    Resource,
    ResourceTemplateReference,
    SamplingMessage,
    SetLevelRequestParams,
    SubscribeRequestParams,
    TextContent,
    UnsubscribeRequestParams,
)
from mcp_types.version import is_version_at_least
from pydantic import BaseModel, Field

Priority = Literal["high", "medium", "low"]

BOARD_URI = "todos://board"
TASK_URI_TEMPLATE = "todos://tasks/{id}"
DEFAULT_THEME = "an engineer's week in hell"


@dataclass
class Task:
    id: str
    title: str
    project: str
    status: Literal["open", "done"] = "open"
    priority: Priority | None = None
    due: str | None = None
    notes: str | None = None


tasks: dict[str, Task] = {}
_next_id = itertools.count(1)


def add_task_record(
    title: str,
    project: str,
    priority: Priority | None = None,
    due: str | None = None,
    notes: str | None = None,
) -> Task:
    created = Task(id=f"t{next(_next_id)}", title=title, project=project, priority=priority, due=due, notes=notes)
    tasks[created.id] = created
    return created


def open_tasks() -> list[Task]:
    return [task for task in tasks.values() if task.status == "open"]


def projects() -> list[str]:
    return list(dict.fromkeys(task.project for task in tasks.values()))


def describe_task(task: Task) -> str:
    details = ", ".join(
        part
        for part in (
            f"priority: {task.priority}" if task.priority else None,
            f"due: {task.due}" if task.due else None,
            task.notes,
        )
        if part
    )
    box = "x" if task.status == "done" else " "
    suffix = f"; {details}" if details else ""
    return f"- [{box}] {task.title} ({task.id}, {task.project}{suffix})"


def render_board() -> str:
    done = [task for task in tasks.values() if task.status == "done"]
    lines = [
        "# Todo board",
        "",
        "## Open",
        *(describe_task(task) for task in open_tasks()),
        "",
        "## Done",
        *(describe_task(task) for task in done),
    ]
    return "\n".join(lines)


# The requestState carried through brainstorm_tasks' multi-round flow is written and read as
# plaintext JSON here; MCPServer seals it (encrypt + verify, with TTL and request binding)
# before it crosses the wire, so a client cannot forge or mutate the carried step/theme/count.
# The key comes from the environment for real deployments and falls back to a per-process one
# for the zero-setup demo (which is fine because one process serves every round).
_request_state_secret = os.environ.get("REQUEST_STATE_SECRET")

mcp = MCPServer(
    "todos",
    version="1.0.0",
    request_state_security=RequestStateSecurity(keys=[_request_state_secret]) if _request_state_secret else None,
    instructions=(
        "todos is a small project todo board (it starts empty). Use list_tasks to see the board, add_task / "
        "add_tasks and complete_task to change it, prioritize to rank the open tasks, brainstorm_tasks to invent "
        "themed example tasks, work_through_tasks to finish every open task with progress updates, and clear_done "
        "to remove finished ones (it asks the user for confirmation). The full board is also available as the "
        "todos://board resource, and it can be watched/subscribed to for change notifications. When the user "
        "greets you or asks what to try, suggest this tour: 1) ask to brainstorm tasks (the server asks how many — "
        "elicitation — then borrows the host model — sampling), 2) ask to prioritize the open tasks (sampling), "
        "3) run the plan-my-day prompt, 4) attach the todos://board resource as context and ask about it, 5) say "
        '"do all my tasks" and watch the progress and log notifications, 6) ask to clear completed tasks (an '
        "elicitation-confirmed bulk delete). Watching the board resource (/watch in cli-client) shows live change "
        "notifications along the way."
    ),
)


def is_modern(ctx: Context) -> bool:
    """Whether this request arrived on a 2026-07-28 (or later) connection."""
    return is_version_at_least(ctx.protocol_version or "", "2026-07-28")


# Per-resource subscriptions (pre-2026 clients call resources/subscribe; tracked here so updates
# only go to subscribers) and the logging/setLevel threshold. Both are process-wide: over stdio a
# process serves exactly one client, and over HTTP this demo shares them across sessions.
resource_subscriptions: set[str] = set()
_log_level_threshold: str | None = None

_LOG_LEVEL_ORDER = {
    "debug": 0,
    "info": 1,
    "notice": 2,
    "warning": 3,
    "error": 4,
    "critical": 5,
    "alert": 6,
    "emergency": 7,
}


async def log_info(ctx: Context, text: str) -> None:
    """Request-tied logging.

    Honours the client's logging/setLevel threshold on pre-2026 connections and the per-request
    log-level `_meta` opt-in (`io.modelcontextprotocol/logLevel`) on 2026-07-28 connections,
    where the server must not send notifications/message without it.
    """
    severity = _LOG_LEVEL_ORDER["info"]
    if is_modern(ctx):
        meta = ctx.request_context.meta
        wanted = meta.get(LOG_LEVEL_META_KEY) if meta else None
        if not isinstance(wanted, str) or _LOG_LEVEL_ORDER.get(wanted, len(_LOG_LEVEL_ORDER)) > severity:
            return
    else:
        threshold = _log_level_threshold
        if threshold is not None and _LOG_LEVEL_ORDER.get(threshold, 0) > severity:
            return
    # The logging capability is deprecated at 2026-07-28, but this notification is still the
    # only wire shape for it on both eras — the deprecation warning is expected, so silence it.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MCPDeprecationWarning)
        await ctx.log("info", text, logger_name="todos")  # pyright: ignore[reportDeprecated]


async def announce_board_change(ctx: Context) -> None:
    """Tell connected clients the board changed: the resource list, and the board resource for watchers.

    Modern (2026-07-28) clients hear about it through their `subscriptions/listen` streams — the
    `ctx.notify_*` calls publish to those and are a no-op when nobody listens. Pre-2026 clients get
    the spontaneous notifications instead. The pre-2026 notifications go to the session that made
    the mutating call: over stdio (one client per process) that is every subscriber; over HTTP
    with several concurrent pre-2026 sessions, other sessions don't hear about it — cross-session
    delivery would need connection-level bookkeeping the high-level API doesn't expose yet.
    """
    await ctx.notify_resources_changed()
    await ctx.notify_resource_updated(BOARD_URI)
    if not is_modern(ctx):
        await ctx.session.send_resource_list_changed()
        if BOARD_URI in resource_subscriptions:
            await ctx.session.send_resource_updated(BOARD_URI)


# --- Interactive flows -----------------------------------------------------------------------
#
# The three interactive tools (clear_done, prioritize, brainstorm_tasks) are written ONCE, as
# state machines over input_required rounds: `flow(responses, state)` either finishes with a
# CallToolResult or returns an InputRequiredResult naming what it still needs. On a 2026-07-28
# connection the round trips ride the wire (the client answers and retries the call, the SDK
# seals/verifies the carried state). On a pre-2026 connection there is no input_required result
# to return, so `run_interactive` runs the same flow locally, fulfilling each round as a real
# push-style elicitation/sampling request — the same job the TypeScript SDK's legacy fulfilment
# shim performs, so no handler branches on the served era.

InteractiveFlow = Callable[[InputResponses | None, str | None], Awaitable[CallToolResult | InputRequiredResult]]

ElicitContent = dict[str, str | int | float | bool | list[str] | None]


async def run_interactive(ctx: Context, flow: InteractiveFlow) -> CallToolResult | InputRequiredResult:
    """Serve one interactive tool call on either protocol era."""
    if is_modern(ctx):
        return await flow(ctx.input_responses, ctx.request_state)
    responses: InputResponses | None = None
    state: str | None = None
    for _ in range(10):
        result = await flow(responses, state)
        if isinstance(result, CallToolResult):
            return result
        responses = {}
        for key, request in (result.input_requests or {}).items():
            if isinstance(request, ElicitRequest) and isinstance(request.params, ElicitRequestFormParams):
                responses[key] = await ctx.session.elicit_form(
                    request.params.message, request.params.requested_schema, related_request_id=ctx.request_id
                )
            elif isinstance(request, CreateMessageRequest):
                # Push-style sampling is deprecated at 2026-07-28, but it is exactly what a
                # pre-2026 session speaks — the deprecation warning is expected, so silence it.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", MCPDeprecationWarning)
                    responses[key] = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
                        request.params.messages,
                        max_tokens=request.params.max_tokens,
                        system_prompt=request.params.system_prompt,
                        include_context=request.params.include_context,
                        temperature=request.params.temperature,
                        stop_sequences=request.params.stop_sequences,
                        metadata=request.params.metadata,
                        model_preferences=request.params.model_preferences,
                        related_request_id=ctx.request_id,
                    )
            else:
                raise RuntimeError(f"unsupported input request for {key!r} on a pre-2026 session")
        state = result.request_state
    raise RuntimeError("interactive flow did not settle within 10 rounds")


def text_result(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=is_error)


def elicit_response_action(response: InputResponse | None) -> str:
    """Read the action from a raw elicitation `input_responses` entry (decline/cancel detection)."""
    if isinstance(response, ElicitResult) and response.action in ("accept", "decline"):
        return response.action
    return "cancel"


def accepted_content(responses: InputResponses | None, key: str) -> ElicitContent | None:
    """The form content of an accepted elicitation response, or None for decline/cancel."""
    response = (responses or {}).get(key)
    if isinstance(response, ElicitResult) and response.action == "accept" and response.content is not None:
        return response.content
    return None


def sampled_text(response: InputResponse | None) -> str:
    """Read the text content from a raw sampling (createMessage) `input_responses` entry."""
    if isinstance(response, CreateMessageResult) and isinstance(response.content, TextContent):
        return response.content.text
    return ""


CLEAR_CONFIRM_SCHEMA: ElicitRequestedSchema = {
    "type": "object",
    "properties": {
        "confirm": {"type": "boolean", "title": "Delete all completed tasks?", "description": "This cannot be undone."}
    },
    "required": ["confirm"],
}

BRAINSTORM_COUNT_SCHEMA: ElicitRequestedSchema = {
    "type": "object",
    "properties": {
        "theme": {"type": "string", "title": "Theme for the invented tasks", "default": DEFAULT_THEME},
        "count": {
            "type": "string",
            "title": "How many tasks should I invent?",
            "enum": ["5", "10", "20", "50", "custom"],
        },
    },
    "required": ["count"],
}

BRAINSTORM_CUSTOM_COUNT_SCHEMA: ElicitRequestedSchema = {
    "type": "object",
    "properties": {"customCount": {"type": "integer", "title": "Custom amount", "minimum": 1, "maximum": 100}},
    "required": ["customCount"],
}


def build_brainstorm_sampling(topic: str, wanted: int) -> CreateMessageRequestParams:
    return CreateMessageRequestParams(
        system_prompt=(
            "You invent short, funny todo items for a given theme. For engineering-flavored themes, lean into "
            'in-jokes like "Migrate the galactron database to omegastar" or "Ensure the tiddlywinks service speaks '
            'gRPC". Reply with one task per line, no numbering, no commentary.'
        ),
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=f'Invent {wanted} todo tasks for the theme "{topic}".'),
            )
        ],
        max_tokens=min(200 + wanted * 40, 1500),
    )


# What the server claims to be doing while it "works through" a task — pure colour for the log stream.
WORK_QUIPS = [
    "applying percussive maintenance",
    "turning it off and on again",
    "blaming DNS first, investigating second",
    "negotiating with the load balancer",
    "consulting the rubber duck for a second opinion",
    "writing the postmortem in advance to save time",
    "adding a TODO to remove the TODO",
    "rolling back the rollback",
]


def parse_brainstorm_count(raw: object) -> int | None:
    """Parse an elicited count value (a preset like "10" or a custom number) into a usable number."""
    # Leading-integer parsing, like the TypeScript reference's Number.parseInt.
    match = re.match(r"\s*[+-]?\d+", str(raw))
    if match is None:
        return None
    count = int(match.group())
    return count if 1 <= count <= 100 else None


def apply_ranking(ranking_text: str, candidates: list[Task]) -> list[Task]:
    """Match the LLM's ranking (one title per line) back to tasks; unmentioned tasks keep their order at the end."""
    remaining = list(candidates)
    ranked: list[Task] = []
    for line in ranking_text.split("\n"):
        normalized = line.lower()
        for index, task in enumerate(remaining):
            if task.title.lower() in normalized:
                ranked.append(remaining.pop(index))
                break
    return ranked + remaining


def priority_for_rank(rank: int, total: int) -> Priority:
    if rank < math.ceil(total / 3):
        return "high"
    if rank < math.ceil(2 * total / 3):
        return "medium"
    return "low"


# --- Resources ---------------------------------------------------------------------------------


@mcp.resource(BOARD_URI, name="board", description="The whole todo board as markdown", mime_type="text/markdown")
def board() -> str:
    return render_board()


@mcp.resource(TASK_URI_TEMPLATE, name="task", description="A single task by id", mime_type="text/markdown")
def task_resource(id: str) -> str:
    task = tasks.get(id)
    return describe_task(task) if task else f"No task with id {id}"


# --- Prompts -----------------------------------------------------------------------------------

THEME_SUGGESTIONS = [
    "space-station maintenance",
    "wizard tower chores",
    "startup launch week",
    "engineer's week in hell",
    "robot uprising prep",
]


@mcp.prompt(
    name="seed-board",
    description="Have the assistant invent themed example tasks and add them to the board (via add_tasks)",
)
def seed_board(theme: Annotated[str, Field(description="A theme for the invented tasks")]) -> str:
    return (
        f'Invent five short, funny todo tasks for the theme "{theme}" and add them to my board with the add_tasks '
        f'tool (use "{theme}" as the project). Then show me the board.'
    )


@mcp.prompt(name="plan-my-day", description="Seed a planning conversation around the current board")
def plan_my_day(focus: Annotated[str, Field(description="Project to focus on")]) -> list[Message]:
    return [
        UserMessage(f"Here is my current todo board:\n\n{render_board()}"),
        AssistantMessage("Got it — I can see your board. What should today look like?"),
        UserMessage(
            f'Plan my day around the "{focus}" project: pick at most three tasks, in order, and say why each one '
            "is next."
        ),
    ]


@mcp.completion()
async def handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    if isinstance(ref, PromptReference):
        if ref.name == "seed-board" and argument.name == "theme":
            return Completion(values=[theme for theme in THEME_SUGGESTIONS if theme.startswith(argument.value)])
        if ref.name == "plan-my-day" and argument.name == "focus":
            return Completion(values=[project for project in projects() if project.startswith(argument.value)])
    if isinstance(ref, ResourceTemplateReference) and ref.uri == TASK_URI_TEMPLATE and argument.name == "id":
        return Completion(values=[task_id for task_id in tasks if task_id.startswith(argument.value)])
    return None


# --- Tools -------------------------------------------------------------------------------------


class AddTaskResult(BaseModel):
    id: str
    title: str
    status: Literal["open", "done"]


@mcp.tool(description="Add a task to the board")
async def add_task(
    title: Annotated[str, Field(description="What needs doing")],
    project: Annotated[str | None, Field(description='Project bucket, e.g. "ops"')] = None,
    priority: Priority | None = None,
    due: Annotated[str | None, Field(description='Free-form due date, e.g. "Friday"')] = None,
    notes: str | None = None,
    *,
    ctx: Context,
) -> Annotated[CallToolResult, AddTaskResult]:
    task = add_task_record(
        title=title,
        project=project if project is not None else "inbox",
        priority=priority,
        due=due,
        notes=notes,
    )
    await announce_board_change(ctx)
    await log_info(ctx, f"added {task.id}: {task.title}")
    return CallToolResult(
        content=[TextContent(type="text", text=f"Added {task.id}: {describe_task(task)}")],
        structured_content={"id": task.id, "title": task.title, "status": task.status},
    )


class TaskInput(BaseModel):
    title: str
    project: str | None = None
    priority: Priority | None = None
    due: str | None = None
    notes: str | None = None


@mcp.tool(description="Add several tasks to the board at once", structured_output=False)
async def add_tasks(
    tasks: Annotated[list[TaskInput], Field(min_length=1, description="Tasks to add")],
    ctx: Context,
) -> str:
    new_tasks = tasks
    added: list[Task] = []
    for index, item in enumerate(new_tasks):
        # Pretend each insert takes a moment so the host has in-flight progress to render.
        await anyio.sleep(0.1)
        added.append(
            add_task_record(
                title=item.title,
                project=item.project if item.project is not None else "inbox",
                priority=item.priority,
                due=item.due,
                notes=item.notes,
            )
        )
        await ctx.report_progress(index + 1, len(new_tasks), f'added "{item.title}"')
    await announce_board_change(ctx)
    await log_info(ctx, f"added {len(added)} task(s)")
    return f"Added {len(added)} task(s):\n" + "\n".join(describe_task(task) for task in added)


@mcp.tool(
    description=(
        "Invent short, funny example tasks for a theme and add them to the board — asks the user how many "
        "(elicitation), then has the LLM connected to the host invent them (sampling)"
    )
)
async def brainstorm_tasks(
    theme: Annotated[
        str | None, Field(description='Theme for the invented tasks (default: "an engineer\'s week in hell")')
    ] = None,
    *,
    ctx: Context,
) -> CallToolResult | InputRequiredResult:
    # The theme can come from the model (tool argument) or from the user (the elicitation form's
    # theme field, pre-filled with a default); the user's answer wins.
    fallback_topic = theme if theme is not None else DEFAULT_THEME

    def resolve_topic(raw: object) -> str:
        return raw.strip() if isinstance(raw, str) and raw.strip() else fallback_topic

    def declined(action: str) -> CallToolResult:
        return text_result(f"Nothing added (user answered: {action}).")

    async def finish(ideas_text: str, wanted: int, topic: str) -> CallToolResult:
        stripped = (re.sub(r"^[-*\d.\s]+", "", line).strip() for line in ideas_text.split("\n"))
        titles = [line for line in stripped if line][:wanted]
        if not titles:
            return text_result("The model did not return any task ideas.", is_error=True)
        added = [add_task_record(title=title, project=topic) for title in titles]
        await announce_board_change(ctx)
        await log_info(ctx, f'brainstormed {len(added)} task(s) for "{topic}"')
        return text_result(
            f"Added {len(added)} brainstormed task(s):\n" + "\n".join(describe_task(task) for task in added)
        )

    def ask_for_ideas(count: int, topic: str) -> InputRequiredResult:
        return InputRequiredResult(
            input_requests={"ideas": CreateMessageRequest(params=build_brainstorm_sampling(topic, count))},
            request_state=json.dumps({"step": "awaiting-ideas", "topic": topic, "count": count}),
        )

    # The whole conversation as a multi-round flow — written ONCE. The flow is a state machine:
    # it dispatches on the carried step (not on which input_responses key happens to be present),
    # so each round knows exactly which answer to read and which data is in scope. The state is
    # sealed by the server before it crosses the wire and verified on the echo.
    async def flow(responses: InputResponses | None, state_token: str | None) -> CallToolResult | InputRequiredResult:
        state: dict[str, Any] = json.loads(state_token) if state_token else {}
        step = state.get("step")
        if step is None:
            # First round: ask for the theme and count.
            return InputRequiredResult(
                input_requests={
                    "count": ElicitRequest(
                        params=ElicitRequestFormParams(
                            message="Let me invent some tasks for the board.",
                            requested_schema=BRAINSTORM_COUNT_SCHEMA,
                        )
                    )
                },
                request_state=json.dumps({"step": "awaiting-count"}),
            )
        if step == "awaiting-count":
            response = (responses or {}).get("count")
            accepted = accepted_content(responses, "count")
            if accepted is None:
                return declined(elicit_response_action(response))
            topic = resolve_topic(accepted.get("theme"))
            if accepted.get("count") == "custom":
                return InputRequiredResult(
                    input_requests={
                        "customCount": ElicitRequest(
                            params=ElicitRequestFormParams(
                                message="How many exactly?", requested_schema=BRAINSTORM_CUSTOM_COUNT_SCHEMA
                            )
                        )
                    },
                    request_state=json.dumps({"step": "awaiting-custom-count", "topic": topic}),
                )
            wanted = parse_brainstorm_count(accepted.get("count"))
            if wanted is None:
                return declined("cancel")
            return ask_for_ideas(wanted, topic)
        if step == "awaiting-custom-count":
            response = (responses or {}).get("customCount")
            accepted = accepted_content(responses, "customCount")
            wanted = parse_brainstorm_count(accepted.get("customCount") if accepted else None)
            if wanted is None:
                return declined(elicit_response_action(response))
            return ask_for_ideas(wanted, str(state["topic"]))
        return await finish(sampled_text((responses or {}).get("ideas")), int(state["count"]), str(state["topic"]))

    return await run_interactive(ctx, flow)


@mcp.tool(description="List tasks on the board", structured_output=False)
async def list_tasks(
    status: Annotated[
        Literal["open", "done", "all"] | None, Field(description="Which tasks to list (default: open)")
    ] = None,
    project: Annotated[str | None, Field(description="Only tasks in this project")] = None,
) -> str:
    wanted = status if status is not None else "open"
    matching = [
        task
        for task in tasks.values()
        if (wanted == "all" or task.status == wanted) and (not project or task.project == project)
    ]
    if not matching:
        return "No matching tasks."
    return "\n".join(describe_task(task) for task in matching)


@mcp.tool(description="Mark a task as done")
async def complete_task(
    task: Annotated[str, Field(description="Task id, or part of its title")],
    ctx: Context,
) -> CallToolResult:
    needle = task.lower()
    found = tasks.get(task) or next(
        (candidate for candidate in tasks.values() if needle in candidate.title.lower()), None
    )
    if found is None:
        return text_result(f'No task matches "{task}".', is_error=True)
    found.status = "done"
    await announce_board_change(ctx)
    await log_info(ctx, f"completed {found.id}: {found.title}")
    return text_result(f'Marked "{found.title}" ({found.id}) as done.')


@mcp.tool(
    description=(
        "Work through every open task one by one (simulated, a few seconds each), logging what it is "
        '"doing", reporting progress, and marking each as done'
    ),
    structured_output=False,
)
async def work_through_tasks(
    # camelCase so the wire argument name matches the TypeScript reference server's schema
    secondsPerTask: Annotated[
        float | None, Field(ge=0, le=15, description="How long to pretend each task takes (default: 3 seconds)")
    ] = None,
    *,
    ctx: Context,
) -> str:
    queue = open_tasks()
    if not queue:
        return "Nothing open — the board is already clear."
    pace_seconds = secondsPerTask if secondsPerTask is not None else 3.0
    for index, task in enumerate(queue):
        # Cancellation: when the client cancels the call (notifications/cancelled), the SDK
        # cancels this handler at its next await, so the loop stops instead of ploughing
        # through the rest of the queue.
        quip = WORK_QUIPS[index % len(WORK_QUIPS)]
        await log_info(ctx, f'working on "{task.title}" — {quip}…')
        await anyio.sleep(pace_seconds)
        task.status = "done"
        await ctx.report_progress(index + 1, len(queue), f'finished "{task.title}"')
        await announce_board_change(ctx)
    await log_info(ctx, f"worked through {len(queue)} open task(s)")
    return f"Worked through {len(queue)} task(s):\n" + "\n".join(f"- {task.title} ✔" for task in queue)


@mcp.tool(description="Delete every completed task (asks the user to confirm first)")
async def clear_done(ctx: Context) -> CallToolResult | InputRequiredResult:
    done = [task for task in tasks.values() if task.status == "done"]
    if not done:
        return text_result("No completed tasks to clear.")
    message = f"Delete {len(done)} completed task(s) from the board?"

    # A single round, written once for both eras — the first call has no responses and returns
    # the question; the re-call carries the answer. (For multi-round flows, dispatch on a carried
    # state instead — see brainstorm_tasks.)
    async def flow(responses: InputResponses | None, state_token: str | None) -> CallToolResult | InputRequiredResult:
        response = (responses or {}).get("confirmation")
        if response is None:
            return InputRequiredResult(
                input_requests={
                    "confirmation": ElicitRequest(
                        params=ElicitRequestFormParams(message=message, requested_schema=CLEAR_CONFIRM_SCHEMA)
                    )
                }
            )
        action = elicit_response_action(response)
        confirmation = accepted_content(responses, "confirmation")
        if confirmation is None or confirmation.get("confirm") is not True:
            # Decline and cancel are answers — report them and stop, never ask again.
            return text_result(f"Nothing deleted (user answered: {action}).")
        for task in done:
            tasks.pop(task.id, None)
        await announce_board_change(ctx)
        await log_info(ctx, f"cleared {len(done)} completed task(s)")
        return text_result(f"Deleted {len(done)} completed task(s).")

    return await run_interactive(ctx, flow)


@mcp.tool(
    description="Rank the open tasks by importance using the LLM connected to the host, and update their priorities"
)
async def prioritize(ctx: Context) -> CallToolResult | InputRequiredResult:
    candidates = open_tasks()
    if not candidates:
        return text_result("No open tasks to prioritize.")
    sampling_params = CreateMessageRequestParams(
        system_prompt=(
            "You prioritize todo lists. Reply with one task title per line, most important first. No commentary."
        ),
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text", text="Rank these tasks:\n" + "\n".join(f"- {task.title}" for task in candidates)
                ),
            )
        ],
        max_tokens=400,
    )

    # A single round, written once for both eras (the ranking arrives on the retried call), so no
    # carried state is needed. For multi-round flows, dispatch on a state instead — see brainstorm_tasks.
    async def flow(responses: InputResponses | None, state_token: str | None) -> CallToolResult | InputRequiredResult:
        response = (responses or {}).get("ranking")
        if response is None:
            return InputRequiredResult(input_requests={"ranking": CreateMessageRequest(params=sampling_params)})
        ranked = apply_ranking(sampled_text(response), candidates)
        for index, task in enumerate(ranked):
            task.priority = priority_for_rank(index, len(ranked))
        # Priorities are board-visible state — watchers and list caches must hear about it.
        await announce_board_change(ctx)
        await log_info(ctx, f"prioritize: ranked {len(ranked)} open task(s) via the host LLM")
        return text_result(
            f"Re-prioritized {len(ranked)} task(s):\n"
            + "\n".join(f"- {task.title} → {task.priority}" for task in ranked)
        )

    return await run_interactive(ctx, flow)


# --- Wire plumbing the high-level server does not (yet) cover -----------------------------------
#
# Three pre-2026 methods (resources/subscribe, resources/unsubscribe, logging/setLevel) and a
# dynamic resources/list have no MCPServer surface yet, so they are registered on the underlying
# low-level server — the same pattern the everything-server uses.


async def handle_subscribe(ctx: ServerRequestContext, params: SubscribeRequestParams) -> EmptyResult:
    resource_subscriptions.add(str(params.uri))
    return EmptyResult()


async def handle_unsubscribe(ctx: ServerRequestContext, params: UnsubscribeRequestParams) -> EmptyResult:
    resource_subscriptions.discard(str(params.uri))
    return EmptyResult()


async def handle_set_logging_level(ctx: ServerRequestContext, params: SetLevelRequestParams) -> EmptyResult:
    global _log_level_threshold
    _log_level_threshold = params.level
    return EmptyResult()


async def handle_list_resources(ctx: ServerRequestContext, params: PaginatedRequestParams) -> ListResourcesResult:
    # The TypeScript reference server lists every task under the todos://tasks/{id} template via
    # the template's list callback; MCPServer has no equivalent hook, so replace the resources/list
    # handler with one that appends a resource per task to the registered board resource.
    resources = await mcp.list_resources()
    resources.extend(
        Resource(
            uri=f"todos://tasks/{task.id}",
            name=task.title,
            description="A single task by id",
            mime_type="text/markdown",
        )
        for task in tasks.values()
    )
    return ListResourcesResult(resources=resources)


_lowlevel = mcp._lowlevel_server  # pyright: ignore[reportPrivateUsage]
_lowlevel.add_request_handler("resources/subscribe", SubscribeRequestParams, handle_subscribe)
_lowlevel.add_request_handler("resources/unsubscribe", UnsubscribeRequestParams, handle_unsubscribe)
_lowlevel.add_request_handler("logging/setLevel", SetLevelRequestParams, handle_set_logging_level)
_lowlevel.add_request_handler("resources/list", PaginatedRequestParams, handle_list_resources)


async def serve_stdio() -> None:
    """Serve over stdio, advertising listChanged capabilities to pre-2026 clients.

    `mcp.run()` would serve stdio too, but its pre-2026 handshake advertises
    listChanged=false for tools/prompts/resources. This server does send those
    notifications (and the TypeScript reference server advertises them), so build
    the initialization options ourselves. Over streamable HTTP the SDK offers no
    equivalent seam, so pre-2026 HTTP clients still see listChanged=false there.
    """
    init_options = _lowlevel.create_initialization_options(
        notification_options=NotificationOptions(prompts_changed=True, resources_changed=True, tools_changed=True)
    )
    async with stdio_server() as (read_stream, write_stream):
        await _lowlevel.run(read_stream, write_stream, init_options)
