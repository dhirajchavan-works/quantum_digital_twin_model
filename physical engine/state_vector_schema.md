# State Vector Schema — Phase 1 Specification

**Module**: `physical_engine/ship_state_vector.py`
**Date**: 2026-04-04
**Status**: SEALED

---

## ShipState — Per-Zone Physical State

A frozen (immutable) dataclass representing the physical condition of a single ship hull zone.

### Fields

| Field | Type | Bounds | Precision | Description |
|---|---|---|---|---|
| `zone_id` | `str` | non-empty | exact | Unique zone identifier (e.g. "bow", "stern") |
| `corrosion_depth` | `float` | unbounded | 8 decimal | Cumulative corrosion depth in mm |
| `coating_thickness` | `float` | >= 0 | 8 decimal | Remaining coating thickness in mm |
| `barnacle_density` | `float` | >= 0 | 8 decimal | Organism density in units/m^2 |
| `roughness` | `float` | >= 0 | 8 decimal | Surface roughness index |
| `risk_score` | `float` | >= 0 | 8 decimal | Computed risk metric (deterministic) |

### Physical Constraints (enforced at construction)

- `coating_thickness >= 0` — coating cannot be negative
- `barnacle_density >= 0` — density cannot be negative
- `roughness >= 0` — roughness cannot be negative
- `zone_id` must be a non-empty string

### Risk Score Formula

```
risk_score = 0.35 * corrosion_depth
           + 0.25 * (1 / max(coating_thickness, 1e-6))
           + 0.20 * barnacle_density
           + 0.20 * roughness
```

Risk score is ALWAYS recomputed from physical parameters via `ShipState.create()`.
Direct construction with an arbitrary `risk_score` is possible but discouraged.

### Hash Contract

```
SHA-256(
    zone_id.encode("utf-8") +
    format(corrosion_depth, ".8f").encode("utf-8") +
    format(coating_thickness, ".8f").encode("utf-8") +
    format(barnacle_density, ".8f").encode("utf-8") +
    format(roughness, ".8f").encode("utf-8") +
    format(risk_score, ".8f").encode("utf-8")
)
```

Fixed 8-decimal precision eliminates cross-platform floating-point drift.

---

## ShipStateVector — Multi-Zone Collection

An ordered collection of `ShipState` objects keyed by `zone_id`.

### Ordering Guarantee

Iteration is **always in sorted `zone_id` order**, regardless of insertion order.
This makes the global hash deterministic.

### Global Hash

```
SHA-256(
    for each zone_id in sorted order:
        zone_id.encode("utf-8") +
        zone_state_hash.encode("utf-8")
)
```

### Mutation Model

`ShipStateVector` uses an **immutable update** pattern:
- `with_updated_zone(new_state)` returns a NEW vector
- `with_updated_zones(updates)` returns a NEW vector with multiple updates
- The original vector is NEVER modified

### Serialization

Round-trip `to_dict()` / `from_dict()` preserves hash identity:
```python
vec2 = ShipStateVector.from_dict(vec.to_dict())
assert vec.global_hash() == vec2.global_hash()
```

---

## Invariants

| ID | Name | Type | Description |
|---|---|---|---|
| P1 | Hash Determinism | GUARANTEE | Same state -> same hash, always |
| P2 | Immutability | GUARANTEE | ShipState is frozen; no field mutation |
| P3 | Sorted Iteration | GUARANTEE | Zone IDs always iterated in sorted order |
| P4 | Risk Recomputation | GUARANTEE | risk_score = f(physical fields) |
| P5 | Physical Bounds | GUARANTEE | coating >= 0, barnacle >= 0, roughness >= 0 |
| P6 | Round-Trip Integrity | GUARANTEE | to_dict -> from_dict preserves hash |
