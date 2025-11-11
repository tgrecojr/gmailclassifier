#!/usr/bin/env python3
"""
Gmail Email Classifier Agent

An agentic application using AWS Bedrock to automatically read and label Gmail emails
based on predefined categories.
"""

import sys,os
import logging
import argparse
from email_classifier_agent import EmailClassifierAgent
import config


def setup_logging(level: str = "INFO"):
    """Configure logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def main():
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    """Main entry point for the email classifier agent."""
    parser = argparse.ArgumentParser(
        description='Gmail Email Classifier Agent using AWS Bedrock'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default=config.LOG_LEVEL,
        help='Logging level'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Gmail Email Classifier Agent")
    logger.info("=" * 60)
    logger.info(f"AWS Region: {config.AWS_REGION}")
    logger.info(f"Bedrock Model: {config.BEDROCK_MODEL_ID}")
    logger.info(f"Labels: {', '.join(config.LABELS)}")
    logger.info(f"Poll Interval: {config.POLL_INTERVAL_SECONDS}s")
    logger.info("=" * 60)

    try:
        # Initialize agent
        agent = EmailClassifierAgent()

        # Run in continuous mode
        agent.run_continuous()

    except KeyboardInterrupt:
        logger.info("\nShutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
