# quantum-signal-engine

Quantum node state signal generator for the Marine Intelligence System.
Produces deterministic, schema-validated events for BHIV Core ingestion.

---

## Run

```bash
python run_signal.py
```

No arguments. No dependencies. Python 3.8+.

---

## Structure

```
quantum-signal-engine/
├── src/
│   ├── signal_generator.py   ← entry logic (calls mapping + builds event)
│   ├── mapping_logic.py      ← deterministic state transition rules
│   └── validator.py          ← schema validation + failure checks
├── run_signal.py             ← MAIN ENTRY POINT
├── requirements.txt
├── README.md
└── review_packets/
    ├── task_1_review.md
    ├── task_2_review.md
    ├── task_3_review.md
    └── task_4_review.md
```

---

## API

```python
from src.signal_generator import generate_state_event

event = generate_state_event({
    "node_id":      "qnode_01",
    "energy_delta": 0.0001,
    "iterations":   120,
    "confidence":   0.92,
    "variance":     0.002
})
```

Output schema: `engine_event_version 2.0`

---

## State Transitions

| Condition | State |
|---|---|
| `energy_delta > 0.01` | DIVERGED |
| `iterations > 500` | DIVERGED |
| `confidence < 0.70` | SUSPENDED |
| `variance > 0.01` | SUSPENDED |
| `confidence >= 0.85` AND `variance <= 0.005` AND `energy_delta <= 0.005` | CONVERGED |
| fallback | SUSPENDED |

---

## Guarantees

- Same input → identical output, always
- Timestamp derived from `iterations`, not `datetime.now()`
- No file I/O, no global state, no randomness in core engine
- Input validated before any computation; output validated before return
- Fails loudly on bad input — no silent failures

---

*Dhiraj Chavan · Marine Intelligence System · April 2026*
