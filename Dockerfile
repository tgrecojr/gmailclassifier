# Gmail Email Classifier - Dockerfile

FROM python:3.14-slim@sha256:33ef7446e8c14b21cb247e23afbcdc90e98853b70812ca46b2265e769a7dfb8b

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py .


# Copy credentials and configs (should be mounted as volumes in production)
# DO NOT build credentials into the image for security
# COPY credentials.json .
# COPY token.json .
# COPY classifier_config.json .
# COPY model_config.json .

# Create directory for state files
RUN mkdir -p /app/data

# Set environment variables
ENV GMAIL_CREDENTIALS_PATH=/app/credentials.json
ENV GMAIL_TOKEN_PATH=/app/token.json
ENV GMAIL_HEADLESS_MODE=true
ENV CLASSIFIER_CONFIG_PATH=/app/classifier_config.json
ENV MODEL_CONFIG_PATH=/app/model_config.json
ENV STATE_FILE=/app/data/.email_state.json

# Run the application
CMD ["python", "main.py"]
