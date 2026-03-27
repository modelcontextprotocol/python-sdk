"""RFC 6570 URI Templates with bidirectional support.

Provides both expansion (template + variables → URI) and matching
(URI → variables). RFC 6570 only specifies expansion; matching is the
inverse operation needed by MCP servers to route ``resources/read``
requests to handlers.

Supports Levels 1-3 fully, plus Level 4 explode modifier for path-like
operators (``{/var*}``, ``{.var*}``, ``{;var*}``). The Level 4 prefix
modifier (``{var:N}``) and query-explode (``{?var*}``) are not supported.

Matching semantics
------------------

Matching is not specified by RFC 6570 (§1.4 explicitly defers to regex
languages). This implementation uses a linear-time two-ended scan that
never backtracks, so match time is O(n) in URI length regardless of
template structure.

A template may contain **at most one multi-segment variable** —
``{+var}``, ``{#var}``, or an explode-modified variable (``{/var*}``,
``{.var*}``, ``{;var*}``). This variable greedily consumes whatever the
surrounding bounded variables and literals do not. Two such variables
in one template are inherently ambiguous (which one gets the extra
segment?) and are rejected at parse time.

Bounded variables before the multi-segment variable match **lazily**
(first occurrence of the following literal); those after match
**greedily** (last occurrence of the preceding literal). Templates
without a multi-segment variable match greedily throughout, identical
to regex semantics.

Reserved expansion ``{+var}`` leaves ``?`` and ``#`` unencoded, but
the scan stops at those characters so ``{+path}{?q}`` can separate path
from query. A value containing a literal ``?`` or ``#`` expands fine
but will not round-trip through ``match()``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, cast
from urllib.parse import quote, unquote

__all__ = [
    "DEFAULT_MAX_TEMPLATE_LENGTH",
    "DEFAULT_MAX_VARIABLES",
    "DEFAULT_MAX_URI_LENGTH",
    "InvalidUriTemplate",
    "Operator",
    "UriTemplate",
    "Variable",
]

Operator = Literal["", "+", "#", ".", "/", ";", "?", "&"]

_OPERATORS: frozenset[str] = frozenset({"+", "#", ".", "/", ";", "?", "&"})

# RFC 6570 §2.3: varname = varchar *(["."] varchar), varchar = ALPHA / DIGIT / "_"
# Dots appear only between varchar groups — not consecutive, not trailing.
# (Percent-encoded varchars are technically allowed but unseen in practice.)
_VARNAME_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")

DEFAULT_MAX_TEMPLATE_LENGTH = 8_192
DEFAULT_MAX_VARIABLES = 256
DEFAULT_MAX_URI_LENGTH = 65_536

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

# Per-operator stop characters for the linear scan. A bounded variable's
# value ends at the first occurrence of any character in its stop set,
# mirroring the character-class boundaries a regex would use but without
# the backtracking.
_STOP_CHARS: dict[Operator, str] = {
    "": "/?#&,",  # simple: everything structural is pct-encoded
    "+": "?#",  # reserved: / allowed, stop at query/fragment
    "#": "",  # fragment: tail of URI, nothing stops it
    ".": "./?#",  # label: stop at next .
    "/": "/?#",  # path segment: stop at next /
    ";": ";/?#",  # path-param value (may be empty: ;name)
    "?": "&#",  # query value (may be empty: ?name=)
    "&": "&#",  # query-cont value
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


@dataclass
class _Expression:
    """A parsed ``{...}`` expression: one operator, one or more variables."""

    operator: Operator
    variables: list[Variable]


_Part = str | _Expression


@dataclass(frozen=True)
class _Lit:
    """A literal run in the flattened match-atom sequence."""

    text: str


@dataclass(frozen=True)
class _Cap:
    """A single-variable capture in the flattened match-atom sequence.

    ``ifemp`` marks the ``;`` operator's optional-equals quirk: ``{;id}``
    expands to ``;id=value`` or bare ``;id`` when the value is empty, so
    the scan must accept both forms.
    """

    var: Variable
    ifemp: bool = False


_Atom: TypeAlias = "_Lit | _Cap"


def _is_greedy(var: Variable) -> bool:
    """Return True if this variable can span multiple path segments.

    Reserved/fragment expansion and explode variables are the only
    constructs whose match range is not bounded by a single structural
    delimiter. A template may contain at most one such variable.
    """
    return var.explode or var.operator in ("+", "#")


def _is_str_sequence(value: object) -> bool:
    """Check if value is a non-string sequence whose items are all strings."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        return False
    seq = cast(Sequence[object], value)
    return all(isinstance(item, str) for item in seq)


