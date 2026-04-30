# Deterministic Transition Engine — Phase 2 Specification

**Module**: `physical_engine/transition_engine.py`
**Date**: 2026-04-04
**Status**: SEALED

---

## Overview

The transition engine converts:
```
input -> transition -> state mutation
```

Every transition is:
- A **pure function**: no side effects, no randomness, no I/O
- **Recorded**: every application produces a frozen `TransitionRecord`
- **Chained**: each record references the previous record's hash
- **Replayable**: same inputs in same order -> identical final state

---

## TransitionInput Schema

| Field | Type | Bounds | Description |
|---|---|---|---|
| `zone_id` | `str` | non-empty | Target zone |
| `corrosion_rate` | `float` | >= 0 | mm/time_unit |
| `coating_degradation_rate` | `float` | >= 0 | mm/time_unit |
| `barnacle_growth_rate` | `float` | >= 0 | units*m^-2/time_unit |
| `roughness_rate` | `float` | any | index/time_unit (negative = polishing) |
| `dt` | `float` | > 0 | Time delta |

---

## Transition Functions

### Standard Physical Transition

```
corrosion_depth_new  = corrosion_depth + corrosion_rate * dt
coating_thickness_new = max(0, coating_thickness - coating_degradation_rate * dt)
barnacle_density_new = max(0, barnacle_density + barnacle_growth_rate * dt)
roughness_new        = max(0, roughness + roughness_rate * dt)
risk_score_new       = recomputed from new values
```

### Accelerated Corrosion Transition

```
coating_factor = 1 + 1/max(coating_thickness, 1e-6)
corrosion_depth_new = corrosion_depth + corrosion_rate * dt * coating_factor
(other fields same as standard)
```

---

## TransitionRecord (Hash Chain)

| Field | Description |
|---|---|
| `sequence_id` | Monotonically increasing (starts at 1) |
| `zone_id` | Which zone was transitioned |
| `input_hash` | SHA-256 of the TransitionInput |
| `pre_state_hash` | SHA-256 of state before transition |
| `post_state_hash` | SHA-256 of state after transition |
| `prev_record_hash` | Hash of the previous TransitionRecord |
| `record_hash` | SHA-256 of THIS record (self-referential) |
| `transition_name` | Name of the function used |

### Genesis Hash

The first record's `prev_record_hash` is `"0" * 64` (64 zeros).

### Chain Verification

```python
valid, error = engine.verify_chain_integrity()
# Verifies: prev_record_hash chain is unbroken
# Verifies: record_hash matches recomputed hash of fields
```

---

## Replay Guarantee

```python
# Same inputs, same order -> same state and same chain
engine1 = DeterministicTransitionEngine()
state1, _ = engine1.apply(initial, input1)
state1, _ = engine1.apply(state1, input2)

engine2 = DeterministicTransitionEngine()
state2, _ = engine2.apply(initial, input1)
state2, _ = engine2.apply(state2, input2)

assert state1.state_hash() == state2.state_hash()
assert engine1.chain_hash == engine2.chain_hash
```

---

## Invariants

| ID | Name | Type | Description |
|---|---|---|---|
| T1 | Pure Transition | GUARANTEE | No side effects in transition functions |
| T2 | Monotonic Sequence | GUARANTEE | sequence_id strictly increases |
| T3 | Chain Integrity | GUARANTEE | Each record references the previous |
| T4 | Replay Determinism | GUARANTEE | Same inputs -> same outputs |
| T5 | Input Validation | GUARANTEE | Zone ID mismatch rejected |
| T6 | Physical Clamping | GUARANTEE | coating, barnacle, roughness clamped >= 0 |
