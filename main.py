#!/usr/bin/env python3
"""
Gmail Email Classifier Agent

Reads unread Gmail messages and labels them with Jev, TypeSafe's
non-generative decision model, via OpenRouter.
"""

import argparse
import logging
import os
import sys

import config
from email_classifier_agent import EmailClassifierAgent
from jev_classifier import OPENROUTER_DECISIONS_URL


def setup_logging(level: str = "INFO"):
    """Configure logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    """Main entry point for the email classifier agent."""
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    parser = argparse.ArgumentParser(
        description="Gmail Email Classifier Agent (Jev via OpenRouter)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=config.LOG_LEVEL,
        help="Logging level",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Gmail Email Classifier Agent")
    logger.info("=" * 60)
    logger.info(f"Decisions URL: {OPENROUTER_DECISIONS_URL}")
    logger.info(f"Model: {config.JEV_MODEL}")
    logger.info(
        f"Thresholds: label >= {config.JEV_LABEL_THRESHOLD}, "
        f"fallback confidence >= {config.JEV_FALLBACK_CONFIDENCE}"
    )
    logger.info(f"Labels: {', '.join(config.LABELS)}")
    logger.info(f"Poll Interval: {config.POLL_INTERVAL_SECONDS}s")
    if config.DRY_RUN:
        logger.info("DRY RUN: labels are logged, Gmail and state are not modified")
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