_PCT_TRIPLET_RE = re.compile(r"%[0-9A-Fa-f]{2}")


def _encode(value: str, *, allow_reserved: bool) -> str:
    """Percent-encode a value per RFC 6570 §3.2.1.

    Simple expansion encodes everything except unreserved characters.
    Reserved expansion (``{+var}``, ``{#var}``) additionally keeps
    RFC 3986 reserved characters intact and passes through existing
    ``%XX`` pct-triplets unchanged (RFC 6570 §3.2.3). A bare ``%`` not
    followed by two hex digits is still encoded to ``%25``.
    """
    if not allow_reserved:
        return quote(value, safe="")

    # Reserved expansion: walk the string, pass through triplets as-is,
    # quote the gaps between them. A bare % with no triplet lands in a
    # gap and gets encoded normally.
    out: list[str] = []
    last = 0
    for m in _PCT_TRIPLET_RE.finditer(value):
        out.append(quote(value[last : m.start()], safe=_RESERVED))
        out.append(m.group())
        last = m.end()
    out.append(quote(value[last:], safe=_RESERVED))
    return "".join(out)


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
                    # RFC §3.2.7 ifemp: ; omits the = for empty values.
                    rendered.append(
                        spec.separator.join(
                            var.name if (v == "" and expr.operator == ";") else f"{var.name}={v}" for v in items
                        )
                    )
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
    _prefix: tuple[_Atom, ...] = field(repr=False, compare=False)
    _greedy: Variable | None = field(repr=False, compare=False)
    _suffix: tuple[_Atom, ...] = field(repr=False, compare=False)
    _query_variables: tuple[Variable, ...] = field(repr=False, compare=False)

    @staticmethod
    def is_template(value: str) -> bool:
        """Check whether a string contains URI template expressions.

        A cheap heuristic for distinguishing concrete URIs from templates
        without the cost of full parsing. Returns ``True`` if the string
        contains at least one ``{...}`` pair.

        Example::

            >>> UriTemplate.is_template("file://docs/{name}")
            True
            >>> UriTemplate.is_template("file://docs/readme.txt")
            False

        Note:
            This does not validate the template. A ``True`` result does
            not guarantee :meth:`parse` will succeed.
        """
        open_i = value.find("{")
        return open_i != -1 and value.find("}", open_i) != -1

    @classmethod
    def parse(
        cls,
        template: str,
        *,
        max_length: int = DEFAULT_MAX_TEMPLATE_LENGTH,
        max_variables: int = DEFAULT_MAX_VARIABLES,
    ) -> UriTemplate:
        """Parse a URI template string.

        Args:
            template: An RFC 6570 URI template.
            max_length: Maximum permitted length of the template string.
                Guards against resource exhaustion.
            max_variables: Maximum number of variables permitted across
                all expressions. Counting variables rather than
                ``{...}`` expressions closes the gap where a single
                ``{v0,v1,...,vN}`` expression packs arbitrarily many
                variables under one expression count.

        Raises:
            InvalidUriTemplate: If the template is malformed, exceeds the
                size limits, or uses unsupported RFC 6570 features.
        """
        if len(template) > max_length:
            raise InvalidUriTemplate(
                f"Template exceeds maximum length of {max_length}",
                template=template,
            )

        parts, variables = _parse(template, max_variables=max_variables)

        # Trailing {?...}/{&...} expressions are matched leniently via
        # parse_qs rather than the scan: order-agnostic, partial, ignores
        # extras. The path portion uses the linear scan.
        path_parts, query_vars = _split_query_tail(parts)
        atoms = _flatten(path_parts)
        prefix, greedy, suffix = _partition_greedy(atoms, template)

        return cls(
            template=template,
            _parts=tuple(parts),
            _variables=tuple(variables),
            _prefix=tuple(prefix),
            _greedy=greedy,
            _suffix=tuple(suffix),
            _query_variables=tuple(query_vars),
        )

    @property
    def variables(self) -> list[Variable]:
        """All variables in the template, in order of appearance."""
        return list(self._variables)

    @property
    def variable_names(self) -> list[str]:
        """All variable names in the template, in order of appearance."""
        return [v.name for v in self._variables]

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

    def match(self, uri: str, *, max_uri_length: int = DEFAULT_MAX_URI_LENGTH) -> dict[str, str | list[str]] | None:
        """Match a concrete URI against this template and extract variables.

        This is the inverse of :meth:`expand`. The URI is matched against
        a regex derived from the template and captured values are
        percent-decoded. The round-trip ``match(expand({k: v})) == {k: v}``
        holds when ``v`` does not contain its operator's separator
        unencoded: ``{.ext}`` with ``ext="tar.gz"`` expands to
        ``.tar.gz`` but matches back as ``ext="tar"`` since the ``.``
        pattern stops at the first dot. RFC 6570 §1.4 notes this is an
        inherent reversal limitation.

        Matching is structural at the URI level only: a simple ``{name}``
        will not match across a literal ``/`` in the URI (the regex stops
        there), but a percent-encoded ``%2F`` that decodes to ``/`` is
        accepted as part of the value. Path-safety validation belongs at
        a higher layer; see :mod:`mcp.shared.path_security`.

        Example::

            >>> t = UriTemplate.parse("file://docs/{name}")
            >>> t.match("file://docs/readme.txt")
            {'name': 'readme.txt'}
            >>> t.match("file://docs/hello%20world.txt")
            {'name': 'hello world.txt'}

            >>> t = UriTemplate.parse("file://docs/{+path}")
            >>> t.match("file://docs/src/main.py")
            {'path': 'src/main.py'}

            >>> t = UriTemplate.parse("/files{/path*}")
            >>> t.match("/files/a/b/c")
            {'path': ['a', 'b', 'c']}

        **Query parameters** (``{?q,lang}`` at the end of a template)
        are matched leniently: order-agnostic, partial, and unrecognized
        params are ignored. Absent params are omitted from the result so
        downstream function defaults can apply::

            >>> t = UriTemplate.parse("logs://{service}{?since,level}")
            >>> t.match("logs://api")
            {'service': 'api'}
            >>> t.match("logs://api?level=error")
            {'service': 'api', 'level': 'error'}
            >>> t.match("logs://api?level=error&since=5m&utm=x")
            {'service': 'api', 'since': '5m', 'level': 'error'}

        Args:
            uri: A concrete URI string.
            max_uri_length: Maximum permitted length of the input URI.
                Oversized inputs return ``None`` without regex evaluation,
                guarding against resource exhaustion.

        Returns:
            A mapping from variable names to decoded values (``str`` for
            scalar variables, ``list[str]`` for explode variables), or
            ``None`` if the URI does not match the template or exceeds
            ``max_uri_length``.
        """
        if len(uri) > max_uri_length:
            return None

        if self._query_variables:
            # Two-phase: scan matches the path, the query is split and
            # decoded manually. Query params may be partial, reordered,
            # or include extras; absent params stay absent so downstream
            # defaults can apply. Fragment is stripped first since the
            # template's {?...} tail never describes a fragment.
            before_fragment, _, _ = uri.partition("#")
            path, _, query = before_fragment.partition("?")
            result = self._scan(path)
            if result is None:
                return None
            if query:
                parsed = _parse_query(query)
                for var in self._query_variables:
                    if var.name in parsed:
                        result[var.name] = parsed[var.name]
            return result

        return self._scan(uri)

    def _scan(self, uri: str) -> dict[str, str | list[str]] | None:
        """Run the two-ended linear scan against the path portion of a URI."""
        n = len(uri)

        # Suffix right-to-left: literals anchor via endswith, bounded
        # vars take the minimum needed (rfind for the preceding literal).
        # This matches regex greedy-first semantics for templates without
        # a greedy var, and minimises the suffix claim when one exists.
        suffix = _scan_suffix(self._suffix, uri, n)
        if suffix is None:
            return None
        suffix_result, suffix_start = suffix

        if self._greedy is None:
            # No greedy var: suffix scan consumed the whole template.
            # It must have consumed the whole URI too.
            return suffix_result if suffix_start == 0 else None

        # Prefix left-to-right: each bounded var takes the minimum
        # needed (find for the following literal), leaving as much as
        # possible for the greedy var in the middle.
        prefix = _scan_prefix(self._prefix, uri, 0, suffix_start)
        if prefix is None:
            return None
        prefix_result, prefix_end = prefix

        # _scan_prefix is bounded by suffix_start, so this holds by
        # construction. Kept as an assertion to document the invariant.
        assert prefix_end <= suffix_start

        middle = uri[prefix_end:suffix_start]
        greedy_value = _extract_greedy(self._greedy, middle)
        if greedy_value is None:
            return None

        return {**prefix_result, self._greedy.name: greedy_value, **suffix_result}

    def __str__(self) -> str:
        return self.template


