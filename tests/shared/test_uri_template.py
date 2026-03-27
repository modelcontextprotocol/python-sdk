"""Tests for RFC 6570 URI template parsing, expansion, and matching."""

import pytest

from mcp.shared.uri_template import DEFAULT_MAX_URI_LENGTH, InvalidUriTemplate, UriTemplate, Variable


def test_parse_literal_only():
    tmpl = UriTemplate.parse("file://docs/readme.txt")
    assert tmpl.variables == []
    assert tmpl.variable_names == []
    assert str(tmpl) == "file://docs/readme.txt"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("file://docs/{name}", True),
        ("file://docs/readme.txt", False),
        ("", False),
        ("{a}", True),
        ("{", False),
        ("}", False),
        ("}{", False),
        ("prefix{+path}/suffix", True),
        ("{invalid syntax but still a template}", True),
    ],
)
def test_is_template(value: str, expected: bool):
    assert UriTemplate.is_template(value) is expected


def test_parse_simple_variable():
    tmpl = UriTemplate.parse("file://docs/{name}")
    assert tmpl.variables == [Variable(name="name", operator="")]
    assert tmpl.variable_names == ["name"]


@pytest.mark.parametrize(
    ("template", "operator"),
    [
        ("{+path}", "+"),
        ("{#frag}", "#"),
        ("{.ext}", "."),
        ("{/seg}", "/"),
        ("{;param}", ";"),
        ("{?q}", "?"),
        ("{&next}", "&"),
    ],
)
def test_parse_all_operators(template: str, operator: str):
    tmpl = UriTemplate.parse(template)
    (var,) = tmpl.variables
    assert var.operator == operator
    assert var.explode is False


def test_parse_multiple_variables_in_expression():
    tmpl = UriTemplate.parse("{?q,lang,page}")
    assert tmpl.variable_names == ["q", "lang", "page"]
    assert all(v.operator == "?" for v in tmpl.variables)


def test_parse_multiple_expressions():
    tmpl = UriTemplate.parse("db://{table}/{id}{?format}")
    assert tmpl.variable_names == ["table", "id", "format"]
    ops = [v.operator for v in tmpl.variables]
    assert ops == ["", "", "?"]


def test_parse_explode_modifier():
    tmpl = UriTemplate.parse("/files{/path*}")
    (var,) = tmpl.variables
    assert var.name == "path"
    assert var.operator == "/"
    assert var.explode is True


@pytest.mark.parametrize("template", ["{.labels*}", "{;params*}"])
def test_parse_explode_supported_operators(template: str):
    tmpl = UriTemplate.parse(template)
    assert tmpl.variables[0].explode is True


def test_parse_mixed_explode_and_plain():
    tmpl = UriTemplate.parse("{/path*}{?q}")
    assert tmpl.variables == [
        Variable(name="path", operator="/", explode=True),
        Variable(name="q", operator="?"),
    ]


def test_parse_varname_with_dots_and_underscores():
    tmpl = UriTemplate.parse("{foo_bar.baz}")
    assert tmpl.variable_names == ["foo_bar.baz"]


def test_parse_rejects_unclosed_expression():
    with pytest.raises(InvalidUriTemplate, match="Unclosed expression") as exc:
        UriTemplate.parse("file://{name")
    assert exc.value.position == 7
    assert exc.value.template == "file://{name"


def test_parse_rejects_empty_expression():
    with pytest.raises(InvalidUriTemplate, match="Empty expression"):
        UriTemplate.parse("file://{}")


def test_parse_rejects_operator_without_variable():
    with pytest.raises(InvalidUriTemplate, match="operator but no variables"):
        UriTemplate.parse("{+}")


@pytest.mark.parametrize(
    "name",
    [
        "-bad",
        "bad-name",
        "bad name",
        "bad/name",
        # RFC §2.3: dots only between varchars, not consecutive or trailing
        "foo..bar",
        "foo.",
    ],
)
def test_parse_rejects_invalid_varname(name: str):
    with pytest.raises(InvalidUriTemplate, match="Invalid variable name"):
        UriTemplate.parse(f"{{{name}}}")


