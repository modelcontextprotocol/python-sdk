"""The v1 -> v2 source transformer.

`transform()` is the whole programmatic surface: it takes one module's source text
and returns the rewritten text plus a list of diagnostics. Everything else in the
package (the CLI, the file runner) is a wrapper around it.

The transformer is built on libCST and is deliberately conservative. A construct is
rewritten only when its meaning is unambiguous from the file alone:

* Names and dotted references are resolved through the file's imports with
  `QualifiedNameProvider`, so an aliased import is never broken and a user symbol
  that happens to share a name with an mcp one is never touched.
* The camelCase -> snake_case attribute rename is restricted to an allowlist of the
  field names v1's `mcp.types` actually declared; nothing else is ever considered.
* Anything whose correct rewrite depends on information that is not in the file --
  a receiver's runtime type, where a relocated keyword argument should land, how a
  lowlevel handler body must be reshaped -- is never guessed at. It is left exactly
  as written and an inline `# mcp-codemod:` marker is inserted above it instead, so
  the remaining work is a single grep away.

Running the transformer over its own output is a no-op: every rewrite produces v2
spellings the tables no longer match, and marker insertion deduplicates against
markers that are already present.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar, cast

import libcst as cst
from libcst.helpers import get_full_name_for_node
from libcst.metadata import (
    CodeRange,
    ExpressionContext,
    ExpressionContextProvider,
    MetadataWrapper,
    PositionProvider,
    QualifiedNameProvider,
    QualifiedNameSource,
)

from mcp_codemod._mappings import (
    CAMEL_FIELDS,
    ERRORDATA_QNAMES,
    FASTMCP_QNAMES,
    LOWLEVEL_DECORATOR_METHODS,
    LOWLEVEL_REMOVED_ATTRS,
    LOWLEVEL_SERVER_QNAMES,
    MCPERROR_QNAMES,
    MODULE_RENAMES,
    REHOMED_IMPORTS,
    REMOVED_APIS,
    REMOVED_ATTRS,
    REMOVED_CTOR_PARAMS,
    REMOVED_MODULES,
    SYMBOL_RENAMES,
    TRANSPORT_CLIENT_QNAMES,
    TRANSPORT_CLIENT_REMOVED_PARAMS,
    TRANSPORT_CLIENT_V1_QNAMES,
    TRANSPORT_CTOR_PARAMS,
)

__all__ = ["Diagnostic", "MARKER", "Result", "transform"]

MARKER = "mcp-codemod"
"""The prefix every inserted comment starts with: `# mcp-codemod: ...`.

After a run, `grep -rn '# mcp-codemod:'` lists exactly the sites that still need a
human. Markers whose message starts with `review:` accompany a rewrite that was
applied heuristically; all others mark something the codemod refused to rewrite.
"""

Severity = Literal["info", "review", "manual"]

# Longest prefix wins, so `mcp.server.fastmcp.prompts` matches `mcp.server.fastmcp`
# rather than a shorter overlapping key, should one ever be added.
_MODULE_RENAMES_LONGEST_FIRST: tuple[tuple[str, str], ...] = tuple(
    sorted(MODULE_RENAMES.items(), key=lambda item: -len(item[0]))
)

_NodeT = TypeVar("_NodeT", bound=cst.CSTNode)
_StatementT = TypeVar("_StatementT", bound="cst.SimpleStatementLine | cst.BaseCompoundStatement")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding the codemod wants a human to see.

    `severity` says what happened at the site: `info` means a safe rewrite was
    applied and is reported for the record only; `review` means a rewrite was
    applied but rests on a heuristic, so an inline marker asks for a look; `manual`
    means nothing was rewritten and the change is the reader's to make.
    """

    line: int
    transform: str
    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class Result:
    """What `transform()` produced for one module."""

    code: str
    diagnostics: list[Diagnostic]
    rewrites: Counter[str]


def _rename_module(dotted: str) -> str | None:
    """Return the v2 spelling of a v1 module path, or None if it is unchanged."""
    for old, new in _MODULE_RENAMES_LONGEST_FIRST:
        if dotted == old or dotted.startswith(old + "."):
            return new + dotted[len(old) :]
    return None


def _removed_module(dotted: str) -> str | None:
    """Return the guidance for a module path v2 deleted, or None if it survives."""
    for root, guidance in REMOVED_MODULES.items():
        if dotted == root or dotted.startswith(root + "."):
            return guidance
    return None


def _dotted_name(dotted: str) -> cst.Attribute | cst.Name:
    # A dotted module path always parses to a Name or a chain of Attributes, which
    # is the only thing import nodes accept; `parse_expression` just cannot say so.
    return cast("cst.Attribute | cst.Name", cst.parse_expression(dotted))


def _names_the_sdk(module: str) -> bool:
    """Whether a dotted module path belongs to the SDK: `mcp`, `mcp_types`, or below."""
    return module in ("mcp", "mcp_types") or module.startswith(("mcp.", "mcp_types."))