def _parse_query(query: str) -> dict[str, str]:
    """Parse a query string into a name→value mapping.

    Unlike ``urllib.parse.parse_qs``, this follows RFC 3986 semantics:
    ``+`` is a literal sub-delim, not a space. Form-urlencoding treats
    ``+`` as space for HTML form submissions, but RFC 6570 and MCP
    resource URIs follow RFC 3986 where only ``%20`` encodes a space.

    Parameter names are **not** percent-decoded. RFC 6570 expansion
    never encodes variable names, so a legitimate match will always
    have the name in literal form. Decoding names would let
    ``%74oken=evil&token=real`` shadow the real ``token`` parameter
    via first-wins.

    Duplicate keys keep the first value. Pairs without ``=`` are
    treated as empty-valued.
    """
    result: dict[str, str] = {}
    for pair in query.split("&"):
        name, _, value = pair.partition("=")
        if name and name not in result:
            result[name] = unquote(value)
    return result


def _extract_greedy(var: Variable, raw: str) -> str | list[str] | None:
    """Decode the greedy variable's isolated middle span.

    For scalar greedy (``{+var}``, ``{#var}``) this is a stop-char
    validation and a single ``unquote``. For explode variables the span
    is a run of separator-delimited segments (``/a/b/c`` or
    ``;keys=a;keys=b``) that is split, validated, and decoded per item.
    """
    spec = _OPERATOR_SPECS[var.operator]
    stops = _STOP_CHARS[var.operator]

    if not var.explode:
        if any(c in stops for c in raw):
            return None
        return unquote(raw)

    sep = spec.separator
    if not raw:
        return []
    # A non-empty explode span must begin with the separator: {/a*}
    # expands to "/x/y", never "x/y". The scan does not consume the
    # separator itself, so it must be the first character here.
    if raw[0] != sep:
        return None
    # Segments must not contain the operator's non-separator stop
    # characters (e.g. {/path*} segments may contain neither ? nor #).
    body_stops = set(stops) - {sep}
    if any(c in body_stops for c in raw):
        return None

    segments: list[str] = []
    prefix = f"{var.name}="
    # split()[0] is always "" because raw starts with the separator;
    # subsequent empties are legitimate values ({/path*} with
    # ["a","","c"] expands to /a//c).
    for seg in raw.split(sep)[1:]:
        if spec.named:
            # Named explode emits name=value per item (or bare name
            # under ; with empty value). Validate the name and strip
            # the prefix before decoding.
            if seg.startswith(prefix):
                seg = seg[len(prefix) :]
            elif seg == var.name:
                seg = ""
            else:
                return None
        segments.append(unquote(seg))
    return segments


