"""The "todos" demo application — a Python port of the TypeScript SDK's reference todos-server.

It is a small but believable application (a project todo board) where every MCP feature has
a job: CRUD tools the model calls from chat, the board and each task exposed as resources,
planning/seeding prompts, a sampling-backed `prioritize` tool that borrows the *host's*
model, elicitation-confirmed `clear_done` and `brainstorm_tasks`, and logging/progress while
it works. State is in-memory and per-process; the point is the wiring, not the persistence.
The transport entry point that serves this over stdio / Streamable HTTP is server.py.

The server speaks both protocol revisions from the same handlers: the interactive tools ask
through resolver dependencies (`Resolve`/`Elicit`/`Sample`), and the framework carries the
questions as `InputRequiredResult` rounds on 2026-07-28 connections or as push-style
elicitation/sampling requests on pre-2026 ones.
"""

import itertools
import math
import os
import re
import warnings
from dataclasses import dataclass
from typing import Annotated, Literal

import anyio
from mcp import MCPDeprecationWarning
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions
from mcp.server.mcpserver import (
    AcceptedElicitation,
    Context,
    Elicit,
    ElicitationResult,
    MCPServer,
    RequestStateSecurity,
    Resolve,
    Sample,
)
from mcp.server.mcpserver.prompts.base import AssistantMessage, Message, UserMessage
from mcp.server.stdio import stdio_server
from mcp_types import (
    LOG_LEVEL_META_KEY,
    CallToolResult,
    Completion,
    CompletionArgument,
    CompletionContext,
    CreateMessageResult,
    EmptyResult,
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


# The requestState that carries brainstorm_tasks' multi-round progress between rounds is
# minted by the resolver framework and sealed by the server (encrypt + verify, with TTL and
# request binding), so a client cannot forge or mutate the recorded answers. The key comes
# from the environment for real deployments and falls back to a per-process one for the
# zero-setup demo (which is fine because one process serves every round).
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
# The three interactive tools (clear_done, prioritize, brainstorm_tasks) ask through resolver
# dependencies: a tool parameter annotated `Annotated[T, Resolve(fn)]` is filled by running `fn`
# before the tool body, and a resolver that returns `Elicit(...)` or `Sample(...)` has the
# framework put the question to the client — carried inside `InputRequiredResult` rounds on
# 2026-07-28 connections, sent as push-style requests on pre-2026 ones, with the multi-round
# state sealed by the server. Every answer is pinned to the exact question render it accepted,
# so a resolver whose question embeds board state (the done count, the open-task titles) never
# consumes a stale answer: if the board changes between rounds, the framework re-asks instead.


class ClearConfirmation(BaseModel):
    confirm: Annotated[bool, Field(title="Delete all completed tasks?", description="This cannot be undone.")]


class BrainstormCountForm(BaseModel):
    # The schema advertises the default so hosts pre-fill the field, but validation must keep an
    # omitted answer distinguishable (None): the theme fallback chain is form answer, then the
    # tool's own theme argument, then the default.
    theme: Annotated[
        str | None, Field(title="Theme for the invented tasks", json_schema_extra={"default": DEFAULT_THEME})
    ] = None
    count: Annotated[Literal["5", "10", "20", "50", "custom"], Field(title="How many tasks should I invent?")]


class BrainstormCustomCountForm(BaseModel):
    # camelCase so the form's wire schema matches the TypeScript reference server's.
    customCount: Annotated[int, Field(title="Custom amount", ge=1, le=100)]


def text_result(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=is_error)


def sampled_text(result: CreateMessageResult | None) -> str:
    """Read the text content from a sampling (createMessage) result."""
    if result is not None and isinstance(result.content, TextContent):
        return result.content.text
    return ""


def build_brainstorm_sampling(topic: str, wanted: int) -> Sample:
    return Sample(
        [
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=f'Invent {wanted} todo tasks for the theme "{topic}".'),
            )
        ],
        system_prompt=(
            "You invent short, funny todo items for a given theme. For engineering-flavored themes, lean into "
            'in-jokes like "Migrate the galactron database to omegastar" or "Ensure the tiddlywinks service speaks '
            'gRPC". Reply with one task per line, no numbering, no commentary.'
        ),
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


def ask_count() -> Elicit[BrainstormCountForm]:
    return Elicit("Let me invent some tasks for the board.", BrainstormCountForm)


def ask_custom_count(
    count_form: Annotated[ElicitationResult[BrainstormCountForm], Resolve(ask_count)],
) -> Elicit[BrainstormCustomCountForm] | None:
    if isinstance(count_form, AcceptedElicitation) and count_form.data.count == "custom":
        return Elicit("How many exactly?", BrainstormCustomCountForm)
    return None


BrainstormOrder = tuple[int, str]
"""(wanted, topic) once the forms settle; the bow-out action string ("decline"/"cancel") otherwise."""