def test_parse_accepts_dotted_varname():
    t = UriTemplate.parse("{a.b.c}")
    assert t.variable_names == ["a.b.c"]


def test_parse_rejects_empty_spec_in_list():
    with pytest.raises(InvalidUriTemplate, match="Invalid variable name"):
        UriTemplate.parse("{a,,b}")


def test_parse_rejects_prefix_modifier():
    with pytest.raises(InvalidUriTemplate, match="Prefix modifier"):
        UriTemplate.parse("{var:3}")


@pytest.mark.parametrize("template", ["{var*}", "{+var*}", "{#var*}", "{?var*}", "{&var*}"])
def test_parse_rejects_unsupported_explode(template: str):
    with pytest.raises(InvalidUriTemplate, match="Explode modifier"):
        UriTemplate.parse(template)


@pytest.mark.parametrize(
    "template",
    [
        # Two explode variables — any combination
        "{/a*}{/b*}",
        "{/a*}{.b*}",
        "{.a*}{;b*}",
        "{/a*}/x{/b*}",  # literal between doesn't help: still two greedy
        "{/a*}{b}{.c*}",  # non-explode between doesn't help either
        # {+var}/{#var} combined with explode
        "{+a}{/b*}",
        # Multi-var + expression: each var is greedy
        "{+a,b}",
        # Two {+var}/{#var} anywhere
        "{+a}/x/{+b}",
        "{+a},{+b}",
        "{#a}/x/{+b}",
        "{+a}.foo.{#b}",
    ],
)
def test_parse_rejects_multiple_multi_segment_variables(template: str):
    # Two multi-segment variables make matching inherently ambiguous:
    # there is no principled way to decide which one absorbs an extra
    # segment. The linear scan can only partition the URI around a
    # single greedy slot.
    with pytest.raises(InvalidUriTemplate, match="more than one multi-segment"):
        UriTemplate.parse(template)


@pytest.mark.parametrize(
    "template",
    [
        "file://docs/{+path}",  # + at end of template
        "file://{+path}.txt",  # + followed by literal only
        "file://{+path}/edit",  # + followed by literal only
        "api/{+path}{?v,page}",  # + followed by query (handled by parse_qs)
        "api/{+path}{&next}",  # + followed by query-continuation
        "page{#section}",  # # at end
        "{a}{#b}",  # # prepends literal '#' that {a}'s stop-set includes
        "{+a}/sep/{b}",  # + with bounded vars after
        "{+a},{b}",
        # Previously rejected for adjacency; now safe under linear scan
        "{+a}{b}",  # suffix var scans back to its stop-char
        "{+a}{/b}",
        "{+a}{.b}",
        "{+a}{;b}",
        "{#a}{b}",
        "prefix/{+path}{.ext}",
        "{a}{+b}",  # prefix var scans forward to its stop-char
        "{.a}{+b}",
        "{/a}{+b}",
        "x{name}{+path}y",
    ],
)
def test_parse_allows_single_multi_segment_variable(template: str):
    # One multi-segment variable is fine: the linear scan isolates it
    # between the prefix and suffix boundaries, and the scan never
    # backtracks so match time stays O(n) regardless of URI content.
    t = UriTemplate.parse(template)
    assert t is not None


@pytest.mark.parametrize(
    "template",
    ["{x}/{x}", "{x,x}", "{a}{b}{a}", "{+x}/foo/{x}"],
)
def test_parse_rejects_duplicate_variable_names(template: str):
    with pytest.raises(InvalidUriTemplate, match="appears more than once"):
        UriTemplate.parse(template)


def test_invalid_uri_template_is_value_error():
    with pytest.raises(ValueError):
        UriTemplate.parse("{}")


@pytest.mark.parametrize(
    "template",
    [
        "{{name}}",  # nested open: body becomes "{name"
        "{a{b}c}",  # brace inside expression
        "{{]{}}{}",  # garbage soup
        "{a,{b}",  # brace in comma list
    ],
)
def test_parse_rejects_nested_braces(template: str):
    # Nested/stray { inside an expression lands in the varname and
    # fails the varname regex rather than needing special handling.
    with pytest.raises(InvalidUriTemplate, match="Invalid variable name"):
        UriTemplate.parse(template)


