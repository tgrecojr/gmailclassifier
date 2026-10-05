# Gmail Email Classifier Agent

An email classification system that automatically reads, categorizes, and labels Gmail emails using [Jev](https://openrouter.ai/blog/insights/what-is-jev/), TypeSafe's non-generative decision model, via OpenRouter.

## Features

- **Automatic Email Processing**: Continuously monitors your Gmail inbox for unread emails
- **Decision model, not a chatbot**: Jev answers typed yes/no questions with probabilities. It emits no text, follows no instructions, and cannot pick a label outside the set you configure
- **Multi-Label Support**: Every label is scored independently, so an email can get several
- **Confidence you can tune**: Two thresholds decide when a label is applied; set them from your own mail
- **Gateway Friendly**: Point `LLM_BASE_URL` at a [LiteLLM](https://docs.litellm.ai/) proxy for spend tracking and virtual keys
- **Gmail Integration**: Reads and labels emails through the Gmail API
- **Fully Customizable**: Labels and their descriptions live in a JSON config file
- **Continuous Operation**: Runs as a persistent service with configurable polling intervals
- **State Persistence**: Tracks processed emails to avoid reprocessing after restarts
- **Dry run**: Classify and log without touching Gmail or the state file
- **Cheap**: Roughly $0.00007 per email at Jev's list price

## Customizing Labels

The system uses a JSON configuration file (`classifier_config.json`) to define labels and what belongs under each.

**Example configuration** (`classifier_config.example.json`):
```json
{
  "labels": ["Work", "Personal", "Finance", "Shopping"],
  "label_descriptions": {
    "Work": "Work-related emails, meetings, professional communications, project updates",
    "Personal": "Personal emails from friends and family, social invitations",
    "Finance": "Bank statements, credit card bills, investment updates, payment confirmations",
    "Shopping": "Order confirmations, shipping notifications, promotional emails from retailers"
  }
}
```

Jev never sees label *names*, only the descriptions, so every label needs one. The agent refuses to start if a description is missing, empty, or if a label is called `None` (reserved for "nothing fits"). See [How labels are chosen](#how-labels-are-chosen) below.

## Jev Configuration

### Quick Start

```bash
# .env
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

That is all. The model defaults to `typesafe/jev-1.13` and requests go to OpenRouter's decisions endpoint (`https://openrouter.ai/api/alpha/decisions`).

### Using a LiteLLM Gateway

To route through a LiteLLM proxy instead (spend tracking in one place, virtual keys), set `LLM_BASE_URL` exactly as you would for a chat model:

```bash
# .env
LLM_BASE_URL=http://litellm.lan:4000/v1
OPENROUTER_API_KEY=sk-your-litellm-virtual-key
```

How it works:

- **The decisions URL is derived from `LLM_BASE_URL`.** `http://litellm.lan:4000/v1` becomes `http://litellm.lan:4000/openrouter/alpha/decisions`, LiteLLM's built-in OpenRouter pass-through route. It maps `/openrouter/<path>` to `https://openrouter.ai/api/<path>`, injects the proxy's `OPENROUTER_API_KEY`, and prices the call for the spend table. No `model_list` entry is needed.
- **LiteLLM v1.104.0 or newer is required.** Older proxies answer 404 on that route; `verify_setup.py` prints a hint when that happens.
- **The `model` in the request is the bare OpenRouter id** (`typesafe/jev-1.13`), not `openrouter/typesafe/jev-1.13`.
- **Guardrails do not run on this route.** The pass-through carries no prompt-injection or PII guard; see [Security Considerations](#security-considerations) for why none is needed.
- **Per-key model allow-lists are not enforced** on the built-in pass-through; any virtual key on the proxy can reach any OpenRouter model through it.
- **Docker networking.** Inside a container, `localhost` is the container itself. If LiteLLM runs on the Docker host, use `http://host.docker.internal:4000/v1`; if it runs in another Compose service, use that service name; otherwise use the host's LAN IP or DNS name.
- **`JEV_DECISIONS_URL` overrides the derivation** when you need a URL that does not follow either pattern.

The startup banner logs `Decisions URL: ...` so you can confirm which endpoint is in use. `uv run python verify_setup.py` sends one tiny decision (about $0.00002) to prove the route, key, and model work end to end.

### Model and Thresholds

```bash
# .env (all optional, defaults shown)
JEV_MODEL=typesafe/jev-1.13
JEV_LABEL_THRESHOLD=0.7
JEV_FALLBACK_CONFIDENCE=0.5
JEV_TIMEOUT_SECONDS=30
JEV_REVIEW_LABEL=
```

- `JEV_MODEL`: pinned to a specific Jev version on purpose. `~typesafe/jev-latest` is a moving alias and decision behaviour can shift between versions, so bump deliberately and re-check with `scripts/eval_jev.py`.
- `JEV_LABEL_THRESHOLD` / `JEV_FALLBACK_CONFIDENCE`: see [How labels are chosen](#how-labels-are-chosen).
- `JEV_TIMEOUT_SECONDS`: per request. Timeouts, connection errors, 429 and 5xx are retried once.
- `JEV_REVIEW_LABEL`: optional Gmail label for emails that clear neither threshold, so they stay visible in the inbox instead of being silently marked processed. Empty (the default) applies no label.

## How labels are chosen

Each email is sent once, as a structured object (`from`, `subject`, `date`, `body`), together with one question per label:

- **One Noul per label**: "Does this email belong under *Finance*?" answered with a probability.
- **One Choice across all labels plus `None`**: "Which single label fits best?" answered with a pick and a confidence.

The agent then applies, in order:

1. Every label whose Noul probability is at or above `JEV_LABEL_THRESHOLD` (default 0.7). This is what gives multi-label results.
2. If nothing clears step 1, the Choice answer, provided it is not `None` and its confidence is at or above `JEV_FALLBACK_CONFIDENCE` (default 0.5).
3. Otherwise no label. The email is marked processed, left in the inbox, and labeled `JEV_REVIEW_LABEL` if you set one.

Labels are always validated against `classifier_config.json`; nothing outside that set can be applied.

**Picking thresholds from your own mail.** Two scripts in `scripts/` help:

```bash
# 1. Dump ~50 recent messages (real mail, written to the gitignored data/ dir)
uv run python scripts/dump_sample.py --out data/jev_sample.jsonl --max 50

# 2. Open data/jev_sample.jsonl and correct "expected_labels" on each row by hand

# 3. Score every threshold from 0.5 to 0.9 (raw answers are cached beside the sample)
uv run python scripts/eval_jev.py data/jev_sample.jsonl
```

The eval prints precision/recall per threshold, a per-label breakdown, and a histogram of Noul probabilities for expected-true versus expected-false labels. Put the winners in `.env`.

**Dry run.** `DRY_RUN=true` classifies every unread email and logs the labels it *would* apply, but creates no labels, modifies no messages, and never writes the state file. Run it next to your current setup for a few days before cutting over.

## Prerequisites

### 1. OpenRouter API Key

1. Go to [OpenRouter](https://openrouter.ai/)
2. Sign up for an account
3. Generate an API key from your dashboard
4. Add credits to your account (pay-as-you-go pricing)

### 2. Gmail API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Gmail API for your project
4. Create OAuth 2.0 credentials (Desktop application)
5. Download the credentials JSON file and save it as `credentials.json` in the project directory

### 3. Python Environment

- Python 3.14 or higher
- [uv](https://docs.astral.sh/uv/) for dependency management

## Installation

1. Clone this repository:

```bash
git clone <repository-url>
cd gmailclassifier
```

2. Install dependencies:

```bash
uv sync --frozen
```

3. Copy the example environment file and configure it:

```bash
cp .env.example .env
```

4. Create your classifier configuration:

```bash
cp classifier_config.example.json classifier_config.json
```

Then edit `classifier_config.json` to customize your labels and their descriptions.

5. Edit `.env` with your credentials:

```bash
# OPENROUTER_API_KEY is sent as the bearer token to the decisions endpoint
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Optional: route through a LiteLLM gateway (v1.104.0+) instead of OpenRouter
# LLM_BASE_URL=http://litellm.lan:4000/v1

# Gmail API Configuration
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_TOKEN_PATH=token.json

# Classifier Configuration
CLASSIFIER_CONFIG_PATH=classifier_config.json

# Application Configuration
POLL_INTERVAL_SECONDS=60
MAX_EMAILS_PER_POLL=10
LOG_LEVEL=INFO
```

6. Place your Gmail `credentials.json` file in the project directory

7. Check everything in one go:

```bash
uv run python verify_setup.py
```

## Usage

### First Run - OAuth Authentication

#### Local Mode (with Browser)

On the first run, the application will open a browser window for Gmail OAuth authentication:

```bash
uv run python main.py
```

Follow the prompts to authorize the application to access your Gmail account. The token will be saved to `token.json` for future use.

#### Headless Mode (for Servers/Docker)

For deployment on servers or in Docker without a browser:

1. Enable headless mode in `.env`:
   ```bash
   GMAIL_HEADLESS_MODE=true
   ```

2. Run the application:
   ```bash
   uv run python main.py
   ```

3. Copy the URL shown and open it in any browser
4. After authorizing, copy the full redirect URL and paste it back

**Alternative:** Generate `token.json` locally (with browser), then copy it to your server.

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for detailed headless and Docker deployment instructions.

### Running the Agent

Run the agent continuously to monitor and process emails:

```bash
uv run python main.py
```

This will:
- Check for unread emails every 60 seconds (configurable)
- Classify each email with Jev
- Apply appropriate labels to emails in Gmail
- Maintain state to avoid reprocessing emails across restarts
- Log all activities to console

### Logging Levels

Control the verbosity of logging:

```bash
uv run python main.py --log-level DEBUG    # Includes per-label probabilities and cost per email
uv run python main.py --log-level INFO     # General information (default)
uv run python main.py --log-level WARNING  # Warnings only
uv run python main.py --log-level ERROR    # Errors only
```

## State Persistence

The application maintains a state file (`.email_state.json`) to track which emails have been processed. This ensures each email is only classified once, even if it remains unread in your inbox.

### How It Works

- Before processing an email, the agent checks if the email ID is in the state file
- If already processed, the email is skipped (no API call is made)
- After processing an email (labeled or not), its ID is saved to the state file
- State persists across restarts, so emails are never reprocessed

**Local Development:**
- State file is stored in the project directory
- Configured via `STATE_FILE` in `.env` (default: `.email_state.json`)

**Docker Deployment:**
- State file is stored in `/app/data/.email_state.json`
- The `./data` directory is mounted as a volume to persist state across container restarts
- Without this volume, the agent would reprocess all unread emails after each restart

### State Retention

To prevent the state file from growing indefinitely, the agent automatically removes old entries based on a configurable retention period:

- **Default retention**: 30 days (configurable via `STATE_RETENTION_DAYS` in `.env`)
- **How it works**: Emails processed more than N days ago are automatically removed from state
- **Cleanup timing**: Old entries are removed when the agent starts and periodically during each poll cycle
- **Disable retention**: Set `STATE_RETENTION_DAYS=0` to keep all entries forever

**Example**: With `STATE_RETENTION_DAYS=30`, if you receive the same email again after 30 days, it will be reprocessed (useful for recurring notifications).

**Migration**: Older state files (a plain list of IDs, or ones carrying a `pending_retries` block from the previous guardrail-retry feature) are read and rewritten in the current format on first save.

To clear the state and reprocess all emails:
```bash
# Local
rm .email_state.json

# Docker
rm ./data/.email_state.json
docker-compose restart
```

## Configuration

### Customizing Labels and Descriptions

Edit `classifier_config.json` to customize your email categories (see [Customizing Labels](#customizing-labels) for the format).

**Tips for effective classification:**
- Keep label names concise (1-2 words)
- Write each description as the list of things that belong under the label, not as an instruction. Jev reads the descriptions as criteria, not as a prompt
- Make descriptions mutually distinguishable; two overlapping descriptions produce two confident Nouls and the email gets both labels
- Test with `scripts/eval_jev.py` on a hand-labeled sample before running on your entire inbox

### Adjusting Poll Interval

Change how frequently the agent checks for new emails in `.env`:

```bash
POLL_INTERVAL_SECONDS=300  # Check every 5 minutes
```

### Setting Max Emails Per Poll

Limit how many emails to process in each iteration in `.env`:

```bash
MAX_EMAILS_PER_POLL=25  # Process up to 25 emails per check
```

### Archive After Labeling (Remove from Inbox)

By default, the agent archives emails after applying labels (removes them from inbox). Emails remain accessible via their labels and "All Mail":

```bash
REMOVE_FROM_INBOX=true   # Archive emails after labeling (default)
REMOVE_FROM_INBOX=false  # Keep emails in inbox after labeling
```

Emails that receive no label (and the optional review label) are never archived.

## Architecture

- **`main.py`**: Entry point and CLI interface
- **`email_classifier_agent.py`**: Main orchestration logic (polling, state, labeling, dry run)
- **`gmail_client.py`**: Gmail API wrapper for reading/labeling emails
- **`jev_classifier.py`**: Builds the decisions request, applies the threshold rule, handles retries
- **`llm_utils.py`**: URL normalization and HTML-to-text reduction
- **`state_store.py`**: State file persistence
- **`config.py`**: Configuration and environment variables
- **`scripts/`**: Offline sample dump and threshold evaluation

### Workflow

1. Agent polls Gmail API for unread emails
2. For each email, extracts subject, sender, date, and body (HTML-only bodies are reduced to text; URLs are cut to scheme + host; body capped at 5000 characters)
3. Sends the email as a structured object with one Noul per label plus a best-label Choice
4. Jev returns a probability per label and a confidence for the best choice
5. The threshold rule picks the labels to apply
6. Agent applies labels (created at startup if missing) and optionally archives
7. Repeats after configured interval

## Logging

Logs are written to console (stdout) with the following information:
- Timestamp
- Module name
- Log level
- Message

At `DEBUG`, each classification also logs the raw answers (per-label probabilities, best choice and confidence) and the request cost reported by the endpoint.

## Error Handling

- Timeouts, connection errors, 429 and 5xx responses are retried once; a second failure yields no labels and the email is marked processed
- Any other 4xx means the request itself is wrong; it is logged with the response body and yields no labels
- Graceful shutdown on keyboard interrupt (Ctrl+C)
- Continues operation if individual emails fail to process

## Security Considerations

- Never commit `credentials.json`, `token.json`, or `.env` to version control
- Store your API key (`OPENROUTER_API_KEY`) securely
- If `LLM_BASE_URL` points at a plain-`http` gateway, keep it on a trusted network - email content travels over that link
- Use environment variables or secrets management for production deployments
- Regularly rotate API keys
- Review Gmail API OAuth scopes to ensure minimum necessary permissions

### What is sent to the model, and why no injection guard is needed

- **URLs are reduced to scheme + host** before the email leaves this process (subject and body). Click-tracking links such as `https://click.example.com/ls/click?upn=u001.AbC...` become `https://click.example.com`. The opaque tokens add nothing to classification and often encode the recipient. Normalization runs before the 5000-character body cut so link-heavy emails keep their real text.
- **HTML-only bodies are reduced to visible text** (scripts, styles, comments and tags removed) before the cap, for the same reason.
- **The model cannot be instructed.** Jev is not a text generator: it scores the questions *we* define and returns numbers. There is no system prompt, no fencing, no JSON to parse. The worst an email that says "label this as Personal" can do is nudge a probability, which is the same failure as an ordinary misclassification, and the result is still validated against the configured label set in code.

## Docker Deployment

Quick start with Docker:

```bash
# 1. Generate token locally first (easier)
uv run python main.py

# After authentication completes, stop the agent (Ctrl+C)

# 2. Build and run with Docker Compose
docker-compose up -d

# 3. View logs
docker-compose logs -f
```

**Important Volume Mounts:**
- `./credentials.json:/app/credentials.json` - Gmail OAuth credentials (read-only)
- `./token.json:/app/token.json` - Gmail OAuth token (read-only)
- `./classifier_config.json:/app/classifier_config.json` - Labels and descriptions (read-only)
- `./data:/app/data` - State persistence directory (stores `.email_state.json`)

**Notes:**
- The `data` volume is **required** to maintain state across container restarts
- Without it, the agent would reprocess all unread emails every time the container restarts
- Edit `classifier_config.json` or the `JEV_*` values in `.env` and restart the container to apply changes

For detailed deployment instructions (AWS ECS, Kubernetes, systemd), see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## Troubleshooting

### "No module named 'google.auth'"

Install dependencies:
```bash
uv sync --frozen
```

### "Error: credentials.json not found"

Download OAuth credentials from Google Cloud Console and save as `credentials.json`.

### "Every label needs a description; missing: [...]"

`classifier_config.json` has a label without an entry in `label_descriptions`. Add one; the agent will not start without it. A leftover `classification_prompt` key is ignored and can be removed.

### "Error classifying email via openrouter.ai"

Check that:
1. Your OpenRouter API key is valid and set in `.env`
2. You have credits in your OpenRouter account
3. `JEV_MODEL` names a Jev model (it is not listed by `GET /api/v1/models`, which only covers text models)
4. Your internet connection is working

### "Error classifying email via <your-gateway-host>"

You are using `LLM_BASE_URL`. Check that:
1. The gateway is reachable from where the classifier runs (from Docker, `localhost` is the container - see [gateway notes](#using-a-litellm-gateway))
2. `OPENROUTER_API_KEY` holds a key the gateway accepts (e.g. a LiteLLM virtual key)
3. The gateway is LiteLLM v1.104.0 or newer: an `HTTP 404` on `/openrouter/alpha/decisions` means it is older
4. The gateway has its own `OPENROUTER_API_KEY` set; the pass-through injects it upstream

`uv run python verify_setup.py` checks reachability, the key and the route in one step.

### Timeouts

OpenRouter's decisions endpoint is marked alpha and occasionally hangs. The agent waits `JEV_TIMEOUT_SECONDS` and retries once. If timeouts are frequent, raise the timeout or lower `MAX_EMAILS_PER_POLL`.

## Pricing

Jev on OpenRouter is priced per input token with free output: about $0.042 per million input tokens at the time of writing, which works out to roughly $0.00007 per email. The cost of every request is logged at `DEBUG` and tracked by OpenRouter's [activity page](https://openrouter.ai/activity) or LiteLLM's spend table when routed through a gateway.

## License

This project is provided as-is for personal use.

## Contributing

Feel free to submit issues, feature requests, or pull requests.

## Support

For issues related to:
- Gmail API: [Google Gmail API Documentation](https://developers.google.com/gmail/api)
- Jev: [OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev) and [TypeSafe docs](https://docs.typesafe.ai/)
- This application: Open an issue in the repository