def _split_rehomed_imports(
    statement: cst.SimpleStatementLine, imported: cst.ImportFrom
) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.BaseStatement] | None:
    """Move `REHOMED_IMPORTS` names out of an already-renamed from-import.

    Returns None when the statement imports none of them. The rehomed names keep
    their `as` aliases; when nothing else was imported, the new statement takes
    the original's place wholesale, formatting included.
    """
    assert imported.module is not None and not isinstance(imported.names, cst.ImportStar)
    module = get_full_name_for_node(imported.module) or ""
    moved: list[cst.ImportAlias] = []
    kept: list[cst.ImportAlias] = []
    targets: set[str] = set()
    for alias in imported.names:
        name = cst.ensure_type(alias.name, cst.Name).value
        target = REHOMED_IMPORTS.get((module, name))
        if target is None:
            kept.append(alias)
        else:
            moved.append(alias.with_changes(comma=cst.MaybeSentinel.DEFAULT))
            targets.add(target)
    if not moved:
        return None
    # Every current row rehomes to one module; revisit if a second target appears.
    replacement = cst.SimpleStatementLine(
        body=[cst.ImportFrom(module=_dotted_name(targets.pop()), names=moved)],
    )
    if not kept:
        return replacement.with_changes(
            leading_lines=statement.leading_lines, trailing_whitespace=statement.trailing_whitespace
        )
    kept[-1] = kept[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
    remaining = statement.with_changes(body=[imported.with_changes(names=kept)])
    return cst.FlattenSentinel([remaining, replacement])


def _with_markers(statement: _StatementT, messages: Sequence[str]) -> _StatementT:
    """Prepend a `# mcp-codemod:` comment per distinct message not already present."""
    existing = {line.comment.value for line in statement.leading_lines if line.comment is not None}
    # `dict.fromkeys` rather than a set: two identical findings on one statement
    # (`a.isError or b.isError`) must produce one comment, in first-seen order.
    comments = list(dict.fromkeys(f"# {MARKER}: {message}" for message in messages))
    fresh = [comment for comment in comments if comment not in existing]
    if not fresh:
        return statement
    inserted = [cst.EmptyLine(comment=cst.Comment(comment)) for comment in fresh]
    return statement.with_changes(leading_lines=[*statement.leading_lines, *inserted])


class _PrePass(cst.CSTVisitor):
    """Collect the facts the transformer needs before it rewrites anything.

    `imports_mcp` gates the name-only heuristics (the camelCase renames and the
    removed-attribute markers) to files that import from the SDK at all -- v1's
    `mcp` or v2's `mcp_types`, since a half-migrated file is just as much the
    tool's business. `plain_imports` is the set of module paths bound by an
    `import a.b.c` statement, so a dotted usage is only rewritten in lockstep
    with the import that backs it; `unrenamed_reference_roots` is its complement,
    the roots that something other than a renamed module still resolves through.
    `user_declared_camel` is every allowlisted camelCase name some class body in
    the file declares itself, where a rename can never be applied blindly.
    `lowlevel_server_vars` records which local names were bound to a lowlevel
    `Server(...)` so its decorators can be told apart from the syntactically
    identical `MCPServer` ones.
    """

    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    def __init__(self) -> None:
        self.imports_mcp = False
        self.plain_imports: set[str] = set()
        self.unrenamed_reference_roots: set[str] = set()
        self.user_declared_camel: set[str] = set()
        self.lowlevel_server_vars: set[str] = set()
        self._class_depth = 0

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._class_depth += 1

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._class_depth -= 1

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.relative or node.module is None:
            return
        if _names_the_sdk(get_full_name_for_node(node.module) or ""):
            self.imports_mcp = True

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name = get_full_name_for_node(alias.name) or ""
            self.plain_imports.add(name)
            if _names_the_sdk(name):
                self.imports_mcp = True

    def visit_Attribute(self, node: cst.Attribute) -> None:
        # Record the root package of every dotted reference that no module rename
        # covers (e.g. the `mcp` in `mcp.ClientSession`). Renaming `import mcp.types`
        # to `import mcp_types` also unbinds `mcp`, which is only a problem when one
        # of these still needs it.
        for qualified in self.get_metadata(QualifiedNameProvider, node, frozenset()):
            if qualified.source is not QualifiedNameSource.LOCAL and _rename_module(qualified.name) is None:
                self.unrenamed_reference_roots.add(qualified.name.split(".")[0])

    def _record_lowlevel_server(self, value: cst.BaseExpression | None, target: cst.BaseExpression) -> None:
        """When `value` calls the lowlevel `Server(...)`, remember the name it binds.

        The target's full spelling is recorded, so an attribute binding like
        `self.server = Server(...)` is recognized exactly like a plain name.
        """
        if not isinstance(value, cst.Call):
            return
        bound = get_full_name_for_node(target)
        if bound is None:
            return
        qualified = {
            q.name
            for q in self.get_metadata(QualifiedNameProvider, value.func, frozenset())
            if q.source is not QualifiedNameSource.LOCAL
        }
        if qualified & LOWLEVEL_SERVER_QNAMES:
            self.lowlevel_server_vars.add(bound)

    def _record_class_field(self, target: cst.BaseExpression) -> None:
        """Remember a camelCase name a class body in this file declares as its own."""
        if self._class_depth and isinstance(target, cst.Name) and target.value in CAMEL_FIELDS:
            self.user_declared_camel.add(target.value)

    def visit_Assign(self, node: cst.Assign) -> None:
        for target in node.targets:
            self._record_class_field(target.target)
            self._record_lowlevel_server(node.value, target.target)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        # `server: Server = Server("x")` is a different node from `server = Server("x")`.
        self._record_class_field(node.target)
        self._record_lowlevel_server(node.value, node.target)


class _V1ToV2(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (QualifiedNameProvider, PositionProvider, ExpressionContextProvider)

    def __init__(self, prepass: _PrePass, *, add_markers: bool) -> None:
        super().__init__()
        self._imports_mcp = prepass.imports_mcp
        self._plain_imports = prepass.plain_imports
        self._unrenamed_reference_roots = prepass.unrenamed_reference_roots
        self._user_declared_camel = prepass.user_declared_camel
        self._lowlevel_server_vars = prepass.lowlevel_server_vars
        self._add_markers = add_markers
        # One frame per open class definition: whether it subclasses `McpError`,
        # so a `super().__init__(...)` inside one gets the constructor treatment.
        self._in_mcperror_class: list[bool] = []
        self.diagnostics: list[Diagnostic] = []
        self.rewrites: Counter[str] = Counter()
        # Name nodes that are not references to a binding and must never be renamed
        # as one: the `.attr` of an attribute access, a `kwarg=` name, a parameter.
        self._not_a_reference: set[int] = set()
        # One frame of pending marker texts per open statement; markers emitted while
        # a statement is being visited attach to that statement on the way out. The
        # bottom frame is a sentinel so the stack is never empty.
        self._pending_markers: list[list[str]] = [[]]
        # One frame per `except` handler we are inside: the name it binds (or "")
        # and whether its type names `McpError`. An inner handler that re-binds a
        # name shadows the outer binding of that name; any other inner handler is
        # transparent to the lookup.
        self._except_bindings: list[tuple[str, bool]] = []
        # Calls that are a `with` item bound to a three-element tuple: the one form
        # whose result tuple `leave_WithItem` can rewrite rather than flag.
        self._narrowable_calls: set[int] = set()

    # -------------------------------------------------------------- bookkeeping

    def _qualified(self, node: cst.CSTNode) -> set[str]:
        """The dotted names `node` resolves to through an import or to a builtin.

        Names that resolve only to a LOCAL binding are deliberately excluded.
        `mcp = MCPServer(...)` is the most common variable name in real MCP code,
        and at module scope an attribute chain on that variable carries a qualified
        name spelled exactly like a module path (`mcp.types`); only a non-local
        source proves the text really names the SDK (or, for `getattr` and
        `hasattr`, the builtin). Every gate in this class goes through here.
        """
        return {
            q.name
            for q in self.get_metadata(QualifiedNameProvider, node, frozenset())
            if q.source is not QualifiedNameSource.LOCAL
        }

    def _root_still_bound(self, root: str, renamed_import: str) -> bool:
        """Whether a plain import other than `renamed_import` still binds `root`.

        `import mcp.client.session` alongside `import mcp.types` keeps `mcp` bound
        whatever happens to `mcp.types`, so renaming the latter unbinds nothing.
        """
        for plain in self._plain_imports - {renamed_import}:
            survives = _rename_module(plain) or plain
            if survives == root or survives.startswith(f"{root}."):
                return True
        return False

    def _diag(self, node: cst.CSTNode, transform: str, severity: Severity, message: str) -> None:
        # Without an explicit default, pyright cannot solve `get_metadata`'s
        # generic for `PositionProvider`; the provider always yields a `CodeRange`.
        line = cast(CodeRange, self.get_metadata(PositionProvider, node)).start.line
        self.diagnostics.append(Diagnostic(line, transform, severity, message))
        if severity != "info":
            self._pending_markers[-1].append(message)

    def _camel_diag(self, node: cst.CSTNode, camel: str, rewrote: str) -> None:
        """Report one camelCase rename; a risky-tier name also gets a review marker."""
        if CAMEL_FIELDS[camel].tier == "risky":
            self._diag(node, "attr_snake_case", "review", f"review: {rewrote}; verify the receiver is an mcp type")
        else:
            self._diag(node, "attr_snake_case", "info", rewrote)
        self.rewrites["attr_snake_case"] += 1

    def on_visit(self, node: cst.CSTNode) -> bool:
        if isinstance(node, cst.SimpleStatementLine | cst.BaseCompoundStatement):
            self._pending_markers.append([])
        return super().on_visit(node)

    def on_leave(
        self, original_node: _NodeT, updated_node: _NodeT
    ) -> _NodeT | cst.RemovalSentinel | cst.FlattenSentinel[_NodeT]:
        result = super().on_leave(original_node, updated_node)
        if isinstance(original_node, cst.SimpleStatementLine | cst.BaseCompoundStatement):
            pending = self._pending_markers.pop()
            if pending and self._add_markers:
                # At statement level every transform here returns the statement
                # itself or a FlattenSentinel of statements -- nothing is removed.
                if isinstance(result, cst.FlattenSentinel):
                    # A split statement: the markers belong above its first piece,
                    # which takes the original's place in the module.
                    pieces = list(result)
                    statement = cast("cst.SimpleStatementLine | cst.BaseCompoundStatement", pieces[0])
                    pieces[0] = cast(_NodeT, _with_markers(statement, pending))
                    result = cst.FlattenSentinel(pieces)
                else:
                    narrowed = cast("cst.SimpleStatementLine | cst.BaseCompoundStatement", result)
                    result = cast(_NodeT, _with_markers(narrowed, pending))
        return result

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._in_mcperror_class.append(any(self._qualified(base.value) & MCPERROR_QNAMES for base in node.bases))

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        self._in_mcperror_class.pop()
        return updated_node

    def _is_mcperror_super_init(self, node: cst.Call) -> bool:
        """Whether `node` is a `super().__init__(...)` call inside a `McpError` subclass."""
        function = node.func
        return (
            bool(self._in_mcperror_class)
            and self._in_mcperror_class[-1]
            and isinstance(function, cst.Attribute)
            and function.attr.value == "__init__"
            and isinstance(function.value, cst.Call)
            and isinstance(function.value.func, cst.Name)
            and function.value.func.value == "super"
        )

    def visit_Attribute(self, node: cst.Attribute) -> None:
        self._not_a_reference.add(id(node.attr))

    def visit_Arg(self, node: cst.Arg) -> None:
        if node.keyword is not None:
            self._not_a_reference.add(id(node.keyword))

    def visit_Param(self, node: cst.Param) -> None:
        self._not_a_reference.add(id(node.name))

    def _is_mcperror_binding(self, name: str) -> bool:
        """Whether the nearest enclosing handler that binds `name` catches `McpError`.

        Handlers that bind some other name (or none) are transparent, so a nested
        `try`/`except` inside an `except McpError as e:` does not hide `e`; one
        that re-binds `e` itself shadows the outer binding.
        """
        for bound, is_mcperror in reversed(self._except_bindings):
            if bound == name:
                return is_mcperror
        return False

    def visit_ExceptHandler(self, node: cst.ExceptHandler) -> None:
        bound = ""
        if node.name is not None and isinstance(node.name.name, cst.Name):
            bound = node.name.name.value
        # `except (McpError, ValueError) as e:` catches a tuple of types.
        if isinstance(node.type, cst.Tuple):
            caught: list[cst.BaseExpression] = [element.value for element in node.type.elements]
        elif node.type is not None:
            caught = [node.type]
        else:
            caught = []
        self._except_bindings.append((bound, any(self._qualified(kind) & MCPERROR_QNAMES for kind in caught)))

    def leave_ExceptHandler(
        self, original_node: cst.ExceptHandler, updated_node: cst.ExceptHandler
    ) -> cst.ExceptHandler:
        self._except_bindings.pop()
        return updated_node

    # ------------------------------------------------------------------ imports

    def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
        if updated_node.relative or updated_node.module is None:
            return updated_node
        module = get_full_name_for_node(updated_node.module) or ""

        # Importing from a deleted module namespace: one marker for the whole
        # statement says everything the per-name checks below could, so they are
        # skipped (the names of a deleted module are gone with it).
        if (module_guidance := _removed_module(module)) is not None:
            self._diag(original_node, "removed_module", "manual", f"`{module}` {module_guidance}")
            return updated_node

        # `QualifiedNameProvider` resolves *references* to a binding; the import
        # alias that creates the binding gets nothing, so it is handled here: a
        # renamed symbol is renamed in place, and importing a name that no longer
        # exists anywhere is marked (its uses elsewhere in the file are marked by
        # `leave_Name`, but an import is often the only mention).
        if not isinstance(updated_node.names, cst.ImportStar):
            aliases: list[cst.ImportAlias] = []
            renamed_any = False
            for alias in updated_node.names:
                # In a `from X import name` statement the alias is always a bare Name.
                qualified = f"{module}.{cst.ensure_type(alias.name, cst.Name).value}"
                if (guidance := _removed_module(qualified) or REMOVED_APIS.get(qualified)) is not None:
                    self._diag(original_node, "removed_api", "manual", f"`{qualified}` {guidance}")
                elif new := SYMBOL_RENAMES.get(qualified):
                    renamed_any = True
                    self.rewrites["symbol_rename"] += 1
                    alias = alias.with_changes(name=cst.Name(new))
                aliases.append(alias)
            if renamed_any:
                updated_node = updated_node.with_changes(names=aliases)

        if (renamed_module := _rename_module(module)) is not None:
            self.rewrites["module_rename"] += 1
            updated_node = updated_node.with_changes(module=_dotted_name(renamed_module))
        return updated_node

    def leave_Import(self, original_node: cst.Import, updated_node: cst.Import) -> cst.Import:
        aliases: list[cst.ImportAlias] = []
        renamed_any = False
        for alias in updated_node.names:
            dotted = get_full_name_for_node(alias.name) or ""
            if (guidance := _removed_module(dotted)) is not None:
                self._diag(original_node, "removed_module", "manual", f"`{dotted}` {guidance}")
            elif (renamed := _rename_module(dotted)) is not None:
                renamed_any = True
                self.rewrites["module_rename"] += 1
                root = dotted.split(".")[0]
                # `import mcp.types` also bound the name `mcp`. When the renamed
                # module lives under a different root package, that binding goes
                # away with the rewrite -- a problem only if some other reference
                # in the file, one no module rename covers, still resolves through
                # it, which the pre-pass recorded. (`PositionProvider` has no entry
                # for an `ImportAlias`, so the diagnostic is anchored on the whole
                # import statement.)
                if (
                    alias.asname is None
                    and renamed.split(".")[0] != root
                    and root in self._unrenamed_reference_roots
                    and not self._root_still_bound(root, dotted)
                ):
                    self._diag(
                        original_node,
                        "module_rename",
                        "review",
                        f"review: `import {dotted}` also bound the name `{root}`; add `import {root}` "
                        f"back if this file still uses other `{root}.` names",
                    )
                alias = alias.with_changes(name=_dotted_name(renamed))
            aliases.append(alias)
        return updated_node.with_changes(names=aliases) if renamed_any else updated_node

    def leave_SimpleStatementLine(
        self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
    ) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.BaseStatement]:
        # `from <parent> import <child>` where `<parent>.<child>` is a renamed module
        # (e.g. `from mcp import types`) bound the OLD module object to a local name.
        # A module cannot be renamed in place, so the binding has to come from a real
        # import of the new module under the same local name instead.
        if len(updated_node.body) != 1:
            return updated_node
        imported = updated_node.body[0]
        if not isinstance(imported, cst.ImportFrom) or isinstance(imported.names, cst.ImportStar):
            return updated_node
        if imported.relative or imported.module is None:
            return updated_node
        # `leave_ImportFrom` already renamed the module and its names, so a name
        # whose public v2 home is elsewhere (`Context` under `.server`) is split
        # out of the statement here, against the renamed spelling.
        rehomed = _split_rehomed_imports(updated_node, imported)
        if rehomed is not None:
            self.rewrites["import_rehome"] += 1
            return rehomed
        parent = get_full_name_for_node(imported.module) or ""
        moved: cst.ImportAlias | None = None
        kept: list[cst.ImportAlias] = []
        for alias in imported.names:
            if moved is None and isinstance(alias.name, cst.Name) and f"{parent}.{alias.name.value}" in MODULE_RENAMES:
                moved = alias
            else:
                kept.append(alias)
        if moved is None:
            return updated_node
        self.rewrites["module_rename"] += 1
        child = cst.ensure_type(moved.name, cst.Name).value
        asname = moved.asname
        local = cst.ensure_type(asname.name, cst.Name).value if asname is not None else child
        target = MODULE_RENAMES[f"{parent}.{child}"]
        replacement = cst.ensure_type(cst.parse_statement(f"import {target} as {local}"), cst.SimpleStatementLine)
        if not kept:
            # The replacement takes the original line's place, so it keeps that
            # line's leading lines AND its trailing comment (`# noqa`, ...).
            return replacement.with_changes(
                leading_lines=updated_node.leading_lines, trailing_whitespace=updated_node.trailing_whitespace
            )
        kept[-1] = kept[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
        remaining = updated_node.with_changes(body=[imported.with_changes(names=kept)])
        return cst.FlattenSentinel([remaining, replacement])

    # ------------------------------------------- references, attributes, calls

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        if id(original_node) in self._not_a_reference:
            return updated_node
        for qualified in self._qualified(original_node):
            if qualified in REMOVED_APIS:
                self._diag(original_node, "removed_api", "manual", f"`{qualified}` {REMOVED_APIS[qualified]}")
                return updated_node
            new = SYMBOL_RENAMES.get(qualified)
            # An aliased import (`... import FastMCP as F`) leaves `F` as the local
            # spelling; only an occurrence of the original name is rewritten.
            if new is not None and original_node.value == qualified.rsplit(".", 1)[-1]:
                self.rewrites["symbol_rename"] += 1
                return updated_node.with_changes(value=new)
        return updated_node

    def leave_Attribute(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.BaseExpression:
        # A READ of `e.error.code` -> `e.code` when `e` is bound by `except McpError
        # as e:`. Only the full three-part chain in a load context is touched: a bare
        # `e.error` may be a whole `ErrorData` being passed somewhere, and an
        # ASSIGNMENT like `e.error.message = ...` must stay as written -- v2's
        # `MCPError.message` is a read-only property over the still-mutable `.error`,
        # so collapsing a write would break code that works on v2 today.
        if (
            original_node.attr.value in ("code", "message", "data")
            and isinstance(original_node.value, cst.Attribute)
            and original_node.value.attr.value == "error"
            and isinstance(original_node.value.value, cst.Name)
            and self._is_mcperror_binding(original_node.value.value.value)
            and self.get_metadata(ExpressionContextProvider, original_node, None) is ExpressionContext.LOAD
        ):
            self.rewrites["mcperror_attr"] += 1
            return updated_node.with_changes(value=cst.ensure_type(updated_node.value, cst.Attribute).value)

        # An attribute the lowlevel `Server` lost whose name survives elsewhere on
        # v2, matched only against a receiver the pre-pass proved is such a server
        # (`server` or `self.server` alike).
        if (get_full_name_for_node(original_node.value) or "") in self._lowlevel_server_vars and (
            lowlevel_guidance := LOWLEVEL_REMOVED_ATTRS.get(original_node.attr.value)
        ) is not None:
            self._diag(original_node, "removed_attr", "manual", lowlevel_guidance)
            return updated_node

        qualified_names = self._qualified(original_node)
        dotted = get_full_name_for_node(original_node)
        # The exact node naming a renamed module, written out as it was imported
        # (the `mcp.types` inside `mcp.types.Tool` after `import mcp.types`). Only
        # this innermost node is replaced -- the chain above it rebuilds around it --
        # and only in lockstep with the import that backs it: a bare `import mcp`
        # also resolves `mcp.types`, but rewriting that usage would leave nothing
        # importing the new module, so it is marked instead.
        if dotted in MODULE_RENAMES and dotted in qualified_names:
            if dotted in self._plain_imports:
                self.rewrites["module_rename"] += 1
                return _dotted_name(MODULE_RENAMES[dotted])
            # `import mcp.server.fastmcp.server` also resolves its own prefix
            # `mcp.server.fastmcp`; the longer node is the one being rewritten, so
            # a name that is the prefix of some plain import needs nothing here.
            if not any(plain.startswith(f"{dotted}.") for plain in self._plain_imports):
                self._diag(
                    original_node,
                    "module_rename",
                    "manual",
                    f"`{dotted}` no longer exists: import `{MODULE_RENAMES[dotted]}` and use it here instead",
                )
            return updated_node

        # A removed API or a renamed symbol reached as an attribute of an imported
        # module, whether written out in full (`mcp.shared.exceptions.McpError`) or
        # through a module alias (`memory.create_connected_server_and_client_session`
        # after `from mcp.shared import memory`). The mirror of `leave_Name`, which
        # sees the bare-name form.
        for qualified in qualified_names:
            if qualified in REMOVED_APIS:
                self._diag(original_node, "removed_api", "manual", f"`{qualified}` {REMOVED_APIS[qualified]}")
                return updated_node
            new = SYMBOL_RENAMES.get(qualified)
            if new is not None and original_node.attr.value == qualified.rsplit(".", 1)[-1]:
                self.rewrites["symbol_rename"] += 1
                return updated_node.with_changes(attr=cst.Name(new))

        # The remaining checks key on nothing but the attribute's name. They only
        # apply in a file that imports the SDK, and never to a receiver the file's
        # imports PROVE is something else (`multiprocessing.get_context(...)`):
        # only a name the imports cannot explain could be an mcp object.
        if not self._imports_mcp or any(not _names_the_sdk(qualified) for qualified in qualified_names):
            return updated_node

        if (guidance := REMOVED_ATTRS.get(original_node.attr.value)) is not None:
            self._diag(original_node, "removed_attr", "manual", guidance)
            return updated_node

        camel = original_node.attr.value
        if camel in CAMEL_FIELDS:
            if camel in self._user_declared_camel:
                # A class in this same file declares this exact field name, so some
                # of its receivers are the user's own objects, whose declaration the
                # codemod is not changing. Renaming those breaks them, so nothing is
                # rewritten and every use is marked instead.
                self._diag(
                    original_node,
                    "attr_snake_case",
                    "manual",
                    f"`.{camel}` is declared by a class in this file and is also a renamed mcp field: "
                    f"rename only the reads of mcp objects to `.{CAMEL_FIELDS[camel].snake}`",
                )
                return updated_node
            snake = CAMEL_FIELDS[camel].snake
            self._camel_diag(original_node, camel, f"renamed `.{camel}` to `.{snake}`")
            return updated_node.with_changes(attr=cst.Name(snake))

        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        callee = self._qualified(original_node.func)

        # `McpError(ErrorData(code=..., message=..., data=...))` flattened to
        # `MCPError(code=..., message=..., data=...)`; the name itself is renamed by
        # `leave_Name`, which has already run on the inner nodes. v1's constructor
        # took a single `ErrorData`; when that one argument is anything other than
        # an inline `ErrorData(...)` call there is nothing safe to unpack, so the
        # call is marked instead -- v2's signature is `(code, message, data=None)`.
        # A subclass's `super().__init__(...)` is the same constructor spelled the
        # one way a qualified name cannot reach, so it gets the same treatment.
        if (callee & MCPERROR_QNAMES or self._is_mcperror_super_init(original_node)) and len(original_node.args) == 1:
            wrapped = original_node.args[0].value
            if isinstance(wrapped, cst.Call) and self._qualified(wrapped.func) & ERRORDATA_QNAMES:
                self.rewrites["mcperror_ctor"] += 1
                return updated_node.with_changes(args=cst.ensure_type(updated_node.args[0].value, cst.Call).args)
            self._diag(
                original_node,
                "mcperror_ctor",
                "manual",
                "the `MCPError` constructor is now `MCPError(code, message, data=None)`: "
                "unpack the `ErrorData` being passed here into those arguments",
            )

        # camelCase keyword arguments still work on v2 (every model field also
        # accepts its camelCase alias by name), so unlike an attribute READ this
        # rename is cosmetic and cannot break the call -- which is why, unlike the
        # attribute form, the risky tier needs no review marker here. Every
        # hand-migrated example in the SDK converted them, so the codemod follows
        # suit, gated on the callee resolving into the SDK.
        if any(name == "mcp" or name.startswith(("mcp.", "mcp_types.")) for name in callee):
            arguments: list[cst.Arg] = []
            renamed_any = False
            for argument in updated_node.args:
                if argument.keyword is not None and argument.keyword.value in CAMEL_FIELDS:
                    renamed_any = True
                    self.rewrites["kwarg_snake_case"] += 1
                    argument = argument.with_changes(keyword=cst.Name(CAMEL_FIELDS[argument.keyword.value].snake))
                arguments.append(argument)
            if renamed_any:
                updated_node = updated_node.with_changes(args=arguments)

        # Transport keywords on the `MCPServer` constructor moved to `run()` or the
        # app methods. Where they belong depends on how the server is started --
        # possibly in another file -- so the kwarg is left in place (v2 rejects it
        # loudly) rather than deleted, which would silently lose configuration.
        if callee & FASTMCP_QNAMES:
            for index, argument in enumerate(original_node.args):
                keyword = argument.keyword.value if argument.keyword is not None else ""
                # v1's positional order was `(name, instructions, ...)`; v2's second
                # parameter is `title`, so anything positional after the name would
                # silently land in the wrong parameter rather than fail.
                if argument.star == "*" or (argument.keyword is None and argument.star == "" and index > 0):
                    self._diag(
                        argument,
                        "positional_ctor_param",
                        "manual",
                        "v1's positional constructor parameters after the name do not line up with "
                        "v2's (`title` is now second): pass these by keyword",
                    )
                elif keyword in TRANSPORT_CTOR_PARAMS:
                    self._diag(
                        argument,
                        "transport_ctor_param",
                        "manual",
                        f"`{keyword}=` is no longer a constructor argument: pass it to "
                        f"`run()` / `sse_app()` / `streamable_http_app()` where the server is started",
                    )
                elif keyword in REMOVED_CTOR_PARAMS:
                    self._diag(argument, "removed_ctor_param", "manual", f"`{keyword}=` {REMOVED_CTOR_PARAMS[keyword]}")

        # The streamable-HTTP client's keyword surface and yield shape both changed.
        # The keyword check lives here so that it fires however the call is used (an
        # `async with` item, `enter_async_context(...)`, an intermediate variable).
        # Only the `as (read, write, _)` with-item form can have its unpacking
        # REWRITTEN (`leave_WithItem` does); every other use of the v1 name is
        # flagged, because where its result lands is not the codemod's to guess.
        if callee & TRANSPORT_CLIENT_QNAMES:
            for argument in original_node.args:
                keyword = argument.keyword.value if argument.keyword is not None else ""
                if keyword in TRANSPORT_CLIENT_REMOVED_PARAMS:
                    self._diag(
                        argument,
                        "transport_client_param",
                        "manual",
                        f"`{keyword}=` is no longer accepted here: configure it on an "
                        f"`httpx.AsyncClient` passed as `http_client=`",
                    )
            if callee & TRANSPORT_CLIENT_V1_QNAMES and id(original_node) not in self._narrowable_calls:
                self._diag(
                    original_node,
                    "transport_client_unpack",
                    "manual",
                    "this client now yields `(read, write)` rather than "
                    "`(read, write, get_session_id)`: update the unpacking",
                )

        # A camelCase field name spelled as a string in `hasattr` / `getattr` /
        # `setattr` is the one string position the rename applies to. Dict keys and
        # other string literals are never touched: camelCase IS the wire format.
        # Like the attribute form, this only applies in a file that imports the SDK.
        if (
            self._imports_mcp
            and callee & {"builtins.getattr", "builtins.hasattr", "builtins.setattr"}
            and len(updated_node.args) >= 2
        ):
            literal = updated_node.args[1].value
            if isinstance(literal, cst.SimpleString):
                value = literal.evaluated_value
                if isinstance(value, str) and value in CAMEL_FIELDS:
                    snake = CAMEL_FIELDS[value].snake
                    builtin = get_full_name_for_node(original_node.func)
                    self._camel_diag(original_node, value, f'renamed "{value}" to "{snake}" in a {builtin} call')
                    replacement = cst.SimpleString(f"{literal.prefix}{literal.quote}{snake}{literal.quote}")
                    arguments = list(updated_node.args)
                    arguments[1] = arguments[1].with_changes(value=replacement)
                    updated_node = updated_node.with_changes(args=arguments)

        return updated_node

    def leave_Decorator(self, original_node: cst.Decorator, updated_node: cst.Decorator) -> cst.Decorator:
        # A lowlevel `@server.call_tool()` is syntactically identical to a high-level
        # `@mcp.tool()`; only the binding of the receiver tells them apart. Migrating
        # the registration also means reordering statements and rewriting the handler
        # signature, which a codemod must never guess at, so this is flag-only.
        decorator = original_node.decorator
        if (
            isinstance(decorator, cst.Call)
            and isinstance(decorator.func, cst.Attribute)
            and (get_full_name_for_node(decorator.func.value) or "") in self._lowlevel_server_vars
            and decorator.func.attr.value in LOWLEVEL_DECORATOR_METHODS
        ):
            method = decorator.func.attr.value
            receiver = get_full_name_for_node(decorator.func.value)
            self._diag(
                original_node,
                "lowlevel_decorator",
                "manual",
                f"the lowlevel `@{receiver}.{method}()` decorator was removed: pass "
                f"`{LOWLEVEL_DECORATOR_METHODS[method]}=` to the `Server(...)` constructor and rewrite "
                f"the handler to take `(ctx, params)` and return a result model",
            )
        return updated_node

    def visit_WithItem(self, node: cst.WithItem) -> None:
        # Only the `as (a, b, c)` form can have its unpacking REWRITTEN, which
        # `leave_WithItem` does; a v1 client call used any other way (no `as`, a
        # single name, `enter_async_context(...)`) gets the yield-shape marker
        # from `leave_Call` instead.
        if (
            isinstance(node.item, cst.Call)
            and node.asname is not None
            and isinstance(node.asname.name, cst.Tuple)
            and len(node.asname.name.elements) == 3
        ):
            self._narrowable_calls.add(id(node.item))

    def leave_WithItem(self, original_node: cst.WithItem, updated_node: cst.WithItem) -> cst.WithItem:
        # The removed-keyword check for these calls lives in `leave_Call`, which
        # sees every form; this narrows the one form whose unpacking is rewritable.
        if not isinstance(original_node.item, cst.Call):
            return updated_node
        if not self._qualified(original_node.item.func) & TRANSPORT_CLIENT_QNAMES:
            return updated_node
        target = original_node.asname
        if target is None or not isinstance(target.name, cst.Tuple):
            return updated_node
        elements = list(cst.ensure_type(cst.ensure_type(updated_node.asname, cst.AsName).name, cst.Tuple).elements)
        if len(elements) != 3:
            return updated_node
        # The third element used to be `get_session_id`, which no longer exists.
        # When it was bound to a real name rather than `_`, later uses will break.
        third = elements[2].value
        if not (isinstance(third, cst.Name) and third.value == "_"):
            self._diag(
                original_node,
                "transport_client_unpack",
                "manual",
                "the third value (`get_session_id`) is gone: remove every use of it",
            )
        self.rewrites["transport_client_unpack"] += 1
        kept = [elements[0], elements[1].with_changes(comma=cst.MaybeSentinel.DEFAULT)]
        narrowed = cst.ensure_type(updated_node.asname, cst.AsName)
        return updated_node.with_changes(
            asname=narrowed.with_changes(name=cst.ensure_type(narrowed.name, cst.Tuple).with_changes(elements=kept))
        )

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        # libCST parses a comment above a module's FIRST statement into
        # `Module.header`, not that statement's `leading_lines`, so the dedup in
        # `_with_markers` cannot see a marker a previous run put there and would
        # insert it again on every run. Drop any marker that is already rendered
        # in the header; everything else about the statement is left alone.
        if not updated_node.body:
            return updated_node
        in_header = {line.comment.value for line in original_node.header if line.comment is not None}
        if not in_header:
            return updated_node
        first = updated_node.body[0]
        kept_lines = [
            line
            for line in first.leading_lines
            if line.comment is None
            or line.comment.value not in in_header
            or not line.comment.value.startswith(f"# {MARKER}:")
        ]
        if len(kept_lines) == len(first.leading_lines):
            return updated_node
        return updated_node.with_changes(body=[first.with_changes(leading_lines=kept_lines), *updated_node.body[1:]])


def transform(source: str, *, add_markers: bool = True) -> Result:
    """Apply every v1 -> v2 rewrite to one module's source and report the rest.

    The returned code is always syntactically valid Python and preserves the input's
    formatting and comments everywhere it was not rewritten. Sites the codemod
    recognized but would not rewrite are described in `Result.diagnostics`; unless
    `add_markers` is false, each one also gets an inline `# mcp-codemod:` comment.

    Raises:
        libcst.ParserSyntaxError: if `source` is not parseable as Python.
    """
    wrapper = MetadataWrapper(cst.parse_module(source))
    prepass = _PrePass()
    wrapper.visit(prepass)
    transformer = _V1ToV2(prepass, add_markers=add_markers)
    module = wrapper.visit(transformer)
    return Result(module.code, transformer.diagnostics, transformer.rewrites)
