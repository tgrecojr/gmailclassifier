# Gmail Email Classifier Agent

An intelligent email classification system that automatically reads, categorizes, and labels Gmail emails using AI-powered classification.

## Features

- **Automatic Email Processing**: Continuously monitors your Gmail inbox for unread emails
- **AI-Powered Classification**: Uses OpenRouter API for access to multiple AI models (Claude, GPT-4, and more)
- **Multi-Label Support**: Emails can be assigned multiple labels simultaneously
- **Gmail Integration**: Seamlessly integrates with Gmail API for reading and labeling emails
- **Fully Customizable**: Configure your own label categories and classification rules via JSON config file
- **Continuous Operation**: Runs as a persistent service with configurable polling intervals
- **State Persistence**: Tracks processed emails to avoid reprocessing after restarts
- **Model Flexibility**: Choose from dozens of models via OpenRouter (Claude, GPT-4, Llama, and more)

## Customizing Labels and Classification

The system uses a JSON configuration file (`classifier_config.json`) to define labels and classification rules. You can easily customize it for your needs!

**Example configuration** (`classifier_config.example.json`):
```json
{
  "labels": [
    "Work",
    "Personal",
    "Finance",
    "Shopping",
    "Travel",
    "Social",
    "Newsletters"
  ],
  "classification_prompt": "Your task is to categorize the email according to the following labels.\n\nWork - Work-related emails...\nPersonal - Personal emails from friends...\n..."
}
```

