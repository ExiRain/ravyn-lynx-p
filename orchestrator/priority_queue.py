from __future__ import annotations

import heapq
import threading

from orchestrator.models import Signal


class SignalQueue:
    """Thread-safe priority queue that auto-expires stale signals."""

    def __init__(self):
        self._heap: list[tuple[int, int, Signal]] = []
        self._lock = threading.Lock()
        self._counter = 0   # tiebreaker — same priority dispatches FIFO

    def push(self, signal: Signal) -> None:
        with self._lock:
            heapq.heappush(
                self._heap,
                (signal.priority, self._counter, signal),
            )
            self._counter += 1

    def pop(self) -> Signal | None:
        """Pop highest-priority non-expired signal. Expired ones are silently discarded."""
        with self._lock:
            while self._heap:
                _, _, signal = heapq.heappop(self._heap)
                if not signal.is_expired():
                    return signal
            return None

    def peek(self) -> Signal | None:
        """Look at the next signal without removing it."""
        with self._lock:
            self._drain_expired()
            if self._heap:
                return self._heap[0][2]
            return None

    def pop_head_if(self, signal: Signal) -> Signal | None:
        """
        Pop the head only if it is still this exact signal.

        The dispatcher peeks, decides, and then acts, and a source can push
        between those two steps. Without the identity check a "drop the
        ambient chatter he is talking over" decision could pop whatever
        arrived in the meantime instead.
        """
        with self._lock:
            self._drain_expired()
            if self._heap and self._heap[0][2] is signal:
                return heapq.heappop(self._heap)[2]
            return None

    def is_empty(self) -> bool:
        with self._lock:
            self._drain_expired()
            return len(self._heap) == 0

    def size(self) -> int:
        with self._lock:
            self._drain_expired()
            return len(self._heap)

    def clear(self) -> None:
        with self._lock:
            self._heap.clear()
            self._counter = 0

    # internal — caller must hold lock
    def _drain_expired(self) -> None:
        while self._heap and self._heap[0][2].is_expired():
            heapq.heappop(self._heap)