def _split_query_tail(parts: list[_Part]) -> tuple[list[_Part], list[Variable]]:
    """Separate trailing ``?``/``&`` expressions from the path portion.

    Lenient query matching (order-agnostic, partial, ignores extras)
    applies when a template ends with one or more consecutive ``?``/``&``
    expressions and the preceding path portion contains no literal
    ``?``. If the path has a literal ``?`` (e.g., ``?fixed=1{&page}``),
    the URI's ``?`` split won't align with the template's expression
    boundary, so strict regex matching is used instead.

    Returns:
        A pair ``(path_parts, query_vars)``. If lenient matching does
        not apply, ``query_vars`` is empty and ``path_parts`` is the
        full input.
    """
    split = len(parts)
    for i in range(len(parts) - 1, -1, -1):
        part = parts[i]
        if isinstance(part, _Expression) and part.operator in ("?", "&"):
            split = i
        else:
            break

    if split == len(parts):
        return parts, []

    # The tail must start with a {?...} expression so that expand()
    # emits a ? the URI can split on. A standalone {&page} expands
    # with an & prefix, which partition("?") won't find.
    first = parts[split]
    assert isinstance(first, _Expression)
    if first.operator != "?":
        return parts, []

    # If the path portion contains a literal ?/# or a {?...}/{#...}
    # expression, lenient matching's partition("#") then partition("?")
    # would strip content the path regex expects to see. Fall back to
    # strict regex.
    for part in parts[:split]:
        if isinstance(part, str):
            if "?" in part or "#" in part:
                return parts, []
        elif part.operator in ("?", "#"):
            return parts, []

    query_vars: list[Variable] = []
    for part in parts[split:]:
        assert isinstance(part, _Expression)
        query_vars.extend(part.variables)

    return parts[:split], query_vars


