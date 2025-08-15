from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

from mcp.server.state.machine import State, InputSymbol

from mcp.server.fastmcp.tools import ToolManager
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.prompts import PromptManager
from mcp.server.fastmcp.prompts.base import Prompt
from mcp.server.fastmcp.resources import ResourceManager
from mcp.server.fastmcp.resources.base import Resource


@dataclass(frozen=True)
class ValidationIssue:
    level: str  # "error" | "warning"
    message: str


class StateMachineValidator:
    """
    Validates the structure and references of a State Machine.

    Expected manager APIs:
      - tool_manager.list_tools() -> list[Tool]
      - prompt_manager.list_prompts() -> list[Prompt]
      - resource_manager.list_resources() -> list[Resource]

    Validation checks performed:
      - Exactly one initial state is defined (and it exists in the state set).
      - Terminal states have no outgoing transitions.
      - All referenced tools/prompts/resources are registered in their managers.
      - Reachability (BFS) is computed using ONLY available artifacts.
      - At least one terminal state is reachable from the initial state.
      - Unreachable states from the initial state are reported as warnings.

    Notes:
      - Reachability uses BFS and filters transitions by available artifacts.
    """

    def __init__(
        self,
        *,
        states: dict[str, State],
        initial_state: Optional[str],
        tool_manager: ToolManager | None,
        prompt_manager: PromptManager | None,
        resource_manager: ResourceManager | None,
    ) -> None:
        self.states: dict[str, State] = states
        self.initial_state: Optional[str] = initial_state
        self.tool_manager: ToolManager | None = tool_manager
        self.prompt_manager: PromptManager | None = prompt_manager
        self.resource_manager: ResourceManager | None = resource_manager
        self.issues: list[ValidationIssue] = []

    def validate(self) -> list[ValidationIssue]:
        """Run all structural and reference checks and return a list of issues."""
        self._check_single_initial()
        self._check_terminal_have_no_outgoing()

        # Collect available artifacts and record missing ones as issues.
        available = self._collect_available_and_check_refs()

        # Compute reachability using only transitions whose artifacts are available.
        reachable = self._compute_reachable(available)

        self._check_at_least_one_reachable_terminal(reachable)
        self._warn_unreachable_states(reachable)
        return self.issues

    # structural checks

    def _check_single_initial(self) -> None:
        """Ensure there is exactly one initial state (and it exists)."""
        flagged = [s.name for s in self.states.values() if s.is_initial]
        if self.initial_state and self.initial_state not in self.states:
            self.issues.append(ValidationIssue("error", f"Initial state '{self.initial_state}' not found."))
            return
        if len(flagged) == 0 and not self.initial_state:
            self.issues.append(ValidationIssue("error", "No initial state defined."))
        elif len(flagged) > 1:
            self.issues.append(ValidationIssue("error", f"Multiple initial states: {', '.join(flagged)}.")) # TODO: this will never happen because of builder pre checks

    def _check_terminal_have_no_outgoing(self) -> None:
        """Terminal states must not define outgoing transitions."""
        for s in self.states.values():
            if s.is_terminal and s.transitions:
                self.issues.append(
                    ValidationIssue("error", f"Terminal state '{s.name}' must not have outgoing transitions.")
                )

    # availability + references

    def _collect_available_and_check_refs(self) -> dict[str, set[str]]:
        """
        Build sets of available artifact identifiers and record missing references as issues.

        Returns:
          {
            "tools": {tool_name, ...},
            "prompts": {prompt_name, ...},
            "resources": {resource_uri_str, ...},
          }
        """
        # Gather referenced identifiers from transitions
        tool_refs: set[str] = set()
        prompt_refs: set[str] = set()
        resource_refs: set[str] = set()

        for s in self.states.values():
            for tr in s.transitions:
                sym: InputSymbol = tr.input_symbol
                if sym.type == "tool":
                    tool_refs.add(sym.name)
                elif sym.type == "prompt":
                    prompt_refs.add(sym.name)
                elif sym.type == "resource":
                    resource_refs.add(sym.name)

        # Resolve availability via managers; record missing items as errors
        tool_names: set[str] = set()
        try:
            if self.tool_manager is None:
                raise ValueError("No tool manager provided.")
            tools: list[Tool] = self.tool_manager.list_tools()
            tool_names = {t.name for t in tools}
            for missing in sorted(tool_refs - tool_names):
                self.issues.append(ValidationIssue("error", f"Referenced tool '{missing}' is not registered."))
        except Exception as e:
            self.issues.append(ValidationIssue("warning", f"Tool check skipped: {e}"))

        prompt_names: set[str] = set()
        try:
            if self.prompt_manager is None:
                raise ValueError("No prompt manager provided.")
            prompts: list[Prompt] = self.prompt_manager.list_prompts()
            prompt_names = {p.name for p in prompts}
            for missing in sorted(prompt_refs - prompt_names):
                self.issues.append(ValidationIssue("error", f"Referenced prompt '{missing}' is not registered."))
        except Exception as e:
            self.issues.append(ValidationIssue("warning", f"Prompt check skipped: {e}"))

        resource_uris: set[str] = set()
        try:
            if self.resource_manager is None:
                raise ValueError("No resource manager provided.")
            resources: list[Resource] = self.resource_manager.list_resources()
            resource_uris = {str(r.uri) for r in resources}
            for missing in sorted(resource_refs - resource_uris):
                self.issues.append(ValidationIssue("error", f"Referenced resource '{missing}' is not registered."))
        except Exception as e:
            self.issues.append(ValidationIssue("warning", f"Resource check skipped: {e}"))

        return {
            "tools": tool_names,
            "prompts": prompt_names,
            "resources": resource_uris,
        }

    # reachability (filtered by availability)

    def _compute_reachable(self, available: dict[str, set[str]]) -> set[str]:
        """
        Compute reachable states using BFS, traversing only transitions whose artifacts
        are available according to `available`.
        """
        # Determine start
        if self.initial_state:
            start = self.initial_state
        else:
            flagged = [s.name for s in self.states.values() if s.is_initial]
            start = flagged[0] if flagged else (next(iter(self.states)) if self.states else None)

        if start is None:
            return set()

        q: deque[str] = deque([start])
        seen: set[str] = {start}

        while q:
            sname = q.popleft()
            s = self.states.get(sname)
            if not s:
                continue

            for tr in s.transitions:
                sym = tr.input_symbol
                # Filter by artifact availability
                if sym.type == "tool" and sym.name not in available["tools"]:
                    continue
                if sym.type == "prompt" and sym.name not in available["prompts"]:
                    continue
                if sym.type == "resource" and sym.name not in available["resources"]:
                    continue

                dst = tr.to_state
                if dst in self.states and dst not in seen:
                    seen.add(dst)
                    q.append(dst)

        return seen

    # post-reachability checks

    def _check_at_least_one_reachable_terminal(self, reachable: set[str]) -> None:
        """At least one terminal state must be reachable from the initial state."""
        if not any(s.is_terminal and s.name in reachable for s in self.states.values()):
            self.issues.append(ValidationIssue("error", "No reachable terminal state from initial."))

    def _warn_unreachable_states(self, reachable: set[str]) -> None:
        """Emit warnings for states that are not reachable from the initial state."""
        for name in self.states.keys():
            if name not in reachable:
                self.issues.append(ValidationIssue("warning", f"State '{name}' is unreachable from initial."))