@pytest.mark.parametrize(
    ("template", "position"),
    [
        ("{", 0),
        ("{{", 0),
        ("file://{name", 7),
        ("{a}{", 3),
        ("}{", 1),  # stray } is literal, then unclosed {
    ],
)
def test_parse_rejects_unclosed_brace(template: str, position: int):
    with pytest.raises(InvalidUriTemplate, match="Unclosed") as exc:
        UriTemplate.parse(template)
    assert exc.value.position == position


@pytest.mark.parametrize(
    "template",
    ["}}", "}", "a}b", "{a}}{b}"],
)
def test_parse_treats_stray_close_brace_as_literal(template: str):
    # RFC 6570 §2.1 strictly excludes } from literals, but we accept it
    # for TypeScript SDK parity. A stray } almost always indicates a
    # typo; rejecting would be more helpful but would also break
    # cross-SDK behavior.
    tmpl = UriTemplate.parse(template)
    assert str(tmpl) == template


def test_parse_stray_close_brace_between_expressions():
    tmpl = UriTemplate.parse("{a}}{b}")
    assert tmpl.variable_names == ["a", "b"]


def test_parse_rejects_oversized_template():
    with pytest.raises(InvalidUriTemplate, match="maximum length"):
        UriTemplate.parse("x" * 101, max_length=100)


def test_parse_rejects_too_many_variables():
    template = "".join(f"{{v{i}}}" for i in range(11))
    with pytest.raises(InvalidUriTemplate, match="maximum of 10 variables"):
        UriTemplate.parse(template, max_variables=10)


def test_parse_counts_variables_not_expressions():
    # A single {v0,v1,...} expression packs many variables under one
    # brace pair. Counting expressions would miss this.
    template = "{" + ",".join(f"v{i}" for i in range(11)) + "}"
    with pytest.raises(InvalidUriTemplate, match="maximum of 10 variables"):
        UriTemplate.parse(template, max_variables=10)


def test_parse_custom_limits_allow_larger():
    template = "".join(f"{{v{i}}}" for i in range(20))
    tmpl = UriTemplate.parse(template, max_variables=20)
    assert len(tmpl.variables) == 20


