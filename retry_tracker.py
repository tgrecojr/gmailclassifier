"""
Bounded, backed-off retry bookkeeping for emails the LLM endpoint rejected.

When a gateway guardrail answers HTTP 400, the email is neither classified
nor permanently skipped: it is parked here and re-offered to the classifier
on a doubling schedule (base, 2x, 4x, ...) until either it succeeds or the
attempt cap is reached. The cap is what keeps a persistently-blocked email
from being scanned forever.

Persisted inside the agent's state file as:

    "pending_retries": {
        "<email_id>": {
            "attempts": 2,
            "last_attempt": "<iso timestamp>",
            "next_attempt": "<iso timestamp>",
            "reason": "<last rejection message, truncated>"
        }
    }
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

REASON_MAX_CHARS = 300


class RetryTracker:
    """Tracks rejected emails and decides when (and whether) to try again."""

    def __init__(
        self,
        max_attempts: int,
        base_delay: timedelta,
        entries: Optional[Dict[str, dict]] = None,
    ):
        # At least one attempt always happens; max_attempts=1 means "never retry".
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay = base_delay
        self.entries: Dict[str, dict] = dict(entries or {})

    # ----- persistence -----------------------------------------------------

    def to_dict(self) -> Dict[str, dict]:
        return dict(self.entries)

    # ----- queries ---------------------------------------------------------

    def is_deferred(self, email_id: str, now: datetime) -> bool:
        """True if the email was rejected before and its next attempt is not due."""
        entry = self.entries.get(email_id)
        if not entry:
            return False
        try:
            return now < datetime.fromisoformat(entry["next_attempt"])
        except KeyError, TypeError, ValueError:
            # Unreadable entry: treat as due so it gets rewritten on the next outcome.
            return False

    def attempts(self, email_id: str) -> int:
        return int(self.entries.get(email_id, {}).get("attempts", 0))

    def delay_after(self, attempts: int) -> timedelta:
        """Backoff following the Nth failed attempt (1-based): base * 2**(N-1)."""
        return self.base_delay * (2 ** max(0, attempts - 1))

    # ----- mutations -------------------------------------------------------

    def record_rejection(self, email_id: str, reason: str, now: datetime) -> bool:
        """
        Record one more failed attempt.

        Returns:
            True if the cap is reached and the caller should give up on the
            email (the entry is removed); False if a later retry is scheduled.
        """
        attempts = self.attempts(email_id) + 1
        if attempts >= self.max_attempts:
            self.entries.pop(email_id, None)
            return True

        self.entries[email_id] = {
            "attempts": attempts,
            "last_attempt": now.isoformat(),
            "next_attempt": (now + self.delay_after(attempts)).isoformat(),
            "reason": reason[:REASON_MAX_CHARS],
        }
        return False

    def clear(self, email_id: str) -> None:
        """Forget an email (classified successfully, or otherwise resolved)."""
        self.entries.pop(email_id, None)

    def prune(self, cutoff: datetime) -> int:
        """Drop entries whose last attempt is older than cutoff. Returns count removed."""
        stale = []
        for email_id, entry in self.entries.items():
            try:
                if datetime.fromisoformat(entry["last_attempt"]) < cutoff:
                    stale.append(email_id)
            except KeyError, TypeError, ValueError:
                stale.append(email_id)
        for email_id in stale:
            del self.entries[email_id]
        if stale:
            logger.info(f"Pruned {len(stale)} stale pending retry entr(y/ies)")
        return len(stale)
