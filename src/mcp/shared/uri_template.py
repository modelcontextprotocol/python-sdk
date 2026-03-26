"""RFC 6570 URI Templates with bidirectional support.

Provides both expansion (template + variables → URI) and matching
(URI → variables). RFC 6570 only specifies expansion; matching is the
inverse operation needed by MCP servers to route ``resources/read``
requests to handlers.

Supports Levels 1-3 fully, plus Level 4 explode modifier for path-like
operators (``{/var*}``, ``{.var*}``, ``{;var*}``). The Level 4 prefix
modifier (``{var:N}``) and query-explode (``{?var*}``) are not supported.

Known matching limitations
--------------------------

Matching is not specified by RFC 6570. A few templates can expand to
URIs that ``match()`` cannot unambiguously reverse:

* Reserved/fragment expressions (``{+var}``, ``{#var}``) are restricted
  to positions that avoid quadratic-time backtracking: at most one per
  template, and not immediately adjacent to another expression. The
  ``[^?#]*`` pattern overlaps with every other operator's character
  class; a failing match against ``{+a}{b}`` or ``{+a}/x/{+b}``
  backtracks O(n²). Use a literal separator before a bounded
  expression (``{+a}/sep/{b}``) or put the reserved expression last
  (``file://docs/{+path}``). Trailing ``{?...}``/``{&...}`` query
  expressions are always fine since they're matched via ``parse_qs``.

* Reserved expansion ``{+var}`` leaves ``?`` and ``#`` unencoded, but
  the match pattern stops at those characters so that templates like
  ``{+path}{?q}`` can correctly separate path from query. A value
  containing a literal ``?`` or ``#`` expands fine but will not
  round-trip through ``match()``. Use simple ``{var}`` (which encodes
  them) if round-trip matters for such values.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import quote, unquote

__all__ = [
    "DEFAULT_MAX_EXPRESSIONS",
    "DEFAULT_MAX_TEMPLATE_LENGTH",
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

DEFAULT_MAX_TEMPLATE_LENGTH = 1_000_000
DEFAULT_MAX_EXPRESSIONS = 10_000
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

# Per-operator character class for regex matching. Each pattern matches
# the characters that can appear in an expanded value for that operator,
# stopping at the next structural delimiter.
_MATCH_PATTERN: dict[Operator, str] = {
    "": r"[^/?#&,]*",  # simple: everything structural is pct-encoded
    "+": r"[^?#]*",  # reserved: / allowed, stop at query/fragment
    "#": r".*",  # fragment: tail of URI
    ".": r"[^./?#]*",  # label: stop at next .
    "/": r"[^/?#]*",  # path segment: stop at next /
    ";": r"[^;/?#]*",  # path-param value (may be empty: ;name)
    "?": r"[^&#]*",  # query value (may be empty: ?name=)
    "&": r"[^&#]*",  # query-cont value
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
    _parts: list[_Part] = field(repr=False, compare=False)
    _variables: list[Variable] = field(repr=False, compare=False)
    _pattern: re.Pattern[str] = field(repr=False, compare=False)
    _path_variables: list[Variable] = field(repr=False, compare=False)
    _query_variables: list[Variable] = field(repr=False, compare=False)

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

        # Trailing {?...}/{&...} expressions are matched leniently via
        # parse_qs instead of regex: order-agnostic, partial, ignores
        # extras. The path portion keeps regex matching.
        path_parts, query_vars = _split_query_tail(parts)
        path_vars = variables[: len(variables) - len(query_vars)]
        pattern = _build_pattern(path_parts)

        return cls(
            template=template,
            _parts=parts,
            _variables=variables,
            _pattern=pattern,
            _path_variables=path_vars,
            _query_variables=query_vars,
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
            # Two-phase: regex matches the path, the query is split and
            # decoded manually. Query params may be partial, reordered,
            # or include extras; absent params stay absent so downstream
            # defaults can apply. Fragment is stripped first since the
            # template's {?...} tail never describes a fragment.
            before_fragment, _, _ = uri.partition("#")
            path, _, query = before_fragment.partition("?")
            m = self._pattern.fullmatch(path)
            if m is None:
                return None
            result = _extract_path(m, self._path_variables)
            if result is None:
                return None
            if query:
                parsed = _parse_query(query)
                for var in self._query_variables:
                    if var.name in parsed:
                        result[var.name] = parsed[var.name]
            return result

        m = self._pattern.fullmatch(uri)
        if m is None:
            return None
        return _extract_path(m, self._variables)

    def __str__(self) -> str:
        return self.template


def _parse_query(query: str) -> dict[str, str]:
    """Parse a query string into a name→value mapping.

    Unlike ``urllib.parse.parse_qs``, this follows RFC 3986 semantics:
    ``+`` is a literal sub-delim, not a space. Form-urlencoding treats
    ``+`` as space for HTML form submissions, but RFC 6570 and MCP
    resource URIs follow RFC 3986 where only ``%20`` encodes a space.

    Duplicate keys keep the first value. Pairs without ``=`` are
    treated as empty-valued.
    """
    result: dict[str, str] = {}
    for pair in query.split("&"):
        name, _, value = pair.partition("=")
        name = unquote(name)
        if name and name not in result:
            result[name] = unquote(value)
    return result


def _extract_path(m: re.Match[str], variables: Sequence[Variable]) -> dict[str, str | list[str]] | None:
    """Decode regex capture groups into a variable-name mapping.

    Handles scalar and explode variables. Named explode (``;``) strips
    and validates the ``name=`` prefix per item, returning ``None`` on
    mismatch.
    """
    result: dict[str, str | list[str]] = {}
    # One capture group per variable, emitted in template order.
    for var, raw in zip(variables, m.groups()):
        spec = _OPERATOR_SPECS[var.operator]

        if var.explode:
            # Explode capture holds the whole run including separators,
            # e.g. "/a/b/c" or ";keys=a;keys=b". Split and decode each.
            if not raw:
                result[var.name] = []
                continue
            segments: list[str] = []
            prefix = f"{var.name}="
            for seg in raw.split(spec.separator):
                if not seg:  # leading separator produces an empty first item
                    continue
                if spec.named:
                    # Named explode emits name=value per item (or bare
                    # name for ; with empty value). Validate the name
                    # and strip the prefix before decoding.
                    if seg.startswith(prefix):
                        seg = seg[len(prefix) :]
                    elif seg == var.name:
                        seg = ""
                    else:
                        return None
                segments.append(unquote(seg))
            result[var.name] = segments
        else:
            result[var.name] = unquote(raw)

    return result


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

    # If the path portion contains a literal ? or a {?...} expression,
    # the URI's ? split won't align with our template boundary. Fall
    # back to strict regex.
    for part in parts[:split]:
        if isinstance(part, str):
            if "?" in part:
                return parts, []
        elif part.operator == "?":
            return parts, []

    query_vars: list[Variable] = []
    for part in parts[split:]:
        assert isinstance(part, _Expression)
        query_vars.extend(part.variables)

    return parts[:split], query_vars


def _build_pattern(parts: Sequence[_Part]) -> re.Pattern[str]:
    """Compile a regex that matches URIs produced by this template.

    Walks parts in order: literals are ``re.escape``'d, expressions
    become capture groups. One group is emitted per variable, in the
    same order as the variables appearing in ``parts``, so
    ``match.groups()`` can be zipped directly.

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
            name = re.escape(var.name)
            if expr.operator == ";":
                # RFC ifemp: ; emits bare name for empty values, so = is
                # optional. The lookahead asserts the name ends at = or a
                # delimiter, preventing {;id} from matching ;identity.
                pieces.append(f"{lead}{name}(?==|[;/?#]|$)=?({body})")
            else:
                # ? and & always emit name=, even for empty values.
                pieces.append(f"{lead}{name}=({body})")
        else:
            pieces.append(f"{lead}({body})")

    return "".join(pieces)


