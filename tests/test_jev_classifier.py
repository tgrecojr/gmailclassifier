"""
Unit tests for jev_classifier.py

The HTTP layer is exercised through httpx2.MockTransport so the request body
OpenRouter would receive is asserted exactly.
"""

import json
import logging

import httpx2 as httpx
import pytest

from jev_classifier import (
    BEST_QUESTION,
    BODY_MAX_CHARS,
    DEFAULT_MODEL,
    NONE_OPTION,
    OPENROUTER_DECISIONS_URL,
    JevClassifier,
    JevRequestError,
    build_questions,
    build_state,
    question_key,
    select_labels,
    validate_labels,
)

LABELS = ["Finance", "Shopping", "Work Stuff"]
DESCRIPTIONS = {
    "Finance": "Bills, bank statements, payment confirmations",
    "Shopping": "Order confirmations and shipping notifications",
    "Work Stuff": "Professional correspondence and project updates",
}


@pytest.fixture
def email():
    return {
        "id": "msg1",
        "subject": "Your AWS Bill is Ready https://aws.amazon.com/billing/x?y=1",
        "from": "billing@aws.amazon.com",
        "date": "2026-04-24",
        "body": "Your monthly AWS bill is now available at https://console.aws.amazon.com/billing/home?region=us",
    }


def _answers(finance=0.95, shopping=0.05, work=0.1, choice="Finance", confidence=0.9):
    return {
        "is_Finance": {"type": "noul", "noul": finance},
        "is_Shopping": {"type": "noul", "noul": shopping},
        "is_Work_Stuff": {"type": "noul", "noul": work},
        BEST_QUESTION: {
            "type": "choice",
            "choice": choice,
            "probabilities": {
                "Finance": 0.9,
                "Shopping": 0.05,
                "Work Stuff": 0.03,
                NONE_OPTION: 0.02,
            },
            "confidence": confidence,
        },
    }


def _response_body(answers=None):
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": answers if answers is not None else _answers(),
        "usage": {"input_tokens": 300, "output_tokens": 0, "cost": 0.0000126},
        "id": "gen-dec-1",
        "provider": "TypeSafe",
    }


