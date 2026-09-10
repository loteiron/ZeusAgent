"""Malformed rate-limit durations must not strand durable replies forever."""
import math
import sqlite3

import pytest

from gateway import delivery_ledger as dl


@pytest.mark.parametrize("value", ["inf", "-inf", "NaN", "1e309", "-1e309"])
def test_nonfinite_flood_duration_has_a_finite_default_deadline(value):
    error = dl.FLOOD_ERROR_PREFIX + value
    wait = dl.flood_wait_seconds(error)
    assert wait == dl.FLOOD_RETRY_DEFAULT_SECONDS
    assert dl.flood_not_before(1000.0, error) == 1000.0 + wait
    delay = dl.flood_retry_delay(value)
    assert math.isfinite(delay)
    assert delay == dl.flood_retry_delay(dl.FLOOD_RETRY_DEFAULT_SECONDS)


def test_overflowing_rate_limit_can_be_recovered_from_real_ledger():
    dl.record_obligation(
        obligation_id="overflow", session_key="s", platform="telegram",
        chat_id="c", thread_id=None, content="A durable reply",
    )
    dl.mark_failed("overflow", "flood_control:1e309")
    with sqlite3.connect(dl._db_path()) as conn:
        stamp = conn.execute(
            "SELECT updated_at FROM delivery_obligations WHERE obligation_id='overflow'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE delivery_obligations SET owner_pid=NULL, owner_started_at=NULL "
            "WHERE obligation_id='overflow'"
        )
    rows = dl.sweep_recoverable(now=stamp + dl.FLOOD_RETRY_DEFAULT_SECONDS + 1)
    assert len(rows) == 1
    assert not rows[0].get("adopted"), "an invalid duration must not park the reply indefinitely"
    assert rows[0]["content"] == "A durable reply"
    assert rows[0]["attempts"] == 1
    assert rows[0]["needs_marker"] is True
