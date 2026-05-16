# syntax=docker/dockerfile:1.24@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
# Gmail Email Classifier - Dockerfile

FROM python:3.14-slim@sha256:7a500125bc50693f2214e842a621440a1b1b9cbb2188f74ab045d29ed2ea5856 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim@sha256:7a500125bc50693f2214e842a621440a1b1b9cbb2188f74ab045d29ed2ea5856

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

COPY *.py ./

RUN mkdir -p /app/data

ENV GMAIL_CREDENTIALS_PATH=/app/credentials.json
ENV GMAIL_TOKEN_PATH=/app/token.json
ENV GMAIL_HEADLESS_MODE=true
ENV CLASSIFIER_CONFIG_PATH=/app/classifier_config.json
ENV MODEL_CONFIG_PATH=/app/model_config.json
ENV STATE_FILE=/app/data/.email_state.json

CMD ["python", "main.py"]
