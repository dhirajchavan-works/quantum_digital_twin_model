"""
latency_ordering.py
====================
Phase 5 — Latency + Ordering Layer

Defines:
    - CausalOrderingPolicy: causal_id is the SOLE ordering authority
    - TimestampPolicy: timestamps are advisory metadata only
    - DelayedInputQueue: buffers inputs awaiting causal predecessors
    - LatencyTracker: measures per-input latency from submission to ack

Guarantees:
    - Ordering under network delay: causal_id always wins
    - Delayed inputs are buffered and released in strict causal order
    - Timestamp is NEVER used for ordering — only for observability
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Ordering Policy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CausalOrderingPolicy:
    """
    Formal policy declaration:
        causal_id (hub-assigned, monotonically increasing)
        is the SOLE authority for event ordering.

    Rules:
        1. Events are processed in causal_id order
        2. If event N+1 arrives before event N, it is BUFFERED
        3. When event N arrives, both N and N+1 are processed in order
        4. No event is ever reordered based on timestamp
        5. Timestamps exist for observability ONLY

    This class is a policy declaration — it holds no state.
    Enforcement is done by DelayedInputQueue.
    """
    policy_name: str = "CAUSAL_ID_AUTHORITY"
    description: str = (
        "causal_id is the sole ordering authority. "
        "Timestamps are advisory metadata. "
        "Events are processed in strict causal_id order. "
        "Out-of-order arrivals are buffered until predecessors arrive."
    )

    def validate_ordering(self, events: List[int]) -> Tuple[bool, Optional[str]]:
        """
        Validate that a list of causal_ids is in strict monotonic order.

        Args:
            events: list of causal_ids in processing order

        Returns:
            (is_valid, error_message)
        """
        for i in range(1, len(events)):
            if events[i] <= events[i - 1]:
                return False, (
                    f"Ordering violation at index {i}: "
                    f"causal_id {events[i]} ≤ {events[i-1]}"
                )
        return True, None


@dataclass(frozen=True)
class TimestampPolicy:
    """
    Formal policy for timestamp handling.

    Rules:
        1. Timestamps are recorded at proposal submission (client-side)
        2. Timestamps are recorded at sequencing (hub-side)
        3. Timestamps are recorded at execution (node-side)
        4. Timestamps are NEVER compared for ordering decisions
        5. Timestamps feed into LatencyTracker for observability only

    This ensures determinism across machines with unsynchronized clocks.
    """
    policy_name: str = "TIMESTAMP_ADVISORY"
    description: str = (
        "Timestamps are advisory metadata for observability. "
        "They are never used for ordering, conflict resolution, or state decisions. "
        "All ordering is determined by causal_id."
    )


# ---------------------------------------------------------------------------
# Timestamp Record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventTimestamps:
    """
    Advisory timestamps captured at each stage of an event's lifecycle.
    Used exclusively for latency measurement — never for ordering.
    """
    causal_id: int
    proposal_id: str
    submitted_at: float              # Client submission time (monotonic)
    sequenced_at: float              # Hub sequencing time (monotonic)
    executed_at: Optional[float]     # Node execution time (monotonic)
    acked_at: Optional[float]        # Ack reception time (monotonic)

    @property
    def submission_to_sequence_ms(self) -> Optional[float]:
        """Latency from client submission to hub sequencing."""
        return (self.sequenced_at - self.submitted_at) * 1000.0

    @property
    def sequence_to_execution_ms(self) -> Optional[float]:
        """Latency from hub sequencing to node execution."""
        if self.executed_at is None:
            return None
        return (self.executed_at - self.sequenced_at) * 1000.0

    @property
    def end_to_end_ms(self) -> Optional[float]:
        """Total latency from submission to ack."""
        if self.acked_at is None:
            return None
        return (self.acked_at - self.submitted_at) * 1000.0


# ---------------------------------------------------------------------------
# Delayed Input Queue
# ---------------------------------------------------------------------------

class DelayedInputQueue:
    """
    Buffers inputs that arrive before their causal predecessor.
    Releases them in strict causal_id order when predecessors arrive.

    This implements the core of the CausalOrderingPolicy.

    Usage:
        queue = DelayedInputQueue()
        ready = queue.enqueue(event)   # returns list of events ready to process
        # process ready events in order
    """

    def __init__(self, start_causal_id: int = 1):
        self._next_expected: int = start_causal_id
        self._buffer: Dict[int, object] = {}   # causal_id → event
        self._processed: List[int] = []         # ordered list of processed causal_ids
        self._total_buffered: int = 0           # total events that were buffered
        self._total_immediate: int = 0          # total events processed immediately

    def enqueue(self, causal_id: int, event: object) -> List[Tuple[int, object]]:
        """
        Enqueue an event. Returns a list of (causal_id, event) pairs
        that are now ready to process, in strict causal order.

        If the event is the next expected, it (and any buffered successors)
        are returned immediately. Otherwise, it is buffered.
        """
        if causal_id < self._next_expected:
            # Duplicate or old event — ignore
            return []

        self._buffer[causal_id] = event

        # Try to drain the buffer in order
        ready: List[Tuple[int, object]] = []
        while self._next_expected in self._buffer:
            evt = self._buffer.pop(self._next_expected)
            ready.append((self._next_expected, evt))
            self._processed.append(self._next_expected)
            self._next_expected += 1

        # Track statistics
        if len(ready) > 0 and causal_id == ready[0][0]:
            self._total_immediate += 1
            self._total_buffered += len(ready) - 1  # released from buffer
        else:
            self._total_buffered += 1
            # Not ready yet — it was added to buffer

        return ready

    @property
    def next_expected(self) -> int:
        """Next expected causal_id."""
        return self._next_expected

    @property
    def buffered_count(self) -> int:
        """Number of events currently buffered."""
        return len(self._buffer)

    @property
    def buffered_ids(self) -> List[int]:
        """Causal IDs currently buffered."""
        return sorted(self._buffer.keys())

    @property
    def processed_ids(self) -> List[int]:
        """All causal IDs processed so far, in order."""
        return list(self._processed)

    @property
    def stats(self) -> dict:
        """Queue statistics."""
        return {
            "total_processed": len(self._processed),
            "total_buffered_events": self._total_buffered,
            "total_immediate_events": self._total_immediate,
            "currently_buffered": self.buffered_count,
            "next_expected": self._next_expected,
        }


# ---------------------------------------------------------------------------
# Latency Tracker
# ---------------------------------------------------------------------------

class LatencyTracker:
    """
    Tracks per-event timing data for observability.

    Does NOT influence ordering — pure observation only.
    """

    def __init__(self):
        self._timestamps: Dict[int, EventTimestamps] = {}  # keyed by causal_id
        self._latencies_ms: List[float] = []                # end-to-end latencies

    def record_submission(self, causal_id: int, proposal_id: str,
                          submitted_at: float):
        """Record when a proposal was submitted by a client."""
        self._timestamps[causal_id] = EventTimestamps(
            causal_id=causal_id,
            proposal_id=proposal_id,
            submitted_at=submitted_at,
            sequenced_at=0.0,
            executed_at=None,
            acked_at=None,
        )

    def record_sequencing(self, causal_id: int, sequenced_at: float):
        """Record when the hub sequenced the event."""
        if causal_id in self._timestamps:
            old = self._timestamps[causal_id]
            self._timestamps[causal_id] = EventTimestamps(
                causal_id=old.causal_id,
                proposal_id=old.proposal_id,
                submitted_at=old.submitted_at,
                sequenced_at=sequenced_at,
                executed_at=old.executed_at,
                acked_at=old.acked_at,
            )

    def record_execution(self, causal_id: int, executed_at: float):
        """Record when a node executed the event."""
        if causal_id in self._timestamps:
            old = self._timestamps[causal_id]
            self._timestamps[causal_id] = EventTimestamps(
                causal_id=old.causal_id,
                proposal_id=old.proposal_id,
                submitted_at=old.submitted_at,
                sequenced_at=old.sequenced_at,
                executed_at=executed_at,
                acked_at=old.acked_at,
            )

    def record_ack(self, causal_id: int, acked_at: float):
        """Record when the ack was received."""
        if causal_id in self._timestamps:
            old = self._timestamps[causal_id]
            ts = EventTimestamps(
                causal_id=old.causal_id,
                proposal_id=old.proposal_id,
                submitted_at=old.submitted_at,
                sequenced_at=old.sequenced_at,
                executed_at=old.executed_at,
                acked_at=acked_at,
            )
            self._timestamps[causal_id] = ts
            if ts.end_to_end_ms is not None:
                self._latencies_ms.append(ts.end_to_end_ms)

    def get_timestamps(self, causal_id: int) -> Optional[EventTimestamps]:
        """Get timestamps for a specific event."""
        return self._timestamps.get(causal_id)

    def get_latency_stats(self) -> dict:
        """Compute latency statistics."""
        if not self._latencies_ms:
            return {
                "count": 0,
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p50_ms": 0.0,
                "p99_ms": 0.0,
            }

        sorted_lat = sorted(self._latencies_ms)
        n = len(sorted_lat)
        return {
            "count": n,
            "avg_ms": sum(sorted_lat) / n,
            "min_ms": sorted_lat[0],
            "max_ms": sorted_lat[-1],
            "p50_ms": sorted_lat[n // 2],
            "p99_ms": sorted_lat[min(int(n * 0.99), n - 1)],
        }


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== latency_ordering.py — Self Test ===\n")

    # Test CausalOrderingPolicy
    policy = CausalOrderingPolicy()
    print(f"  Policy: {policy.policy_name}")
    valid, err = policy.validate_ordering([1, 2, 3, 4, 5])
    assert valid, f"Should be valid: {err}"
    valid2, err2 = policy.validate_ordering([1, 2, 4, 3, 5])
    assert not valid2, "Should detect out-of-order"
    print(f"  Ordering validation: PASS ✓")

    # Test DelayedInputQueue — out-of-order arrival
    queue = DelayedInputQueue(start_causal_id=1)

    # Event 3 arrives first
    ready = queue.enqueue(3, {"type": "event_3"})
    assert len(ready) == 0, "Event 3 should be buffered"
    print(f"  Event 3 buffered (waiting for 1): OK ✓")

    # Event 1 arrives
    ready = queue.enqueue(1, {"type": "event_1"})
    assert len(ready) == 1 and ready[0][0] == 1, "Event 1 should be released"
    print(f"  Event 1 released: OK ✓")

    # Event 2 arrives — should release 2 AND 3
    ready = queue.enqueue(2, {"type": "event_2"})
    assert len(ready) == 2, f"Events 2 and 3 should be released, got {len(ready)}"
    assert ready[0][0] == 2 and ready[1][0] == 3
    print(f"  Events 2+3 released in order: OK ✓")
    print(f"  Queue stats: {queue.stats}")

    # Test LatencyTracker
    tracker = LatencyTracker()
    t0 = time.monotonic()
    tracker.record_submission(1, "p1", t0)
    tracker.record_sequencing(1, t0 + 0.001)
    tracker.record_execution(1, t0 + 0.002)
    tracker.record_ack(1, t0 + 0.003)

    ts = tracker.get_timestamps(1)
    assert ts is not None
    assert ts.end_to_end_ms is not None and ts.end_to_end_ms > 0
    print(f"  Latency tracking: end_to_end={ts.end_to_end_ms:.3f}ms ✓")

    stats = tracker.get_latency_stats()
    print(f"  Latency stats: {stats}")

    print("\n✓ latency_ordering.py — All self-tests passed.")