def _classifier(handler, **overrides):
    kwargs = dict(
        api_key="sk-test",
        labels=LABELS,
        label_descriptions=DESCRIPTIONS,
        retry_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    kwargs.update(overrides)
    return JevClassifier(**kwargs)


@pytest.mark.unit
class TestBuildState:
    def test_named_fields_with_urls_reduced_to_host(self, email):
        state = build_state(email)
        assert set(state) == {"from", "subject", "date", "body"}
        assert state["from"] == "billing@aws.amazon.com"
        assert state["subject"] == "Your AWS Bill is Ready https://aws.amazon.com"
        assert (
            state["body"]
            == "Your monthly AWS bill is now available at https://console.aws.amazon.com"
        )

    def test_html_body_is_reduced_to_text(self):
        state = build_state(
            {"body": "<html><body><p>Hello</p><script>x()</script></body></html>"}
        )
        assert state["body"] == "Hello"

    def test_body_is_capped_and_snippet_is_fallback(self):
        assert (
            len(build_state({"body": "x" * (BODY_MAX_CHARS + 500)})["body"])
            == BODY_MAX_CHARS
        )
        assert build_state({"snippet": "short"})["body"] == "short"
        assert build_state({})["body"] == ""


@pytest.mark.unit
class TestBuildQuestions:
    def test_one_noul_per_label_plus_choice_with_none(self):
        questions = build_questions(LABELS, DESCRIPTIONS)
        assert set(questions) == {
            "is_Finance",
            "is_Shopping",
            "is_Work_Stuff",
            BEST_QUESTION,
        }
        noul = questions["is_Work_Stuff"]
        assert noul["type"] == "noul"
        assert "'Work Stuff'" in noul["instructions"]
        assert noul["criteria"]["true"] == DESCRIPTIONS["Work Stuff"]
        best = questions[BEST_QUESTION]
        assert best["type"] == "choice"
        assert list(best["criteria"]) == LABELS + [NONE_OPTION]
        assert best["criteria"]["Finance"] == DESCRIPTIONS["Finance"]

    def test_question_key_normalises_unsafe_characters(self):
        assert question_key("Work Stuff") == "is_Work_Stuff"
        assert question_key("AI/ML & Data") == "is_AI_ML_Data"


@pytest.mark.unit
class TestValidateLabels:
    def test_accepts_valid_config(self):
        validate_labels(LABELS, DESCRIPTIONS)

    def test_rejects_missing_description(self):
        with pytest.raises(ValueError, match="missing"):
            validate_labels(LABELS, {"Finance": "x", "Shopping": "y", "Work Stuff": ""})

    def test_rejects_reserved_none_label_and_collisions_and_empty(self):
        with pytest.raises(ValueError, match="reserved"):
            validate_labels(["None"], {"None": "x"})
        with pytest.raises(ValueError, match="collide"):
            validate_labels(["A B", "A-B"], {"A B": "x", "A-B": "y"})
        with pytest.raises(ValueError, match="At least one"):
            validate_labels([], {})


@pytest.mark.unit
class TestSelectLabels:
    def test_every_noul_at_or_above_threshold_in_config_order(self):
        answers = _answers(finance=0.7, shopping=0.71, work=0.69)
        assert select_labels(answers, LABELS, 0.7, 0.5) == ["Finance", "Shopping"]

    def test_falls_back_to_confident_choice(self):
        answers = _answers(
            finance=0.6, shopping=0.1, work=0.1, choice="Finance", confidence=0.55
        )
        assert select_labels(answers, LABELS, 0.7, 0.5) == ["Finance"]

    def test_no_label_when_fallback_is_none_or_unconfident_or_unknown(self):
        assert (
            select_labels(
                _answers(0.1, 0.1, 0.1, choice=NONE_OPTION, confidence=0.99),
                LABELS,
                0.7,
                0.5,
            )
            == []
        )
        assert (
            select_labels(
                _answers(0.1, 0.1, 0.1, choice="Finance", confidence=0.3),
                LABELS,
                0.7,
                0.5,
            )
            == []
        )
        assert (
            select_labels(
                _answers(0.1, 0.1, 0.1, choice="Travel", confidence=0.9),
                LABELS,
                0.7,
                0.5,
            )
            == []
        )

    def test_tolerates_missing_or_malformed_answers(self):
        assert select_labels({}, LABELS, 0.7, 0.5) == []
        assert (
            select_labels(
                {"is_Finance": {"noul": "high"}, BEST_QUESTION: "Finance"},
                LABELS,
                0.7,
                0.5,
            )
            == []
        )
        assert select_labels({"is_Finance": {"noul": 1}}, LABELS, 0.7, 0.5) == [
            "Finance"
        ]


@pytest.mark.unit
class TestJevClassifierHttp:
    def test_request_body_and_headers(self, email):
        seen = []

        def handler(request: httpx.Request):
            seen.append(request)
            return httpx.Response(200, json=_response_body())

        classifier = _classifier(handler)
        assert classifier.classify_email(email) == ["Finance"]

        assert len(seen) == 1
        request = seen[0]
        assert str(request.url) == OPENROUTER_DECISIONS_URL
        assert request.headers["authorization"] == "Bearer sk-test"
        assert request.headers["x-title"] == "gmailclassifier"
        body = json.loads(request.content)
        assert (
            body["model"] == DEFAULT_MODEL
        )  # bare OpenRouter id, no "openrouter/" prefix
        assert body["state"] == build_state(email)
        assert body["questions"] == build_questions(LABELS, DESCRIPTIONS)
        assert "messages" not in body

    def test_decide_returns_raw_answers_and_logs_usage(self, email, caplog):
        caplog.set_level(logging.DEBUG)
        classifier = _classifier(lambda r: httpx.Response(200, json=_response_body()))
        answers = classifier.decide(email)
        assert answers["is_Finance"]["noul"] == 0.95
        assert "cost=1.26e-05" in caplog.text

    def test_thresholds_from_constructor_are_applied(self, email):
        answers = _answers(finance=0.75, shopping=0.72, work=0.1)
        classifier = _classifier(
            lambda r: httpx.Response(200, json=_response_body(answers)),
            label_threshold=0.74,
        )
        assert classifier.classify_email(email) == ["Finance"]

    def test_timeout_is_retried_once_then_succeeds(self, email):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(200, json=_response_body())

        assert _classifier(handler).classify_email(email) == ["Finance"]
        assert len(calls) == 2

    def test_persistent_timeout_yields_empty(self, email, caplog):
        caplog.set_level(logging.ERROR)
        calls = []

        def handler(request):
            calls.append(1)
            raise httpx.ConnectError("down", request=request)

        assert _classifier(handler).classify_email(email) == []
        assert len(calls) == 2
        assert "transport error" in caplog.text

    @pytest.mark.parametrize("status", [429, 502, 503])
    def test_retryable_status_is_retried_once(self, email, status):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(status, json={"error": "busy"})
            return httpx.Response(200, json=_response_body())

        assert _classifier(handler).classify_email(email) == ["Finance"]
        assert len(calls) == 2

    def test_client_error_is_not_retried_and_raises_from_decide(self, email):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(
                400, json={"error": {"message": "Invalid request parameters"}}
            )

        classifier = _classifier(handler)
        with pytest.raises(JevRequestError, match="HTTP 400"):
            classifier.decide(email)
        assert classifier.classify_email(email) == []
        assert len(calls) == 2  # one per call, no retry

    def test_malformed_bodies_yield_empty(self, email, caplog):
        caplog.set_level(logging.ERROR)
        assert (
            _classifier(
                lambda r: httpx.Response(200, content=b"not json")
            ).classify_email(email)
            == []
        )
        assert "non-JSON" in caplog.text
        assert (
            _classifier(
                lambda r: httpx.Response(200, json={"answers": "nope"})
            ).classify_email(email)
            == []
        )
        assert "malformed" in caplog.text

    def test_invalid_label_config_fails_at_construction(self):
        with pytest.raises(ValueError):
            _classifier(
                lambda r: httpx.Response(200),
                labels=["None"],
                label_descriptions={"None": "x"},
            )
