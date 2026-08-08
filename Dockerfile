# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
# Gmail Email Classifier - Dockerfile

FROM cgr.dev/chainguard/python:latest-dev@sha256:7b79c054afd14f566d1d52ea1d4d037267ec8570efedbc6ead779d89ba943abe AS builder

USER root

COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Pre-download the prompt-injection detection model so the container
# never needs network access to HuggingFace at runtime
ARG INJECTION_ML_MODEL=protectai/deberta-v3-base-prompt-injection-v2
ENV HF_HOME=/app/models
RUN /app/.venv/bin/python -c "\
from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
AutoTokenizer.from_pretrained('${INJECTION_ML_MODEL}'); \
AutoModelForSequenceClassification.from_pretrained('${INJECTION_ML_MODEL}')"

RUN mkdir -p /app/data && chown -R nonroot:nonroot /app

FROM cgr.dev/chainguard/python:latest@sha256:1bd5d5a1efa2802a5467a4c1faf54e74150a9c88a8a454cef8f7b11592ea91d9

WORKDIR /app

COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv
COPY --from=builder --chown=nonroot:nonroot /app/data /app/data
COPY --from=builder --chown=nonroot:nonroot /app/models /app/models
COPY --chown=nonroot:nonroot *.py ./

ENV PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/app/models \
    HF_HUB_OFFLINE=1 \
    GMAIL_CREDENTIALS_PATH=/app/credentials.json \
    GMAIL_TOKEN_PATH=/app/token.json \
    GMAIL_HEADLESS_MODE=true \
    CLASSIFIER_CONFIG_PATH=/app/classifier_config.json \
    MODEL_CONFIG_PATH=/app/model_config.json \
    STATE_FILE=/app/data/.email_state.json

ENTRYPOINT []
CMD ["python", "main.py"]
