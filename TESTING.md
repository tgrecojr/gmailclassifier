# Testing Guide

## Overview

This project uses pytest for testing with comprehensive unit test coverage for all LLM providers and utility functions.

## Requirements

- Python 3.13
- pytest
- pytest-cov
- pytest-mock

Install test dependencies:

```bash
pip install -r requirements-dev.txt
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
pytest tests/test_bedrock_provider.py::TestBedrockProvider -v
```

### Run specific test method

```bash
pytest tests/test_llm_utils.py::TestParseLabelsParsing::test_plain_json_object -v
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                      # Shared fixtures and test data
├── test_llm_utils.py                # Tests for llm_utils.py (100% coverage)
├── test_llm_factory.py              # Tests for llm_factory.py (100% coverage)
├── test_bedrock_provider.py         # Tests for BedrockProvider (95% coverage)
├── test_anthropic_provider.py       # Tests for AnthropicProvider (86% coverage)
├── test_openai_provider.py          # Tests for OpenAIProvider (72% coverage)
└── test_ollama_provider.py          # Tests for OllamaProvider (72% coverage)
```

## Test Coverage

Current test coverage focuses on:

- **llm_utils.py**: 70% coverage
  - Email content construction
  - Classification prompt construction
  - JSON parsing edge cases
  - Label validation and case-insensitive matching

- **llm_factory.py**: 100% coverage
  - Provider creation for all types
  - Configuration handling
  - Error handling for invalid providers

- **Provider modules**: 72-95% coverage
  - Successful classification
  - API error handling
  - JSON parsing edge cases
  - Invalid label filtering
  - Case-insensitive label matching

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

- Runs on Python 3.13
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
- `mock_responses`: Mock API responses for all providers

### Mocking External APIs

Use `patch.dict('sys.modules', ...)` to mock external library imports:

```python
with patch.dict('sys.modules', {'anthropic': mock_anthropic}):
    from providers.anthropic_provider import AnthropicProvider
    provider = AnthropicProvider(api_key="test-key")
    result = provider.classify_email(...)
```

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
- Invalid provider types

## Future Testing

Planned test additions (see issue #5):

- Integration tests with real API calls (optional, requires API keys)
- End-to-end tests for email classification workflow
- Performance benchmarking tests
- Consistency tests across providers
- Provider fallback mechanism tests

## Troubleshooting

### Import errors

If you see `ModuleNotFoundError`, ensure all dependencies are installed:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Coverage not updating

Clear coverage cache:

```bash
rm -rf .coverage htmlcov/
pytest tests/ --cov=.
```

### Tests failing on CI but passing locally

Check Python version consistency:

```bash
python --version  # Should be 3.13.x
```

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [pytest-mock documentation](https://pytest-mock.readthedocs.io/)
