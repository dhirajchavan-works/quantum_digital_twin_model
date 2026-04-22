#Marine-twin-simulator
 

## Dhiraj Chavan — Interface Readiness + Minimum Runnable Signal Execution
### Marine Intelligence System | Quantum Signal Generator
**Date:** April 14, 2026
**Task:** — BHIV Core Interface Preparation

---

## 1. ENTRY POINT

**File:** `run_signal.py`
**Command:**
```
python run_signal.py
```

No arguments required. No external dependencies. No file I/O. Runs completely self-contained.

Internally it:
1. Constructs a fixed sample input payload (hardcoded, as permitted by Phase 1 rules)
2. Calls `generate_state_event()` once (Phase 4)
3. Runs 4 failure/edge-case inputs through the validator (Phase 5)
4. Runs the same input 5 times and proves identical output (Phase 6)

---

## 2. CORE FLOW (3 files)

### File 1 — `signal_generator.py`
**Role:** Callable entry point. The ONLY function BHIV Core will invoke.

```
generate_state_event(input_payload: dict) -> dict
```

Internal sequence:
```
input_payload
    │
    ▼
validator.validate_input()       ← fails loudly if anything is wrong
    │
    ▼
mapping_logic.resolve_transition()  ← deterministic state decision
    │
    ▼
timestamp construction           ← deterministic: anchor + (iterations × 60s)
    │
    ▼
event dict assembly              ← matches engine_event_version 2.0 schema
    │
    ▼
validator.validate_output()      ← confirms output shape before returning
    │
    ▼
return event dict
```

**Rules enforced here:** no I/O, no global state, no randomness.

---

### File 2 — `mapping_logic.py`
**Role:** Pure deterministic state transition engine.

Inputs: `energy_delta`, `confidence`, `variance`, `iterations`, `seq`
Output: `(next_state, cause, sigma)`

**Transition table (priority order — first match wins):**

| Condition | Next State | Cause |
|-----------|-----------|-------|
| `energy_delta > 0.01` | DIVERGED | energy spike |
| `iterations > 500` | DIVERGED | runaway iteration count |
| `confidence < 0.70` | SUSPENDED | low confidence floor |
| `variance > 0.01` | SUSPENDED | high variance ceiling |
| `confidence ≥ 0.85` AND `variance ≤ 0.005` AND `energy_delta ≤ 0.005` | CONVERGED | all criteria met |
| (fallback) | SUSPENDED | marginal — criteria not fully met |

**Previous state inference** (no stored state needed):
- `iterations == 0` → prev = `INITIALISING`
- `iterations > 0` → prev = `ACTIVE`

**sigma computation:**
```
sigma = sqrt(variance)
```

---

### File 3 — `validator.py`
**Role:** Input and output schema enforcement. Fails loudly. Never silently accepts bad data.

**Required input fields:**

| Field | Type | Constraint |
|-------|------|-----------|
| `node_id` | str | non-empty |
| `energy_delta` | float | ≥ 0.0 |
| `iterations` | int | ≥ 0 |
| `confidence` | float | in [0.0, 1.0] |
| `variance` | float | ≥ 0.0 |

**Output validation checks:** confirms `engine_event_version`, `node_ref`, `transition` (with `prev`, `next`, `cause`, `seq` as int, `ts`), and `uncertainty_envelope` (with `confidence`, `sigma`) are all present and correctly typed before the event is returned.

---

## 3. LIVE FLOW — Input → Output

### Input
```json
{
  "node_id": "qnode_01",
  "energy_delta": 0.0001,
  "iterations": 120,
  "confidence": 0.92,
  "variance": 0.002
}
```

### Transformation trace

**Step 1 — validator.validate_input()**
- `node_id` = "qnode_01" ✅ non-empty string
- `energy_delta` = 0.0001 ✅ float ≥ 0.0
- `iterations` = 120 ✅ int ≥ 0
- `confidence` = 0.92 ✅ float in [0.0, 1.0]
- `variance` = 0.002 ✅ float ≥ 0.0

**Step 2 — mapping_logic.resolve_transition()**
- Rule 1: energy_delta=0.0001 ≤ 0.01 → not DIVERGED
- Rule 2: iterations=120 ≤ 500 → not DIVERGED
- Rule 3: confidence=0.92 ≥ 0.70 → not SUSPENDED
- Rule 4: variance=0.002 ≤ 0.01 → not SUSPENDED
- Rule 5: confidence=0.92 ≥ 0.85, variance=0.002 ≤ 0.005, energy_delta=0.0001 ≤ 0.005 → **CONVERGED** ✅
- sigma = sqrt(0.002) = 0.04472136

**Step 3 — timestamp (deterministic)**
- anchor = 2026-01-01T00:00:00Z
- offset = 120 × 60s = 7200s = 2 hours
- ts = `2026-01-01T02:00:00Z`

**Step 4 — event assembly**

### Output
```json
{
  "engine_event_version": "2.0",
  "node_ref": "qnode_01",
  "transition": {
    "prev": "ACTIVE",
    "next": "CONVERGED",
    "cause": "confidence=0.92≥0.85, variance=0.002≤0.005, energy_delta=0.0001≤0.005",
    "seq": 1,
    "ts": "2026-01-01T02:00:00Z"
  },
  "uncertainty_envelope": {
    "confidence": 0.92,
    "sigma": 0.04472136
  }
}
```

---

## 4. WHAT WAS BUILT

### Callable Interface
`generate_state_event(input_payload: dict) -> dict` in `signal_generator.py`.
- Single function. No constructor. No instance required.
- BHIV Core calls this directly.
- Validates input before any logic runs.
- Validates output before returning.

