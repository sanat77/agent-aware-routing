import pytest

from tracker.errors import TransientError
from tracker.retry import backoff_delays, retry_call


def test_gives_up_after_configured_attempts(case):
    calls = []

    def always_locked():
        calls.append(1)
        raise TransientError("database is locked")

    with pytest.raises(TransientError):
        retry_call(always_locked, attempts=case["attempts"], sleep=lambda s: None)
    assert len(calls) == case["attempts"]


def test_non_transient_errors_not_retried(case):
    calls = []

    def broken():
        calls.append(1)
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        retry_call(broken, attempts=case["attempts"], sleep=lambda s: None)
    assert len(calls) == 1


def test_backoff_doubles_each_attempt(case):
    expected = [case["base"] * (2 ** i) for i in range(case["attempts"] - 1)]
    assert backoff_delays(case["attempts"], case["base"]) == pytest.approx(expected)


def test_sleeps_follow_backoff_schedule(case):
    slept = []
    outcomes = [TransientError("locked")] * (case["attempts"] - 1) + ["ok"]

    def flaky():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert retry_call(flaky, attempts=case["attempts"], base_delay=case["base"], sleep=slept.append) == "ok"
    assert slept == pytest.approx([case["base"] * (2 ** i) for i in range(case["attempts"] - 1)])


def test_exhausted_retries_reraise_last_error(case):
    def always_locked():
        raise TransientError(case["message"])

    with pytest.raises(TransientError, match=case["message"]):
        retry_call(always_locked, attempts=case["attempts"], sleep=lambda s: None)
