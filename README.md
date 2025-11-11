# Gmail Email Classifier Agent

An intelligent email classification system that automatically reads, categorizes, and labels Gmail emails using AI-powered classification.

## Features

- **Automatic Email Processing**: Continuously monitors your Gmail inbox for unread emails
- **AI-Powered Classification**: Supports multiple LLM providers (AWS Bedrock, Anthropic, OpenAI, Ollama)
- **Multi-Label Support**: Emails can be assigned multiple labels simultaneously
- **Gmail Integration**: Seamlessly integrates with Gmail API for reading and labeling emails
- **Fully Customizable**: Configure your own label categories and classification rules via JSON config file
- **Continuous Operation**: Runs as a persistent service with configurable polling intervals
- **State Persistence**: Tracks processed emails to avoid reprocessing after restarts
- **Privacy Options**: Use local LLMs (Ollama) to keep emails on your machine

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

## Choosing an LLM Provider

The Gmail Classifier supports multiple LLM providers. Choose the one that best fits your needs:

| Provider | Cost | Privacy | Setup Complexity | Best For |
|----------|------|---------|------------------|----------|
| **Ollama** | FREE | ⭐⭐⭐ Local | Medium | Privacy-conscious users, free local processing |
| **Anthropic API** | Paid | Cloud | Easy | Simple setup, direct Claude access |
| **OpenAI** | Paid | Cloud | Easy | Existing OpenAI users, GPT-4 access |
| **AWS Bedrock** | Paid | Cloud | Complex | AWS infrastructure users, enterprise |

### Quick Start by Provider

**Ollama (Free, Local, Private)**
```bash
# .env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=http://localhost:11434
```
Requirements: Install [Ollama](https://ollama.ai/) locally and pull a model (`ollama pull llama3`)

**Anthropic Direct API (Easiest Cloud Setup)**
```bash
# .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```
Requirements: [Anthropic API key](https://console.anthropic.com/)

**OpenAI API**
```bash
# .env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4-turbo
```
Requirements: [OpenAI API key](https://platform.openai.com/)

**AWS Bedrock**
```bash
# .env
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```
Requirements: AWS account with Bedrock access

## Prerequisites

### 1. Gmail API Credentials (Required for all providers)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Gmail API for your project
4. Create OAuth 2.0 credentials (Desktop application)
5. Download the credentials JSON file and save it as `credentials.json` in the project directory

### 2. LLM Provider (Choose one)

Select and configure one of the following providers:

- **Ollama**: Install from [ollama.ai](https://ollama.ai/) and pull a model
- **Anthropic**: Get API key from [console.anthropic.com](https://console.anthropic.com/)
- **OpenAI**: Get API key from [platform.openai.com](https://platform.openai.com/)
- **AWS Bedrock**: Requires AWS account with Bedrock access and IAM permissions

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
# Install core dependencies
pip install -r requirements.txt

# Install provider-specific dependencies (choose one or more)
pip install anthropic  # For Anthropic provider
pip install openai     # For OpenAI provider
pip install ollama     # For Ollama provider
# Bedrock dependencies (boto3) are included by default
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

5. Edit `.env` with your credentials:

```bash
# LLM Provider Selection
LLM_PROVIDER=bedrock  # Options: bedrock, anthropic, openai, ollama

# Provider-specific configuration (configure the one you're using)
# See "Choosing an LLM Provider" section above for details

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

See [Choosing an LLM Provider](#choosing-an-llm-provider) section for provider-specific configuration details.

6. Place your Gmail `credentials.json` file in the project directory

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
- Classify each email using AWS Bedrock
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

The application maintains a state file (`.email_state.json`) to track which emails have been processed. This prevents reprocessing the same emails after a restart.

**Local Development:**
- State file is stored in the project directory
- Configured via `STATE_FILE` in `.env` (default: `.email_state.json`)

**Docker Deployment:**
- State file is stored in `/app/data/.email_state.json`
- The `./data` directory is mounted as a volume to persist state across container restarts
- Without this volume, the agent would reprocess all unread emails after each restart

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
- **`bedrock_classifier.py`**: AWS Bedrock integration for AI classification
- **`config.py`**: Configuration and environment variables

### Workflow

1. Agent polls Gmail API for unread emails
2. For each email, extracts subject, sender, date, and body
3. Sends email content to AWS Bedrock with classification prompt
4. Bedrock returns applicable labels in JSON format
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
- Store AWS credentials securely (consider using AWS IAM roles instead of access keys)
- Use environment variables or AWS Secrets Manager for production deployments
- Regularly rotate AWS access keys
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
- `./data:/app/data` - State persistence directory (stores `.email_state.json`)

**Notes:**
- The `data` volume is **required** to maintain state across container restarts
- Without it, the agent would reprocess all unread emails every time the container restarts
- Edit `classifier_config.json` to customize labels; restart the container to apply changes

For detailed deployment instructions (AWS ECS, Kubernetes, systemd), see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## Troubleshooting

### "No module named 'google.auth'"

Install dependencies:
```bash
pip install -r requirements.txt
```

### "Error: credentials.json not found"

Download OAuth credentials from Google Cloud Console and save as `credentials.json`.

### "AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel"

Ensure your AWS IAM user/role has Bedrock permissions:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel"
            ],
            "Resource": "*"
        }
    ]
}
```

### "Model not found" or "Invalid model ID"

Verify the model ID in `.env` matches an available Bedrock model in your region. Check the [AWS Bedrock documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html) for available models.

## AWS Bedrock Pricing

Be aware of AWS Bedrock pricing for Claude models:
- Charged per input/output token
- Monitor usage in AWS Cost Explorer
- Consider setting up billing alerts

Typical costs for email classification:
- ~500-1000 tokens per email classification
- Claude 3.5 Sonnet: ~$0.003-0.015 per email

## License

This project is provided as-is for personal use.

## Contributing

Feel free to submit issues, feature requests, or pull requests.

## Support

For issues related to:
- Gmail API: [Google Gmail API Documentation](https://developers.google.com/gmail/api)
- AWS Bedrock: [AWS Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- This application: Open an issue in the repository