### Deterministic Mapping
Priority-ordered rule table in `mapping_logic.resolve_transition()`.
- Pure function — takes a dict, returns a dict.
- No side effects. No randomness. No I/O.
- Same input always triggers same rule, same output.
- Timestamp is derived from `iterations` via a fixed arithmetic formula, not `datetime.now()`.

### Execution Script
`run_signal.py` covers:
- Phase 4: single execution with console output
- Phase 5: four failure/edge-case demonstrations
- Phase 6: 5-run determinism proof with pass/fail verdict

---

## 5. FAILURE CASES

### Case 1 — Missing required field

**Input:**
```json
{ "node_id": "qnode_04", "iterations": 50, "confidence": 0.90, "variance": 0.002 }
```
*(energy_delta missing)*

**Result:**
```
ValidationError: Input validation failed (1 error(s)):
  • Missing required field(s): ['energy_delta']
```
No event is returned. No computation occurs.

---

### Case 2 — Low confidence → SUSPENDED

**Input:**
```json
{ "node_id": "qnode_02", "energy_delta": 0.0003, "iterations": 80, "confidence": 0.55, "variance": 0.003 }
```

**Result:**
```json
{
  "transition": {
    "next": "SUSPENDED",
    "cause": "confidence=0.55 below suspend floor 0.7"
  }
}
```

---

### Case 3 — High energy_delta → DIVERGED

**Input:**
```json
{ "node_id": "qnode_03", "energy_delta": 0.05, "iterations": 200, "confidence": 0.88, "variance": 0.001 }
```

**Result:**
```json
{
  "transition": {
    "next": "DIVERGED",
    "cause": "energy_delta=0.05 exceeds diverge threshold 0.01"
  }
}
```

---

### Case 4 — confidence out of valid range → ValidationError

**Input:**
```json
{ "node_id": "qnode_05", "energy_delta": 0.0002, "iterations": 60, "confidence": 1.5, "variance": 0.001 }
```

**Result:**
```
ValidationError: Input validation failed (1 error(s)):
  • Field 'confidence' = 1.5: must be a float in [0.0, 1.0].
```
No event is returned.

---

## 6. PROOF — Console Output

```
============================================================
  Quantum Signal Generator — Task 4 Execution
  Marine Intelligence System | BHIV Core Interface
============================================================

────────────────────────────────────────────────────────────
  PHASE 4 — Single Execution
────────────────────────────────────────────────────────────

Input payload:
{
  "node_id": "qnode_01",
  "energy_delta": 0.0001,
  "iterations": 120,
  "confidence": 0.92,
  "variance": 0.002
}

Output event:
{
  "engine_event_version": "2.0",
  "node_ref": "qnode_01",
  "transition": {
    "prev": "ACTIVE",
    "next": "CONVERGED",
    "cause": "confidence=0.92≥0.85, variance=0.002≤0.005, energy_delta=0.0001≤0.005",
    "seq": 1,
    "ts": "2026-01-01T02:00:00Z"
  },
  "uncertainty_envelope": {
    "confidence": 0.92,
    "sigma": 0.04472136
  }
}

────────────────────────────────────────────────────────────
  PHASE 5 — Failure Cases
────────────────────────────────────────────────────────────

  ▶  Low confidence → SUSPENDED
     → transition: SUSPENDED
     → cause:      confidence=0.55 below suspend floor 0.7

  ▶  High energy_delta → DIVERGED
     → transition: DIVERGED
     → cause:      energy_delta=0.05 exceeds diverge threshold 0.01

  ▶  Missing field → ValidationError
     → ValidationError (expected): Input validation failed (1 error(s)):
  • Missing required field(s): ['energy_delta']

  ▶  confidence out of range → ValidationError
     → ValidationError (expected): Input validation failed (1 error(s)):
  • Field 'confidence' = 1.5: must be a float in [0.0, 1.0].

────────────────────────────────────────────────────────────
  PHASE 6 — Determinism Proof (5 runs, same input)
────────────────────────────────────────────────────────────
  Run 1: transition='CONVERGED'   sigma=0.04472136  ts=2026-01-01T02:00:00Z
  Run 2: transition='CONVERGED'   sigma=0.04472136  ts=2026-01-01T02:00:00Z
  Run 3: transition='CONVERGED'   sigma=0.04472136  ts=2026-01-01T02:00:00Z
  Run 4: transition='CONVERGED'   sigma=0.04472136  ts=2026-01-01T02:00:00Z
  Run 5: transition='CONVERGED'   sigma=0.04472136  ts=2026-01-01T02:00:00Z

  ✅  All 5 outputs are IDENTICAL — determinism CONFIRMED.
────────────────────────────────────────────────────────────

  EXECUTION COMPLETE
  Determinism status: PASS ✅
```

---

## Compliance Checklist

| Requirement | Status |
|-------------|--------|
| Single callable entry point `generate_state_event()` | ✅ |
| No file I/O | ✅ |
| No global mutable state | ✅ |
| No randomness | ✅ |
| Correct output schema (engine_event_version 2.0) | ✅ |
| `sigma = sqrt(variance)` | ✅ |
| `seq` is integer | ✅ |
| `ts` is valid ISO 8601 | ✅ |
| Same input → same output (5-run proof) | ✅ |
| Fails loudly on invalid input | ✅ |
| No orchestration / routing logic built | ✅ |
| No Kanishk integration | ✅ |
| Max 3 core files | ✅ (signal_generator, mapping_logic, validator) |
| `run_signal.py` executes with `python run_signal.py` | ✅ |
| Review packet present at `/review_packets/task_4_review_packet.md` | ✅ |

---

*Quantum Signal Generator — Task 4 | Dhiraj Chavan | April 14, 2026*
*Marine Intelligence System — BHIV Core Interface Preparation*
