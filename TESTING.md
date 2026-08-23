# Testing Guide

## Overview

This project uses pytest for unit testing the classifier, Gmail client, configuration loading, and shared utilities. All external APIs (Gmail, the LLM endpoint) are mocked.

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
pytest tests/test_openrouter_classifier.py::TestOpenRouterClassifierInit -v
```

### Run specific test method

```bash
pytest tests/test_llm_utils.py::TestParseLabelsParsing::test_plain_json_object -v
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                      # Shared fixtures, creates a throwaway classifier_config.json
├── test_config.py                   # model_config.json validation, LLM_BASE_URL resolution
├── test_email_classifier_agent.py   # Agent wiring, state tracking and retention
├── test_gmail_client.py             # Gmail API client (mocked googleapiclient)
├── test_llm_utils.py                # Prompt construction and JSON label parsing
└── test_openrouter_classifier.py    # OpenRouterClassifier (mocked openai client)
```

## Test Coverage

CI enforces a **70%** minimum; the suite currently sits around 80%.

What is covered:

- **config.py**: model config validation, `LLM_BASE_URL` defaulting/override/empty handling
- **openrouter_classifier.py**: client construction (default OpenRouter URL, custom gateway URL, empty fallback), request parameters, error handling, label filtering
- **email_classifier_agent.py**: classifier receives config values including `LLM_BASE_URL`, state persistence and retention pruning
- **gmail_client.py**: OAuth flow, message fetching, labelling, inbox removal
- **llm_utils.py**: email/prompt construction, JSON parsing edge cases, case-insensitive label matching

`main.py`, `setup_token.py`, and `verify_setup.py` are entry-point scripts excluded from coverage (see `[tool.coverage.run]` in `pyproject.toml`).

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
- Enforces 70% coverage threshold
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
- `classification_prompt`: Sample classification prompt

### Mocking External APIs

`OpenRouterClassifier` imports `openai` lazily inside `__init__`, so patch `openai.OpenAI` and then swap in a fresh `MagicMock` client per test:

```python
with patch("openai.OpenAI") as mock_openai:
    mock_openai.return_value = MagicMock()
    classifier = OpenRouterClassifier(api_key="test-key", base_url="http://litellm:4000/v1")

classifier.client = MagicMock()
classifier.client.chat.completions.create.return_value = fake_response
result = classifier.classify_email(email, prompt, labels)
```

Tests that depend on `config.py` module-level values use the `reload_config` fixture in `tests/test_config.py`, which reloads the module with environment overrides while keeping a developer's real `.env` out of the picture.

## Edge Cases Tested

### JSON Parsing

- Plain JSON object: `{"labels": ["AWS", "Finance"]}`
- JSON in markdown code blocks
- JSON with extra text before/after
- Invalid JSON structures
- Non-string labels in arrays
- Case-insensitive label matching
- Empty labels arrays

### Error Handling

- API connection errors
- Authentication errors
- Rate limiting
- Timeout errors
- Missing dependencies (ImportError)
- Empty / whitespace `LLM_BASE_URL` falling back to OpenRouter

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
