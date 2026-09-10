"""Untrusted Retry-After values must never create an infinite wait or overflow."""

import math

import pytest

from agent.retry_utils import jittered_backoff, parse_retry_after_seconds


@pytest.mark.parametrize("value", ["inf", "Infinity", "NaN", "1e9999", float("inf"), float("nan"), 10**400])
def test_non_finite_retry_after_is_rejected(value):
    assert parse_retry_after_seconds(value) is None


def test_backoff_remains_bounded_after_many_retries():
    delay = jittered_backoff(99999, base_delay=5.0, max_delay=120.0, jitter_ratio=0.5)
    assert math.isfinite(delay) and 0 <= delay <= 180.0
