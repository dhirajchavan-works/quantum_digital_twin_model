# -*- coding: utf-8 -*-
"""
mapping_logic.py
Deterministic state transition engine for the Quantum Signal Generator.

Rules are pure functions — same input always produces same output.
No randomness. No I/O. No global state.

State space:
  CONVERGED  — quantum node has stabilised to a valid ground state
  DIVERGED   — node is numerically unstable or physically invalid
  SUSPENDED  — node is in a low-confidence holding state pending retry

Transition table (priority order — first matching rule wins):
  ┌──────────────────────────────────────────────────────────────┐
  │  Condition                          → Next State             │
  ├──────────────────────────────────────────────────────────────┤
  │  energy_delta > DIVERGE_ENERGY      → DIVERGED              │
  │  confidence   < CONFIDENCE_SUSPEND  → SUSPENDED             │
  │  variance     > VARIANCE_SUSPEND    → SUSPENDED             │
  │  iterations   > ITER_DIVERGE        → DIVERGED              │
  │  confidence   >= CONFIDENCE_CONV                            │
  │  AND variance <= VARIANCE_CONV                              │
  │  AND energy_delta <= CONVERGE_ENERGY → CONVERGED            │
  │  (fallback)                          → SUSPENDED            │
  └──────────────────────────────────────────────────────────────┘
"""

import math
from typing import Tuple

# ── Thresholds (all values are inclusive bounds) ──────────────────────────────
DIVERGE_ENERGY       = 0.01     # energy_delta above this → DIVERGED
CONVERGE_ENERGY      = 0.005    # energy_delta at/below this (with other checks) → CONVERGED
CONFIDENCE_SUSPEND   = 0.70     # confidence below this → SUSPENDED
CONFIDENCE_CONV      = 0.85     # confidence at/above this (with other checks) → CONVERGED
VARIANCE_SUSPEND     = 0.01     # variance above this → SUSPENDED
VARIANCE_CONV        = 0.005    # variance at/below this (with other checks) → CONVERGED
ITER_DIVERGE         = 500      # iterations above this → DIVERGED (runaway)

# ── Previous-state resolution ────────────────────────────────────────────────
# Without stored state we infer prev_state from inputs.
# ACTIVE: node has been running (iterations > 0, energy_delta is meaningful).
# INITIALISING: first iteration, no prior state.
_PREV_STATE_ACTIVE       = "ACTIVE"
_PREV_STATE_INITIALISING = "INITIALISING"


def _infer_prev_state(payload: dict) -> str:
    """Deterministically infer the previous state from the input payload."""
    if payload["iterations"] == 0:
        return _PREV_STATE_INITIALISING
    return _PREV_STATE_ACTIVE


def _determine_next_state(payload: dict) -> Tuple[str, str]:
    """
    Apply the transition table and return (next_state, cause).
    Pure function — no side effects.
    """
    e  = payload["energy_delta"]
    c  = payload["confidence"]
    v  = payload["variance"]
    it = payload["iterations"]

    # Rule 1: energy spike → diverge immediately
    if e > DIVERGE_ENERGY:
        return (
            "DIVERGED",
            f"energy_delta={e} exceeds diverge threshold {DIVERGE_ENERGY}"
        )

    # Rule 2: runaway iteration count → diverge
    if it > ITER_DIVERGE:
        return (
            "DIVERGED",
            f"iterations={it} exceeds runaway limit {ITER_DIVERGE}"
        )

    # Rule 3: low confidence → suspend
    if c < CONFIDENCE_SUSPEND:
        return (
            "SUSPENDED",
            f"confidence={c} below suspend floor {CONFIDENCE_SUSPEND}"
        )

    # Rule 4: high variance → suspend
    if v > VARIANCE_SUSPEND:
        return (
            "SUSPENDED",
            f"variance={v} exceeds suspend ceiling {VARIANCE_SUSPEND}"
        )

    # Rule 5: all convergence criteria met → converge
    if (c >= CONFIDENCE_CONV
            and v <= VARIANCE_CONV
            and e <= CONVERGE_ENERGY):
        return (
            "CONVERGED",
            f"confidence={c}>={CONFIDENCE_CONV}, "
            f"variance={v}<={VARIANCE_CONV}, "
            f"energy_delta={e}<={CONVERGE_ENERGY}"
        )

    # Fallback: marginal state — hold in suspension
    return (
        "SUSPENDED",
        "marginal values: criteria not fully met for convergence"
    )


def resolve_transition(payload: dict, seq: int) -> dict:
    """
    Public API consumed by signal_generator.py.

    Args:
        payload : validated input dict (node_id, energy_delta, iterations,
                  confidence, variance)
        seq     : monotonic sequence counter supplied by caller

    Returns:
        transition dict:
          {
            "prev":  str,
            "next":  str,
            "cause": str,
            "seq":   int,
          }
        plus sigma (float) for the uncertainty envelope.
    """
    prev        = _infer_prev_state(payload)
    next_state, cause = _determine_next_state(payload)
    sigma       = math.sqrt(payload["variance"])

    return {
        "transition": {
            "prev":  prev,
            "next":  next_state,
            "cause": cause,
            "seq":   int(seq),
        },
        "sigma": sigma,
    }
