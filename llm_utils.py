"""
Text preparation shared by the Gmail client and the classifier.

Everything here reduces an email to the text that carries classification
signal: tracking-link paths and HTML markup are noise to the model and, in the
case of link tokens, often identify the recipient.
"""

import html
import logging
import re

logger = logging.getLogger(__name__)

# Matches a URL and captures scheme + host; everything after the host
# (path, query, fragment) is dropped by normalize_urls().
_URL = re.compile(r"(https?://[^/?#\s)>\]]+)[^\s)>\]]*")


def normalize_urls(text: str) -> str:
    """
    Reduce every URL in text to scheme + host.

    Marketing and notification emails are full of click-tracking links whose
    paths are long opaque tokens. Those tokens frequently embed
    recipient-specific IDs that have no business being sent to a model, and
    the host alone carries all the classification signal.
    """
    return _URL.sub(r"\1", text)


# HTML detection / reduction for bodies where Gmail only offered a text/html
# part. Tag soup is "unrelated content" to a classifier; the visible text is
# what carries the signal.
_HTML_HINT = re.compile(
    r"<\s*(html|body|div|p|br|table|tr|td|span|a|img)\b", re.IGNORECASE
)
_HTML_DROP = re.compile(
    r"<(script|style|head|title)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_HTML_BREAK = re.compile(
    r"<\s*(br|/p|/div|/tr|/li|/h[1-6]|/table)\b[^>]*>", re.IGNORECASE
)
_HTML_TAG = re.compile(r"<[^>]*>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def looks_like_html(text: str) -> bool:
    """True if the text contains common HTML structural tags."""
    return bool(_HTML_HINT.search(text))


def strip_html(text: str) -> str:
    """
    Reduce an HTML fragment to its visible text.

    Drops script/style/head blocks and comments, turns block-level closers and
    <br> into newlines, removes remaining tags, unescapes entities and
    collapses whitespace. Regex based on purpose: good enough for
    classification, no extra dependency.
    """
    text = _HTML_COMMENT.sub(" ", text)
    text = _HTML_DROP.sub(" ", text)
    text = _HTML_BREAK.sub("\n", text)
    text = _HTML_TAG.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v\u00a0]+", " ", text)
    text = re.sub(r" *\n[ \n]*", "\n", text)
    return text.strip()


def log_classification_result(email: dict, labels: list[str], provider: str):
    """
    Log the classification result in a consistent format.

    Args:
        email: Email dictionary
        labels: Predicted labels
        provider: Provider name for logging
    """
    subject = email.get("subject", "No Subject")
    if labels:
        logger.info(
            f"[{provider}] Classified '{subject[:50]}...' with labels: {labels}"
        )
    else:
        logger.warning(f"[{provider}] No labels predicted for '{subject[:50]}...'")
