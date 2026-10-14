"""
Unit tests for mail_text.py

Tests cover:
- URL normalization (scheme + host only)
- HTML detection and reduction to visible text
"""

import pytest

from mail_text import looks_like_html, normalize_urls, strip_html


@pytest.mark.unit
class TestNormalizeUrls:
    """Test URL reduction to scheme + host."""

    # @spec INTAKE-TEXT-001
    def test_strips_tracking_path_and_query(self):
        text = (
            "Shop now: https://click.mailer.example.com/ls/click?upn="
            "u001.AbCdEf123456789-_x9Y8z7W6v5U4t3S2r1Q0pO&v=2 today"
        )

        assert normalize_urls(text) == (
            "Shop now: https://click.mailer.example.com today"
        )

    # @spec INTAKE-TEXT-001
    def test_preserves_scheme_and_port(self):
        assert normalize_urls("see http://host.lan:8080/path?x=1") == (
            "see http://host.lan:8080"
        )

    # @spec INTAKE-TEXT-001
    def test_strips_query_directly_after_host(self):
        assert normalize_urls("https://t.example.com?u=abc123") == (
            "https://t.example.com"
        )
        assert normalize_urls("https://t.example.com#frag") == ("https://t.example.com")

    # @spec INTAKE-TEXT-002
    def test_stops_at_closing_delimiters(self):
        text = "(https://a.example.com/x/y) <https://b.example.com/z> [https://c.example.com/q]"

        assert normalize_urls(text) == (
            "(https://a.example.com) <https://b.example.com> [https://c.example.com]"
        )

    # @spec INTAKE-TEXT-001
    def test_multiple_urls_and_plain_text_untouched(self):
        text = (
            "Hello https://one.example.com/aaa and https://two.example.com/bbb/ccc\n"
            "Plain line with no links."
        )

        assert normalize_urls(text) == (
            "Hello https://one.example.com and https://two.example.com\n"
            "Plain line with no links."
        )

    # @spec INTAKE-TEXT-001
    def test_no_urls_is_identity(self):
        assert normalize_urls("nothing to see here") == "nothing to see here"
        assert normalize_urls("") == ""

    # @spec INTAKE-TEXT-006
    def test_idempotent(self):
        once = normalize_urls("https://x.example.com/a?b=c")

        assert normalize_urls(once) == once


@pytest.mark.unit
class TestStripHtml:
    """HTML bodies are reduced to visible text before reaching the model."""

    # @spec INTAKE-TEXT-004
    def test_detects_html_by_structural_tags(self):
        assert looks_like_html("<html><body><p>Hi</p></body></html>") is True
        assert looks_like_html("Order <b>shipped</b>") is False
        assert looks_like_html("Plain text, 3 < 5 and 7 > 2") is False

    # @spec INTAKE-TEXT-003
    def test_drops_script_style_head_and_comments(self):
        raw = (
            "<html><head><title>T</title><style>p{color:red}</style></head>"
            "<body><!-- hidden --><script>alert(1)</script><p>Visible</p></body></html>"
        )
        assert strip_html(raw) == "Visible"

    # @spec INTAKE-TEXT-003
    def test_block_closers_become_newlines_and_entities_unescape(self):
        raw = "<div>Line one &amp; more</div><p>Line&nbsp;two</p>Tail<br>End"
        assert strip_html(raw) == "Line one & more\nLine two\nTail\nEnd"

    # @spec INTAKE-TEXT-003
    def test_collapses_whitespace(self):
        raw = "<p>  a   b </p>\n\n\n<p>\t c </p>"
        assert strip_html(raw) == "a b\nc"

    # @spec INTAKE-TEXT-005
    def test_truncated_tag_at_end_does_not_eat_text(self):
        # gmail_client caps bodies at 5000 chars, which can cut mid-tag
        assert strip_html('<p>kept</p><a href="https://x') == 'kept\n<a href="https://x'
