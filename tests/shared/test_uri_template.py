"""Tests for RFC 6570 URI template parsing, expansion, and matching."""

import pytest

from mcp.shared.uri_template import InvalidUriTemplate, UriTemplate, Variable


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
        "{/a*}{/b*}",  # same operator
        "{/a*}{.b*}",  # different operators: / char class includes ., still ambiguous
        "{.a*}{;b*}",
    ],
)
def test_parse_rejects_adjacent_explodes(template: str):
    with pytest.raises(InvalidUriTemplate, match="Adjacent explode"):
        UriTemplate.parse(template)


@pytest.mark.parametrize(
    "template",
    [
        # {+var} immediately adjacent to any expression
        "{+a}{b}",
        "{+a}{/b}",
        "{+a}{/b*}",
        "{+a}{.b}",
        "{+a}{;b}",
        "{#a}{b}",
        "{+a,b}",  # multi-var in one expression: same adjacency
        "prefix/{+path}{.ext}",  # literal before doesn't help
        # Two {+var}/{#var} anywhere, even with literals between
        "{+a}/x/{+b}",
        "{+a},{+b}",
        "{#a}/x/{+b}",
        "{+a}.foo.{#b}",
    ],
)
def test_parse_rejects_reserved_quadratic_patterns(template: str):
    # These patterns cause O(n²) regex backtracking when a trailing
    # literal fails to match. Rejecting at parse time eliminates the
    # ReDoS vector at the source.
    with pytest.raises(InvalidUriTemplate, match="quadratic"):
        UriTemplate.parse(template)


@pytest.mark.parametrize(
    "template",
    [
        "file://docs/{+path}",  # + at end of template
        "file://{+path}.txt",  # + followed by literal only
        "file://{+path}/edit",  # + followed by literal only
        "api/{+path}{?v,page}",  # + followed by query (stripped before regex)
        "api/{+path}{&next}",  # + followed by query-continuation
        "page{#section}",  # # at end
        "{a}{+b}",  # + preceded by expression is fine; only following matters
        "{+a}/sep/{b}",  # literal + bounded expression after: linear
        "{+a},{b}",  # same: literal disambiguates when second is bounded
    ],
)
def test_parse_allows_reserved_in_safe_positions(template: str):
    # These do not exhibit quadratic backtracking: end-of-template,
    # literal + bounded expression, or trailing query expression
    # (handled by parse_qs outside the path regex).
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
    # RFC 6570 is lenient about } outside expressions; most implementations
    # (including the TypeScript SDK) treat it as a literal rather than erroring.
    tmpl = UriTemplate.parse(template)
    assert str(tmpl) == template


def test_parse_stray_close_brace_between_expressions():
    tmpl = UriTemplate.parse("{a}}{b}")
    assert tmpl.variable_names == ["a", "b"]


def test_parse_allows_explode_separated_by_literal():
    tmpl = UriTemplate.parse("{/a*}/x{/b*}")
    assert len(tmpl.variables) == 2


def test_parse_allows_explode_separated_by_non_explode_var():
    tmpl = UriTemplate.parse("{/a*}{b}{.c*}")
    assert len(tmpl.variables) == 3


def test_parse_rejects_oversized_template():
    with pytest.raises(InvalidUriTemplate, match="maximum length"):
        UriTemplate.parse("x" * 101, max_length=100)


def test_parse_rejects_too_many_expressions():
    with pytest.raises(InvalidUriTemplate, match="maximum of"):
        UriTemplate.parse("{a}" * 11, max_expressions=10)


def test_parse_custom_limits_allow_larger():
    template = "".join(f"{{v{i}}}" for i in range(20))
    tmpl = UriTemplate.parse(template, max_expressions=20)
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
        # {+x,y} is rejected at parse time (quadratic backtracking +
        # inherent ambiguity). Use {+x}/{+y} with a literal separator.
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
        # Multiple ?/& expressions collected together
        ("api{?v}{&page,limit}", "api?limit=10&v=2", {"v": "2", "limit": "10"}),
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


def test_match_adjacent_vars_disambiguated_by_literal():
    # A literal between vars resolves the ambiguity.
    t = UriTemplate.parse("{a}-{b}")
    assert t.match("foo-bar") == {"a": "foo", "b": "bar"}


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
    from mcp.shared.uri_template import DEFAULT_MAX_URI_LENGTH

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