def _parse(template: str, *, max_variables: int) -> tuple[list[_Part], list[Variable]]:
    """Split a template into an ordered sequence of literals and expressions.

    Walks the string, alternating between collecting literal runs and
    parsing ``{...}`` expressions. The resulting ``parts`` sequence
    preserves positional interleaving so ``match()`` and ``expand()`` can
    walk it in order.

    Raises:
        InvalidUriTemplate: On unclosed braces, too many expressions, or
            any error surfaced by :func:`_parse_expression`.
    """
    parts: list[_Part] = []
    variables: list[Variable] = []
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

        # Delegate body (between braces, exclusive) to the expression parser.
        expr = _parse_expression(template, template[brace + 1 : end], brace)
        parts.append(expr)
        variables.extend(expr.variables)

        if len(variables) > max_variables:
            raise InvalidUriTemplate(
                f"Template exceeds maximum of {max_variables} variables",
                template=template,
            )

        # Advance past the closing brace.
        i = end + 1

    _check_duplicate_variables(template, variables)
    return parts, variables


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

    return _Expression(operator=operator, variables=variables)


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


def _flatten(parts: list[_Part]) -> list[_Atom]:
    """Lower expressions into a flat sequence of literals and single-variable captures.

    Operator prefixes and separators become explicit ``_Lit`` atoms so
    the scan only ever sees two atom kinds. Adjacent literals are
    coalesced so that anchor-finding (``find``/``rfind``) operates on
    the longest possible literal, reducing false matches.

    Explode variables emit no lead literal: the explode capture
    includes its own separator-prefixed repetitions (``{/a*}`` →
    ``/x/y/z``, not ``/`` then ``x/y/z``).
    """
    atoms: list[_Atom] = []

    def push_lit(text: str) -> None:
        if not text:
            return
        if atoms and isinstance(atoms[-1], _Lit):
            atoms[-1] = _Lit(atoms[-1].text + text)
        else:
            atoms.append(_Lit(text))

    for part in parts:
        if isinstance(part, str):
            push_lit(part)
            continue
        spec = _OPERATOR_SPECS[part.operator]
        for i, var in enumerate(part.variables):
            lead = spec.prefix if i == 0 else spec.separator
            if var.explode:
                atoms.append(_Cap(var))
            elif spec.named:
                # ; uses ifemp (bare name when empty); ? and & always
                # emit name= so the equals is part of the literal.
                if part.operator == ";":
                    push_lit(f"{lead}{var.name}")
                    atoms.append(_Cap(var, ifemp=True))
                else:
                    push_lit(f"{lead}{var.name}=")
                    atoms.append(_Cap(var))
            else:
                push_lit(lead)
                atoms.append(_Cap(var))
    return atoms


def _partition_greedy(atoms: list[_Atom], template: str) -> tuple[list[_Atom], Variable | None, list[_Atom]]:
    """Split atoms at the single greedy variable, if any.

    Returns ``(prefix, greedy_var, suffix)``. If there is no greedy
    variable the entire atom list is returned as the suffix so that
    the right-to-left scan (which matches regex-greedy semantics)
    handles it.

    Raises:
        InvalidUriTemplate: If more than one greedy variable is
            present. Two multi-segment variables in one template are
            inherently ambiguous — there is no principled way to decide
            which one absorbs an extra segment.
    """
    greedy_idx: int | None = None
    for i, atom in enumerate(atoms):
        if isinstance(atom, _Cap) and _is_greedy(atom.var):
            if greedy_idx is not None:
                raise InvalidUriTemplate(
                    "Template contains more than one multi-segment variable "
                    "({+var}, {#var}, or explode modifier); matching would be ambiguous",
                    template=template,
                )
            greedy_idx = i
    if greedy_idx is None:
        return [], None, atoms
    greedy = atoms[greedy_idx]
    assert isinstance(greedy, _Cap)
    return atoms[:greedy_idx], greedy.var, atoms[greedy_idx + 1 :]