def _parse(template: str, *, max_expressions: int) -> tuple[list[_Part], list[Variable]]:
    """Split a template into an ordered sequence of literals and expressions.

    Walks the string, alternating between collecting literal runs and
    parsing ``{...}`` expressions. The resulting ``parts`` sequence
    preserves positional interleaving so ``match()`` and ``expand()`` can
    walk it in order.

    Raises:
        InvalidUriTemplate: On unclosed braces, too many expressions, or
            any error surfaced by :func:`_parse_expression` or
            :func:`_check_ambiguous_adjacency`.
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

    _check_ambiguous_adjacency(template, parts)
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


def _check_ambiguous_adjacency(template: str, parts: list[_Part]) -> None:
    """Reject templates where adjacent expressions would cause ambiguous or quadratic matching.

    Two patterns are rejected:

    1. Adjacent explode variables (``{/a*}{/b*}``): the split between
       ``a`` and ``b`` in ``/x/y/z`` is undetermined. Different
       operators don't help since character classes overlap.

    2. Reserved/fragment expansion in a position that causes quadratic
       backtracking. The ``[^?#]*`` pattern for ``+`` and ``#``
       overlaps with every other operator's character class, so when a
       trailing match fails the engine backtracks through O(n) split
       points. Two conditions trigger this:

       - ``{+var}`` immediately adjacent to any expression
         (``{+a}{b}``, ``{+a}{/b*}``)
       - Two ``{+var}``/``{#var}`` anywhere in the path, even with a
         literal between them (``{+a}/x/{+b}``) — the literal does not
         disambiguate since ``[^?#]*`` matches it too

       A 64KB payload against either can consume tens of seconds of CPU.

    Trailing ``{?...}``/``{&...}`` expressions are handled via
    ``parse_qs`` outside the path regex, so they do not count against
    any check.

    Raises:
        InvalidUriTemplate: If any pattern is detected.
    """
    prev_explode = False
    prev_reserved = False
    seen_reserved = False
    for part in parts:
        if isinstance(part, str):
            # A literal breaks immediate adjacency but does not reset
            # the seen-reserved count: [^?#]* matches most literals.
            prev_explode = False
            prev_reserved = False
            continue
        for var in part.variables:
            # ?/& are stripped before pattern building and never reach
            # the path regex.
            if var.operator in ("?", "&"):
                prev_explode = False
                prev_reserved = False
                continue

            if prev_reserved:
                raise InvalidUriTemplate(
                    "{+var} or {#var} immediately followed by another expression "
                    "causes quadratic-time matching; separate them with a literal",
                    template=template,
                )
            if var.operator in ("+", "#") and seen_reserved:
                raise InvalidUriTemplate(
                    "Multiple {+var} or {#var} expressions in one template cause "
                    "quadratic-time matching even with literals between them",
                    template=template,
                )
            if var.explode and prev_explode:
                raise InvalidUriTemplate(
                    "Adjacent explode expressions are ambiguous for matching and not supported",
                    template=template,
                )

            prev_explode = var.explode
            prev_reserved = var.operator in ("+", "#")
            if prev_reserved:
                seen_reserved = True
