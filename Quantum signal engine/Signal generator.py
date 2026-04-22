# -*- coding: utf-8 -*-
"""
signal_generator.py
Quantum Signal Generator — callable interface for the Marine Intelligence System.

PUBLIC API (the only thing BHIV Core / tests / run_signal.py call):

    generate_state_event(input_payload: dict) -> dict

Rules:
  → no file I/O
  → no global mutable state
  → no randomness
  → same input always returns identical output
"""

from datetime import datetime, timezone, timedelta

import mapping_logic
import validator

# Monotonic sequence counter — read-only default.
# Caller may supply "seq" in payload to override (useful for multi-event streams).
_DEFAULT_SEQ = 1


def generate_state_event(input_payload: dict) -> dict:
    """
    Callable entry point.  Convert a raw quantum-node snapshot into a
    fully structured engine-compatible event.

    Args:
        input_payload: dict with keys:
            node_id      (str)   — node identifier
            energy_delta (float) — energy change since last iteration
            iterations   (int)   — VQE iteration count
            confidence   (float) — optimizer confidence [0, 1]
            variance     (float) — output variance

            Optional:
            seq          (int)   — sequence override (default: 1)

    Returns:
        Engine-compatible event dict matching engine_event_version 2.0.

    Raises:
        validator.ValidationError: on any invalid input (fails loudly).
    """

    # ── PHASE 5: Validate input FIRST ────────────────────────────────────────
    cleaned = validator.validate_input(input_payload)

    # ── Sequence number ───────────────────────────────────────────────────────
    seq = int(input_payload.get("seq", _DEFAULT_SEQ))

    # ── PHASE 2: Deterministic state mapping ─────────────────────────────────
    mapping = mapping_logic.resolve_transition(cleaned, seq=seq)
    transition = mapping["transition"]
    sigma      = mapping["sigma"]

    # ── Timestamp — deterministic: fixed to epoch anchor + iteration offset ──
    # This ensures same input → same timestamp.
    # Anchor: 2026-01-01T00:00:00Z + (iterations * 60 seconds)
    anchor    = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts_dt     = anchor + timedelta(seconds=cleaned["iterations"] * 60)
    timestamp = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── PHASE 3: Build engine-compatible output ───────────────────────────────
    event = {
        "engine_event_version": "2.0",
        "node_ref": cleaned["node_id"],
        "transition": {
            "prev":  transition["prev"],
            "next":  transition["next"],
            "cause": transition["cause"],
            "seq":   transition["seq"],       # int — enforced
            "ts":    timestamp,               # ISO 8601 — deterministic
        },
        "uncertainty_envelope": {
            "confidence": cleaned["confidence"],
            "sigma":      round(sigma, 8),    # sqrt(variance)
        },
    }

    # ── Validate output shape before returning ────────────────────────────────
    validator.validate_output(event)

    return event
