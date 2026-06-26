# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# Gmail Email Classifier - Dockerfile

FROM cgr.dev/chainguard/python:latest-dev@sha256:a38c998396e846c009bcabfc70702f64205b8db1dde71c8c8e5e734213afb237 AS builder

USER root

COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:99ea34acedc870ba4ad11a1f540a1c04267c9f30aadc465a94406f52dfda2c36 /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

RUN mkdir -p /app/data && chown -R nonroot:nonroot /app

FROM cgr.dev/chainguard/python:latest@sha256:79dc146af52dbbaece4c9aed21bec2579742f3f90a222e9e5bc6f976cf508189

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
