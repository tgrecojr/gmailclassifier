# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# Gmail Email Classifier - Dockerfile

FROM cgr.dev/chainguard/python:latest-dev@sha256:727c118ee34aab194fa2b25c0116f669fc1459fd6bda6e2f570a15c75c9fda4e AS builder

USER root

COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

RUN mkdir -p /app/data && chown -R nonroot:nonroot /app

FROM cgr.dev/chainguard/python:latest@sha256:4d908c6a44ba22460e34a2f6dd665b8fcb82bd3e6c887e749bd6fef243e10094

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv
COPY --from=builder --chown=nonroot:nonroot /app/data /app/data
COPY --chown=nonroot:nonroot *.py ./

ENV PATH="/app/.venv/bin:$PATH" \
    GMAIL_CREDENTIALS_PATH=/app/credentials.json \
    GMAIL_TOKEN_PATH=/app/token.json \
    GMAIL_HEADLESS_MODE=true \
    CLASSIFIER_CONFIG_PATH=/app/classifier_config.json \
    MODEL_CONFIG_PATH=/app/model_config.json \
    STATE_FILE=/app/data/.email_state.json

ENTRYPOINT []
CMD ["python", "main.py"]
