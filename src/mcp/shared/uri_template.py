"""RFC 6570 URI Templates with bidirectional support.

Provides both expansion (template + variables → URI) and matching
(URI → variables). RFC 6570 only specifies expansion; matching is the
inverse operation needed by MCP servers to route ``resources/read``
requests to handlers.

Supports Levels 1-3 fully, plus Level 4 explode modifier for path-like
operators (``{/var*}``, ``{.var*}``, ``{;var*}``). The Level 4 prefix
modifier (``{var:N}``) and query-explode (``{?var*}``) are not supported.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import quote, unquote

__all__ = ["InvalidUriTemplate", "Operator", "UriTemplate", "Variable"]

Operator = Literal["", "+", "#", ".", "/", ";", "?", "&"]

_OPERATORS: frozenset[str] = frozenset({"+", "#", ".", "/", ";", "?", "&"})

# RFC 6570 §2.3: varname = varchar *(["."] varchar), varchar = ALPHA / DIGIT / "_"
# (Percent-encoded varchars are technically allowed but unseen in practice.)
_VARNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.]*$")

DEFAULT_MAX_TEMPLATE_LENGTH = 1_000_000
DEFAULT_MAX_EXPRESSIONS = 10_000

# RFC 3986 reserved characters, kept unencoded by {+var} and {#var}.
_RESERVED = ":/?#[]@!$&'()*+,;="


@dataclass(frozen=True)
class _OperatorSpec:
    """Expansion behavior for a single operator (RFC 6570 §3.2, Table in §A)."""

    prefix: str
    """Leading character emitted before the first variable."""
    separator: str
    """Character between variables (and between exploded list items)."""
    named: bool
    """Emit ``name=value`` pairs (query/path-param style) rather than bare values."""
    allow_reserved: bool
    """Keep reserved characters unencoded ({+var}, {#var})."""


_OPERATOR_SPECS: dict[Operator, _OperatorSpec] = {
    "": _OperatorSpec(prefix="", separator=",", named=False, allow_reserved=False),
    "+": _OperatorSpec(prefix="", separator=",", named=False, allow_reserved=True),
    "#": _OperatorSpec(prefix="#", separator=",", named=False, allow_reserved=True),
    ".": _OperatorSpec(prefix=".", separator=".", named=False, allow_reserved=False),
    "/": _OperatorSpec(prefix="/", separator="/", named=False, allow_reserved=False),
    ";": _OperatorSpec(prefix=";", separator=";", named=True, allow_reserved=False),
    "?": _OperatorSpec(prefix="?", separator="&", named=True, allow_reserved=False),
    "&": _OperatorSpec(prefix="&", separator="&", named=True, allow_reserved=False),
}

# Per-operator character class for regex matching. Each pattern matches
# the characters that can appear in an expanded value for that operator,
# stopping at the next structural delimiter.
_MATCH_PATTERN: dict[Operator, str] = {
    "": r"[^/?#&,]+",  # simple: everything structural is pct-encoded
    "+": r"[^?#]+",  # reserved: / allowed, stop at query/fragment
    "#": r".+",  # fragment: tail of URI
    ".": r"[^./?#]+",  # label: stop at next .
    "/": r"[^/?#]+",  # path segment: stop at next /
    ";": r"[^;/?#]*",  # path-param value (may be empty: ;name)
    "?": r"[^&#]*",  # query value (may be empty: ?name=)
    "&": r"[^&#]*",  # query-cont value
}

# Characters that must not appear in a DECODED value for each operator.
# If %2F smuggles a / into a simple {var}, the decoded value violates
# the template author's declared structure and the match is rejected.
_STRUCTURAL_FORBIDDEN: dict[Operator, frozenset[str]] = {
    "": frozenset("/?#&"),
    "+": frozenset(),
    "#": frozenset(),
    ".": frozenset("./?#"),
    "/": frozenset("/?#"),
    ";": frozenset(";/?#"),
    "?": frozenset("&#"),
    "&": frozenset("&#"),
}


class InvalidUriTemplate(ValueError):
    """Raised when a URI template string is malformed or unsupported.

    Attributes:
        template: The template string that failed to parse.
        position: Character offset where the error was detected, or None
            if the error is not tied to a specific position.
    """

    def __init__(self, message: str, *, template: str, position: int | None = None) -> None:
        super().__init__(message)
        self.template = template
        self.position = position


@dataclass(frozen=True)
class Variable:
    """A single variable within a URI template expression."""

    name: str
    operator: Operator
    explode: bool = False


@dataclass(frozen=True)
class _Expression:
    """A parsed ``{...}`` expression: one operator, one or more variables."""

    operator: Operator
    variables: tuple[Variable, ...]


_Part = str | _Expression


def _is_str_sequence(value: object) -> bool:
    """Check if value is a non-string sequence whose items are all strings."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        return False
    seq = cast(Sequence[object], value)
    return all(isinstance(item, str) for item in seq)


def _encode(value: str, *, allow_reserved: bool) -> str:
    """Percent-encode a value per RFC 6570 §3.2.1.

    Simple expansion encodes everything except unreserved characters.
    Reserved expansion ({+var}, {#var}) additionally keeps RFC 3986
    reserved characters intact.
    """
    safe = _RESERVED if allow_reserved else ""
    return quote(value, safe=safe)


def _expand_expression(expr: _Expression, variables: Mapping[str, str | Sequence[str]]) -> str:
    """Expand a single ``{...}`` expression into its URI fragment.

    Walks the expression's variables, encoding and joining defined ones
    according to the operator's spec. Undefined variables are skipped
    (RFC 6570 §2.3); if all are undefined, the expression contributes
    nothing (no prefix is emitted).
    """
    spec = _OPERATOR_SPECS[expr.operator]
    rendered: list[str] = []

    for var in expr.variables:
        if var.name not in variables:
            # Undefined: skip entirely, no placeholder.
            continue

        value = variables[var.name]

        # Explicit type guard: reject non-str scalars with a clear message
        # rather than a confusing "not iterable" from the sequence branch.
        if not isinstance(value, str) and not _is_str_sequence(value):
            raise TypeError(f"Variable {var.name!r} must be str or a sequence of str, got {type(value).__name__}")

        if isinstance(value, str):
            encoded = _encode(value, allow_reserved=spec.allow_reserved)
            if spec.named:
                # ; uses "name" for empty values, ?/& use "name=" (RFC §3.2.7-8)
                if value == "" and expr.operator == ";":
                    rendered.append(var.name)
                else:
                    rendered.append(f"{var.name}={encoded}")
            else:
                rendered.append(encoded)
        else:
            # Sequence value.
            items = [_encode(v, allow_reserved=spec.allow_reserved) for v in value]
            if not items:
                continue
            if var.explode:
                # Each item gets the operator's separator; named ops repeat the key.
                if spec.named:
                    rendered.append(spec.separator.join(f"{var.name}={v}" for v in items))
                else:
                    rendered.append(spec.separator.join(items))
            else:
                # Non-explode: comma-join into a single value.
                joined = ",".join(items)
                rendered.append(f"{var.name}={joined}" if spec.named else joined)

    if not rendered:
        return ""
    return spec.prefix + spec.separator.join(rendered)


@dataclass(frozen=True)
class UriTemplate:
    """A parsed RFC 6570 URI template.

    Construct via :meth:`parse`. Instances are immutable and hashable;
    equality is based on the template string alone.
    """

    template: str
    _parts: tuple[_Part, ...] = field(repr=False, compare=False)
    _variables: tuple[Variable, ...] = field(repr=False, compare=False)
    _pattern: re.Pattern[str] = field(repr=False, compare=False)

    @classmethod
    def parse(
        cls,
        template: str,
        *,
        max_length: int = DEFAULT_MAX_TEMPLATE_LENGTH,
        max_expressions: int = DEFAULT_MAX_EXPRESSIONS,
    ) -> UriTemplate:
        """Parse a URI template string.

        Args:
            template: An RFC 6570 URI template.
            max_length: Maximum permitted length of the template string.
                Guards against resource exhaustion.
            max_expressions: Maximum number of ``{...}`` expressions
                permitted. Guards against pathological inputs that could
                produce expensive regexes.

        Raises:
            InvalidUriTemplate: If the template is malformed, exceeds the
                size limits, or uses unsupported RFC 6570 features.
        """
        if len(template) > max_length:
            raise InvalidUriTemplate(
                f"Template exceeds maximum length of {max_length}",
                template=template,
            )

        parts, variables = _parse(template, max_expressions=max_expressions)
        pattern = _build_pattern(parts)
        return cls(template=template, _parts=parts, _variables=variables, _pattern=pattern)

    @property
    def variables(self) -> tuple[Variable, ...]:
        """All variables in the template, in order of appearance."""
        return self._variables

    @property
    def variable_names(self) -> tuple[str, ...]:
        """All variable names in the template, in order of appearance."""
        return tuple(v.name for v in self._variables)

    def expand(self, variables: Mapping[str, str | Sequence[str]]) -> str:
        """Expand the template by substituting variable values.

        String values are percent-encoded according to their operator:
        simple ``{var}`` encodes reserved characters; ``{+var}`` and
        ``{#var}`` leave them intact. Sequence values are joined with
        commas for non-explode variables, or with the operator's
        separator for explode variables.

        Example::

            >>> t = UriTemplate.parse("file://docs/{name}")
            >>> t.expand({"name": "hello world.txt"})
            'file://docs/hello%20world.txt'

            >>> t = UriTemplate.parse("file://docs/{+path}")
            >>> t.expand({"path": "src/main.py"})
            'file://docs/src/main.py'

            >>> t = UriTemplate.parse("/search{?q,lang}")
            >>> t.expand({"q": "mcp", "lang": "en"})
            '/search?q=mcp&lang=en'

            >>> t = UriTemplate.parse("/files{/path*}")
            >>> t.expand({"path": ["a", "b", "c"]})
            '/files/a/b/c'

        Args:
            variables: Values for each template variable. Keys must be
                strings; values must be ``str`` or a sequence of ``str``.

        Returns:
            The expanded URI string.

        Note:
            Per RFC 6570, variables absent from the mapping are
            **silently omitted**. This is the correct behavior for
            optional query parameters (``{?page}`` with no page yields
            no ``?page=``), but for required path segments it produces
            a structurally incomplete URI. If you need all variables
            present, validate before calling::

                missing = set(t.variable_names) - variables.keys()
                if missing:
                    raise ValueError(f"Missing: {missing}")

        Raises:
            TypeError: If a value is neither ``str`` nor an iterable of
                ``str``. Non-string scalars (``int``, ``None``) are not
                coerced.
        """
        out: list[str] = []
        for part in self._parts:
            if isinstance(part, str):
                out.append(part)
            else:
                out.append(_expand_expression(part, variables))
        return "".join(out)

    def match(self, uri: str) -> dict[str, str | list[str]] | None:
        """Match a concrete URI against this template and extract variables.

        This is the inverse of :meth:`expand`. The URI is matched against
        a regex derived from the template; captured values are
        percent-decoded and validated for structural integrity.

        **Structural integrity**: decoded values must not contain
        characters that are structurally significant for their operator.
        A simple ``{name}`` whose value decodes to contain ``/`` is
        rejected — if that was intended, the template author should use
        ``{+name}``. This blocks the ``%2F``-smuggling vector where a
        client encodes a path separator to bypass single-segment
        semantics.

        Example::

            >>> t = UriTemplate.parse("file://docs/{name}")
            >>> t.match("file://docs/readme.txt")
            {'name': 'readme.txt'}
            >>> t.match("file://docs/hello%20world.txt")
            {'name': 'hello world.txt'}
            >>> t.match("file://docs/..%2Fetc%2Fpasswd") is None  # / in simple var
            True

            >>> t = UriTemplate.parse("file://docs/{+path}")
            >>> t.match("file://docs/src/main.py")
            {'path': 'src/main.py'}

            >>> t = UriTemplate.parse("/files{/path*}")
            >>> t.match("/files/a/b/c")
            {'path': ['a', 'b', 'c']}

        Args:
            uri: A concrete URI string.

        Returns:
            A mapping from variable names to decoded values (``str`` for
            scalar variables, ``list[str]`` for explode variables), or
            ``None`` if the URI does not match the template or a decoded
            value violates structural integrity.
        """
        m = self._pattern.fullmatch(uri)
        if m is None:
            return None

        result: dict[str, str | list[str]] = {}
        # One capture group per variable, emitted in template order.
        for var, raw in zip(self._variables, m.groups()):
            spec = _OPERATOR_SPECS[var.operator]
            forbidden = _STRUCTURAL_FORBIDDEN[var.operator]

            if var.explode:
                # Explode capture holds the whole run including separators,
                # e.g. "/a/b/c". Split, decode each segment, check each.
                if not raw:
                    result[var.name] = []
                    continue
                segments: list[str] = []
                for seg in raw.split(spec.separator):
                    if not seg:  # leading separator produces an empty first item
                        continue
                    decoded = unquote(seg)
                    if any(c in decoded for c in forbidden):
                        return None
                    segments.append(decoded)
                result[var.name] = segments
            else:
                decoded = unquote(raw)
                # Structural integrity: reject if decoding revealed a
                # delimiter the operator doesn't permit.
                if any(c in decoded for c in forbidden):
                    return None
                result[var.name] = decoded

        return result

    def __str__(self) -> str:
        return self.template


def _build_pattern(parts: tuple[_Part, ...]) -> re.Pattern[str]:
    """Compile a regex that matches URIs produced by this template.

    Walks parts in order: literals are ``re.escape``'d, expressions
    become capture groups. One group is emitted per variable, in the
    same order as ``UriTemplate._variables``, so ``match.groups()`` can
    be zipped directly.

    Raises:
        re.error: Only if pattern assembly is buggy — should not happen
            for templates that passed :func:`_parse`.
    """
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(re.escape(part))
        else:
            chunks.append(_expression_pattern(part))
    return re.compile("".join(chunks))


def _expression_pattern(expr: _Expression) -> str:
    """Build the regex fragment for a single ``{...}`` expression.

    Emits the operator's prefix, then one capture group per variable
    separated by the operator's separator. Named operators (``; ? &``)
    include ``name=`` before the capture.
    """
    spec = _OPERATOR_SPECS[expr.operator]
    body = _MATCH_PATTERN[expr.operator]
    sep = re.escape(spec.separator)
    prefix = re.escape(spec.prefix)

    pieces: list[str] = []
    for i, var in enumerate(expr.variables):
        # First var gets the prefix; subsequent vars get the separator.
        lead = prefix if i == 0 else sep

        if var.explode:
            # Capture the whole run of separator+value repetitions.
            # Non-greedy so a trailing literal can terminate the run.
            pieces.append(f"((?:{sep}{body})*?)")
        elif spec.named:
            # ;name=val or ?name=val — the = is optional for ; with empty value
            eq = "=?" if expr.operator == ";" else "="
            pieces.append(f"{lead}{re.escape(var.name)}{eq}({body})")
        else:
            pieces.append(f"{lead}({body})")

    return "".join(pieces)


def _parse(template: str, *, max_expressions: int) -> tuple[tuple[_Part, ...], tuple[Variable, ...]]:
    """Split a template into an ordered sequence of literals and expressions.

    Walks the string, alternating between collecting literal runs and
    parsing ``{...}`` expressions. The resulting ``parts`` sequence
    preserves positional interleaving so ``match()`` and ``expand()`` can
    walk it in order.

    Raises:
        InvalidUriTemplate: On unclosed braces, too many expressions, or
            any error surfaced by :func:`_parse_expression` or
            :func:`_check_adjacent_explodes`.
    """
    parts: list[_Part] = []
    variables: list[Variable] = []
    expression_count = 0
    i = 0
    n = len(template)

    while i < n:
        # Find the next expression opener from the current cursor.
        brace = template.find("{", i)

        if brace == -1:
            # No more expressions; everything left is a trailing literal.
            parts.append(template[i:])
            break

        if brace > i:
            # Literal text between cursor and the brace.
            parts.append(template[i:brace])

        end = template.find("}", brace)
        if end == -1:
            raise InvalidUriTemplate(
                f"Unclosed expression at position {brace}",
                template=template,
                position=brace,
            )

        expression_count += 1
        if expression_count > max_expressions:
            raise InvalidUriTemplate(
                f"Template exceeds maximum of {max_expressions} expressions",
                template=template,
            )

        # Delegate body (between braces, exclusive) to the expression parser.
        expr = _parse_expression(template, template[brace + 1 : end], brace)
        parts.append(expr)
        variables.extend(expr.variables)

        # Advance past the closing brace.
        i = end + 1

    _check_adjacent_explodes(template, parts)
    _check_duplicate_variables(template, variables)
    return tuple(parts), tuple(variables)


def _parse_expression(template: str, body: str, pos: int) -> _Expression:
    """Parse the body of a single ``{...}`` expression.

    The body is everything between the braces. It consists of an optional
    leading operator character followed by one or more comma-separated
    variable specifiers. Each specifier is a name with an optional
    trailing ``*`` (explode modifier).

    Args:
        template: The full template string, for error reporting.
        body: The expression body, braces excluded.
        pos: Character offset of the opening brace, for error reporting.

    Raises:
        InvalidUriTemplate: On empty body, invalid variable names, or
            unsupported modifiers.
    """
    if not body:
        raise InvalidUriTemplate(f"Empty expression at position {pos}", template=template, position=pos)

    # Peel off the operator, if any. Membership check justifies the cast.
    operator: Operator = ""
    if body[0] in _OPERATORS:
        operator = cast(Operator, body[0])
        body = body[1:]
        if not body:
            raise InvalidUriTemplate(
                f"Expression has operator but no variables at position {pos}",
                template=template,
                position=pos,
            )

    # Remaining body is comma-separated variable specs: name[*]
    variables: list[Variable] = []
    for spec in body.split(","):
        if ":" in spec:
            raise InvalidUriTemplate(
                f"Prefix modifier {{var:N}} is not supported (in {spec!r} at position {pos})",
                template=template,
                position=pos,
            )

        explode = spec.endswith("*")
        name = spec[:-1] if explode else spec

        if not _VARNAME_RE.match(name):
            raise InvalidUriTemplate(
                f"Invalid variable name {name!r} at position {pos}",
                template=template,
                position=pos,
            )

        # Explode only makes sense for operators that repeat a separator.
        # Simple/reserved/fragment have no per-item separator; query-explode
        # needs order-agnostic dict matching which we don't support yet.
        if explode and operator in ("", "+", "#", "?", "&"):
            raise InvalidUriTemplate(
                f"Explode modifier on {{{operator}{name}*}} is not supported for matching",
                template=template,
                position=pos,
            )

        variables.append(Variable(name=name, operator=operator, explode=explode))

    return _Expression(operator=operator, variables=tuple(variables))


def _check_duplicate_variables(template: str, variables: list[Variable]) -> None:
    """Reject templates that use the same variable name more than once.

    RFC 6570 requires repeated variables to expand to the same value,
    which would require backreference matching with potentially
    exponential cost. Rather than silently returning only the last
    captured value, we reject at parse time.

    Raises:
        InvalidUriTemplate: If any variable name appears more than once.
    """
    seen: set[str] = set()
    for var in variables:
        if var.name in seen:
            raise InvalidUriTemplate(
                f"Variable {var.name!r} appears more than once; repeated variables are not supported",
                template=template,
            )
        seen.add(var.name)


def _check_adjacent_explodes(template: str, parts: list[_Part]) -> None:
    """Reject templates with adjacent same-operator explode variables.

    Patterns like ``{/a*}{/b*}`` are ambiguous for matching: given
    ``/x/y/z``, the split between ``a`` and ``b`` is undetermined. We
    reject these at parse time rather than picking an arbitrary
    resolution. A literal between them (``{/a*}/x{/b*}``) or a different
    operator (``{/a*}{.b*}``) disambiguates.

    Raises:
        InvalidUriTemplate: If two explode variables with the same
            operator appear with no literal or non-explode variable
            between them.
    """
    prev_explode_op: Operator | None = None
    for part in parts:
        if isinstance(part, str):
            # Literal text breaks any adjacency.
            prev_explode_op = None
            continue
        for var in part.variables:
            if var.explode:
                if prev_explode_op == var.operator:
                    raise InvalidUriTemplate(
                        f"Adjacent explode expressions with operator {var.operator!r} are ambiguous and not supported",
                        template=template,
                    )
                prev_explode_op = var.operator
            else:
                # A non-explode variable also breaks adjacency.
                prev_explode_op = None
