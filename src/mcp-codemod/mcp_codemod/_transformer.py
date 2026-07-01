"""The v1 -> v2 source transformer.

`transform()` is the whole programmatic surface: one module's source text in,
rewritten text plus diagnostics out. Rewrites are deliberately conservative: a
construct is rewritten only when its meaning is unambiguous from the file alone
(names resolved through the imports, camelCase renames restricted to v1's declared
field names); anything else is left as written under an inline `# mcp-codemod:`
marker. Running the transformer over its own output is a no-op.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar, cast

import libcst as cst
from libcst.helpers import get_full_name_for_node
from libcst.metadata import (
    CodeRange,
    MetadataWrapper,
    PositionProvider,
    QualifiedNameProvider,
    QualifiedNameSource,
)

from mcp_codemod._adapters import (
    ADAPTER_IMPORTS,
    LOWLEVEL_HANDLER_SPECS,
    TEMPLATE_LOCALS,
    build_adapter,
    cache_name,
    handler_name,
)
from mcp_codemod._mappings import (
    CAMEL_FIELDS,
    CLIENT_SESSION_QNAMES,
    ERRORDATA_QNAMES,
    FASTMCP_QNAMES,
    LOWLEVEL_CTOR_POSITIONAL_PARAMS,
    LOWLEVEL_REMOVED_ATTRS,
    LOWLEVEL_SERVER_QNAMES,
    MCPERROR_QNAMES,
    MODULE_RENAMES,
    PYDANTIC_URL_QNAMES,
    REHOMED_IMPORTS,
    REMOVED_APIS,
    REMOVED_ATTRS,
    REMOVED_CTOR_PARAMS,
    REMOVED_MODULES,
    SESSION_LIST_METHODS,
    SESSION_URI_METHODS,
    SYMBOL_RENAMES,
    TIMEDELTA_QNAMES,
    TRANSPORT_CLIENT_QNAMES,
    TRANSPORT_CLIENT_REMOVED_PARAMS,
    TRANSPORT_CLIENT_V1_QNAMES,
    TRANSPORT_CTOR_PARAMS,
    UNION_TYPE_ALIASES,
)

__all__ = ["Diagnostic", "MARKER", "Result", "transform"]

MARKER = "mcp-codemod"
"""The prefix of every inserted comment; `grep -rn '# mcp-codemod:'` lists the sites still needing a human."""

Severity = Literal["info", "review", "manual"]

# Longest prefix wins, should overlapping keys ever be added.
_MODULE_RENAMES_LONGEST_FIRST: tuple[tuple[str, str], ...] = tuple(
    sorted(MODULE_RENAMES.items(), key=lambda item: -len(item[0]))
)

_NodeT = TypeVar("_NodeT", bound=cst.CSTNode)
_StatementT = TypeVar("_StatementT", bound="cst.SimpleStatementLine | cst.BaseCompoundStatement")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding the codemod wants a human to see.

    `info`: a safe rewrite was applied, reported for the record; `review`: a rewrite
    was applied but rests on a heuristic; `manual`: nothing was rewritten.
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
    # A dotted path always parses to a Name or Attribute chain; `parse_expression` cannot say so.
    return cast("cst.Attribute | cst.Name", cst.parse_expression(dotted))


def _names_the_sdk(module: str) -> bool:
    """Whether a dotted module path belongs to the SDK: `mcp`, `mcp_types`, or below."""
    return module in ("mcp", "mcp_types") or module.startswith(("mcp.", "mcp_types."))


def _split_rehomed_imports(
    statement: cst.SimpleStatementLine, imported: cst.ImportFrom
) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.BaseStatement] | None:
    """Split `REHOMED_IMPORTS` names into their own from-import, or return None when there are none."""
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


def _import_binds(node: cst.BaseSmallStatement) -> set[str]:
    """The module-level names one import statement binds."""
    binds: set[str] = set()
    if isinstance(node, cst.Import):
        for alias in node.names:
            if alias.asname is not None:
                binds.add(cst.ensure_type(alias.asname.name, cst.Name).value)
            else:
                binds.add((get_full_name_for_node(alias.name) or "").split(".")[0])
    elif isinstance(node, cst.ImportFrom) and not isinstance(node.names, cst.ImportStar):
        for alias in node.names:
            bound = alias.asname.name if alias.asname is not None else alias.name
            binds.add(cst.ensure_type(bound, cst.Name).value)
    return binds


def _statement_binds(node: cst.BaseSmallStatement) -> set[str]:
    """The plain names one small statement binds (assignment targets and imports)."""
    binds = _import_binds(node)
    if isinstance(node, cst.Assign):
        for target in node.targets:
            if isinstance(target.target, cst.Name):
                binds.add(target.target.value)
    elif isinstance(node, cst.AnnAssign) and isinstance(node.target, cst.Name):
        binds.add(node.target.value)
    return binds


def _is_v2_timeout_shape(value: cst.BaseExpression) -> bool:
    """Whether a timeout expression is already valid v2: `None`, a numeric literal,
    or a `.total_seconds()` call (including the one a previous run emitted)."""
    if isinstance(value, cst.Name) and value.value == "None":
        return True
    if isinstance(value, cst.Integer | cst.Float):
        return True
    return (
        isinstance(value, cst.Call)
        and isinstance(value.func, cst.Attribute)
        and value.func.attr.value == "total_seconds"
    )


def _with_markers(statement: _StatementT, messages: Sequence[str]) -> _StatementT:
    """Prepend a `# mcp-codemod:` comment per distinct message not already present."""
    existing = {line.comment.value for line in statement.leading_lines if line.comment is not None}
    # `dict.fromkeys` rather than a set: dedupe while keeping first-seen order.
    comments = list(dict.fromkeys(f"# {MARKER}: {message}" for message in messages))
    fresh = [comment for comment in comments if comment not in existing]
    if not fresh:
        return statement
    inserted = [cst.EmptyLine(comment=cst.Comment(comment)) for comment in fresh]
    return statement.with_changes(leading_lines=[*statement.leading_lines, *inserted])


class _PrePass(cst.CSTVisitor):
    """Collect the facts the transformer needs before it rewrites anything.

    `imports_mcp` gates the name-only heuristics to files that import the SDK
    (v1's `mcp` or v2's `mcp_types` -- a half-migrated file is still in scope).
    `lowlevel_server_vars` tells a lowlevel `Server`'s decorators apart from the
    syntactically identical `MCPServer` ones; `user_declared_camel` is every
    allowlisted camelCase name a class body in this file declares itself.
    `client_session_vars` backs the session-method rewrites, and `bound_names` /
    `import_binds` back the adapter name-collision and import-injection checks.
    """

    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    def __init__(self) -> None:
        self.imports_mcp = False
        self.plain_imports: set[str] = set()
        self.unrenamed_reference_roots: set[str] = set()
        self.user_declared_camel: set[str] = set()
        self.lowlevel_server_vars: set[str] = set()
        self.client_session_vars: set[str] = set()
        self.bound_names: set[str] = set()
        self.import_binds: set[str] = set()
        # Module-level bindings only: a function-local `json = ...` cannot shadow
        # an injected module import, and a TYPE_CHECKING-gated import does not
        # bind at runtime, so both are computed from the module body directly.
        self.module_bindings: set[str] = set()
        self.module_import_binds: set[str] = set()
        self._class_depth = 0

    def visit_Module(self, node: cst.Module) -> None:
        for statement in node.body:
            if isinstance(statement, cst.FunctionDef | cst.ClassDef):
                self.module_bindings.add(statement.name.value)
                continue
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for small in statement.body:
                for bind in _statement_binds(small):
                    self.module_bindings.add(bind)
                if isinstance(small, cst.Import | cst.ImportFrom):
                    for bind in _import_binds(small):
                        self.module_import_binds.add(bind)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.bound_names.add(node.name.value)
        self._class_depth += 1

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._class_depth -= 1

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if not isinstance(node.names, cst.ImportStar):
            for alias in node.names:
                # A from-import alias (and its `as` name) is always a plain Name.
                bound = cst.ensure_type(alias.asname.name if alias.asname is not None else alias.name, cst.Name)
                self.import_binds.add(bound.value)
                self.bound_names.add(bound.value)
        if node.relative or node.module is None:
            return
        if _names_the_sdk(get_full_name_for_node(node.module) or ""):
            self.imports_mcp = True

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name = get_full_name_for_node(alias.name) or ""
            self.plain_imports.add(name)
            # `import a.b` binds `a`; `import a.b as c` binds `c`.
            bound = alias.asname.name if alias.asname is not None else None
            bind = bound.value if isinstance(bound, cst.Name) else name.split(".")[0]
            self.import_binds.add(bind)
            self.bound_names.add(bind)
            if _names_the_sdk(name):
                self.imports_mcp = True

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.bound_names.add(node.name.value)
        for param in (*node.params.posonly_params, *node.params.params, *node.params.kwonly_params):
            if param.annotation is not None:
                annotated = {
                    q.name
                    for q in self.get_metadata(QualifiedNameProvider, param.annotation.annotation, frozenset())
                    if q.source is not QualifiedNameSource.LOCAL
                }
                if annotated & CLIENT_SESSION_QNAMES:
                    self.client_session_vars.add(param.name.value)

    def visit_WithItem(self, node: cst.WithItem) -> None:
        if node.asname is not None:
            self._record_binding(node.item, node.asname.name)

    def visit_Attribute(self, node: cst.Attribute) -> None:
        # Renaming `import mcp.types` to `import mcp_types` also unbinds `mcp` -- a
        # problem only when a reference no module rename covers still resolves through it.
        for qualified in self.get_metadata(QualifiedNameProvider, node, frozenset()):
            if qualified.source is not QualifiedNameSource.LOCAL and _rename_module(qualified.name) is None:
                self.unrenamed_reference_roots.add(qualified.name.split(".")[0])

    def _record_binding(self, value: cst.BaseExpression | None, target: cst.BaseExpression) -> None:
        """Record a name bound to a lowlevel `Server(...)` or a `ClientSession(...)`, `self.server` included."""
        bound = get_full_name_for_node(target)
        if bound is not None and isinstance(target, cst.Name):
            self.bound_names.add(bound)
        if not isinstance(value, cst.Call) or bound is None:
            return
        qualified = {
            q.name
            for q in self.get_metadata(QualifiedNameProvider, value.func, frozenset())
            if q.source is not QualifiedNameSource.LOCAL
        }
        if qualified & LOWLEVEL_SERVER_QNAMES:
            self.lowlevel_server_vars.add(bound)
        elif qualified & CLIENT_SESSION_QNAMES:
            self.client_session_vars.add(bound)

    def _record_class_field(self, target: cst.BaseExpression) -> None:
        """Remember a camelCase name a class body in this file declares as its own."""
        if self._class_depth and isinstance(target, cst.Name) and target.value in CAMEL_FIELDS:
            self.user_declared_camel.add(target.value)

    def visit_Assign(self, node: cst.Assign) -> None:
        for target in node.targets:
            self._record_class_field(target.target)
            self._record_binding(node.value, target.target)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self._record_class_field(node.target)
        self._record_binding(node.value, node.target)


class _V1ToV2(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (QualifiedNameProvider, PositionProvider)

    def __init__(self, prepass: _PrePass, *, add_markers: bool) -> None:
        super().__init__()
        self._imports_mcp = prepass.imports_mcp
        self._plain_imports = prepass.plain_imports
        self._unrenamed_reference_roots = prepass.unrenamed_reference_roots
        self._user_declared_camel = prepass.user_declared_camel
        self._lowlevel_server_vars = prepass.lowlevel_server_vars
        self._client_session_vars = prepass.client_session_vars
        self._bound_names = prepass.bound_names
        self._module_bindings = prepass.module_bindings
        self._module_import_binds = prepass.module_import_binds
        self._add_markers = add_markers
        # `ADAPTER_IMPORTS` names the emitted adapters reference; `leave_Module` injects the missing imports.
        self._needed_imports: set[str] = set()
        # One frame per open class definition: whether it subclasses `McpError`.
        self._in_mcperror_class: list[bool] = []
        self.diagnostics: list[Diagnostic] = []
        self.rewrites: Counter[str] = Counter()
        # Name nodes that are not references (an attribute's `.attr`, a `kwarg=`, a parameter).
        self._not_a_reference: set[int] = set()
        # Pending marker texts per open statement, attached on the way out; the bottom frame is a sentinel.
        self._pending_markers: list[list[str]] = [[]]
        # Calls that are a `with` item bound to a three-element tuple: the one form `leave_WithItem` rewrites.
        self._narrowable_calls: set[int] = set()

    # -------------------------------------------------------------- bookkeeping

    def _qualified(self, node: cst.CSTNode) -> set[str]:
        """The dotted names `node` resolves to through an import or to a builtin.

        LOCAL-only resolutions are excluded: `mcp` is the most common variable name
        in real MCP code, and an attribute chain on such a variable carries a
        qualified name spelled exactly like a module path (`mcp.types`).
        """
        return {
            q.name
            for q in self.get_metadata(QualifiedNameProvider, node, frozenset())
            if q.source is not QualifiedNameSource.LOCAL
        }

    def _root_still_bound(self, root: str, renamed_import: str) -> bool:
        """Whether a plain import other than `renamed_import` still binds `root`."""
        for plain in self._plain_imports - {renamed_import}:
            survives = _rename_module(plain) or plain
            if survives == root or survives.startswith(f"{root}."):
                return True
        return False

    def _diag(self, node: cst.CSTNode, transform: str, severity: Severity, message: str) -> None:
        # The cast: pyright cannot solve `get_metadata`'s generic for `PositionProvider`.
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
                # Statement-level transforms only return the statement itself or a FlattenSentinel.
                if isinstance(result, cst.FlattenSentinel):
                    # Markers on a split statement go above its first piece.
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

    # ------------------------------------------------------------------ imports

    def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
        if updated_node.relative or updated_node.module is None:
            return updated_node
        module = get_full_name_for_node(updated_node.module) or ""

        # One statement-level marker covers everything imported from a deleted module.
        if (module_guidance := _removed_module(module)) is not None:
            self._diag(original_node, "removed_module", "manual", f"`{module}` {module_guidance}")
            return updated_node

        # `QualifiedNameProvider` resolves references, not the import alias that
        # creates the binding, so renames and removed-name markers apply here directly.
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
                # `import mcp.types` also bound `mcp`; renaming to a different root drops
                # that binding, a problem only when the pre-pass saw another reference still
                # resolving through it. (`PositionProvider` has no entry for an `ImportAlias`.)
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
        # `from <parent> import <child>` of a renamed module bound the OLD module
        # object; only a real import of the new module can rebind the local name.
        if len(updated_node.body) != 1:
            return updated_node
        imported = updated_node.body[0]
        if not isinstance(imported, cst.ImportFrom) or isinstance(imported.names, cst.ImportStar):
            return updated_node
        if imported.relative or imported.module is None:
            return updated_node
        # `leave_ImportFrom` has already run, so the split is against the renamed spelling.
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
            # Keep the original line's leading lines and trailing comment (`# noqa`, ...).
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
            # An aliased import keeps its local spelling; only the original name is rewritten.
            if new is not None and original_node.value == qualified.rsplit(".", 1)[-1]:
                self.rewrites["symbol_rename"] += 1
                return updated_node.with_changes(value=new)
        return updated_node

    def leave_Attribute(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.BaseExpression:
        # `e.error.code` is deliberately NOT collapsed to `e.code`: v2 keeps a typed
        # `.error`, so the v1 spelling still runs -- migration, not modernization.

        # An attribute the lowlevel `Server` lost, on a receiver the pre-pass proved is one.
        if (get_full_name_for_node(original_node.value) or "") in self._lowlevel_server_vars and (
            lowlevel_guidance := LOWLEVEL_REMOVED_ATTRS.get(original_node.attr.value)
        ) is not None:
            self._diag(original_node, "removed_attr", "manual", lowlevel_guidance)
            return updated_node

        qualified_names = self._qualified(original_node)
        # Pydantic classmethods are gone from the union aliases on v2.
        if original_node.attr.value.startswith("model_"):
            receiver_names = self._qualified(original_node.value)
            for qualified in receiver_names:
                if (alias := UNION_TYPE_ALIASES.get(qualified)) is not None:
                    self._diag(
                        original_node,
                        "union_alias",
                        "manual",
                        f"`{alias}` is a plain union type on v2 with no pydantic methods: "
                        f"validate with `pydantic.TypeAdapter({alias})` instead",
                    )
                    break

        dotted = get_full_name_for_node(original_node)
        # The innermost node naming a renamed module (`mcp.types` inside `mcp.types.Tool`),
        # rewritten only in lockstep with a backing plain import: after a bare
        # `import mcp`, rewriting would leave nothing importing the new module.
        if dotted in MODULE_RENAMES and dotted in qualified_names:
            if dotted in self._plain_imports:
                self.rewrites["module_rename"] += 1
                return _dotted_name(MODULE_RENAMES[dotted])
            # A prefix of some plain import needs nothing here: the longer node is being rewritten.
            if not any(plain.startswith(f"{dotted}.") for plain in self._plain_imports):
                self._diag(
                    original_node,
                    "module_rename",
                    "manual",
                    f"`{dotted}` no longer exists: import `{MODULE_RENAMES[dotted]}` and use it here instead",
                )
            return updated_node

        # The mirror of `leave_Name`: removed or renamed symbols reached as a module attribute.
        for qualified in qualified_names:
            if qualified in REMOVED_APIS:
                self._diag(original_node, "removed_api", "manual", f"`{qualified}` {REMOVED_APIS[qualified]}")
                return updated_node
            new = SYMBOL_RENAMES.get(qualified)
            if new is not None and original_node.attr.value == qualified.rsplit(".", 1)[-1]:
                self.rewrites["symbol_rename"] += 1
                return updated_node.with_changes(attr=cst.Name(new))

        # The remaining checks key on the bare attribute name alone: only in an
        # SDK-importing file, never on a receiver the imports prove is something else.
        if not self._imports_mcp or any(not _names_the_sdk(qualified) for qualified in qualified_names):
            return updated_node

        if (guidance := REMOVED_ATTRS.get(original_node.attr.value)) is not None:
            self._diag(original_node, "removed_attr", "manual", guidance)
            return updated_node

        camel = original_node.attr.value
        if camel in CAMEL_FIELDS:
            if camel in self._user_declared_camel:
                # A class in this file declares this same field, so some receivers
                # are the user's own objects: mark every use rather than break them.
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

    def _rewrite_session_timeout(self, callee: set[str], original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        """Convert `ClientSession`'s v1 `timedelta` timeout to v2's float seconds.

        Only an inline `timedelta(...)` is provably convertible; any other non-None
        value gets a marker instead of a guess.
        """
        if not callee & CLIENT_SESSION_QNAMES:
            return updated_node
        arguments = list(updated_node.args)
        # Qualified-name metadata exists only for ORIGINAL nodes; the rewrite applies to updated ones.
        for index, argument in enumerate(original_node.args):
            positional_timeout = index == 2 and argument.keyword is None and argument.star == ""
            keyword_timeout = argument.keyword is not None and argument.keyword.value == "read_timeout_seconds"
            if not (positional_timeout or keyword_timeout):
                continue
            value = argument.value
            if isinstance(value, cst.Call) and self._qualified(value.func) & TIMEDELTA_QNAMES:
                self.rewrites["timeout_seconds"] += 1
                self._diag(original_node, "timeout_seconds", "info", "converted a `timedelta` timeout to seconds")
                arguments[index] = arguments[index].with_changes(
                    value=cst.Call(func=cst.Attribute(value=arguments[index].value, attr=cst.Name("total_seconds")))
                )
                updated_node = updated_node.with_changes(args=arguments)
            elif not _is_v2_timeout_shape(value):
                self._diag(
                    original_node,
                    "timeout_seconds",
                    "manual",
                    "v1's `read_timeout_seconds` was a `timedelta`; v2 takes float seconds: "
                    "pass this value's `.total_seconds()`",
                )
        return updated_node

    def _rewrite_session_method(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        """Rewrite `cursor=` and pydantic-URL uris on a receiver the pre-pass proved is a `ClientSession`."""
        function = original_node.func
        if (
            isinstance(function, cst.Attribute)
            and (get_full_name_for_node(function.value) or "") in self._client_session_vars
        ):
            method = function.attr.value
            if method in SESSION_LIST_METHODS and len(original_node.args) == 1:
                argument = original_node.args[0]
                if argument.keyword is not None and argument.keyword.value == "cursor":
                    self._needed_imports.add("mcp_types")
                    self.rewrites["session_cursor"] += 1
                    self._diag(original_node, "session_cursor", "info", "wrapped `cursor=` in `PaginatedRequestParams`")
                    wrapped = cst.Call(
                        func=_dotted_name("mcp_types.PaginatedRequestParams"),
                        args=[
                            cst.Arg(
                                keyword=cst.Name("cursor"),
                                value=updated_node.args[0].value,
                                equal=cst.AssignEqual(
                                    whitespace_before=cst.SimpleWhitespace(""),
                                    whitespace_after=cst.SimpleWhitespace(""),
                                ),
                            )
                        ],
                    )
                    updated_node = updated_node.with_changes(
                        args=[updated_node.args[0].with_changes(keyword=cst.Name("params"), value=wrapped)]
                    )
            elif method in SESSION_URI_METHODS and len(original_node.args) == 1:
                value = original_node.args[0].value
                if (
                    original_node.args[0].keyword is None
                    and isinstance(value, cst.Call)
                    and self._qualified(value.func) & PYDANTIC_URL_QNAMES
                    and len(value.args) == 1
                    and value.args[0].keyword is None
                ):
                    self.rewrites["uri_str"] += 1
                    self._diag(original_node, "uri_str", "info", f"`{method}` takes a plain `str` uri on v2")
                    unwrapped = cst.ensure_type(updated_node.args[0].value, cst.Call).args[0].value
                    updated_node = updated_node.with_changes(args=[updated_node.args[0].with_changes(value=unwrapped)])
        return updated_node

    def _rewrite_uri_kwargs(self, callee: set[str], original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        """Unwrap a pydantic URL passed as `uri=`: rewritten on a proven SDK callee, marked elsewhere."""
        # Qualified-name metadata exists only for ORIGINAL nodes; the rewrite applies to updated ones.
        for index, argument in enumerate(original_node.args):
            value = argument.value
            if (
                argument.keyword is not None
                and argument.keyword.value == "uri"
                and isinstance(value, cst.Call)
                and self._qualified(value.func) & PYDANTIC_URL_QNAMES
                and len(value.args) == 1
                and value.args[0].keyword is None
            ):
                if any(name == "mcp" or name.startswith(("mcp.", "mcp_types.")) for name in callee):
                    self.rewrites["uri_str"] += 1
                    self._diag(original_node, "uri_str", "info", "resource URIs are plain `str` on v2")
                    arguments = list(updated_node.args)
                    unwrapped = cst.ensure_type(arguments[index].value, cst.Call).args[0].value
                    arguments[index] = arguments[index].with_changes(value=unwrapped)
                    updated_node = updated_node.with_changes(args=arguments)
                elif self._imports_mcp:
                    self._diag(
                        original_node,
                        "uri_str",
                        "manual",
                        "v2 resource URIs are plain `str`: drop this URL wrapper if the value lands in an mcp type",
                    )
        return updated_node

    def _flag_union_construction(self, callee: set[str], original_node: cst.Call) -> None:
        """Flag construction of a v1 RootModel wrapper that is a plain union alias on v2."""
        for qualified in callee:
            if (alias := UNION_TYPE_ALIASES.get(qualified)) is not None:
                self._diag(
                    original_node,
                    "union_alias",
                    "manual",
                    f"`{alias}` is a plain union type on v2 and cannot be constructed: "
                    f"build the concrete message type instead",
                )

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        callee = self._qualified(original_node.func)

        # v1's single-`ErrorData` constructor maps exactly onto v2's classmethod
        # `MCPError.from_error_data(...)`; `leave_Name` has already renamed the name itself.
        if callee & MCPERROR_QNAMES and len(original_node.args) == 1:
            self.rewrites["mcperror_ctor"] += 1
            return updated_node.with_changes(
                func=cst.Attribute(value=updated_node.func, attr=cst.Name("from_error_data"))
            )

        # `super().__init__(...)` cannot become a classmethod call, so an inline
        # `ErrorData(...)` is flattened into v2's `(code, message, data=None)`.
        if self._is_mcperror_super_init(original_node) and len(original_node.args) == 1:
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

        self._flag_union_construction(callee, original_node)

        # camelCase kwargs still work at RUNTIME on v2 (fields accept their aliases)
        # but fail type-checking against the snake_case `__init__` signatures. The
        # rename cannot break the call, so no review marker even for the risky tier.
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

        # Transport keywords moved off the constructor; where they belong depends on
        # how the server is started, so they stay put (v2 rejects them loudly).
        if callee & FASTMCP_QNAMES:
            for index, argument in enumerate(original_node.args):
                keyword = argument.keyword.value if argument.keyword is not None else ""
                # v1's positional order was `(name, instructions, ...)`; v2's second
                # parameter is `title`, so later positionals would silently land wrong.
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

        # v2's lowlevel `Server` ctor is keyword-only after `name` but kept v1's
        # parameter names and order, so positionals convert one for one; a `*`-splat
        # hides how many positions it fills and is left for v2 to reject.
        if (
            callee & LOWLEVEL_SERVER_QNAMES
            and 1 < len(original_node.args) <= 1 + len(LOWLEVEL_CTOR_POSITIONAL_PARAMS)
            and not any(argument.star for argument in original_node.args)
        ):
            arguments = []
            for index, argument in enumerate(updated_node.args):
                if index > 0 and argument.keyword is None:
                    self.rewrites["lowlevel_ctor_kwargs"] += 1
                    argument = argument.with_changes(
                        keyword=cst.Name(LOWLEVEL_CTOR_POSITIONAL_PARAMS[index - 1]),
                        equal=cst.AssignEqual(
                            whitespace_before=cst.SimpleWhitespace(""), whitespace_after=cst.SimpleWhitespace("")
                        ),
                    )
                arguments.append(argument)
            if arguments != list(updated_node.args):
                updated_node = updated_node.with_changes(args=arguments)

        updated_node = self._rewrite_session_timeout(callee, original_node, updated_node)
        updated_node = self._rewrite_session_method(original_node, updated_node)
        updated_node = self._rewrite_uri_kwargs(callee, original_node, updated_node)

        # The keyword check lives here so it fires however the call is used; only the
        # `as (read, write, _)` with-item form gets its unpacking rewritten
        # (`leave_WithItem` does), every other use of the v1 name is flagged.
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

        # A `getattr`/`hasattr`/`setattr` name string is the one string position the
        # rename applies to; other literals never are -- camelCase IS the wire format.
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

    def _lowlevel_decorator(self, node: cst.FunctionDef) -> tuple[str, str, cst.Call] | None:
        """The (receiver, kind, decorator call) of a lowlevel registration, or None."""
        for wrapper in node.decorators:
            decorator = wrapper.decorator
            if (
                isinstance(decorator, cst.Call)
                and isinstance(decorator.func, cst.Attribute)
                and (get_full_name_for_node(decorator.func.value) or "") in self._lowlevel_server_vars
                and decorator.func.attr.value in LOWLEVEL_HANDLER_SPECS
            ):
                return (
                    cast(str, get_full_name_for_node(decorator.func.value)),
                    decorator.func.attr.value,
                    decorator,
                )
        return None

    def _lowlevel_blocker(self, node: cst.FunctionDef, receiver: str, kind: str, decorator: cst.Call) -> str | None:
        """Why this decorator site cannot be rewritten, or None when it can.

        Each check guards a way the generated adapter could silently misbehave
        rather than fail loudly.
        """
        if len(node.decorators) > 1:
            return "another decorator is stacked on it"
        if "." in receiver:
            return "the server is reached through an attribute"
        if self._in_mcperror_class:
            return "the handler is defined in a class body"
        if node.asynchronous is None:
            return "the handler is not `async def`"
        arguments = decorator.args
        if kind == "call_tool" and len(arguments) == 1:
            argument = arguments[0]
            if not (
                argument.keyword is not None
                and argument.keyword.value == "validate_input"
                and isinstance(argument.value, cst.Name)
                and argument.value.value in ("True", "False")
            ):
                return "the decorator call has arguments the codemod cannot evaluate"
        elif arguments:
            return "the decorator call has arguments the codemod cannot evaluate"
        parameters = node.params
        if (
            parameters.star_kwarg is not None
            or parameters.kwonly_params
            or not isinstance(parameters.star_arg, cst.MaybeSentinel)
        ):
            return "the handler signature does not match the v1 form"
        positional = [*parameters.posonly_params, *parameters.params]
        required = sum(1 for parameter in positional if parameter.default is None)
        if not required <= LOWLEVEL_HANDLER_SPECS[kind].arity <= len(positional):
            return "the handler signature does not match the v1 form"
        emitted = {handler_name(node.name.value)}
        if kind == "call_tool":
            emitted.add(cache_name(receiver))
        if emitted & self._bound_names:
            return "a generated name is already bound in this file"
        if node.name.value in TEMPLATE_LOCALS[kind]:
            return "the handler's name collides with a name the generated adapter uses"
        # A module-level non-import binding of a name the adapter references would
        # shadow the injected import (`json = None` breaks `json.dumps` at runtime).
        needed = set(LOWLEVEL_HANDLER_SPECS[kind].imports) | {"AnyUrl"}
        if needed & (self._module_bindings - self._module_import_binds):
            return "a name the generated adapter needs is already bound in this file"
        return None

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.BaseStatement | cst.FlattenSentinel[cst.BaseStatement]:
        found = self._lowlevel_decorator(original_node)
        if found is None:
            return updated_node
        receiver, kind, decorator = found
        blocked = self._lowlevel_blocker(original_node, receiver, kind, decorator)
        if blocked is not None:
            register = (
                "add_notification_handler" if LOWLEVEL_HANDLER_SPECS[kind].notification else "add_request_handler"
            )
            self._diag(
                original_node,
                "lowlevel_registration",
                "manual",
                f"the lowlevel `@{receiver}.{kind}()` decorator was removed and this site was not rewritten "
                f"automatically ({blocked}): register the handler with `{receiver}.{register}(...)` "
                f"taking `(ctx, params)`",
            )
            return updated_node
        validate_input = True
        for argument in decorator.args:
            validate_input = cst.ensure_type(argument.value, cst.Name).value == "True"
        # v1 always passed `AnyUrl` to the uri kinds, but a handler annotated
        # `uri: str` declared its own contract -- honor it and skip the wrapper.
        uri_as_str = False
        if kind in ("read_resource", "subscribe_resource", "unsubscribe_resource"):
            parameter = [*original_node.params.posonly_params, *original_node.params.params][0]
            annotation = parameter.annotation.annotation if parameter.annotation is not None else None
            uri_as_str = isinstance(annotation, cst.Name) and annotation.value == "str"
            if not uri_as_str:
                self._needed_imports.add("AnyUrl")
        spec = LOWLEVEL_HANDLER_SPECS[kind]
        self._needed_imports.update(spec.imports)
        self.rewrites["lowlevel_registration"] += 1
        self._diag(
            original_node,
            "lowlevel_registration",
            "info",
            f"registered `{original_node.name.value}` for `{kind}` through a generated v1-compat adapter",
        )
        adapter = list(
            cst.parse_module(
                build_adapter(
                    kind, original_node.name.value, receiver, validate_input=validate_input, uri_as_str=uri_as_str
                )
            ).body
        )
        # `parse_module` files leading blank lines under `Module.header`; restore the separation.
        adapter[0] = adapter[0].with_changes(leading_lines=[cst.EmptyLine(), cst.EmptyLine()])
        stripped = updated_node.with_changes(
            decorators=[],
            leading_lines=[*updated_node.leading_lines, *updated_node.decorators[0].leading_lines],
        )
        return cst.FlattenSentinel([stripped, *adapter])

    def visit_WithItem(self, node: cst.WithItem) -> None:
        # Only `as (a, b, c)` can have its unpacking rewritten; every other use of a
        # v1 client call gets the yield-shape marker from `leave_Call` instead.
        if (
            isinstance(node.item, cst.Call)
            and node.asname is not None
            and isinstance(node.asname.name, cst.Tuple)
            and len(node.asname.name.elements) == 3
        ):
            self._narrowable_calls.add(id(node.item))

    def leave_WithItem(self, original_node: cst.WithItem, updated_node: cst.WithItem) -> cst.WithItem:
        # `leave_Call` covers the removed keywords; this narrows the one rewritable form.
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
        # A third element bound to a real name (not `_`) leaves broken uses behind.
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
        # Imports the generated adapters need. Inserted at the TOP of the module
        # (below only the docstring and `__future__` imports) so they precede the
        # registration code wherever the decorator sat -- a mid-file import as the
        # anchor would leave the adapter running before its imports bind. Dedup is
        # against the updated module's top-level import binds, so a rename this
        # run produced (`import mcp_types as types`) counts and a conditional or
        # function-local import does not.
        if self._needed_imports:
            bound: set[str] = set()
            body = list(updated_node.body)
            insert_at = 0
            for index, statement in enumerate(body):
                if not isinstance(statement, cst.SimpleStatementLine):
                    continue
                for small in statement.body:
                    bound |= _import_binds(small)
                    is_docstring = index == 0 and isinstance(small, cst.Expr)
                    is_future = (
                        isinstance(small, cst.ImportFrom)
                        and small.module is not None
                        and get_full_name_for_node(small.module) == "__future__"
                    )
                    if (is_docstring or is_future) and insert_at == index:
                        insert_at = index + 1
            missing = [name for name in ADAPTER_IMPORTS if name in self._needed_imports and name not in bound]
            if missing:
                body[insert_at:insert_at] = [cst.parse_statement(ADAPTER_IMPORTS[name]) for name in missing]
                updated_node = updated_node.with_changes(body=body)

        # libCST parses a comment above the module's FIRST statement into
        # `Module.header`, not `leading_lines`, so `_with_markers` cannot see a
        # marker a previous run put there; drop any already rendered in the header.
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

    The output is always valid Python with the input's formatting preserved outside
    rewrites; unless `add_markers` is false, each non-info diagnostic also gets an
    inline `# mcp-codemod:` comment.

    Raises:
        libcst.ParserSyntaxError: if `source` is not parseable as Python.
    """
    wrapper = MetadataWrapper(cst.parse_module(source))
    prepass = _PrePass()
    wrapper.visit(prepass)
    transformer = _V1ToV2(prepass, add_markers=add_markers)
    module = wrapper.visit(transformer)
    return Result(module.code, transformer.diagnostics, transformer.rewrites)