def test_equality_based_on_template_string():
    a = UriTemplate.parse("file://{name}")
    b = UriTemplate.parse("file://{name}")
    c = UriTemplate.parse("file://{other}")
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_frozen():
    tmpl = UriTemplate.parse("{x}")
    with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError
        tmpl.template = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("template", "variables", "expected"),
    [
        # Level 1: simple, encodes reserved chars
        ("{var}", {"var": "value"}, "value"),
        ("{var}", {"var": "hello world"}, "hello%20world"),
        ("{var}", {"var": "a/b"}, "a%2Fb"),
        ("file://docs/{name}", {"name": "readme.txt"}, "file://docs/readme.txt"),
        # Level 2: reserved expansion keeps / ? # etc.
        ("{+var}", {"var": "a/b/c"}, "a/b/c"),
        ("{+var}", {"var": "a?b#c"}, "a?b#c"),
        # RFC §3.2.3: reserved expansion passes through existing
        # pct-triplets unchanged; bare % is still encoded.
        ("{+var}", {"var": "path%2Fto"}, "path%2Fto"),
        ("{+var}", {"var": "50%"}, "50%25"),
        ("{+var}", {"var": "50%2"}, "50%252"),
        ("{+var}", {"var": "a%2Fb%20c"}, "a%2Fb%20c"),
        ("{#var}", {"var": "a%2Fb"}, "#a%2Fb"),
        # Simple expansion still encodes % unconditionally (triplet
        # preservation is reserved-only).
        ("{var}", {"var": "path%2Fto"}, "path%252Fto"),
        ("file://docs/{+path}", {"path": "src/main.py"}, "file://docs/src/main.py"),
        # Level 2: fragment
        ("{#var}", {"var": "section"}, "#section"),
        ("{#var}", {"var": "a/b"}, "#a/b"),
        # Level 3: label
        ("file{.ext}", {"ext": "txt"}, "file.txt"),
        # Level 3: path segment
        ("{/seg}", {"seg": "docs"}, "/docs"),
        # Level 3: path-style param
        ("{;id}", {"id": "42"}, ";id=42"),
        ("{;id}", {"id": ""}, ";id"),
        # Level 3: query
        ("{?q}", {"q": "search"}, "?q=search"),
        ("{?q}", {"q": ""}, "?q="),
        ("/search{?q,lang}", {"q": "mcp", "lang": "en"}, "/search?q=mcp&lang=en"),
        # Level 3: query continuation
        ("?a=1{&b}", {"b": "2"}, "?a=1&b=2"),
        # Multi-var in one expression
        ("{x,y}", {"x": "1", "y": "2"}, "1,2"),
        # {+x,y} is rejected at parse time: each var in a + expression
        # is multi-segment, and a template may only have one.
        # Sequence values, non-explode (comma-join)
        ("{/list}", {"list": ["a", "b", "c"]}, "/a,b,c"),
        ("{?list}", {"list": ["a", "b"]}, "?list=a,b"),
        # Explode: each item gets separator
        ("{/path*}", {"path": ["a", "b", "c"]}, "/a/b/c"),
        ("{.labels*}", {"labels": ["x", "y"]}, ".x.y"),
        ("{;keys*}", {"keys": ["a", "b"]}, ";keys=a;keys=b"),
        # RFC §3.2.7 ifemp: ; omits = for empty explode items
        ("{;keys*}", {"keys": ["a", "", "b"]}, ";keys=a;keys;keys=b"),
        # Undefined variables omitted
        ("{?q,page}", {"q": "x"}, "?q=x"),
        ("{a}{b}", {"a": "x"}, "x"),
        ("{?page}", {}, ""),
        # Empty sequence omitted
        ("{/path*}", {"path": []}, ""),
        # Literal-only template
        ("file://static", {}, "file://static"),
    ],
)
def test_expand(template: str, variables: dict[str, str | list[str]], expected: str):
    assert UriTemplate.parse(template).expand(variables) == expected


def test_expand_encodes_special_chars_in_simple():
    t = UriTemplate.parse("{v}")
    assert t.expand({"v": "a&b=c"}) == "a%26b%3Dc"


def test_expand_preserves_special_chars_in_reserved():
    t = UriTemplate.parse("{+v}")
    assert t.expand({"v": "a&b=c"}) == "a&b=c"


