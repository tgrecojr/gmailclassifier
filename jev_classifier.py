"""
Jev (TypeSafe System One) email classifier via OpenRouter's Decisions API.

Jev is a non-generative decision model: it takes a structured ``state`` and
typed ``questions`` and returns a probability distribution over the options we
define. It emits no text, calls no tools, and cannot pick a label outside the
configured set, so no separate prompt-injection guard sits in front of it.

Request shape (one call per email, all questions evaluated in parallel):

    state     -> {"from", "subject", "date", "body"} of the email
    questions -> one Noul (yes/no probability) per label
                 + one Choice across all labels plus a "None" option

Label selection: every Noul at or above ``label_threshold`` is applied. If
none clears it, the Choice answer is applied when its confidence is at or
above ``fallback_confidence`` and it is not "None".

The endpoint is normally LiteLLM's built-in OpenRouter pass-through
(``<litellm>/openrouter/alpha/decisions``); see decisions_url_for().
"""

import logging
import re
import time
from urllib.parse import urlparse

import httpx2 as httpx

from llm_utils import (
    log_classification_result,
    looks_like_html,
    normalize_urls,
    strip_html,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "typesafe/jev-1.13"
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
# LiteLLM >= 1.104.0 maps /openrouter/<path> to https://openrouter.ai/api/<path>
LITELLM_DECISIONS_PATH = "/openrouter/alpha/decisions"

BEST_QUESTION = "best"
NONE_OPTION = "None"
BODY_MAX_CHARS = 5000
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 2

_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_]+")


class JevRequestError(Exception):
    """The decisions endpoint could not be reached or answered unusably."""


def decisions_url_for(base_url: str) -> str:
    """
    Derive the decisions endpoint from an OpenAI-compatible base URL.

    ``https://openrouter.ai/api/v1``  -> ``https://openrouter.ai/api/alpha/decisions``
    ``http://litellm:4000/v1``        -> ``http://litellm:4000/openrouter/alpha/decisions``
    """
    root = base_url.strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    host = urlparse(root).netloc.lower()
    if host.endswith("openrouter.ai"):
        return f"{root}/alpha/decisions"
    return f"{root}{LITELLM_DECISIONS_PATH}"


def question_key(label: str) -> str:
    """Question id for a label's Noul. Ids are never shown to the model."""
    return "is_" + _KEY_UNSAFE.sub("_", label)


def build_state(email: dict) -> dict:
    """
    The email as a named-field object. HTML bodies are reduced to text, URLs
    to scheme + host, and the body is capped; all three cut the unrelated
    content that TypeSafe documents as hurting Jev's accuracy.
    """
    body = str(email.get("body") or email.get("snippet") or "")
    if looks_like_html(body):
        body = strip_html(body)
    return {
        "from": str(email.get("from", "Unknown")),
        "subject": normalize_urls(str(email.get("subject", "No Subject"))),
        "date": str(email.get("date", "Unknown")),
        "body": normalize_urls(body)[:BODY_MAX_CHARS],
    }


def build_questions(labels: list[str], descriptions: dict[str, str]) -> dict:
    """One Noul per label plus a Choice with a 'None' escape hatch."""
    questions = {}
    for label in labels:
        questions[question_key(label)] = {
            "type": "noul",
            "instructions": f"Does this email belong under the label '{label}'?",
            "criteria": {
                "true": descriptions[label],
                "false": f"The email does not match the '{label}' description",
            },
        }
    criteria = {label: descriptions[label] for label in labels}
    criteria[NONE_OPTION] = "None of the other labels fit this email"
    questions[BEST_QUESTION] = {
        "type": "choice",
        "instructions": "Which single label fits this email best?",
        "criteria": criteria,
    }
    return questions


