# Phase 04 — Hybrid Compute Layer (Quantum + Classical)
**Deliverable:** `compute_layer.md`
**Author:** Dhiraj Chavan | Quantum Track | 

---

## Why quantum and classical are split — the honest answer

Quantum computers today are excellent at one specific type of problem: computing the **exact electronic structure of materials**. They are NOT good at running a real-time iterative simulation with thousands of zone updates per timestep. They are too slow, have too many errors, and are not designed for that kind of work.

So the correct architecture — not a compromise, the genuinely correct design — is:

- **Quantum runs once (or occasionally)** to produce highly accurate parameter tables
- **Classical runs the live simulation every timestep** using those tables

The two layers are completely decoupled. You can upgrade one without breaking the other.

---

## Architecture Overview

```
┌─────────────────────────────────┐     ┌──────────────────────────────────┐
│   OFFLINE — QUANTUM             │     │   ONLINE — CLASSICAL             │
│   (Runs once / when needed)     │     │   (Runs every simulation step)   │
│                                 │     │                                  │
│  VQE — Variational Quantum      │     │  Python: NumPy + SciPy           │
│  Eigensolver                    │     │  All 5 simulation step calcs     │
│  Computes exact corrosion rate  │     │  Zone state updates per timestep │
│  constant k for each:           │     │  Reads quantum tables as lookup  │
│    - steel alloy type           │     │                                  │
│    - temperature grid           │     │  PostgreSQL + HDF5               │
│    - salinity grid              │     │  Stores zone state snapshots     │
│  Output: material_table.json    │     │  Provides historical trend data  │
│                                 │     │  Feeds the decision engine       │
│  Molecular Simulation           │     │                                  │
│  Computes coating polymer decay │     │                                  │
│  rates under UV + saltwater     │     │                                  │
│  Output: coating_properties.json│     │                                  │
└──────────────┬──────────────────┘     └──────────────────────────────────┘
               │
               │  DATA BRIDGE (JSON files loaded at startup)
               │  material_table.json
               └─ coating_properties.json
                        ↓
        k = material_table[alloy][temperature][salinity]
        decay = coating_properties[type][uv_index]
```

---

## OFFLINE QUANTUM — Part 1: Material Properties (VQE)

The corrosion rate constant **k** is the most physics-sensitive number in the whole simulation. It depends on the exact electronic structure of the steel alloy — the activation energy for the iron oxidation reaction at the metal-water interface.

Classical DFT (Density Functional Theory) estimates this with approximations that introduce errors, especially for complex modern alloy compositions. VQE solves the same problem **exactly**, by directly simulating the quantum mechanics of the electrons in the material.

VQE runs once for each alloy type, across a grid of temperatures and salinities, and stores results as a JSON lookup table:

```json
// material_table.json — output of quantum VQE computation
// Loaded by simulation engine at startup
{
  "steel_grade_DH36": {
    "corrosion_k": {
      "temp_10_salinity_30": 0.0318,
      "temp_15_salinity_33": 0.0374,
      "temp_20_salinity_35": 0.0421,
      "temp_25_salinity_35": 0.0589,
      "temp_30_salinity_38": 0.0712
    },
    "roughness_factor":  0.034,
    "failure_depth_mm":  3.0
  },
  "steel_grade_A36": { "...": "..." }
}
```

---

## OFFLINE QUANTUM — Part 2: Coating Chemistry Parameters

Quantum molecular simulation computes how fast the polymer chains in the coating break down under UV radiation and in saltwater. This determines the decay rates used in Step 5 of the simulation engine.

Classical molecular dynamics estimates these rates. Quantum simulation gives exact energy landscapes — more accurate predictions of when the coating will fail and at what rate.

```json
// coating_properties.json — output of quantum molecular simulation
{
  "epoxy_antifouling_v2": {
    "uv_decay_rate":         0.0032,
    "chemical_decay_rate":   0.0011,
    "failure_threshold":     15,
    "max_coating_thickness": 200,
    "adhesion_decay_curve":  [1.0, 0.92, 0.81, 0.67, 0.48, 0.29]
  },
  "vinyl_tar_epoxy_v1": { "...": "..." }
}
```

---

## ONLINE CLASSICAL — every timestep

When the simulation is advancing week by week, updating all zones, there is **no quantum hardware involved**. The classical engine reads the JSON files at startup and uses them as lookup tables.

| Component | Role |
|-----------|------|
| Python (NumPy, SciPy) | All numerical zone update calculations |
| Pandas | Managing zone objects, writing snapshots to disk |
| OpenFOAM | Offline pre-computation of the CFD flow table for Step 2 |
| PostgreSQL + PostGIS | Environment database, spatial queries by zone position |
| HDF5 | Efficient time-series storage of zone state snapshots |

---

## Data Flow Between Layers

```
[Quantum Offline]
    ↓ VQE computation (one-time per alloy/coating type)
    ↓ Output: material_table.json + coating_properties.json
    ↓
[Classical Startup]
    ↓ Load both JSON files into memory at engine init
    ↓
[Classical Per-Timestep]
    ↓ Step 1: Read env_database → zone environmental values
    ↓ Step 2: Read flow_table → zone flow velocity
    ↓ Step 3: Compute fouling growth using loaded params
    ↓ Step 4: k = material_table[alloy][temp][salinity] → corrosion_rate
    ↓ Step 5: decay = coating_properties[type] → coating wear
    ↓ Write zone snapshots → HDF5 + PostgreSQL
    ↓ Feed decision engine
```

---

## When does quantum need to run again?

| Event That Triggers a Re-Run | What Quantum Does | How Often |
|------------------------------|-------------------|-----------|
| New steel alloy used on ship | Re-run VQE for that alloy | On demand |
| New coating product deployed | Re-run molecular sim for new coating | On demand |
| Annual accuracy audit fails | Full recalibration run | Once per year |
| Inspection shows model drifting | Selective k-value correction run | As needed |
| Quantum hardware upgraded | Full table refresh for better accuracy | Once per generation |

**Hardware setup:** Currently using Qiskit (IBM) or PennyLane, running on IBM Quantum systems or classical simulators. The interface is designed so that when fault-tolerant quantum computers become available, the system can point at real QPU hardware without changing any other code.
