"""Bounded in-process single-flight receipts, independent of context TTL.

Transport loss never cancels an operation. No external exactly-once guarantee
is implied. Running work is never evicted, even after its publication deadline.
"""

from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic


class OperationBusy(RuntimeError):
    pass


class OperationExpired(RuntimeError):
    pass


class OperationConflict(ValueError):
    pass


@dataclass
class Operation:
    fingerprint: tuple
    deadline: float
    recover_until: float
    event: Event = field(default_factory=Event)
    state: str = "running"
    result: object = None
    running: bool = True


class OperationStore:
    def __init__(self, *, capacity=6400, deadline=90.0, recovery=3600.0, clock=monotonic):
        if not 0 < deadline < recovery or capacity < 1:
            raise ValueError("operation deadline must precede recovery expiry")
        self.capacity, self.deadline, self.recovery, self.clock = capacity, deadline, recovery, clock
        self._items, self._lock = {}, Lock()

    def _prune(self):
        now = self.clock()
        for key, item in list(self._items.items()):
            if not item.running and item.recover_until <= now:
                del self._items[key]

    def lookup(self, key, fingerprint):
        with self._lock:
            self._prune()
            item = self._items.get(key)
            if item is not None and item.fingerprint != fingerprint:
                raise OperationConflict("operation content conflict")
            return item

    def reserve(self, key, fingerprint, *, deadline_seconds=None):
        with self._lock:
            self._prune()
            if key in self._items:
                item = self._items[key]
                if item.fingerprint != fingerprint:
                    raise OperationConflict("operation content conflict")
                return item, False
            if len(self._items) >= self.capacity:
                raise OperationBusy("receipt capacity full")
            now = self.clock()
            lifetime = self.deadline if deadline_seconds is None else min(self.deadline, deadline_seconds)
            item = Operation(fingerprint, now + lifetime, now + self.recovery)
            self._items[key] = item
            return item, True

    def publish(self, item, response, install):
        with self._lock:
            if self.clock() >= item.deadline or item.state != "running":
                item.state, item.running = "abandoned", False
                item.event.set()
                raise OperationExpired("operation deadline exceeded")
            # install must contain only prevalidated in-memory publication.
            install()
            item.result, item.state, item.running = response, "done", False
            item.event.set()

    def abort(self, item):
        with self._lock:
            if item.state != "done":
                item.state, item.running = "abandoned", False
            item.event.set()

    def wait(self, item, timeout=2.0):
        item.event.wait(max(0.0, min(timeout, item.deadline - self.clock())))
        with self._lock:
            if item.state == "done":
                return item.result.model_copy(deep=True, update={"replayed": True})
            if self.clock() >= item.deadline:
                item.state = "abandoned"  # worker still owns execution capacity
            if item.state == "abandoned":
                raise OperationExpired("operation no longer publishable")
            raise OperationBusy("operation still running")
