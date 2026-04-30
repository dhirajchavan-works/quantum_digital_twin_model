# Multi-Zone Execution — Phase 3 Specification

**Module**: `physical_engine/multi_zone_executor.py`
**Date**: 2026-04-04
**Status**: SEALED

---

## Overview

The MultiZoneExecutor manages deterministic evolution of ALL ship zones as an atomic unit.

```
{zone_id: TransitionInput} -> sorted processing -> atomic update -> ZoneBatch record
```

---

## Ordering Guarantee

**All zones are processed in sorted `zone_id` order.**

```python
for zone_id in sorted(transitions.keys()):
    # process zone
```

This ensures:
- Same input set -> same processing order regardless of dict insertion order
- Deterministic hash chain across zones
- No platform-dependent ordering variation

---

## Atomicity Model

Each batch is **all-or-nothing**:

1. **Pre-validation**: All zone_ids are checked before any transitions
2. **Sequential processing**: Zones processed in sorted order through the transition engine
3. **Atomic state update**: `ShipStateVector.with_updated_zones()` replaces all at once
4. **Post-logging**: `ZoneBatch` record created with pre/post global hashes

If ANY zone transition fails, NONE are applied.

---

## ZoneBatch Record

| Field | Description |
|---|---|
| `batch_id` | Monotonically increasing (starts at 1) |
| `zone_transitions` | Tuple of (zone_id, TransitionInput) in sorted order |
| `pre_global_hash` | Global state hash before batch |
| `post_global_hash` | Global state hash after batch |
| `transition_records` | Tuple of per-zone TransitionRecords |
| `batch_hash` | SHA-256 of this batch |
| `prev_batch_hash` | Hash of the previous batch (chain) |

### Batch Chain

```
Genesis -> Batch_1 -> Batch_2 -> ... -> Batch_N
```

Each batch's `prev_batch_hash` points to the previous batch's `batch_hash`.
Genesis hash is `"0" * 64`.

---

## Cross-Zone Consistency

After every batch, the executor verifies:
```
latest_batch.post_global_hash == current_state.global_hash()
```

This ensures the state vector was not corrupted between batch creation and current state.

---

## Replay

```python
replay_exec = MultiZoneExecutor.replay(
    initial_state,
    [batch1_inputs, batch2_inputs, batch3_inputs]
)
assert replay_exec.global_hash == original_exec.global_hash
```

The `replay()` static method constructs a fresh executor and applies all inputs
in sequence, proving determinism.

---

## Invariants

| ID | Name | Type | Description |
|---|---|---|---|
| Z1 | Sorted Processing | GUARANTEE | Zones always processed in sorted zone_id order |
| Z2 | Batch Atomicity | GUARANTEE | All-or-nothing batch application |
| Z3 | Batch Chain | GUARANTEE | Each batch references the previous |
| Z4 | Cross-Zone Consistency | GUARANTEE | post_hash matches live state |
| Z5 | Replay Determinism | GUARANTEE | Same inputs -> same batches -> same hashes |
| Z6 | No Partial Update | PROHIBITION | Impossible to update subset without batch |
