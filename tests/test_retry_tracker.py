"""
Unit tests for retry_tracker.RetryTracker (pure logic, no I/O).
"""

from datetime import datetime, timedelta, timezone

import pytest

from retry_tracker import REASON_MAX_CHARS, RetryTracker

NOW = datetime(2026, 8, 23, 18, 11, 40, tzinfo=timezone.utc)
BASE = timedelta(minutes=30)


@pytest.mark.unit
class TestBackoffSchedule:
    def test_delay_doubles_from_base(self):
        tracker = RetryTracker(max_attempts=5, base_delay=BASE)

        assert tracker.delay_after(1) == timedelta(minutes=30)
        assert tracker.delay_after(2) == timedelta(hours=1)
        assert tracker.delay_after(3) == timedelta(hours=2)
        assert tracker.delay_after(4) == timedelta(hours=4)

    def test_delay_for_zero_attempts_is_base(self):
        tracker = RetryTracker(max_attempts=5, base_delay=BASE)

        assert tracker.delay_after(0) == BASE


@pytest.mark.unit
class TestRecordRejection:
    def test_first_rejection_schedules_retry(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)

        gave_up = tracker.record_rejection("m1", "prompt injection detected", NOW)

        assert gave_up is False
        entry = tracker.entries["m1"]
        assert entry["attempts"] == 1
        assert entry["last_attempt"] == NOW.isoformat()
        assert entry["next_attempt"] == (NOW + BASE).isoformat()
        assert entry["reason"] == "prompt injection detected"

    def test_subsequent_rejections_back_off(self):
        tracker = RetryTracker(max_attempts=5, base_delay=BASE)
        tracker.record_rejection("m1", "r", NOW)
        second = NOW + timedelta(hours=1)

        gave_up = tracker.record_rejection("m1", "r", second)

        assert gave_up is False
        assert tracker.attempts("m1") == 2
        assert (
            tracker.entries["m1"]["next_attempt"]
            == (second + timedelta(hours=1)).isoformat()
        )

    def test_cap_reached_gives_up_and_forgets_entry(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)
        assert tracker.record_rejection("m1", "r", NOW) is False
        assert tracker.record_rejection("m1", "r", NOW) is False

        assert tracker.record_rejection("m1", "r", NOW) is True
        assert "m1" not in tracker.entries
        assert tracker.attempts("m1") == 0

    def test_max_attempts_one_never_retries(self):
        tracker = RetryTracker(max_attempts=1, base_delay=BASE)

        assert tracker.record_rejection("m1", "r", NOW) is True
        assert tracker.entries == {}

    def test_max_attempts_below_one_is_clamped(self):
        assert RetryTracker(max_attempts=0, base_delay=BASE).max_attempts == 1
        assert RetryTracker(max_attempts=-5, base_delay=BASE).max_attempts == 1

    def test_reason_is_truncated(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)

        tracker.record_rejection("m1", "x" * (REASON_MAX_CHARS + 50), NOW)

        assert len(tracker.entries["m1"]["reason"]) == REASON_MAX_CHARS

    def test_entries_are_independent_per_email(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)
        tracker.record_rejection("a", "r", NOW)
        tracker.record_rejection("a", "r", NOW)
        tracker.record_rejection("b", "r", NOW)

        assert tracker.attempts("a") == 2
        assert tracker.attempts("b") == 1


@pytest.mark.unit
class TestIsDeferred:
    def test_unknown_email_is_not_deferred(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)

        assert tracker.is_deferred("nope", NOW) is False

    def test_deferred_until_next_attempt(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)
        tracker.record_rejection("m1", "r", NOW)

        assert tracker.is_deferred("m1", NOW) is True
        assert tracker.is_deferred("m1", NOW + BASE - timedelta(seconds=1)) is True
        assert tracker.is_deferred("m1", NOW + BASE) is False
        assert tracker.is_deferred("m1", NOW + timedelta(days=1)) is False

    def test_unreadable_entry_is_due(self):
        tracker = RetryTracker(
            max_attempts=3, base_delay=BASE, entries={"m1": {"attempts": "?"}}
        )

        assert tracker.is_deferred("m1", NOW) is False

    def test_clear_removes_deferral(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)
        tracker.record_rejection("m1", "r", NOW)

        tracker.clear("m1")

        assert tracker.is_deferred("m1", NOW) is False
        assert tracker.entries == {}

    def test_clear_unknown_is_noop(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)

        tracker.clear("nope")

        assert tracker.entries == {}


@pytest.mark.unit
class TestPersistenceAndPrune:
    def test_round_trip_through_dict(self):
        tracker = RetryTracker(max_attempts=3, base_delay=BASE)
        tracker.record_rejection("m1", "r", NOW)

        restored = RetryTracker(
            max_attempts=3, base_delay=BASE, entries=tracker.to_dict()
        )

        assert restored.attempts("m1") == 1
        assert restored.is_deferred("m1", NOW) is True
        # to_dict is a copy, not the live dict
        tracker.to_dict().clear()
        assert tracker.attempts("m1") == 1

    def test_prune_drops_old_and_unreadable_entries(self):
        old = NOW - timedelta(days=40)
        tracker = RetryTracker(max_attempts=5, base_delay=BASE)
        tracker.record_rejection("old", "r", old)
        tracker.record_rejection("recent", "r", NOW)
        tracker.entries["broken"] = {"attempts": 1}

        removed = tracker.prune(NOW - timedelta(days=30))

        assert removed == 2
        assert set(tracker.entries) == {"recent"}

    def test_prune_nothing_to_do(self):
        tracker = RetryTracker(max_attempts=5, base_delay=BASE)
        tracker.record_rejection("recent", "r", NOW)

        assert tracker.prune(NOW - timedelta(days=30)) == 0
