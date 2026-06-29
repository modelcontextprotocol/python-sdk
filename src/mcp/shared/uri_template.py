"""RFC 6570 URI Templates with bidirectional support.

RFC 6570 only specifies expansion (template + variables → URI); matching
(URI → variables) is the inverse operation MCP servers need to route
`resources/read` requests. Levels 1-3 are supported fully, plus the Level 4
explode modifier for path-like operators (`{/var*}`, `{.var*}`, `{;var*}`);
the prefix modifier (`{var:N}`) and query-explode (`{?var*}`) are not.

Matching (which RFC 6570 §1.4 leaves to regex languages) uses a two-ended
scan that never backtracks: O(n·v) in URI length and variable count, so no
input produces superpolynomial time. A template may contain at most one
multi-segment variable — `{+var}`, `{#var}`, or an exploded variable — which
greedily consumes whatever the surrounding bounded variables and literals do
not; bounded variables before it match lazily, those after it greedily
(templates without one are greedy throughout, like regex). Variables
adjacent with no literal between them are rejected at parse time; operators
that emit a lead character supply that literal, so `{+path}{.ext}` is fine
while `{+path}{ext}` is not.

Reserved expansion `{+var}` leaves `?` and `#` unencoded, but the scan stops
at those characters so `{+path}{?q}` can separate path from query; a value
containing a literal `?` or `#` expands fine but will not round-trip through
`match()`.
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

# RFC 6570 §2.3: varname = varchar *(["."] varchar), varchar = ALPHA / DIGIT / "_".
# Percent-encoded varchars are technically allowed but unseen in practice.
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
    """Emit `name=value` pairs (query/path-param style) rather than bare values."""
    allow_reserved: bool
    """Keep reserved characters unencoded ({+var}, {#var})."""
    ifemp: str
    """Suffix after a named variable with empty value (RFC §A): '' for ;, '=' for ?/&."""


_OPERATOR_SPECS: dict[Operator, _OperatorSpec] = {
    "": _OperatorSpec(prefix="", separator=",", named=False, allow_reserved=False, ifemp=""),
    "+": _OperatorSpec(prefix="", separator=",", named=False, allow_reserved=True, ifemp=""),
    "#": _OperatorSpec(prefix="#", separator=",", named=False, allow_reserved=True, ifemp=""),
    ".": _OperatorSpec(prefix=".", separator=".", named=False, allow_reserved=False, ifemp=""),
    "/": _OperatorSpec(prefix="/", separator="/", named=False, allow_reserved=False, ifemp=""),
    ";": _OperatorSpec(prefix=";", separator=";", named=True, allow_reserved=False, ifemp=""),
    "?": _OperatorSpec(prefix="?", separator="&", named=True, allow_reserved=False, ifemp="="),
    "&": _OperatorSpec(prefix="&", separator="&", named=True, allow_reserved=False, ifemp="="),
}

# Per-operator stop set: a bounded variable's value ends at the first stop
# character — the character-class boundary a regex would use, minus backtracking.
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
        position: Character offset of the error, or None if not positional.
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
    """A parsed `{...}` expression: one operator, one or more variables."""

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

    `ifemp` marks the `;` operator's quirk: `{;id}` expands to `;id=value`
    or bare `;id` when the value is empty, so the scan must accept both.
    """

    var: Variable
    ifemp: bool = False


_Atom: TypeAlias = _Lit | _Cap


def _is_greedy(var: Variable) -> bool:
    """True if the variable's match range is unbounded by a single delimiter (at most one per template)."""
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

    Reserved expansion ({+var}, {#var}) keeps RFC 3986 reserved characters
    and existing `%XX` triplets intact (§3.2.3); a bare `%` not followed by
    two hex digits is still encoded to `%25`.
    """
    if not allow_reserved:
        return quote(value, safe="")

    # Pass triplets through as-is, quote the gaps; a bare % lands in a gap.
    out: list[str] = []
    last = 0
    for m in _PCT_TRIPLET_RE.finditer(value):
        out.append(quote(value[last : m.start()], safe=_RESERVED))
        out.append(m.group())
        last = m.end()
    out.append(quote(value[last:], safe=_RESERVED))
    return "".join(out)


def _expand_expression(expr: _Expression, variables: Mapping[str, str | Sequence[str]]) -> str:
    """Expand a single `{...}` expression into its URI fragment.

    Undefined variables are skipped (RFC 6570 §2.3); if all are undefined,
    the expression contributes nothing (no prefix is emitted).
    """
    spec = _OPERATOR_SPECS[expr.operator]
    rendered: list[str] = []

    for var in expr.variables:
        if var.name not in variables:
            continue

        value = variables[var.name]

        # Reject non-str scalars here for a clear message rather than a
        # confusing "not iterable" from the sequence branch.
        if not isinstance(value, str) and not _is_str_sequence(value):
            raise TypeError(f"Variable {var.name!r} must be str or a sequence of str, got {type(value).__name__}")

        if isinstance(value, str):
            encoded = _encode(value, allow_reserved=spec.allow_reserved)
            if spec.named:
                rendered.append(f"{var.name}{spec.ifemp}" if value == "" else f"{var.name}={encoded}")
            else:
                rendered.append(encoded)
        else:
            items = [_encode(v, allow_reserved=spec.allow_reserved) for v in value]
            if not items:
                continue
            if var.explode:
                if spec.named:
                    rendered.append(
                        spec.separator.join(f"{var.name}{spec.ifemp}" if v == "" else f"{var.name}={v}" for v in items)
                    )
                else:
                    rendered.append(spec.separator.join(items))
            else:
                # Non-explode: comma-join, then ifemp applies to the joined value (RFC 6570 §3.2.1).
                joined = ",".join(items)
                if spec.named:
                    rendered.append(f"{var.name}{spec.ifemp}" if joined == "" else f"{var.name}={joined}")
                else:
                    rendered.append(joined)

    if not rendered:
        return ""
    return spec.prefix + spec.separator.join(rendered)


@dataclass(frozen=True)
class UriTemplate:
    """A parsed RFC 6570 URI template.

    Construct via :meth:`parse`. Immutable and hashable; equality is based
    on the template string alone.
    """

    template: str
    _parts: list[_Part] = field(repr=False, compare=False)
    _variables: list[Variable] = field(repr=False, compare=False)
    _prefix: list[_Atom] = field(repr=False, compare=False)
    _greedy: Variable | None = field(repr=False, compare=False)
    _suffix: list[_Atom] = field(repr=False, compare=False)
    _query_variables: list[Variable] = field(repr=False, compare=False)

    @staticmethod
    def is_template(value: str) -> bool:
        """Check whether a string contains at least one `{...}` pair.

        A cheap heuristic for distinguishing concrete URIs from templates;
        `True` does not guarantee :meth:`parse` will succeed.
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
            max_length: Maximum template length; guards resource exhaustion.
            max_variables: Maximum variables across all expressions —
                counted per variable, not per expression, so `{v0,...,vN}`
                cannot pack arbitrarily many under one expression.

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

        # Trailing {?...}/{&...} runs are matched as a lenient query string, not via the linear scan.
        path_parts, query_vars = _split_query_tail(parts)
        atoms = _flatten(path_parts)
        prefix, greedy, suffix = _partition_greedy(atoms, template)

        return cls(
            template=template,
            _parts=parts,
            _variables=variables,
            _prefix=prefix,
            _greedy=greedy,
            _suffix=suffix,
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

    @property
    def query_variable_names(self) -> frozenset[str]:
        """Names of variables that :meth:`match` treats as optional query parameters.

        Variables in a trailing run of `{?...}`/`{&...}` expressions are
        matched leniently: a URI may omit any of them, and omitted names are
        absent from the result. Every other variable is bound on every
        successful match (possibly to an empty string) — including a
        `{&...}` with no preceding `{?...}`, which never emits the `?` the
        lenient split keys on and is therefore matched strictly.
        """
        return frozenset(v.name for v in self._query_variables)

    def expand(self, variables: Mapping[str, str | Sequence[str]]) -> str:
        """Expand the template by substituting variable values.

        String values are percent-encoded per their operator: simple `{var}`
        encodes reserved characters; `{+var}` and `{#var}` leave them
        intact. Sequence values are comma-joined, or joined with the
        operator's separator for explode variables.

        Example::

            >>> t = UriTemplate.parse("file://docs/{name}")
            >>> t.expand({"name": "hello world.txt"})
            'file://docs/hello%20world.txt'

            >>> t = UriTemplate.parse("/search{?q,lang}")
            >>> t.expand({"q": "mcp", "lang": "en"})
            '/search?q=mcp&lang=en'

        Note:
            Per RFC 6570, variables absent from the mapping are silently
            omitted — correct for optional query parameters, but a missing
            path variable yields a structurally incomplete URI. Check
            `set(t.variable_names) - variables.keys()` first if you need
            all variables present.

        Raises:
            TypeError: If a value is neither `str` nor an iterable of
                `str`; non-string scalars (`int`, `None`) are not coerced.
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

        The inverse of :meth:`expand`; captured values are percent-decoded.
        The round-trip `match(expand({k: v})) == {k: v}` holds when `v` does
        not contain its operator's separator unencoded: `{.ext}` with
        `ext="tar.gz"` expands but does not match back — an inherent
        reversal limitation noted by RFC 6570 §1.4.

        Matching is structural at the URI level only: a simple `{name}`
        will not match across a literal `/`, but a percent-encoded `%2F`
        that decodes to `/` is accepted as part of the value. Path-safety
        validation belongs at a higher layer; see
        :mod:`mcp.shared.path_security`.

        Trailing query expressions (`{?q,lang}`) match leniently:
        order-agnostic, partial, unrecognized params ignored, and absent
        params omitted from the result so downstream defaults can apply.

        Example::

            >>> t = UriTemplate.parse("file://docs/{name}")
            >>> t.match("file://docs/hello%20world.txt")
            {'name': 'hello world.txt'}

            >>> t = UriTemplate.parse("logs://{service}{?since,level}")
            >>> t.match("logs://api?level=error")
            {'service': 'api', 'level': 'error'}

        Args:
            max_uri_length: Oversized inputs return None without scanning,
                guarding against resource exhaustion.

        Returns:
            Variable names mapped to decoded values (`str`, or `list[str]`
            for explode variables), or None if the URI does not match or
            exceeds `max_uri_length`.
        """
        if len(uri) > max_uri_length:
            return None

        if self._query_variables:
            # Scan the path, then decode the query separately. Fragment is
            # stripped first: the template's {?...} tail never describes one.
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

        if self._greedy is None:
            # No greedy var: the suffix IS the whole template, scanned
            # right-to-left and anchored so atoms[0] matches at position 0.
            suffix = _scan_suffix(self._suffix, uri, n, anchored=True)
            if suffix is None:
                return None
            suffix_result, suffix_start = suffix
            return suffix_result if suffix_start == 0 else None

        # The parser rejects a capture adjacent to the greedy slot, so a
        # non-empty suffix begins with a _Lit whose rfind anchor is independent
        # of the prefix scan: scan the suffix first, then cap the prefix at it.
        suffix = _scan_suffix(self._suffix, uri, n, anchored=False)
        if suffix is None:
            return None
        suffix_result, suffix_start = suffix
        prefix = _scan_prefix(self._prefix, uri, 0, suffix_start)
        if prefix is None:
            return None
        prefix_result, prefix_end = prefix

        # The greedy var takes [prefix_end, suffix_start). The prefix scan is
        # bounded by suffix_start, so this holds by construction; guard rather
        # than assert so a future regression surfaces as a non-match.
        if suffix_start < prefix_end:
            return None  # pragma: no cover - unreachable while bounds hold
        middle = uri[prefix_end:suffix_start]
        greedy_value = _extract_greedy(self._greedy, middle)
        if greedy_value is None:
            return None

        return {**prefix_result, self._greedy.name: greedy_value, **suffix_result}

    def __str__(self) -> str:
        return self.template


def _parse_query(query: str) -> dict[str, str]:
    """Parse a query string into a name→value mapping.

    Unlike `urllib.parse.parse_qs`, this follows RFC 3986 rather than
    form-urlencoding: `+` is a literal sub-delim, only `%20` is a space.
    Names are not percent-decoded — RFC 6570 expansion never encodes them,
    and decoding would let `%74oken=evil&token=real` shadow the real `token`
    via first-wins. Duplicate keys keep the first value; pairs without `=`
    are empty-valued.
    """
    result: dict[str, str] = {}
    for pair in query.split("&"):
        name, _, value = pair.partition("=")
        if name and name not in result:
            result[name] = unquote(value)
    return result


def _extract_greedy(var: Variable, raw: str) -> str | list[str] | None:
    """Decode the greedy variable's isolated middle span.

    Scalar greedy ({+var}, {#var}): stop-char validation plus one unquote.
    Explode: split the separator-delimited run (`/a/b/c`, `;keys=a;keys=b`),
    validate, and decode per item.
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
    # A non-empty explode span must begin with the separator: {/a*} expands
    # to "/x/y", never "x/y", and the scan leaves the separator in the span.
    if raw[0] != sep:
        return None
    # Segments must not contain the operator's other stop chars (e.g. ?/# under {/path*}).
    body_stops = set(stops) - {sep}
    if any(c in body_stops for c in raw):
        return None

    segments: list[str] = []
    prefix = f"{var.name}="
    # split()[0] is always "" (raw starts with the separator); later
    # empties are legitimate values (/a//c).
    for seg in raw.split(sep)[1:]:
        if spec.named:
            # Named explode emits name=value per item (bare name under ; when empty).
            if seg.startswith(prefix):
                seg = seg[len(prefix) :]
            elif seg == var.name:
                seg = ""
            else:
                return None
        segments.append(unquote(seg))
    return segments


def _split_query_tail(parts: list[_Part]) -> tuple[list[_Part], list[Variable]]:
    """Separate trailing `?`/`&` expressions from the path portion.

    Lenient query matching applies when the template ends with consecutive
    `?`/`&` expressions; when it does not apply, `query_vars` is empty and
    `path_parts` is the full input.
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

    # The tail must start with {?...} so expand() emits the ? the URI is
    # split on; a leading {&page} expands with & and partition("?") misses it.
    first = parts[split]
    assert isinstance(first, _Expression)
    if first.operator != "?":
        return parts, []

    # A literal ?/# or a {?...}/{#...} expression in the path would be
    # stripped by the lenient partitions before the path scan sees it;
    # fall back to the strict scan.
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

    Raises:
        InvalidUriTemplate: On unclosed braces, too many variables, or any
            error surfaced by :func:`_parse_expression`.
    """
    parts: list[_Part] = []
    variables: list[Variable] = []
    i = 0
    n = len(template)

    while i < n:
        brace = template.find("{", i)

        if brace == -1:
            parts.append(template[i:])
            break

        if brace > i:
            parts.append(template[i:brace])

        end = template.find("}", brace)
        if end == -1:
            raise InvalidUriTemplate(
                f"Unclosed expression at position {brace}",
                template=template,
                position=brace,
            )

        expr = _parse_expression(template, template[brace + 1 : end], brace)
        parts.append(expr)
        variables.extend(expr.variables)

        if len(variables) > max_variables:
            raise InvalidUriTemplate(
                f"Template exceeds maximum of {max_variables} variables",
                template=template,
            )

        i = end + 1

    _check_duplicate_variables(template, variables)
    _check_single_query_expression(template, parts)
    return parts, variables


def _parse_expression(template: str, body: str, pos: int) -> _Expression:
    """Parse the body (between braces) of a single `{...}` expression.

    The body is an optional leading operator followed by comma-separated
    `name[*]` variable specifiers. `template` and `pos` (offset of the
    opening brace) are for error reporting only.

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

        # Simple/reserved/fragment have no per-item separator to explode on;
        # query-explode needs order-agnostic dict matching, unsupported so far.
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

    RFC 6570 requires repeated variables to expand to the same value, which
    matching would need potentially-exponential backreference support for;
    reject at parse time rather than silently keeping the last capture.

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


def _check_single_query_expression(template: str, parts: list[_Part]) -> None:
    """Reject templates with more than one `{?...}` expression.

    Two would expand to a URI with two `?` characters — malformed per
    RFC 3986 §3.4. Use `{?a,b}` or `{?a}{&b}` instead.
    """
    seen = False
    for part in parts:
        if isinstance(part, _Expression) and part.operator == "?":
            if seen:
                raise InvalidUriTemplate(
                    "Template contains more than one {?...} expression; "
                    "use {?a,b} or {?a}{&b} for multiple query parameters",
                    template=template,
                )
            seen = True


def _flatten(parts: list[_Part]) -> list[_Atom]:
    """Lower expressions into a flat sequence of literals and single-variable captures.

    Operator prefixes and separators become explicit `_Lit` atoms; adjacent
    literals are coalesced so find/rfind anchors on the longest run. Explode
    variables emit no lead literal — the capture includes its own
    separator-prefixed repetitions (`{/a*}` → `/x/y/z`).
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
                # ; uses ifemp (bare name when empty); ?/& always emit name= as literal.
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

    With no greedy variable the entire atom list is returned as the suffix
    so the right-to-left scan (regex-greedy semantics) handles it.

    Raises:
        InvalidUriTemplate: If two variables are adjacent with no literal
            between them (the scan has nothing to anchor the boundary on),
            or if more than one multi-segment variable is present (which
            one absorbs an extra segment is inherently ambiguous).
    """
    greedy_idx: int | None = None
    prev: _Atom | None = None
    for i, atom in enumerate(atoms):
        if isinstance(atom, _Cap):
            if isinstance(prev, _Cap):
                raise InvalidUriTemplate(
                    f"Variables {prev.var.name!r} and {atom.var.name!r} are adjacent "
                    "with no literal separator; matching cannot determine where one "
                    "ends and the other begins. Add a literal between them or use a "
                    "single variable.",
                    template=template,
                )
            if _is_greedy(atom.var):
                if greedy_idx is not None:
                    raise InvalidUriTemplate(
                        "Template contains more than one multi-segment variable "
                        "({+var}, {#var}, or explode modifier); matching would be ambiguous",
                        template=template,
                    )
                greedy_idx = i
        prev = atom
    if greedy_idx is None:
        return [], None, atoms
    greedy = atoms[greedy_idx]
    assert isinstance(greedy, _Cap)
    return atoms[:greedy_idx], greedy.var, atoms[greedy_idx + 1 :]


def _scan_suffix(
    atoms: Sequence[_Atom], uri: str, end: int, *, anchored: bool
) -> tuple[dict[str, str | list[str]], int] | None:
    """Scan atoms right-to-left from `end`, returning captures and start position.

    Each bounded variable takes the minimum span that lets its preceding
    literal match (rfind), making the first variable in template order
    greedy — identical to Python regex semantics for greedy groups. When
    `anchored`, the atoms are the entire template (no greedy variable) and
    `atoms[0]` must match at position 0, not at its rightmost occurrence.
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
            # ;name or ;name=value, preceding _Lit is ";name": try the
            # empty (bare-name) form first, else require =value.
            assert isinstance(prev, _Lit)
            if uri.endswith(prev.text, 0, pos):
                result[var.name] = ""
                i -= 1
                continue
            earliest = pos
            while earliest > 0 and uri[earliest - 1] not in stops:
                earliest -= 1
            eq = uri.find("=", earliest, pos)
            if eq == -1:
                return None
            result[var.name] = unquote(uri[eq + 1 : pos])
            pos = eq
            i -= 1
            continue

        # Earliest valid start: the var cannot extend left past a stop-char.
        earliest = pos
        while earliest > 0 and uri[earliest - 1] not in stops:
            earliest -= 1

        if prev is None:
            start = earliest
        else:
            # The parser rejects adjacent captures, so prev can only be a _Lit.
            assert isinstance(prev, _Lit)
            if anchored and i - 1 == 0:
                # First atom of the template is positionally fixed at 0;
                # rfind would land inside the value when the literal repeats
                # ("prefix-{id}" against "prefix-prefix-123").
                start = len(prev.text)
                if start < earliest or start > pos:
                    return None
            else:
                # Rightmost occurrence of the preceding literal ending within the var's range.
                idx = uri.rfind(prev.text, 0, pos)
                if idx == -1 or idx + len(prev.text) < earliest:
                    return None
                start = idx + len(prev.text)

        result[var.name] = unquote(uri[start:pos])
        pos = start
        i -= 1
    return result, pos


def _scan_prefix(
    atoms: Sequence[_Atom], uri: str, start: int, limit: int
) -> tuple[dict[str, str | list[str]], int] | None:
    """Scan atoms left-to-right from `start`, not exceeding `limit`.

    Each bounded variable takes the minimum span that lets its following
    literal match (find), leaving the greedy variable as much as possible.
    """
    result: dict[str, str | list[str]] = {}
    pos = start
    for i, atom in enumerate(atoms):
        if isinstance(atom, _Lit):
            end = pos + len(atom.text)
            if end > limit or uri[pos:end] != atom.text:
                return None
            pos = end
            continue

        var = atom.var
        stops = _STOP_CHARS[var.operator]
        # A literal always follows: the parser rejects adjacent captures, and a
        # capture ending the prefix would be adjacent to the greedy variable.
        nxt = atoms[i + 1]
        assert isinstance(nxt, _Lit)

        if atom.ifemp:
            # RFC 6570 §3.2.7 ifemp: bare ;name when empty, ;name=val otherwise.
            if uri.startswith(nxt.text, pos):
                # Empty value. Checked before '=' so a literal that itself
                # starts with '=' is not mistaken for the ifemp separator.
                result[var.name] = ""
                continue
            if pos < limit and uri[pos] == "=":
                pos += 1  # value follows; fall through to the scan
            else:
                # No following literal and no '=': the URI's name continued
                # past the template's (e.g. ;keys vs ;key) — no parse.
                return None

        # Latest valid end: first stop-char or the scan limit.
        latest = pos
        while latest < limit and uri[latest] not in stops:
            latest += 1

        # First occurrence of the following literal = minimum span. The search
        # window's upper bound forces any hit to start at or before `latest`,
        # so the var never extends past a stop-char.
        end = uri.find(nxt.text, pos, latest + len(nxt.text))
        if end == -1:
            return None

        result[var.name] = unquote(uri[pos:end])
        pos = end
    return result, pos
