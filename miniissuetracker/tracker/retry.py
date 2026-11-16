"""Retry helper with exponential backoff for transient failures."""
import time

from .errors import TransientError


def backoff_delays(attempts, base_delay, max_delay=2.0):
    """Delays slept between attempts: base, 2*base, 4*base ... capped at max_delay.

    `attempts` total tries means attempts - 1 sleeps.
    """
    return [min(base_delay * (2 ** i), max_delay) for i in range(max(attempts - 1, 0))]


def retry_call(func, attempts=3, base_delay=0.05, sleep=time.sleep, retry_on=(TransientError,)):
    """Call `func` up to `attempts` times, retrying only on `retry_on` exceptions.

    Non-retryable exceptions propagate immediately. After the final failed attempt
    the last exception is re-raised.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    delays = backoff_delays(attempts, base_delay)
    for attempt in range(attempts):
        try:
            return func()
        except retry_on:
            if attempt == attempts - 1:
                raise
            sleep(delays[attempt])