@pytest.mark.parametrize(
    "value",
    [42, None, 3.14, {"a": "b"}, ["ok", 42], b"bytes"],
)
def test_expand_rejects_invalid_value_types(value: object):
    t = UriTemplate.parse("{v}")
    with pytest.raises(TypeError, match="must be str or a sequence of str"):
        t.expand({"v": value})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    ("template", "uri", "expected"),
    [
        # Level 1: simple
        ("{var}", "hello", {"var": "hello"}),
        ("file://docs/{name}", "file://docs/readme.txt", {"name": "readme.txt"}),
        ("{a}/{b}", "foo/bar", {"a": "foo", "b": "bar"}),
        # Level 2: reserved allows /
        ("file://docs/{+path}", "file://docs/src/main.py", {"path": "src/main.py"}),
        ("{+var}", "a/b/c", {"var": "a/b/c"}),
        # Level 2: fragment
        ("page{#section}", "page#intro", {"section": "intro"}),
        # Level 3: label
        ("file{.ext}", "file.txt", {"ext": "txt"}),
        # Level 3: path segment
        ("api{/version}", "api/v1", {"version": "v1"}),
        # Level 3: path-style param
        ("item{;id}", "item;id=42", {"id": "42"}),
        ("item{;id}", "item;id", {"id": ""}),
        # Explode: ; emits name=value per item, match strips the prefix
        ("item{;keys*}", "item;keys=a;keys=b", {"keys": ["a", "b"]}),
        ("item{;keys*}", "item;keys=a;keys;keys=b", {"keys": ["a", "", "b"]}),
        ("item{;keys*}", "item", {"keys": []}),
        # Level 3: query. Lenient matching: partial, reordered, and
        # extra params are all accepted. Absent params stay absent.
        ("search{?q}", "search?q=hello", {"q": "hello"}),
        ("search{?q}", "search?q=", {"q": ""}),
        ("search{?q}", "search", {}),
        ("search{?q,lang}", "search?q=mcp&lang=en", {"q": "mcp", "lang": "en"}),
        ("search{?q,lang}", "search?lang=en&q=mcp", {"q": "mcp", "lang": "en"}),
        ("search{?q,lang}", "search?q=mcp", {"q": "mcp"}),
        ("search{?q,lang}", "search", {}),
        ("search{?q}", "search?q=mcp&utm=x&ref=y", {"q": "mcp"}),
        # URL-encoded query values are decoded
        ("search{?q}", "search?q=hello%20world", {"q": "hello world"}),
        # + is a literal sub-delim per RFC 3986, not a space (form-encoding)
        ("search{?q}", "search?q=C++", {"q": "C++"}),
        ("search{?q}", "search?q=1.0+build.5", {"q": "1.0+build.5"}),
        # Fragment is stripped before query parsing
        ("logs://{service}{?level}", "logs://api?level=error#section1", {"service": "api", "level": "error"}),
        ("search{?q}", "search#frag", {}),
        # Multiple ?/& expressions collected together
        ("api{?v}{&page,limit}", "api?limit=10&v=2", {"v": "2", "limit": "10"}),
        # Standalone {&var} falls through to strict regex (expands with
        # & prefix, no ? for lenient matching to split on)
        ("api{&page}", "api&page=2", {"page": "2"}),
        # Literal ? in path portion falls through to strict regex
        ("api?x{?page}", "api?x?page=2", {"page": "2"}),
        # {?...} expression in path portion also falls through
        ("api{?q}x{?page}", "api?q=1x?page=2", {"q": "1", "page": "2"}),
        # {#...} or literal # in path portion falls through: lenient
        # matching would strip the fragment before the path regex sees it
        ("page{#section}{?q}", "page#intro?q=x", {"section": "intro", "q": "x"}),
        ("page#lit{?q}", "page#lit?q=x", {"q": "x"}),
        # Empty & segments in query are skipped
        ("search{?q}", "search?&q=hello&", {"q": "hello"}),
        # Duplicate query keys keep first value
        ("search{?q}", "search?q=first&q=second", {"q": "first"}),
        # Percent-encoded parameter names are NOT decoded: RFC 6570
        # expansion never encodes names, so an encoded name cannot be
        # a legitimate match. Prevents HTTP parameter pollution.
        ("api://x{?token}", "api://x?%74oken=evil&token=real", {"token": "real"}),
        ("api://x{?token}", "api://x?%74oken=evil", {}),
        # Level 3: query continuation with literal ? falls back to
        # strict regex (template-order, all-present required)
        ("?a=1{&b}", "?a=1&b=2", {"b": "2"}),
        # Explode: path segments as list
        ("/files{/path*}", "/files/a/b/c", {"path": ["a", "b", "c"]}),
        ("/files{/path*}", "/files", {"path": []}),
        ("/files{/path*}/edit", "/files/a/b/edit", {"path": ["a", "b"]}),
        # Explode: labels
        ("host{.labels*}", "host.example.com", {"labels": ["example", "com"]}),
        # Repeated-slash literals preserved exactly
        ("///{a}////{b}////", "///x////y////", {"a": "x", "b": "y"}),
    ],
)
def test_match(template: str, uri: str, expected: dict[str, str | list[str]]):
    assert UriTemplate.parse(template).match(uri) == expected


