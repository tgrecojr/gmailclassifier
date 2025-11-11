# Deployment Guide for Gmail Email Classifier

This guide covers deploying the Gmail Email Classifier in headless environments (Docker, servers, cloud).

## Table of Contents

- [Headless OAuth Setup](#headless-oauth-setup)
- [Docker Deployment](#docker-deployment)
- [AWS ECS Deployment](#aws-ecs-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Systemd Service (Linux)](#systemd-service-linux)

---

## Headless OAuth Setup

### Step 1: Configure Google Cloud Console

Since headless environments can't open a browser, you need to set up OAuth for console-based authorization:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **APIs & Services > Credentials**
3. Edit your OAuth 2.0 Client ID
4. Under **Authorized redirect URIs**, add:
   ```
   http://localhost:1
   ```
   Or use `urn:ietf:wg:oauth:2.0:oob` for out-of-band (deprecated but may still work)

### Step 2: Generate Token Locally (Method 1 - Recommended)

The easiest approach is to generate the token on your local machine:

```bash
# On your local machine with a browser
python main.py

# After authentication completes, stop the agent (Ctrl+C)
# This creates token.json - copy it to your server
scp token.json user@server:/path/to/gmailclassifier/
```

### Step 3: Generate Token in Headless Mode (Method 2)

If you need to generate the token directly on the server:

1. Set headless mode in `.env`:
   ```bash
   GMAIL_HEADLESS_MODE=true
   ```

2. Run the application:
   ```bash
   python main.py
   ```

3. The app will print a URL:
   ```
   Please visit this URL to authorize the application:
   https://accounts.google.com/o/oauth2/auth?...
   ```

4. Copy this URL and open it in any browser (on any device)

5. After authorizing, Google will redirect you to a URL like:
   ```
   http://localhost:1/?code=4/0AY0e-g7...&scope=https://...
   ```

6. Copy the **entire URL** and paste it back into the terminal

7. The app will save `token.json` for future use

---

## Docker Deployment

### Build and Run with Docker

1. **Generate token first** (see Headless OAuth Setup above)

2. **Create `.env` file** with your configuration:
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
   docker-compose up -d
   ```

2. **View logs**:
   ```bash
   docker-compose logs -f
   ```

3. **Stop the service**:
   ```bash
   docker-compose down
   ```

**Important:** The `./data` volume is required to persist the email state file (`.email_state.json`) across container restarts. Without it, the agent would reprocess all unread emails after each restart.

---

## AWS ECS Deployment

### Prerequisites

- AWS CLI configured
- ECR repository created
- ECS cluster created

### Step 1: Push Image to ECR

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# Tag image
docker tag gmail-classifier:latest \
  YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/gmail-classifier:latest

# Push image
docker push YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/gmail-classifier:latest
```

### Step 2: Store Credentials in AWS Secrets Manager

```bash
# Store Gmail credentials
aws secretsmanager create-secret \
  --name gmail-classifier/credentials \
  --secret-string file://credentials.json

# Store Gmail token
aws secretsmanager create-secret \
  --name gmail-classifier/token \
  --secret-string file://token.json

# Store classifier configuration
aws secretsmanager create-secret \
  --name gmail-classifier/config \
  --secret-string file://classifier_config.json

# Store AWS credentials
aws secretsmanager create-secret \
  --name gmail-classifier/aws-keys \
  --secret-string '{"AWS_ACCESS_KEY_ID":"xxx","AWS_SECRET_ACCESS_KEY":"xxx"}'
```

### Step 3: Create ECS Task Definition

Create `ecs-task-definition.json`:

```json
{
  "family": "gmail-classifier",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "containerDefinitions": [
    {
      "name": "gmail-classifier",
      "image": "YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/gmail-classifier:latest",
      "essential": true,
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/gmail-classifier",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "mountPoints": [
        {
          "sourceVolume": "data",
          "containerPath": "/app/data",
          "readOnly": false
        }
      ],
      "environment": [
        {"name": "AWS_REGION", "value": "us-east-1"},
        {"name": "GMAIL_HEADLESS_MODE", "value": "true"},
        {"name": "POLL_INTERVAL_SECONDS", "value": "60"}
      ],
      "secrets": [
        {
          "name": "AWS_ACCESS_KEY_ID",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:gmail-classifier/aws-keys:AWS_ACCESS_KEY_ID::"
        },
        {
          "name": "AWS_SECRET_ACCESS_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:gmail-classifier/aws-keys:AWS_SECRET_ACCESS_KEY::"
        }
      ]
    }
  ],
  "volumes": [
    {
      "name": "data",
      "host": {}
    }
  ]
}
```

**Note:** For ECS, you'll need to handle credentials/config files differently. Options:
1. **Build into image** (not recommended for credentials): Uncomment the COPY lines in Dockerfile
2. **Use S3 + init script**: Download files from S3 on container start
3. **Use Secrets Manager with file mounting** (advanced): Requires additional ECS configuration

For the classifier config specifically, you can:
- Store it in Parameter Store and write to file on startup
- Or simply build `classifier_config.json` into the Docker image (safe to do, unlike credentials)

### Alternative: Build config into image

Since `classifier_config.json` contains no secrets, you can safely build it into your Docker image:

```dockerfile
# In Dockerfile, add:
COPY classifier_config.json /app/classifier_config.json
```

Then rebuild and push your image. This is the simplest approach for the config file.

**For persistent state storage:** The task definition above uses ephemeral host storage for `/app/data`. For production, consider using EFS:

```json
"volumes": [
  {
    "name": "data",
    "efsVolumeConfiguration": {
      "fileSystemId": "fs-xxxxxxxx",
      "transitEncryption": "ENABLED"
    }
  }
]
```

### Step 4: Create ECS Service

```bash
aws ecs create-service \
  --cluster your-cluster \
  --service-name gmail-classifier \
  --task-definition gmail-classifier \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx]}"
```

---

## Kubernetes Deployment

### Step 1: Create Secrets

```bash
# Create namespace
kubectl create namespace gmail-classifier

# Create secret for credentials and config
kubectl create secret generic gmail-credentials \
  --from-file=credentials.json \
  --from-file=token.json \
  --from-file=classifier_config.json \
  -n gmail-classifier

# Create secret for environment variables
kubectl create secret generic gmail-env \
  --from-literal=AWS_ACCESS_KEY_ID=your_key \
  --from-literal=AWS_SECRET_ACCESS_KEY=your_secret \
  -n gmail-classifier
```

### Step 2: Create Deployment

Create `k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gmail-classifier
  namespace: gmail-classifier
spec:
  replicas: 1
  selector:
    matchLabels:
      app: gmail-classifier
  template:
    metadata:
      labels:
        app: gmail-classifier
    spec:
      containers:
      - name: gmail-classifier
        image: YOUR_REGISTRY/gmail-classifier:latest
        env:
        - name: AWS_REGION
          value: "us-east-1"
        - name: GMAIL_HEADLESS_MODE
          value: "true"
        - name: POLL_INTERVAL_SECONDS
          value: "60"
        - name: AWS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: gmail-env
              key: AWS_ACCESS_KEY_ID
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: gmail-env
              key: AWS_SECRET_ACCESS_KEY
        volumeMounts:
        - name: gmail-credentials
          mountPath: /app/credentials.json
          subPath: credentials.json
          readOnly: true
        - name: gmail-credentials
          mountPath: /app/token.json
          subPath: token.json
          readOnly: true
        - name: gmail-credentials
          mountPath: /app/classifier_config.json
          subPath: classifier_config.json
          readOnly: true
        - name: data
          mountPath: /app/data
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: gmail-credentials
        secret:
          secretName: gmail-credentials
      - name: data
        emptyDir: {}
        # Note: For production, use a PersistentVolumeClaim to persist state across pod restarts
        # persistentVolumeClaim:
        #   claimName: gmail-classifier-data
```

### Step 3: Deploy

```bash
kubectl apply -f k8s-deployment.yaml
kubectl logs -f deployment/gmail-classifier -n gmail-classifier
```

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
Environment="PATH=/home/your-user/gmailclassifier/venv/bin"
ExecStart=/home/your-user/gmailclassifier/venv/bin/python main.py
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
   - AWS Secrets Manager, Kubernetes Secrets, or environment variables
   - Rotate credentials regularly

3. **Limit permissions**
   - Use minimum required Gmail API scopes
   - Use IAM roles instead of access keys when possible

4. **Monitor costs**
   - Set up AWS billing alerts for Bedrock usage
   - Monitor API usage in Google Cloud Console

5. **Use read-only mounts**
   - Mount credentials as read-only in containers
   - Separate token storage from application code

6. **Network security**
   - Run containers in private subnets
   - Use security groups to restrict outbound traffic
   - Enable VPC endpoints for AWS services

---

## Troubleshooting

### Token expires or becomes invalid

Regenerate the token using headless mode or locally, then copy it to your deployment.

### "Resource exhausted" errors from Bedrock

Implement rate limiting or increase poll interval:
```bash
POLL_INTERVAL_SECONDS=300  # 5 minutes
```

### Container restarts frequently

Check logs:
```bash
docker logs gmail-classifier
# or
kubectl logs deployment/gmail-classifier
```

Common issues:
- Missing credentials
- Invalid AWS credentials
- Expired Gmail token
- Bedrock model not available in region

---

## Monitoring

### CloudWatch Logs (AWS)

Create log group:
```bash
aws logs create-log-group --log-group-name /ecs/gmail-classifier
```

### Prometheus Metrics (Advanced)

Consider adding metrics export:
- Emails processed
- Classification latency
- API errors
- Bedrock costs

---

## Scaling Considerations

- **Don't run multiple instances** - Gmail API has rate limits and multiple instances might process the same emails
- **Use locking** - If you must scale, implement distributed locking (Redis, DynamoDB)
- **Batch processing** - Increase `MAX_EMAILS_PER_POLL` instead of running multiple instances
