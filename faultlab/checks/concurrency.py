import threading
import time

from tracker.sequence import TicketSequence


def test_concurrent_ticket_numbers_are_unique(case):
    sequence = TicketSequence(start=case["start"])
    original_store = sequence._store

    def slow_store(value):
        time.sleep(0.02)  # widen the race window deterministically
        original_store(value)

    sequence._store = slow_store
    results = []
    gate = threading.Barrier(case["threads"])

    def worker():
        gate.wait(timeout=5)
        results.append(sequence.next())

    threads = [threading.Thread(target=worker) for _ in range(case["threads"])]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(results) == list(range(case["start"], case["start"] + case["threads"]))
    assert sequence.peek() == case["start"] + case["threads"]