def _scan_suffix(atoms: Sequence[_Atom], uri: str, end: int) -> tuple[dict[str, str | list[str]], int] | None:
    """Scan atoms right-to-left from ``end``, returning captures and start position.

    Each bounded variable takes the minimum span that lets its
    preceding literal match (found via ``rfind``), which makes the
    *first* variable in template order greedy — identical to Python
    regex semantics for a sequence of greedy groups.
    """
    result: dict[str, str | list[str]] = {}
    pos = end
    i = len(atoms) - 1
    while i >= 0:
        atom = atoms[i]
        if isinstance(atom, _Lit):
            n = len(atom.text)
            if pos < n or uri[pos - n : pos] != atom.text:
                return None
            pos -= n
            i -= 1
            continue

        var = atom.var
        stops = _STOP_CHARS[var.operator]
        prev = atoms[i - 1] if i > 0 else None

        if atom.ifemp:
            # ;name or ;name=value. The preceding _Lit is ";name".
            # Try empty first: if the lit ends at pos the value is
            # absent (RFC ifemp). Otherwise require =value.
            assert isinstance(prev, _Lit)
            if uri.endswith(prev.text, 0, pos):
                result[var.name] = ""
                i -= 1
                continue
            start = pos
            while start > 0 and uri[start - 1] not in stops and uri[start - 1] != "=":
                start -= 1
            if start == 0 or uri[start - 1] != "=":
                return None
            result[var.name] = unquote(uri[start:pos])
            pos = start - 1
            i -= 1
            continue

        # Earliest valid start: the var cannot extend left past any
        # stop-char, so scan backward to find that boundary.
        earliest = pos
        while earliest > 0 and uri[earliest - 1] not in stops:
            earliest -= 1

        if prev is None:
            start = earliest
        elif isinstance(prev, _Lit):
            # Rightmost occurrence of the preceding literal whose end
            # falls within the var's valid range.
            idx = uri.rfind(prev.text, 0, pos)
            if idx == -1 or idx + len(prev.text) < earliest:
                return None
            start = idx + len(prev.text)
        else:
            # Adjacent capture with no literal anchor: this (later)
            # var takes nothing, the earlier var takes the span.
            start = pos

        result[var.name] = unquote(uri[start:pos])
        pos = start
        i -= 1
    return result, pos


def _scan_prefix(
    atoms: Sequence[_Atom], uri: str, start: int, limit: int
) -> tuple[dict[str, str | list[str]], int] | None:
    """Scan atoms left-to-right from ``start``, not exceeding ``limit``.

    Each bounded variable takes the minimum span that lets its
    following literal match (found via ``find``), leaving the
    greedy variable as much of the URI as possible.
    """
    result: dict[str, str | list[str]] = {}
    pos = start
    n = len(atoms)
    for i in range(n):
        atom = atoms[i]
        if isinstance(atom, _Lit):
            end = pos + len(atom.text)
            if end > limit or uri[pos:end] != atom.text:
                return None
            pos = end
            continue

        var = atom.var
        stops = _STOP_CHARS[var.operator]
        nxt = atoms[i + 1] if i + 1 < n else None

        if atom.ifemp:
            # Optional = after ;name. A non-= non-delimiter here means
            # the name continued (e.g. ;keys vs ;key) — reject.
            if pos < limit and uri[pos] == "=":
                pos += 1
            elif pos < limit and uri[pos] not in stops:
                return None

        # Latest valid end: the var stops at the first stop-char or
        # the scan limit, whichever comes first.
        latest = pos
        while latest < limit and uri[latest] not in stops:
            latest += 1

        if nxt is None:
            end = latest
        elif isinstance(nxt, _Lit):
            # First occurrence of the following literal starting
            # within the var's valid range.
            idx = uri.find(nxt.text, pos, latest + len(nxt.text))
            if idx == -1 or idx > latest:
                return None
            end = idx
        else:
            end = latest

        result[var.name] = unquote(uri[pos:end])
        pos = end
    return result, pos
