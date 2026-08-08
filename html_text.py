"""
HTML-to-plain-text conversion for untrusted email bodies.

Strips markup and drops content that is invisible to a human reader
(script/style blocks, display:none / visibility:hidden / zero-font-size
elements, hidden attributes) so hidden instructions never reach the
classification prompt.
"""

import re
from html import unescape
from html.parser import HTMLParser

# Tags whose content is never visible to the reader
_INVISIBLE_TAGS = {"script", "style", "head", "title", "template", "noscript"}

# Tags that never have closing tags
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}

# Inline styles that hide an element's text from the reader
_HIDING_STYLE = re.compile(
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?:\.0*)?(?:\s|;|$)"
    r"|font-size\s*:\s*0",
    re.IGNORECASE,
)

# Block-level tags that imply a line break in the text rendering
_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "tr",
    "table",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "section",
    "article",
}


class _HTMLTextExtractor(HTMLParser):
    """Extract human-visible text from HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._stack = []
        self._hidden_depth = None

    @staticmethod
    def _is_hidden(attrs) -> bool:
        for name, value in attrs:
            name = name.lower()
            if name == "hidden":
                return True
            if name == "aria-hidden" and (value or "").lower() == "true":
                return True
            if name == "style" and value and _HIDING_STYLE.search(value):
                return True
        return False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _BLOCK_TAGS and self._hidden_depth is None:
            self._parts.append("\n")
        if tag in _VOID_TAGS:
            return
        self._stack.append(tag)
        if self._hidden_depth is None and (
            tag in _INVISIBLE_TAGS or self._is_hidden(attrs)
        ):
            self._hidden_depth = len(self._stack)

    def handle_endtag(self, tag):
        tag = tag.lower()
        # Pop to the most recent matching open tag (tolerates malformed HTML)
        if tag in self._stack:
            while self._stack:
                popped = self._stack.pop()
                if popped == tag:
                    break
        if self._hidden_depth is not None and len(self._stack) < self._hidden_depth:
            self._hidden_depth = None
        if tag in _BLOCK_TAGS and self._hidden_depth is None:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._hidden_depth is None:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # Collapse runs of whitespace while preserving line structure
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """
    Convert untrusted HTML to the plain text a human reader would see.

    Args:
        html: Raw HTML string

    Returns:
        Visible plain text with hidden elements removed
    """
    try:
        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        extractor.close()
        return extractor.get_text()
    except Exception:
        # On parser failure, fall back to crude tag stripping rather than
        # passing raw HTML through to the prompt
        return unescape(re.sub(r"<[^>]+>", " ", html)).strip()