See [Configuration](#configuration) section below for details on customizing your labels.

## OpenRouter Configuration

This application uses [OpenRouter](https://openrouter.ai/) to provide access to multiple AI models through a single API. OpenRouter offers:

- **Access to 100+ models**: Claude, GPT-4, Llama, Gemini, and more
- **Unified API**: One API key for all models
- **Competitive pricing**: Pay only for what you use
- **No vendor lock-in**: Switch models anytime

### Quick Start

```bash
# .env
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
```

**Popular model options:**
- `anthropic/claude-3.5-sonnet` - Best for complex classification (default)
- `anthropic/claude-3-haiku` - Faster and cheaper
- `openai/gpt-4-turbo` - Alternative high-quality option
- `meta-llama/llama-3.1-70b-instruct` - Open source option

See [OpenRouter Models](https://openrouter.ai/docs#models) for the full list of available models.

### Model Configuration

The application supports two ways to configure the model settings:

**Option 1: Model Configuration File (Recommended for Docker)**

Create a `model_config.json` file to externalize model settings. This is especially useful for Docker deployments where you can mount the config file and change model parameters without recreating the container:

```bash
cp model_config.example.json model_config.json
```

Then edit `model_config.json`:
```json
{
  "model": "anthropic/claude-3.5-sonnet",
  "temperature": 0.0,
  "max_tokens": 1000
}
```

Set the path in your `.env` file:
```bash
MODEL_CONFIG_PATH=model_config.json
```

**Benefits:**
- Change model settings without recreating Docker containers (just restart)
- Easy A/B testing of different models in production
- Clear separation between secrets (.env) and model config

**Option 2: Environment Variables (Fallback)**

If `MODEL_CONFIG_PATH` is not set, the application falls back to environment variables:

```bash
# .env
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_TEMPERATURE=0.0
OPENROUTER_MAX_TOKENS=1000
```

**Configuration Parameters:**
- `model`: OpenRouter model ID (see [available models](https://openrouter.ai/docs#models))
- `temperature`: Sampling temperature (0.0-2.0, lower = more deterministic)
- `max_tokens`: Maximum tokens in response (typically 1000 is sufficient)

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

- Python 3.11 or higher
- pip package manager

## Installation

1. Clone this repository:

```bash
git clone <repository-url>
cd gmailclassifier
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy the example environment file and configure it:

```bash
cp .env.example .env
```

4. Create your classifier configuration:

```bash
cp classifier_config.example.json classifier_config.json
```

Then edit `classifier_config.json` to customize your labels and classification prompt.

5. Create your model configuration (optional, but recommended):

```bash
cp model_config.example.json model_config.json
```

Then edit `model_config.json` to configure model settings (model, temperature, max_tokens).

6. Edit `.env` with your credentials:

```bash
# OpenRouter API Configuration
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet

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

7. Place your Gmail `credentials.json` file in the project directory

## Usage

### First Run - OAuth Authentication

#### Local Mode (with Browser)

On the first run, the application will open a browser window for Gmail OAuth authentication:

```bash
python main.py
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
   python main.py
   ```

3. Copy the URL shown and open it in any browser
4. After authorizing, copy the full redirect URL and paste it back

**Alternative:** Generate `token.json` locally (with browser), then copy it to your server.

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for detailed headless and Docker deployment instructions.

### Running the Agent

Run the agent continuously to monitor and process emails:

```bash
python main.py
```

This will:
- Check for unread emails every 60 seconds (configurable)
- Classify each email using OpenRouter
- Apply appropriate labels to emails in Gmail
- Maintain state to avoid reprocessing emails across restarts
- Log all activities to console

### Logging Levels

Control the verbosity of logging:

```bash
python main.py --log-level DEBUG    # Detailed debug information
python main.py --log-level INFO     # General information (default)
python main.py --log-level WARNING  # Warnings only
python main.py --log-level ERROR    # Errors only
```

## State Persistence

The application maintains a state file (`.email_state.json`) to track which emails have been processed. This **prevents duplicate LLM calls** and saves money by ensuring each email is only classified once, even if it remains unread in your inbox.

### How It Works

- Before processing an email, the agent checks if the email ID is in the state file
- If already processed, the email is skipped (no LLM call is made)
- After successfully processing an email, its ID is saved to the state file
- State persists across restarts, so emails are never reprocessed

This is especially important because:
- Emails may remain unread even after being classified and labeled
- The agent continuously polls for unread emails
- Without state tracking, the same emails would be sent to the LLM repeatedly, wasting money

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

**Migration**: The state file automatically migrates from the old format (list of IDs) to the new format (dictionary with timestamps) on first load.

To clear the state and reprocess all emails:
```bash
# Local
rm .email_state.json

# Docker
rm ./data/.email_state.json
docker-compose restart
```

## Configuration

### Customizing Labels and Classification Rules

Edit `classifier_config.json` to customize your email categories:

```json
{
  "labels": [
    "Work",
    "Personal",
    "Finance",
    "Shopping"
  ],
  "classification_prompt": "Your task is to categorize the email according to the following labels.\n\nWork - Work-related emails, meetings, and professional communications\nPersonal - Personal emails from friends and family\nFinance - Bank statements, bills, and payment notifications\nShopping - Order confirmations and shipping notifications\n\nOne email can have more than one label. Return only label names in JSON format, nothing else. Do not make things up."
}
```

**Tips for effective classification:**
- Keep label names concise (1-2 words)
- Provide clear, specific descriptions in the prompt
- Include examples of what each label covers
- The AI can assign multiple labels to a single email
- Test your prompt with a few emails before running on your entire inbox

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

When enabled:
- Emails are removed from your inbox after classification
- They remain accessible under their assigned labels (AWS, Claude, Github, etc.)
- Keeps your inbox clean and organized
- You can still find all emails in Gmail's "All Mail" view

## Architecture

The application consists of several components:

- **`main.py`**: Entry point and CLI interface
- **`email_classifier_agent.py`**: Main orchestration logic
- **`gmail_client.py`**: Gmail API wrapper for reading/labeling emails
- **`openrouter_classifier.py`**: OpenRouter API integration for AI classification
- **`config.py`**: Configuration and environment variables

### Workflow

1. Agent polls Gmail API for unread emails
2. For each email, extracts subject, sender, date, and body
3. Sends email content to OpenRouter with classification prompt
4. OpenRouter (using configured model) returns applicable labels in JSON format
5. Agent creates Gmail labels (if they don't exist)
6. Applies labels to the email in Gmail
7. Repeats after configured interval

## Logging

Logs are written to console (stdout) with the following information:
- Timestamp
- Module name
- Log level
- Message

Configure log verbosity using the `--log-level` flag or `LOG_LEVEL` environment variable.

## Error Handling

The application includes robust error handling:
- Retries on transient failures
- Graceful shutdown on keyboard interrupt (Ctrl+C)
- Continues operation if individual emails fail to process
- Logs all errors for debugging

## Security Considerations

- Never commit `credentials.json`, `token.json`, or `.env` to version control
- Store OpenRouter API key securely
- Use environment variables or secrets management for production deployments
- Regularly rotate API keys
- Review Gmail API OAuth scopes to ensure minimum necessary permissions

## Docker Deployment

Quick start with Docker:

```bash
# 1. Generate token locally first (easier)
python main.py

# After authentication completes, stop the agent (Ctrl+C)

# 2. Build and run with Docker Compose
docker-compose up -d

# 3. View logs
docker-compose logs -f
```

**Important Volume Mounts:**
- `./credentials.json:/app/credentials.json` - Gmail OAuth credentials (read-only)
- `./token.json:/app/token.json` - Gmail OAuth token (read-only)
- `./classifier_config.json:/app/classifier_config.json` - Labels and classification rules (read-only)
- `./model_config.json:/app/model_config.json` - Model configuration (read-only)
- `./data:/app/data` - State persistence directory (stores `.email_state.json`)

**Notes:**
- The `data` volume is **required** to maintain state across container restarts
- Without it, the agent would reprocess all unread emails every time the container restarts
- Edit `classifier_config.json` to customize labels; restart the container to apply changes
- **Edit `model_config.json` to change model settings (model, temperature, max_tokens) and just restart - no need to recreate the container!**

For detailed deployment instructions (AWS ECS, Kubernetes, systemd), see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## Troubleshooting

### "No module named 'google.auth'"

Install dependencies:
```bash
pip install -r requirements.txt
```

### "Error: credentials.json not found"

Download OAuth credentials from Google Cloud Console and save as `credentials.json`.

### "Error classifying email with OpenRouter"

Check that:
1. Your OpenRouter API key is valid and set in `.env`
2. You have credits in your OpenRouter account
3. The model ID is correct (see [OpenRouter Models](https://openrouter.ai/docs#models))
4. Your internet connection is working

### "Model not found" or "Invalid model ID"

Verify the model ID in `.env` matches an available OpenRouter model. Check the [OpenRouter Models documentation](https://openrouter.ai/docs#models) for available models.

## OpenRouter Pricing

OpenRouter pricing varies by model:
- **Claude 3.5 Sonnet**: ~$0.003-0.015 per email classification
- **Claude 3 Haiku**: ~$0.001-0.005 per email (cheaper)
- **GPT-4 Turbo**: ~$0.01-0.03 per email
- **Llama 3.1 70B**: ~$0.001-0.005 per email (open source)

Typical usage for email classification:
- ~500-1000 tokens per email
- Pay only for what you use
- Monitor usage in [OpenRouter Dashboard](https://openrouter.ai/activity)

## License

This project is provided as-is for personal use.

## Contributing

Feel free to submit issues, feature requests, or pull requests.

## Support

For issues related to:
- Gmail API: [Google Gmail API Documentation](https://developers.google.com/gmail/api)
- OpenRouter: [OpenRouter Documentation](https://openrouter.ai/docs)
- This application: Open an issue in the repository
