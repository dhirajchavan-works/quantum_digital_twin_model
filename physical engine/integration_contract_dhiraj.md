# Integration Contract — Dhiraj (Phase 7 Specification)

**Module**: `physical_engine/dhiraj_integration.py`
**Date**: 2026-04-04
**Status**: SEALED

---

## Overview

This document defines the formal contract between Dhiraj's simulation layer
and the Deterministic Physical Intelligence Engine.

**Guarantee**: `same simulation input -> same deterministic evolution`

---

## Input Schema (Dhiraj -> Engine)

### SimulationOutput (top-level)

| Field | Type | Required | Description |
|---|---|---|---|
| `simulation_id` | `str` | YES | Globally unique simulation run identifier |
| `model_version` | `str` | YES | Dhiraj's model version tag (must be consistent) |
| `zones` | `dict` | YES | {zone_id: SimulationZoneOutput} |
| `metadata` | `dict` | NO | Optional advisory metadata |

### SimulationZoneOutput (per-zone)

| Field | Type | Bounds | Description |
|---|---|---|---|
| `zone_id` | `str` | non-empty | Must match the zone key |
| `corrosion_rate` | `float` | >= 0 | mm/time_unit |
| `coating_degradation_rate` | `float` | >= 0 | mm/time_unit |
| `barnacle_growth_rate` | `float` | >= 0 | units*m^-2/time_unit |
| `roughness_rate` | `float` | any | index/time_unit |
| `dt` | `float` | > 0 | Time delta (must be identical across all zones) |
| `simulation_id` | `str` | match | Must match top-level simulation_id |
| `model_version` | `str` | match | Must match top-level model_version |

---

## Wire Format (JSON)

```json
{
  "simulation_id": "sim_20260404_001",
  "model_version": "v2.1.0",
  "zones": {
    "bow": {
      "zone_id": "bow",
      "corrosion_rate": 0.05,
      "coating_degradation_rate": 0.02,
      "barnacle_growth_rate": 0.50,
      "roughness_rate": 0.01,
      "dt": 1.0,
      "simulation_id": "sim_20260404_001",
      "model_version": "v2.1.0"
    },
    "stern": { ... },
    "port": { ... },
    "starboard": { ... }
  },
  "metadata": {
    "notes": "optional metadata"
  }
}
```

---

## Validation Rules

### Hard Errors (block processing)

1. `simulation_id` must be non-empty
2. `model_version` must be non-empty
3. At least one zone must be present
4. `zone_id` in data must match the zone key
5. `corrosion_rate >= 0`
6. `coating_degradation_rate >= 0`
7. `barnacle_growth_rate >= 0`
8. `dt > 0`
9. `dt` must be identical across all zones in one output
10. `model_version` must be consistent across all zones

### Soft Warnings (log but proceed)

1. `corrosion_rate > 10.0` — unrealistically high
2. `dt > 365.0` — very large time step
3. Extra zones not in state vector

### Zone Coverage

If `expected_zones` is provided, ALL expected zones must appear in the output.
Missing zones trigger a hard error.

---

## Conversion Pipeline

```
SimulationOutput
    |
    v (ContractValidator.validate)
ValidationResult
    |
    v (SimulationToTransitionAdapter.convert)
Dict[str, TransitionInput]
    |
    v (MultiZoneExecutor.execute_batch)
ZoneBatch + Updated ShipStateVector
```

### Determinism Proof

```python
# Verified by SimulationToTransitionAdapter.verify_determinism():
adapter = SimulationToTransitionAdapter()
for _ in range(100):
    transitions, _ = adapter.convert(same_output)
    # All 100 conversions produce identical input_hash() values
```

---

## Content Hash

Each SimulationOutput has a deterministic content hash:

```
SHA-256(
    simulation_id +
    model_version +
    for each zone_id in sorted order:
        zone_id +
        format(corrosion_rate, ".8f") +
        format(coating_degradation_rate, ".8f") +
        format(barnacle_growth_rate, ".8f") +
        format(roughness_rate, ".8f") +
        format(dt, ".8f")
)
```

This allows Dhiraj to verify that the engine received and processed
exactly what his simulation produced.

---

## End-to-End Verification

```
Dhiraj's simulation_output.content_hash()
    ==
Engine's received content hash
    ->
Engine's TransitionInput hashes match expected
    ->
Engine's final state hash is deterministic
```

---

## Invariants

| ID | Name | Type | Description |
|---|---|---|---|
| I1 | Contract Schema | GUARANTEE | All required fields validated |
| I2 | Deterministic Conversion | GUARANTEE | Same output -> same TransitionInputs |
| I3 | Content Hash Stability | GUARANTEE | Same data -> same content hash |
| I4 | Zone Coverage | GUARANTEE | Missing zones trigger error |
| I5 | Round-Trip Integrity | GUARANTEE | to_dict -> from_dict preserves hash |
| I6 | Bound Validation | GUARANTEE | Negative rates rejected |