@pytest.mark.parametrize(
    ("template", "uri"),
    [
        ("file://docs/{name}", "file://other/readme.txt"),
        ("{a}/{b}", "foo"),
        ("file{.ext}", "file"),
        ("static", "different"),
        # Anchoring: trailing extra component must not match. Guards
        # against a refactor from fullmatch() to match() or search().
        ("/users/{id}", "/users/123/extra"),
        ("/users/{id}/posts/{pid}", "/users/1/posts/2/extra"),
        # Repeated-slash literal with wrong slash count
        ("///{a}////{b}////", "//x////y////"),
        # ; name boundary: {;id} must not match a longer parameter name
        ("item{;id}", "item;identity=john"),
        ("item{;id}", "item;ident"),
        # ; explode: wrong parameter name in any segment rejects the match
        ("item{;keys*}", "item;admin=true"),
        ("item{;keys*}", "item;keys=a;admin=true"),
        # Lenient-query branch: path portion fails to match
        ("api/{name}{?q}", "wrong/path?q=x"),
        # Lenient-query branch: ; explode name mismatch in path portion
        ("item{;keys*}{?q}", "item;wrong=x?q=1"),
    ],
)
def test_match_no_match(template: str, uri: str):
    assert UriTemplate.parse(template).match(uri) is None


def test_match_adjacent_vars_with_prefix_names():
    # Two adjacent simple vars where one name is a prefix of the other.
    # We use positional capture groups, so names only affect the result
    # dict keys, not the regex. Adjacent unrestricted vars are inherently
    # ambiguous; greedy * resolution means the first takes everything.
    t = UriTemplate.parse("{var}{vara}")
    assert t.match("ab") == {"var": "ab", "vara": ""}
    assert t.match("abcd") == {"var": "abcd", "vara": ""}


def test_match_explode_preserves_empty_list_items():
    # Splitting the explode capture on its separator yields a leading
    # empty item from the operator prefix; only that one is stripped.
    # Subsequent empties are legitimate values from the input list.
    t = UriTemplate.parse("{/path*}")
    assert t.match("/a//c") == {"path": ["a", "", "c"]}
    assert t.match("//a") == {"path": ["", "a"]}
    assert t.match("/a/") == {"path": ["a", ""]}

    t = UriTemplate.parse("host{.labels*}")
    assert t.match("host.a..c") == {"labels": ["a", "", "c"]}


def test_match_adjacent_vars_disambiguated_by_literal():
    # A literal between vars resolves the ambiguity.
    t = UriTemplate.parse("{a}-{b}")
    assert t.match("foo-bar") == {"a": "foo", "b": "bar"}


@pytest.mark.parametrize(
    ("template", "uri", "expected"),
    [
        # {+var} followed by a bounded var: suffix scan reads back to
        # the bounded var's stop-char, greedy var gets the rest.
        ("{+path}{/name}", "a/b/c/readme", {"path": "a/b/c", "name": "readme"}),
        ("{+path}{.ext}", "src/main.py", {"path": "src/main", "ext": "py"}),
        ("prefix/{+path}{.ext}", "prefix/a/b.txt", {"path": "a/b", "ext": "txt"}),
        # {+var} preceded by a bounded var: prefix scan reads forward
        # to the bounded var's stop-char.
        ("{/name}{+rest}", "/foo/bar/baz", {"name": "foo", "rest": "/bar/baz"}),
        # Bounded vars before the greedy var match lazily (first anchor)
        ("{owner}@{+path}", "alice@src/main", {"owner": "alice", "path": "src/main"}),
        # Bounded vars after the greedy var match greedily (last anchor)
        ("{+path}@{name}", "src@main@v1", {"path": "src@main", "name": "v1"}),
        # {#frag} with a trailing bounded var
        ("{#section}{/page}", "#intro/1", {"section": "intro", "page": "1"}),
    ],
)
def test_match_greedy_with_adjacent_bounded_vars(template: str, uri: str, expected: dict[str, str]):
    # These templates were previously rejected at parse time to avoid
    # regex backtracking. The linear scan handles them in O(n).
    assert UriTemplate.parse(template).match(uri) == expected


