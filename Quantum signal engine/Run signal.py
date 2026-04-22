# -*- coding: utf-8 -*-
"""
run_signal.py
Single execution script for the Quantum Signal Generator.
Covers PHASE 4 (run once) and PHASE 6 (determinism proof -- run 5 times).

Usage:
    python run_signal.py
"""

import io
import json
import os
import sys

# ── PATH FIX ──────────────────────────────────────────────────────────────────
# Add the folder that contains run_signal.py to sys.path so that Python can
# always find signal_generator.py, mapping_logic.py, and validator.py,
# even when VS Code runs the script from a different working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Windows UTF-8 fix ─────────────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import signal_generator
from validator import ValidationError

# ── Sample input (fixed -- hardcoded as permitted by Phase 1 rules) ───────────
SAMPLE_INPUT = {
    "node_id":      "qnode_01",
    "energy_delta": 0.0001,
    "iterations":   120,
    "confidence":   0.92,
    "variance":     0.002,
}

# ── Additional test payloads (Phase 5 failure cases + Phase 6 determinism) ────
FAILURE_INPUTS = [
    {
        "label": "Low confidence -> SUSPENDED",
        "payload": {
            "node_id":      "qnode_02",
            "energy_delta": 0.0003,
            "iterations":   80,
            "confidence":   0.55,
            "variance":     0.003,
        },
    },
    {
        "label": "High energy_delta -> DIVERGED",
        "payload": {
            "node_id":      "qnode_03",
            "energy_delta": 0.05,
            "iterations":   200,
            "confidence":   0.88,
            "variance":     0.001,
        },
    },
    {
        "label": "Missing field -> ValidationError",
        "payload": {
            "node_id":      "qnode_04",
            "iterations":   50,
            "confidence":   0.90,
            "variance":     0.002,
        },
    },
    {
        "label": "confidence out of range -> ValidationError",
        "payload": {
            "node_id":      "qnode_05",
            "energy_delta": 0.0002,
            "iterations":   60,
            "confidence":   1.5,
            "variance":     0.001,
        },
    },
]


def _separator(title=""):
    line = "-" * 60
    if title:
        print("\n" + line)
        print("  " + title)
        print(line)
    else:
        print(line)


def phase_4_single_run():
    """PHASE 4 -- Create input, call generate_state_event, print output."""
    _separator("PHASE 4 -- Single Execution")
    print("\nInput payload:")
    print(json.dumps(SAMPLE_INPUT, indent=2))
    event = signal_generator.generate_state_event(SAMPLE_INPUT)
    print("\nOutput event:")
    print(json.dumps(event, indent=2))
    return event


def phase_5_failure_cases():
    """PHASE 5 -- Demonstrate validation and failure handling."""
    _separator("PHASE 5 -- Failure Cases")
    for case in FAILURE_INPUTS:
        print("\n  >>  " + case["label"])
        try:
            event = signal_generator.generate_state_event(case["payload"])
            print("     -> transition: " + event["transition"]["next"])
            print("     -> cause:      " + event["transition"]["cause"])
        except ValidationError as exc:
            print("     -> ValidationError (expected): " + str(exc))
        except Exception as exc:
            print("     -> Unexpected error: " + str(exc))


def phase_6_determinism_proof():
    """PHASE 6 -- Run same input 5 times. All outputs must be identical."""
    _separator("PHASE 6 -- Determinism Proof (5 runs, same input)")
    results = []
    for i in range(1, 6):
        event = signal_generator.generate_state_event(SAMPLE_INPUT)
        serialised = json.dumps(event, sort_keys=True)
        results.append(serialised)
        print(
            "  Run %d: transition=%-12s  sigma=%s  ts=%s"
            % (
                i,
                repr(event["transition"]["next"]),
                event["uncertainty_envelope"]["sigma"],
                event["transition"]["ts"],
            )
        )
    all_identical = all(r == results[0] for r in results)
    print()
    if all_identical:
        print("  [PASS] All 5 outputs are IDENTICAL -- determinism CONFIRMED.")
    else:
        print("  [FAIL] DETERMINISM FAILURE -- outputs differ across runs!")
        for i, r in enumerate(results, 1):
            print("  Run %d: %s" % (i, r))
    return all_identical


def main():
    print("\n" + "=" * 60)
    print("  Quantum Signal Generator -- Task 4 Execution")
    print("  Marine Intelligence System | BHIV Core Interface")
    print("=" * 60)
    phase_4_single_run()
    phase_5_failure_cases()
    deterministic = phase_6_determinism_proof()
    _separator()
    print("\n  EXECUTION COMPLETE")
    print("  Determinism status: " + ("PASS" if deterministic else "FAIL"))
    print()
    sys.exit(0 if deterministic else 1)


if __name__ == "__main__":
    main()