def _probability(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def select_labels(
    answers: dict,
    labels: list[str],
    label_threshold: float,
    fallback_confidence: float,
) -> list[str]:
    """Pure decision rule over a decisions response's ``answers`` object."""
    chosen = []
    for label in labels:
        answer = answers.get(question_key(label))
        p = _probability(answer.get("noul")) if isinstance(answer, dict) else None
        if p is not None and p >= label_threshold:
            chosen.append(label)
    if chosen:
        return chosen

    best = answers.get(BEST_QUESTION)
    if not isinstance(best, dict):
        return []
    choice = best.get("choice")
    confidence = _probability(best.get("confidence"))
    if (
        choice in labels
        and confidence is not None
        and confidence >= fallback_confidence
    ):
        return [choice]
    return []


def validate_labels(labels: list[str], descriptions: dict[str, str]) -> None:
    """Fail fast on configs Jev cannot represent unambiguously."""
    if not labels:
        raise ValueError("At least one label is required")
    missing = [label for label in labels if not descriptions.get(label)]
    if missing:
        raise ValueError(f"Every label needs a description; missing: {missing}")
    if NONE_OPTION in labels:
        raise ValueError(f"'{NONE_OPTION}' is reserved for the no-label option")
    keys = [question_key(label) for label in labels]
    if len(set(keys)) != len(keys):
        raise ValueError(f"Label names collide after normalisation: {labels}")


class JevClassifier:
    """Classify emails with Jev through the OpenRouter decisions endpoint."""

    def __init__(
        self,
        api_key: str,
        labels: list[str],
        label_descriptions: dict[str, str],
        model: str = DEFAULT_MODEL,
        decisions_url: str = OPENROUTER_DECISIONS_URL,
        label_threshold: float = 0.7,
        fallback_confidence: float = 0.5,
        timeout_seconds: float = 30.0,
        retry_delay_seconds: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ):
        validate_labels(labels, label_descriptions)
        self.labels = list(labels)
        self.model = model
        self.decisions_url = decisions_url
        self.label_threshold = label_threshold
        self.fallback_confidence = fallback_confidence
        self.retry_delay_seconds = retry_delay_seconds
        self.questions = build_questions(self.labels, label_descriptions)
        self.provider_name = urlparse(decisions_url).netloc or decisions_url
        self.client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/tgrecojr/gmailclassifier",
                "X-Title": "gmailclassifier",
            },
        )
        logger.info(
            f"Initialized Jev classifier at {decisions_url} (model: {model}, "
            f"label_threshold: {label_threshold}, fallback_confidence: {fallback_confidence})"
        )

    def _post(self, payload: dict) -> httpx.Response:
        """POST with one retry on transport errors and retryable statuses."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.client.post(self.decisions_url, json=payload)
            except httpx.TransportError as e:  # includes timeouts
                if attempt == MAX_ATTEMPTS:
                    raise JevRequestError(f"transport error: {e!r}") from e
                logger.warning(f"{self.provider_name}: {e!r}; retrying once")
                time.sleep(self.retry_delay_seconds)
                continue
            if response.status_code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                logger.warning(
                    f"{self.provider_name} answered {response.status_code}; retrying once"
                )
                time.sleep(self.retry_delay_seconds)
                continue
            if response.status_code >= 400:
                raise JevRequestError(
                    f"HTTP {response.status_code}: {response.text[:300]}"
                )
            return response
        raise JevRequestError("exhausted attempts")  # pragma: no cover

    def decide(self, email: dict) -> dict:
        """
        Run the questions against one email and return the raw ``answers``
        object (per-label probabilities, best choice with confidence).

        Raises JevRequestError on any failure.
        """
        payload = {
            "model": self.model,
            "state": build_state(email),
            "questions": self.questions,
        }
        response = self._post(payload)
        try:
            data = response.json()
        except ValueError as e:
            raise JevRequestError(f"non-JSON response: {response.text[:200]}") from e
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict):
            raise JevRequestError(f"malformed response: {str(data)[:200]}")
        usage = data.get("usage") or {}
        logger.debug(
            f"[{self.provider_name}] model={data.get('model')} "
            f"input_tokens={usage.get('input_tokens')} cost={usage.get('cost')} "
            f"answers={answers}"
        )
        return answers

    def classify_email(self, email: dict) -> list[str]:
        """Return the labels to apply; failures are logged and yield []."""
        try:
            answers = self.decide(email)
        except JevRequestError as e:
            logger.error(f"Error classifying email via {self.provider_name}: {e}")
            return []
        labels = select_labels(
            answers, self.labels, self.label_threshold, self.fallback_confidence
        )
        log_classification_result(email, labels, self.provider_name)
        return labels
