# Latency + Ordering Model — Phase 5 Specification

**Module**: `physical_engine/latency_ordering.py`
**Date**: 2026-04-04
**Status**: SEALED

---

## Core Policy: causal_id is the SOLE ordering authority

```
RULE: Events are processed in strict causal_id order.
RULE: Timestamps are advisory metadata — NEVER used for ordering.
RULE: Out-of-order arrivals are buffered until predecessors arrive.
```

---

## Timestamp vs causal_id Policy

| Aspect | causal_id | Timestamp |
|---|---|---|
| Authority | SOLE ordering authority | Advisory metadata |
| Assigned by | Hub (centralized) | Client/Node (local clock) |
| Monotonicity | Strictly monotonic | Not guaranteed across machines |
| Used for ordering | YES | NEVER |
| Used for | Processing order, replay | Latency measurement, observability |
| Cross-machine sync | Guaranteed by hub | Not guaranteed |

### Why timestamps cannot order

- Client clocks may be unsynchronized (minutes or hours apart)
- Network delays are non-deterministic
- Using timestamps would make replay non-deterministic
- causal_id assignment is centralized and gap-free

---

## Delayed Input Handling

### DelayedInputQueue Protocol

```
State: next_expected = 1, buffer = {}

Arrival: event(causal_id=3)
  -> buffer = {3: event}
  -> release = [] (waiting for 1)

Arrival: event(causal_id=1)
  -> next_expected becomes 2
  -> release = [(1, event)]

Arrival: event(causal_id=2)
  -> next_expected becomes 4
  -> release = [(2, event), (3, event)]  <- cascading release!
```

### Guarantees

1. Events are NEVER processed out of causal_id order
2. Buffered events are released in cascading order when predecessors arrive
3. Duplicate/old events (causal_id < next_expected) are silently ignored
4. Buffer size is bounded by the maximum gap in causal_id sequence

---

## Ordering Guarantees Under Network Delay

### Scenario: 3 clients, varying network latency

```
Time   Client_1    Client_2    Client_3    Hub (causal_id)
t0     submit(A)   -           -           -> A gets id=1
t1     -           submit(B)   -           -> B gets id=2
t2     -           -           submit(C)   -> C gets id=3

Node receives: C, A, B (arbitrary network order)

DelayedInputQueue processes:
  C arrives -> buffered (waiting for 1)
  A arrives -> processed (id=1), next_expected=2
  B arrives -> processed (id=2, 3 cascading), next_expected=4
```

**Result**: All nodes process events in order 1, 2, 3 regardless of arrival order.

---

## Latency Tracking

### EventTimestamps

| Stage | Timestamp | Collected by |
|---|---|---|
| `submitted_at` | Client submission | Client |
| `sequenced_at` | Hub sequencing | Hub |
| `executed_at` | Node execution | Node |
| `acked_at` | Ack reception | Hub |

### Computed Metrics

- `submission_to_sequence_ms` = sequenced_at - submitted_at
- `sequence_to_execution_ms` = executed_at - sequenced_at
- `end_to_end_ms` = acked_at - submitted_at

### Latency Statistics

- Average, min, max
- P50 (median), P99
- Rolling window (last 1000 events)

---

## Invariants

| ID | Name | Type | Description |
|---|---|---|---|
| L1 | Causal Authority | GUARANTEE | causal_id is the sole ordering authority |
| L2 | Timestamp Advisory | GUARANTEE | Timestamps never influence ordering |
| L3 | Buffered Ordering | GUARANTEE | Out-of-order events buffered until predecessors arrive |
| L4 | Cascading Release | GUARANTEE | Buffered successors released when predecessor arrives |
| L5 | No Reordering | PROHIBITION | Events are never reordered based on timestamp |
| L6 | Duplicate Ignore | GUARANTEE | Old/duplicate events silently ignored |