@pytest.mark.parametrize(
    ("template", "uri"),
    [
        # Adjacent bounded vars with a failing suffix: scan commits to
        # one split and fails immediately, no retry.
        ("{a}{b}X", "z" * 200),
        ("{a}{b}{c}X", "z" * 200),
        # Mid-template {?...} with greedy var and failing suffix.
        ("{?a}{+b}x", "?a=" + "y" * 200),
        # Chained anchors that all appear in input but suffix fails.
        ("{a}L{b}L{c}L{d}M", "L" * 200),
    ],
)
def test_match_no_backtracking_on_pathological_input(template: str, uri: str):
    # These patterns caused O(n²) or worse backtracking under the regex
    # matcher. The linear scan returns None without retrying splits.
    # (Correctness check only; we benchmark separately to avoid flaky
    # timing assertions in CI.)
    assert UriTemplate.parse(template).match(uri) is None


@pytest.mark.parametrize(
    ("template", "uri"),
    [
        # Prefix literal mismatch before a greedy var
        ("file://{+path}", "http://x"),
        # Prefix anchor not found: {a} needs '@' before greedy but none exists
        ("{a}@{+path}", "no-at-sign-here"),
        # Prefix literal doesn't fit within suffix boundary
        ("foo{+a}oob", "fooob"),
        # Greedy scalar contains its own stop-char ({+var} stops at ?)
        ("api://{+path}", "api://foo?bar"),
        # Explode span doesn't start with its separator
        ("X{/path*}", "Xnoslash"),
        # Explode body contains a non-separator stop-char
        ("X{/path*}", "X/a?b"),
    ],
)
def test_match_greedy_rejection_paths(template: str, uri: str):
    assert UriTemplate.parse(template).match(uri) is None


@pytest.mark.parametrize(
    ("template", "uri", "expected"),
    [
        # ifemp in prefix before a greedy var: =value form
        ("api{;key}{+rest}", "api;key=abc/xyz", {"key": "abc", "rest": "/xyz"}),
        # ifemp in prefix: bare form (empty value)
        ("api{;key}{+rest}", "api;key/xyz", {"key": "", "rest": "/xyz"}),
        # Adjacent bounded caps in prefix: first takes to stop-char
        ("{a}{b}{+rest}", "foo/bar", {"a": "foo", "b": "", "rest": "/bar"}),
    ],
)
def test_match_prefix_scan_edge_cases(template: str, uri: str, expected: dict[str, str]):
    assert UriTemplate.parse(template).match(uri) == expected


def test_match_prefix_ifemp_rejects_name_continuation():
    # {;key} before a greedy var: ;keys has no = and the 's' continues
    # the name, so this is not our parameter.
    t = UriTemplate.parse("api{;key}{+rest}")
    assert t.match("api;keys/xyz") is None


def test_match_large_uri_against_greedy_template():
    # Large payload against a greedy template — the scan visits each
    # character once for the suffix anchor and once for the greedy
    # validation, so this is O(n) not O(n²).
    t = UriTemplate.parse("{+path}/end")
    body = "seg/" * 15000
    result = t.match(body + "end")
    assert result == {"path": body[:-1]}
    # And the failing case returns None without retrying splits.
    assert t.match(body + "nope") is None


def test_match_decodes_percent_encoding():
    t = UriTemplate.parse("file://docs/{name}")
    assert t.match("file://docs/hello%20world.txt") == {"name": "hello world.txt"}


def test_match_escapes_template_literals():
    # Regression: previous impl didn't escape . in literals, making it
    # a regex wildcard. "fileXtxt" should NOT match "file.txt/{id}".
    t = UriTemplate.parse("file.txt/{id}")
    assert t.match("file.txt/42") == {"id": "42"}
    assert t.match("fileXtxt/42") is None


