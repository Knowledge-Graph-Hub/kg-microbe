"""Bounded, flushed progress for long merge serialization and release phases."""

import time
from contextlib import contextmanager


class MergeProgress:
    """Report counters, not record contents or an estimated completion time."""

    def __init__(self, phase, *, interval=100_000, unit="rows"):
        """Start one phase; callers choose an explicit bounded reporting interval."""
        self.phase = phase
        self.interval = interval
        self.unit = unit
        self.count = 0
        self.next_report = interval
        self.started = time.monotonic()
        self.report("start")

    def report(self, state):
        """Flush a small status record even when stdout is redirected to a log."""
        elapsed = time.monotonic() - self.started
        print(f"[merge-progress] {self.phase} {state} {self.unit}={self.count} elapsed={elapsed:.1f}s", flush=True)

    def advance(self, amount=1):
        """Emit at most one report per bounded batch, including large byte reads."""
        self.count += amount
        if self.count >= self.next_report:
            self.report("running")
            self.next_report = (self.count // self.interval + 1) * self.interval


@contextmanager
def merge_phase(phase, **kwargs):
    """Report terminal success or failure without changing exception/publication semantics."""
    progress = MergeProgress(phase, **kwargs)
    try:
        yield progress
    except BaseException:
        progress.report("failed")
        raise
    else:
        progress.report("complete")
