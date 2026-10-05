# Testing Guide

## Overview

This project uses pytest for unit testing the Jev classifier, Gmail client, agent, configuration loading, and shared utilities. All external APIs are mocked: Gmail through `googleapiclient` mocks, the decisions endpoint through `httpx2.MockTransport`.

> **Note:** All commands below assume you've set up the environment with `uv sync --frozen`. Prefix any bare `pytest`, `black`, `flake8`, or `python` command with `uv run` so it executes inside the project's `.venv`.

## Requirements

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- pytest, pytest-cov, pytest-mock (installed via `uv sync`)

Install test dependencies:

```bash
uv sync --frozen
```

## Running Tests

### Run all unit tests

```bash
pytest tests/ -v -m unit
```

### Run all tests with coverage

```bash
pytest tests/ --cov=. --cov-report=term-missing --cov-report=html
```

### Run specific test file

```bash
pytest tests/test_llm_utils.py -v
```

### Run specific test class

```bash
pytest tests/test_jev_classifier.py::TestSelectLabels -v
```

### Run specific test method

```bash
pytest tests/test_jev_classifier.py::TestSelectLabels::test_falls_back_to_confident_choice -v
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                      # Shared fixtures; points CLASSIFIER_CONFIG_PATH at a throwaway config
├── test_config.py                   # classifier_config.json validation, LLM_BASE_URL / JEV_* resolution
├── test_email_classifier_agent.py   # Agent wiring, labeling, review label, dry run, state and retention
├── test_gmail_client.py             # Gmail API client (mocked googleapiclient), HTML fallback stripping
├── test_jev_classifier.py           # Request shape, threshold rule, HTTP retries (httpx2.MockTransport)
└── test_llm_utils.py                # URL normalization, HTML reduction, result logging
```

## Test Coverage

CI enforces a **75%** minimum; the suite currently sits around 95%.

What is covered:

- **config.py**: classifier config validation (labels, `label_descriptions`, reserved `None`), `LLM_BASE_URL` defaulting/override/empty handling, `JEV_*` defaults, overrides and range checks, `DRY_RUN`
- **jev_classifier.py**: decisions URL derivation, request body (one Noul per label, Choice with `None`), state building (URL normalization, HTML stripping, body cap), `select_labels` matrix, retry on timeout/429/5xx, 4xx and malformed bodies yielding `[]`
- **email_classifier_agent.py**: classifier receives config values, labels applied and archived, review label for unlabeled mail, dry run writes nothing, state persistence and retention pruning, legacy state migration, polling loop
- **gmail_client.py**: OAuth flow, message fetching, HTML-only body reduction, labelling, inbox removal
- **llm_utils.py**: URL normalization, HTML detection and reduction, result logging

`main.py`, `setup_token.py`, `verify_setup.py` and `scripts/` are entry points excluded from coverage (see `[tool.coverage.run]` in `pyproject.toml`).

## Test Categories

Tests are marked with the following categories:

- `@pytest.mark.unit`: Unit tests (fast, no external dependencies)
- `@pytest.mark.integration`: Integration tests (slower, may require external services)
- `@pytest.mark.slow`: Slow-running tests

Run only unit tests:
```bash
pytest -m unit
```

## Coverage Reports

After running tests with coverage, view the HTML report:

```bash
open htmlcov/index.html
```

## Continuous Integration

Tests run automatically on every push and pull request via GitHub Actions.

See `.github/workflows/test.yml` for CI configuration.

### CI Workflow

- Runs on Python 3.14
- Executes all unit tests
- Generates coverage reports
- Uploads coverage to Codecov
- Enforces 75% coverage threshold
- Runs linting (flake8, black)

## Writing New Tests

### Test Structure

Follow this pattern for new tests:

```python
import pytest
from unittest.mock import Mock, patch


@pytest.mark.unit
class TestMyFeature:
    """Tests for MyFeature."""

    def test_success_case(self, test_email, test_labels):
        """Test successful operation."""
        # Arrange
        expected = ["AWS", "Finance"]

        # Act
        result = my_function(test_email, test_labels)

        # Assert
        assert result == expected
```

### Using Fixtures

Common fixtures are defined in `tests/conftest.py`:

- `test_email`: Sample email dictionary
- `test_labels`: Sample label list
- `test_label_descriptions`: Sample per-label descriptions

### Mocking External APIs

`JevClassifier` accepts an `httpx2` transport, so tests hand it a `MockTransport` and assert on the exact request LiteLLM/OpenRouter would receive:

```python
import httpx2 as httpx

def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["model"] == "typesafe/jev-1.13"
    return httpx.Response(200, json={"answers": {...}})

classifier = JevClassifier(
    api_key="sk-test",
    labels=labels,
    label_descriptions=descriptions,
    retry_delay_seconds=0,
    transport=httpx.MockTransport(handler),
)
assert classifier.classify_email(email) == ["Finance"]
```

Agent tests patch `email_classifier_agent.JevClassifier` and `email_classifier_agent.GmailClient` with `Mock` objects, and patch `email_classifier_agent.config` so each test controls thresholds, `DRY_RUN`, `JEV_REVIEW_LABEL` and the state file path.

Tests that depend on `config.py` module-level values use the `reload_config` fixture in `tests/test_config.py`, which reloads the module with environment overrides while keeping a developer's real `.env` out of the picture.

## Edge Cases Tested

### Label selection

- Several Nouls at or above the threshold (multi-label, config order preserved)
- Nothing above the threshold, confident Choice fallback applied
- Choice of `None`, unconfident Choice, or a label outside the config: no label
- Missing or malformed answers (non-numeric `noul`, non-dict entries) ignored

### Request and state

- One Noul per label plus a Choice containing `None`; question ids never carry meaning
- Label names with spaces or punctuation produce unique, safe question ids
- URLs reduced to scheme + host; HTML-only bodies reduced to text; body capped at 5000 characters
- `classifier_config.json` without `label_descriptions`, with a missing description, or using the reserved `None` label

### Error Handling

- Timeout, connection error, 429 and 5xx retried once; second failure yields `[]`
- Other 4xx not retried, yields `[]`
- Non-JSON or malformed response bodies yield `[]`
- Agent exceptions leave the email unprocessed (retried next poll)
- Empty / whitespace `LLM_BASE_URL` falling back to OpenRouter; out-of-range `JEV_*` values fail at startup

## Future Testing

Possible additions:

- Integration tests with real API calls (optional, requires API keys)
- End-to-end tests for the email classification workflow

## Troubleshooting

### Import errors

If you see `ModuleNotFoundError`, ensure all dependencies are installed:

```bash
uv sync --frozen
```

### Coverage not updating

Clear coverage cache:

```bash
rm -rf .coverage htmlcov/
uv run pytest tests/ --cov=.
```

### Tests failing on CI but passing locally

Check Python version consistency:

```bash
uv run python --version  # Should be 3.14.x
```

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [pytest-mock documentation](https://pytest-mock.readthedocs.io/)
