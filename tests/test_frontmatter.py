"""Tests for palaia.frontmatter — YAML frontmatter parsing and serialization."""

from __future__ import annotations

from palaia.frontmatter import FRONTMATTER_RE, parse_yaml_simple, to_yaml_simple


class TestParseYamlSimple:
    def test_simple_string(self):
        assert parse_yaml_simple("name: hello") == {"name": "hello"}

    def test_integer(self):
        assert parse_yaml_simple("count: 42") == {"count": 42}

    def test_negative_integer(self):
        assert parse_yaml_simple("offset: -1") == {"offset": -1}

    def test_float(self):
        assert parse_yaml_simple("score: 3.14") == {"score": 3.14}

    def test_negative_float(self):
        assert parse_yaml_simple("temp: -0.1") == {"temp": -0.1}

    def test_boolean_true(self):
        assert parse_yaml_simple("active: true") == {"active": True}

    def test_boolean_false(self):
        assert parse_yaml_simple("active: false") == {"active": False}

    def test_null(self):
        assert parse_yaml_simple("value: null") == {"value": None}

    def test_list(self):
        assert parse_yaml_simple("tags: [a, b, c]") == {"tags": ["a", "b", "c"]}

    def test_quoted_string_with_colon(self):
        assert parse_yaml_simple('url: "http://example.com"') == {
            "url": "http://example.com"
        }

    def test_empty_value(self):
        result = parse_yaml_simple("key:")
        assert result == {"key": ""}

    def test_multiline_body(self):
        text = "title: Hello\nscope: team\ntype: memory"
        result = parse_yaml_simple(text)
        assert result == {"title": "Hello", "scope": "team", "type": "memory"}


class TestToYamlSimple:
    def test_string_value(self):
        assert to_yaml_simple({"name": "hello"}) == "name: hello"

    def test_string_with_colon_gets_quoted(self):
        # Strings with special chars like newlines or --- get quoted
        result = to_yaml_simple({"url": "has\nnewline"})
        assert '"' in result

    def test_integer_value(self):
        assert to_yaml_simple({"count": 42}) == "count: 42"

    def test_list_value(self):
        assert to_yaml_simple({"tags": ["a", "b"]}) == "tags: [a, b]"

    def test_none_value_omitted(self):
        # None values are serialized as "null"
        result = to_yaml_simple({"key": None})
        assert result == "key: null"

    def test_roundtrip(self):
        data = {"title": "Test", "count": 5, "active": True, "tags": ["x", "y"]}
        yaml_str = to_yaml_simple(data)
        parsed = parse_yaml_simple(yaml_str)
        assert parsed == data


class TestFrontmatterRe:
    def test_matches_frontmatter(self):
        text = "---\ntitle: Hello\n---\n"
        match = FRONTMATTER_RE.match(text)
        assert match is not None
        assert "title: Hello" in match.group(1)

    def test_no_frontmatter(self):
        text = "Just some plain text"
        match = FRONTMATTER_RE.match(text)
        assert match is None

    def test_frontmatter_with_body(self):
        text = "---\ntitle: Hello\n---\nBody content here"
        match = FRONTMATTER_RE.match(text)
        assert match is not None
        body = text[match.end():]
        assert body == "Body content here"
