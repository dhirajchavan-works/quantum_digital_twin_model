# run_signal.py
# MAIN ENTRY POINT
#
# Usage:
#   python run_signal.py
#
# Creates input → calls system → prints final event.
# Also runs failure cases and 5-run determinism proof.

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import signal_generator
from validator import ValidationError

# ── Input ─────────────────────────────────────────────────────────────────────
SAMPLE_INPUT = {
    "node_id":      "qnode_01",
    "energy_delta": 0.0001,
    "iterations":   120,
    "confidence":   0.92,
    "variance":     0.002,
}

# ── Failure / edge-case payloads ──────────────────────────────────────────────
FAILURE_INPUTS = [
    {
        "label": "Low confidence -> SUSPENDED",
        "payload": {"node_id": "qnode_02", "energy_delta": 0.0003, "iterations": 80, "confidence": 0.55, "variance": 0.003},
    },
    {
        "label": "High energy_delta -> DIVERGED",
        "payload": {"node_id": "qnode_03", "energy_delta": 0.05, "iterations": 200, "confidence": 0.88, "variance": 0.001},
    },
    {
        "label": "Missing field -> ValidationError",
        "payload": {"node_id": "qnode_04", "iterations": 50, "confidence": 0.90, "variance": 0.002},
    },
    {
        "label": "confidence out of range -> ValidationError",
        "payload": {"node_id": "qnode_05", "energy_delta": 0.0002, "iterations": 60, "confidence": 1.5, "variance": 0.001},
    },
]


def _sep(title=""):
    line = "-" * 60
    if title:
        print(f"\n{line}\n  {title}\n{line}")
    else:
        print(line)


def run():
    print("\n" + "=" * 60)
    print("  Quantum Signal Generator")
    print("  Marine Intelligence System | BHIV Core Interface")
    print("=" * 60)

    # ── Single execution ──────────────────────────────────────
    _sep("PHASE 4 -- Single Execution")
    print("\nInput:")
    print(json.dumps(SAMPLE_INPUT, indent=2))

    event = signal_generator.generate_state_event(SAMPLE_INPUT)

    print("\nOutput:")
    print(json.dumps(event, indent=2))

    # ── Failure cases ─────────────────────────────────────────
    _sep("PHASE 5 -- Failure Cases")
    for case in FAILURE_INPUTS:
        print(f"\n  >>  {case['label']}")
        try:
            e = signal_generator.generate_state_event(case["payload"])
            print(f"     -> transition: {e['transition']['next']}")
            print(f"     -> cause:      {e['transition']['cause']}")
        except ValidationError as exc:
            print(f"     -> ValidationError (expected): {exc}")

    # ── Determinism proof ─────────────────────────────────────
    _sep("PHASE 6 -- Determinism Proof (5 runs, same input)")
    results = []
    for i in range(1, 6):
        e = signal_generator.generate_state_event(SAMPLE_INPUT)
        results.append(json.dumps(e, sort_keys=True))
        print(f"  Run {i}: transition={e['transition']['next']!r:<12}  sigma={e['uncertainty_envelope']['sigma']}  ts={e['transition']['ts']}")

    all_same = all(r == results[0] for r in results)
    print()
    if all_same:
        print("  [PASS] All 5 outputs IDENTICAL -- determinism CONFIRMED.")
    else:
        print("  [FAIL] DETERMINISM FAILURE -- outputs differ!")

    _sep()
    print(f"\n  EXECUTION COMPLETE  |  Determinism: {'PASS' if all_same else 'FAIL'}")
    print()
    sys.exit(0 if all_same else 1)


if __name__ == "__main__":
    run()
