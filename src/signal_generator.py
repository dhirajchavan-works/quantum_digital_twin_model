# signal_generator.py
# Entry logic — calls mapping + builds engine-compatible event.
#
# PUBLIC API:
#   generate_state_event(input_payload: dict) -> dict
#
# Rules:
#   no file I/O · no global mutable state · no randomness
#   same input always returns identical output

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone, timedelta
import mapping_logic
import validator

_DEFAULT_SEQ = 1


def generate_state_event(input_payload: dict) -> dict:
    """
    Convert a raw quantum-node snapshot into a fully structured
    engine-compatible event (engine_event_version 2.0).

    Args:
        input_payload: dict — node_id, energy_delta, iterations,
                              confidence, variance, [seq]

    Returns:
        engine event dict

    Raises:
        validator.ValidationError on invalid input
    """
    # 1. Validate input before any computation
    cleaned = validator.validate_input(input_payload)

    # 2. Sequence number
    seq = int(input_payload.get("seq", _DEFAULT_SEQ))

    # 3. Deterministic state mapping
    mapping    = mapping_logic.resolve_transition(cleaned, seq=seq)
    transition = mapping["transition"]
    sigma      = mapping["sigma"]

    # 4. Deterministic timestamp — anchor + (iterations × 60s)
    #    Same input → same timestamp, guaranteed.
    anchor    = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts_dt     = anchor + timedelta(seconds=cleaned["iterations"] * 60)
    timestamp = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5. Assemble event
    event = {
        "engine_event_version": "2.0",
        "node_ref": cleaned["node_id"],
        "transition": {
            "prev":  transition["prev"],
            "next":  transition["next"],
            "cause": transition["cause"],
            "seq":   transition["seq"],
            "ts":    timestamp,
        },
        "uncertainty_envelope": {
            "confidence": cleaned["confidence"],
            "sigma":      round(sigma, 8),
        },
    }

    # 6. Validate output shape before returning
    validator.validate_output(event)

    return event