def resolve_brainstorm_order(
    theme: str | None,
    count_form: Annotated[ElicitationResult[BrainstormCountForm], Resolve(ask_count)],
    custom_form: Annotated[ElicitationResult[BrainstormCustomCountForm], Resolve(ask_custom_count)],
) -> BrainstormOrder | str:
    """Reduce the form answers to (wanted, topic), or to the answer's action when the user bowed out.

    The theme can come from the model (tool argument) or from the user (the form's theme field,
    pre-filled with a default); the user's answer wins.
    """
    if not isinstance(count_form, AcceptedElicitation):
        return count_form.action
    answered_theme = (count_form.data.theme or "").strip()
    topic = answered_theme or (theme if theme is not None else DEFAULT_THEME)
    if count_form.data.count == "custom":
        if not isinstance(custom_form, AcceptedElicitation):
            return custom_form.action
        return custom_form.data.customCount, topic
    # The framework validated the answer against the form, so a preset is always a number.
    return int(count_form.data.count), topic


def sample_ideas(
    order: Annotated[BrainstormOrder | str, Resolve(resolve_brainstorm_order)],
) -> Sample | None:
    if isinstance(order, str):
        return None
    wanted, topic = order
    return build_brainstorm_sampling(topic, wanted)


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
    order: Annotated[BrainstormOrder | str, Resolve(resolve_brainstorm_order)],
    ideas: Annotated[CreateMessageResult | None, Resolve(sample_ideas)],
    ctx: Context,
) -> CallToolResult:
    if isinstance(order, str):
        return text_result(f"Nothing added (user answered: {order}).")
    wanted, topic = order
    stripped = (re.sub(r"^[-*\d.\s]+", "", line).strip() for line in sampled_text(ideas).split("\n"))
    titles = [line for line in stripped if line][:wanted]
    if not titles:
        return text_result("The model did not return any task ideas.", is_error=True)
    added = [add_task_record(title=title, project=topic) for title in titles]
    await announce_board_change(ctx)
    await log_info(ctx, f'brainstormed {len(added)} task(s) for "{topic}"')
    return text_result(f"Added {len(added)} brainstormed task(s):\n" + "\n".join(describe_task(task) for task in added))


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


def confirm_clear() -> Elicit[ClearConfirmation] | ClearConfirmation:
    """Ask only when there is something to delete.

    An empty board resolves to a non-confirmation with no round-trip, so even if tasks complete
    concurrently before the tool body runs, nothing is deleted without the user being asked.
    """
    done = sum(1 for task in tasks.values() if task.status == "done")
    if done == 0:
        return ClearConfirmation(confirm=False)
    return Elicit(f"Delete {done} completed task(s) from the board?", ClearConfirmation)


@mcp.tool(description="Delete every completed task (asks the user to confirm first)", structured_output=False)
async def clear_done(
    confirmation: Annotated[ElicitationResult[ClearConfirmation], Resolve(confirm_clear)],
    ctx: Context,
) -> str:
    done = [task for task in tasks.values() if task.status == "done"]
    if not done:
        return "No completed tasks to clear."
    if not (isinstance(confirmation, AcceptedElicitation) and confirmation.data.confirm):
        # Decline and cancel are answers — report them and stop, never ask again.
        return f"Nothing deleted (user answered: {confirmation.action})."
    for task in done:
        tasks.pop(task.id, None)
    await announce_board_change(ctx)
    await log_info(ctx, f"cleared {len(done)} completed task(s)")
    return f"Deleted {len(done)} completed task(s)."


def rank_open_tasks() -> Sample | None:
    """Ask the host's model to rank the open tasks; there is nothing to ask on an empty board."""
    candidates = open_tasks()
    if not candidates:
        return None
    return Sample(
        [
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text", text="Rank these tasks:\n" + "\n".join(f"- {task.title}" for task in candidates)
                ),
            )
        ],
        system_prompt=(
            "You prioritize todo lists. Reply with one task title per line, most important first. No commentary."
        ),
        max_tokens=400,
    )


@mcp.tool(
    description="Rank the open tasks by importance using the LLM connected to the host, and update their priorities",
    structured_output=False,
)
async def prioritize(
    ranking: Annotated[CreateMessageResult | None, Resolve(rank_open_tasks)],
    ctx: Context,
) -> str:
    # Key off the resolver's decision, not a recount: if it saw an empty board and sampled
    # nothing, don't invent priorities for tasks that appeared concurrently since.
    if ranking is None:
        return "No open tasks to prioritize."
    candidates = open_tasks()
    ranked = apply_ranking(sampled_text(ranking), candidates)
    for index, task in enumerate(ranked):
        task.priority = priority_for_rank(index, len(ranked))
    # Priorities are board-visible state — watchers and list caches must hear about it.
    await announce_board_change(ctx)
    await log_info(ctx, f"prioritize: ranked {len(ranked)} open task(s) via the host LLM")
    return f"Re-prioritized {len(ranked)} task(s):\n" + "\n".join(
        f"- {task.title} → {task.priority}" for task in ranked
    )


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