@pytest.mark.parametrize(
    ("template", "uri", "expected"),
    [
        # Percent-encoded delimiters round-trip through match/expand.
        # Path-safety validation belongs to ResourceSecurity, not here.
        ("file://docs/{name}", "file://docs/a%2Fb", {"name": "a/b"}),
        ("{var}", "a%3Fb", {"var": "a?b"}),
        ("{var}", "a%23b", {"var": "a#b"}),
        ("{var}", "a%26b", {"var": "a&b"}),
        ("file{.ext}", "file.a%2Eb", {"ext": "a.b"}),
        ("api{/v}", "api/a%2Fb", {"v": "a/b"}),
        ("search{?q}", "search?q=a%26b", {"q": "a&b"}),
        ("{;filter}", ";filter=a%3Bb", {"filter": "a;b"}),
    ],
)
def test_match_encoded_delimiters_roundtrip(template: str, uri: str, expected: dict[str, str]):
    assert UriTemplate.parse(template).match(uri) == expected


def test_match_reserved_expansion_handles_slash():
    # {+var} allows literal / (not just encoded)
    t = UriTemplate.parse("{+path}")
    assert t.match("a%2Fb") == {"path": "a/b"}
    assert t.match("a/b") == {"path": "a/b"}


def test_match_double_encoding_decoded_once():
    # %252F is %2F encoded again. Single decode gives "%2F" (a literal
    # percent sign, a '2', and an 'F'). Guards against over-decoding.
    t = UriTemplate.parse("file://docs/{name}")
    assert t.match("file://docs/..%252Fetc") == {"name": "..%2Fetc"}


def test_match_rejects_oversized_uri():
    t = UriTemplate.parse("{var}")
    assert t.match("x" * 100, max_uri_length=50) is None


def test_match_accepts_uri_within_custom_limit():
    t = UriTemplate.parse("{var}")
    assert t.match("x" * 100, max_uri_length=200) == {"var": "x" * 100}


def test_match_default_uri_length_limit():
    t = UriTemplate.parse("{+var}")
    # Just at the limit: should match
    assert t.match("x" * DEFAULT_MAX_URI_LENGTH) is not None
    # One over: should reject
    assert t.match("x" * (DEFAULT_MAX_URI_LENGTH + 1)) is None


def test_match_explode_encoded_separator_in_segment():
    # An encoded separator inside a segment decodes as part of the value,
    # not as a split point. The split happens at literal separators only.
    t = UriTemplate.parse("/files{/path*}")
    assert t.match("/files/a%2Fb/c") == {"path": ["a/b", "c"]}


@pytest.mark.parametrize(
    ("template", "variables"),
    [
        ("{var}", {"var": "hello"}),
        ("file://docs/{name}", {"name": "readme.txt"}),
        ("file://docs/{+path}", {"path": "src/main.py"}),
        ("search{?q,lang}", {"q": "mcp", "lang": "en"}),
        ("file{.ext}", {"ext": "txt"}),
        ("/files{/path*}", {"path": ["a", "b", "c"]}),
        ("{var}", {"var": "hello world"}),
        ("item{;id}", {"id": "42"}),
        ("item{;id}", {"id": ""}),
        # Defined-but-empty values still emit the operator prefix; match
        # must accept the empty capture after it.
        ("page{#section}", {"section": ""}),
        ("file{.ext}", {"ext": ""}),
        ("api{/v}", {"v": ""}),
        ("x{name}y", {"name": ""}),
        ("item{;keys*}", {"keys": ["a", "b", "c"]}),
        ("item{;keys*}", {"keys": ["a", "", "b"]}),
        # Empty strings in explode lists round-trip for unnamed operators
        ("{/path*}", {"path": ["a", "", "c"]}),
        ("{/path*}", {"path": ["", "a"]}),
        ("host{.labels*}", {"labels": ["a", "", "c"]}),
        # Partial query expansion round-trips: expand omits undefined
        # vars, match leaves them absent from the result.
        ("logs://{service}{?since,level}", {"service": "api"}),
        ("logs://{service}{?since,level}", {"service": "api", "since": "1h"}),
        ("logs://{service}{?since,level}", {"service": "api", "since": "1h", "level": "error"}),
    ],
)
def test_roundtrip_expand_then_match(template: str, variables: dict[str, str | list[str]]):
    t = UriTemplate.parse(template)
    uri = t.expand(variables)
    assert t.match(uri) == variables
