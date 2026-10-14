# Deployment Guide for Gmail Email Classifier

This guide covers running the Gmail Email Classifier unattended: minting the Gmail token, running the container with Docker Compose, or running it as a systemd service.

## Table of Contents

- [Gmail Token for a Headless Host](#gmail-token-for-a-headless-host)
- [Docker Deployment](#docker-deployment)
- [Systemd Service (Linux)](#systemd-service-linux)
- [Security Best Practices](#security-best-practices)
- [Troubleshooting](#troubleshooting)
- [Scaling Considerations](#scaling-considerations)

---

## Gmail Token for a Headless Host

A server or container has no browser, so mint the token on a machine that does and copy it over.

```bash
# On your local machine with a browser
uv run python setup_token.py

# Follow the browser prompt. The script saves token.json and confirms it
# can read your inbox. Then copy it to the server:
scp token.json user@server:/path/to/gmailclassifier/
```

`setup_token.py` backs up an existing `token.json` before replacing it. The token is stored as JSON; a `token.json` written by an older version of the agent (a pickled object) is read once and rewritten as JSON on the next start.

If you must authorize on the server itself, set `GMAIL_HEADLESS_MODE=true` and run `main.py` from an interactive terminal: it prints an authorization URL, you open it in any browser, and paste the full redirect URL back. This requires a TTY; a container started without one fails immediately with a message pointing back at `setup_token.py`.

---

## Docker Deployment

### Build and Run with Docker

1. **Generate the token first** (see above)

2. **Create `.env`** with your configuration:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Build the Docker image**:
   ```bash
   docker build -t gmail-classifier .
   ```

4. **Run the container**:
   ```bash
   docker run -d \
     --name gmail-classifier \
     --restart unless-stopped \
     -v $(pwd)/credentials.json:/app/credentials.json:ro \
     -v $(pwd)/token.json:/app/token.json:ro \
     -v $(pwd)/classifier_config.json:/app/classifier_config.json:ro \
     -v $(pwd)/data:/app/data \
     --env-file .env \
     gmail-classifier
   ```

5. **View logs**:
   ```bash
   docker logs -f gmail-classifier
   ```

### Using Docker Compose (Recommended)

1. **Start the service**:
   ```bash
   docker compose up -d
   ```

2. **View logs**:
   ```bash
   docker compose logs -f
   ```

3. **Stop the service**:
   ```bash
   docker compose down
   ```

**Important:** The `./data` volume is required to persist the email state file (`.email_state.json`) across container restarts. Without it, the agent would reprocess all unread emails after each restart.

The published image is `ghcr.io/tgrecojr/gmailclassifier:latest`, built for `linux/amd64` on every push to `main`, signed with cosign, with an SBOM and build provenance attested to the registry. The image already sets `GMAIL_HEADLESS_MODE=true` and the container paths for credentials, token, label config, and state.

---

## Systemd Service (Linux)

For running on a Linux server with systemd:

### Step 1: Create Service File

Create `/etc/systemd/system/gmail-classifier.service`:

```ini
[Unit]
Description=Gmail Email Classifier Agent
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/gmailclassifier
Environment="PATH=/home/your-user/gmailclassifier/.venv/bin"
ExecStart=/home/your-user/gmailclassifier/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Step 2: Enable and Start

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable gmail-classifier

# Start service
sudo systemctl start gmail-classifier

# Check status
sudo systemctl status gmail-classifier

# View logs
sudo journalctl -u gmail-classifier -f
```

---

## Security Best Practices

1. **Never commit credentials to git**
   - Use `.gitignore` to exclude `credentials.json`, `token.json`, `.env`

2. **Use secrets management**
   - Environment variables or your platform's secret store
   - Rotate credentials regularly

3. **Limit permissions**
   - The agent requests only the `gmail.modify` scope
   - Give the classifier its own OpenRouter key with a spend limit

4. **Monitor costs**
   - Set a credit limit / usage alerts in the [OpenRouter dashboard](https://openrouter.ai/activity)
   - Monitor API usage in Google Cloud Console

5. **Use read-only mounts**
   - Mount credentials as read-only in containers
   - Separate token storage from application code

6. **Network security**
   - Run containers in private subnets
   - Restrict outbound traffic to Google and OpenRouter

---

## Troubleshooting

### Token expires or becomes invalid

Regenerate the token with `setup_token.py` on a machine with a browser, then copy it to your deployment.

### Rate-limit (429) errors from OpenRouter

Increase the poll interval or reduce the batch size:
```bash
POLL_INTERVAL_SECONDS=300  # 5 minutes
MAX_EMAILS_PER_POLL=5
```

The agent retries a 429 once and backs off across consecutive failed polls, up to ten times the poll interval.

### Container restarts frequently

Check logs:
```bash
docker logs gmail-classifier
```

Common issues:
- Missing credentials
- Invalid or missing `OPENROUTER_API_KEY`
- Expired Gmail token
- `classifier_config.json` missing a `label_descriptions` entry for one of its labels (the agent refuses to start)

---

## Scaling Considerations

- **Don't run multiple instances** - Gmail API has rate limits and multiple instances would process the same emails and race on the state file
- **Batch processing** - Increase `MAX_EMAILS_PER_POLL` instead of running multiple instances
