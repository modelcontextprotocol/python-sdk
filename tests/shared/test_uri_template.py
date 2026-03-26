"""Tests for RFC 6570 URI template parsing, expansion, and matching."""

import pytest

from mcp.shared.uri_template import InvalidUriTemplate, UriTemplate, Variable


def test_parse_literal_only():
    tmpl = UriTemplate.parse("file://docs/readme.txt")
    assert tmpl.variables == ()
    assert tmpl.variable_names == ()
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
    assert tmpl.variables == (Variable(name="name", operator=""),)
    assert tmpl.variable_names == ("name",)


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
    assert tmpl.variable_names == ("q", "lang", "page")
    assert all(v.operator == "?" for v in tmpl.variables)


def test_parse_multiple_expressions():
    tmpl = UriTemplate.parse("db://{table}/{id}{?format}")
    assert tmpl.variable_names == ("table", "id", "format")
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
    assert tmpl.variables == (
        Variable(name="path", operator="/", explode=True),
        Variable(name="q", operator="?"),
    )


def test_parse_varname_with_dots_and_underscores():
    tmpl = UriTemplate.parse("{foo_bar.baz}")
    assert tmpl.variable_names == ("foo_bar.baz",)


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


@pytest.mark.parametrize("name", ["-bad", "bad-name", "bad name", "bad/name"])
def test_parse_rejects_invalid_varname(name: str):
    with pytest.raises(InvalidUriTemplate, match="Invalid variable name"):
        UriTemplate.parse(f"{{{name}}}")


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


def test_parse_rejects_adjacent_explodes_same_operator():
    with pytest.raises(InvalidUriTemplate, match="Adjacent explode"):
        UriTemplate.parse("{/a*}{/b*}")


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
    assert tmpl.variable_names == ("a", "b")


def test_parse_allows_adjacent_explodes_different_operator():
    tmpl = UriTemplate.parse("{/a*}{.b*}")
    assert len(tmpl.variables) == 2


def test_parse_allows_explode_separated_by_literal():
    tmpl = UriTemplate.parse("{/a*}/x{/b*}")
    assert len(tmpl.variables) == 2


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
        ("{+x,y}", {"x": "a/b", "y": "c/d"}, "a/b,c/d"),
        # Sequence values, non-explode (comma-join)
        ("{/list}", {"list": ["a", "b", "c"]}, "/a,b,c"),
        ("{?list}", {"list": ["a", "b"]}, "?list=a,b"),
        # Explode: each item gets separator
        ("{/path*}", {"path": ["a", "b", "c"]}, "/a/b/c"),
        ("{.labels*}", {"labels": ["x", "y"]}, ".x.y"),
        ("{;keys*}", {"keys": ["a", "b"]}, ";keys=a;keys=b"),
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
        # Level 3: query
        ("search{?q}", "search?q=hello", {"q": "hello"}),
        ("search{?q}", "search?q=", {"q": ""}),
        ("search{?q,lang}", "search?q=mcp&lang=en", {"q": "mcp", "lang": "en"}),
        # Level 3: query continuation
        ("?a=1{&b}", "?a=1&b=2", {"b": "2"}),
        # Explode: path segments as list
        ("/files{/path*}", "/files/a/b/c", {"path": ["a", "b", "c"]}),
        ("/files{/path*}", "/files", {"path": []}),
        ("/files{/path*}/edit", "/files/a/b/edit", {"path": ["a", "b"]}),
        # Explode: labels
        ("host{.labels*}", "host.example.com", {"labels": ["example", "com"]}),
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
        ("search{?q}", "search"),
        ("static", "different"),
    ],
)
def test_match_no_match(template: str, uri: str):
    assert UriTemplate.parse(template).match(uri) is None


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
    ("template", "uri"),
    [
        # %2F in simple var — encoded-slash path traversal
        ("file://docs/{name}", "file://docs/..%2F..%2Fetc%2Fpasswd"),
        ("file://docs/{name}", "file://docs/..%2f..%2fetc%2fpasswd"),
        # %3F (?) in simple var
        ("{var}", "a%3Fb"),
        # %2E (.) in label var — would break label structure
        ("file{.ext}", "file.a%2Eb"),
        # %2F in path-segment var
        ("api{/v}", "api/a%2Fb"),
        # %26 (&) in query var — would break query structure
        ("search{?q}", "search?q=a%26b"),
    ],
)
def test_match_structural_integrity_rejects_smuggled_delimiters(template: str, uri: str):
    assert UriTemplate.parse(template).match(uri) is None


def test_match_structural_integrity_allows_slash_in_reserved():
    # {+var} explicitly permits / — structural check must not block it
    t = UriTemplate.parse("{+path}")
    assert t.match("a%2Fb") == {"path": "a/b"}
    assert t.match("a/b") == {"path": "a/b"}


def test_match_double_encoding_decoded_once():
    # %252F is %2F encoded again. Single decode gives "%2F" (a literal
    # percent sign, a '2', and an 'F'), which contains no '/' and should
    # be accepted. Guards against over-decoding.
    t = UriTemplate.parse("file://docs/{name}")
    assert t.match("file://docs/..%252Fetc") == {"name": "..%2Fetc"}


def test_match_multi_param_one_poisoned_rejects_whole():
    # One bad param in a multi-param template rejects the entire match
    t = UriTemplate.parse("file://{org}/{repo}")
    assert t.match("file://acme/..%2Fsecret") is None
    # But the same template with clean params matches fine
    assert t.match("file://acme/project") == {"org": "acme", "repo": "project"}


def test_match_bare_encoded_delimiter_rejected():
    # A value that decodes to only the forbidden delimiter
    t = UriTemplate.parse("file://docs/{name}")
    assert t.match("file://docs/%2F") is None


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


def test_match_structural_integrity_per_explode_segment():
    t = UriTemplate.parse("/files{/path*}")
    # Each segment checked independently
    assert t.match("/files/a%2Fb/c") is None


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
    ],
)
def test_roundtrip_expand_then_match(template: str, variables: dict[str, str | list[str]]):
    t = UriTemplate.parse(template)
    uri = t.expand(variables)
    assert t.match(uri) == variables
