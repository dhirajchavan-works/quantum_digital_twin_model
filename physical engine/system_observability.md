# System Observability — Phase 6 Specification

**Module**: `physical_engine/observability.py`
**Date**: 2026-04-04
**Status**: SEALED

---

## Overview

The observability layer is a READ-ONLY observer that collects structured metrics from
the physical engine ecosystem. It does NOT modify any engine state.

---

## Metrics Catalog

### Throughput Metrics

| Metric | Unit | Description |
|---|---|---|
| `total_transitions` | count | Total transitions applied across all zones |
| `total_batches` | count | Total batches executed |
| `transitions_per_sec` | ops/sec | Transitions per second since start |
| `batches_per_sec` | ops/sec | Batches per second since start |

### Latency Metrics

| Metric | Unit | Description |
|---|---|---|
| `avg_ms` | milliseconds | Average end-to-end latency |
| `p50_ms` | milliseconds | 50th percentile (median) latency |
| `p99_ms` | milliseconds | 99th percentile latency |
| `max_ms` | milliseconds | Maximum observed latency |

### Divergence Metrics

| Metric | Unit | Description |
|---|---|---|
| `total_checks` | count | Total consensus checks performed |
| `divergence_count` | count | Number of checks where nodes disagreed |
| `divergence_rate` | ratio | divergence_count / total_checks (0.0 = perfect) |

### State Metrics

| Metric | Type | Description |
|---|---|---|
| `active_zones` | int | Number of zones in the state vector |
| `global_hash` | str | Current global state hash |
| `batch_chain_hash` | str | Current batch chain tip hash |

### Cluster Metrics

| Metric | Type | Description |
|---|---|---|
| `total_nodes` | int | Number of registered distributed nodes |
| `consensus` | bool | Whether all nodes currently agree |

---

## Dashboard Output Schema

```json
{
  "throughput": {
    "total_transitions": 12,
    "total_batches": 3,
    "transitions_per_sec": 4000.0,
    "batches_per_sec": 1000.0
  },
  "latency": {
    "avg_ms": 0.35,
    "p50_ms": 0.30,
    "p99_ms": 0.52,
    "max_ms": 0.55
  },
  "divergence": {
    "total_checks": 3,
    "divergence_count": 0,
    "divergence_rate": 0.0
  },
  "state": {
    "active_zones": 4,
    "global_hash": "de3561826877eaa8...",
    "batch_chain_hash": "a9432aac79e394a6..."
  },
  "cluster": {
    "total_nodes": 3,
    "consensus": true
  },
  "zones": {
    "bow": {
      "corrosion_depth": 0.25,
      "coating_thickness": 4.44,
      "barnacle_density": 3.5,
      "roughness": 0.33,
      "risk_score": 0.79,
      "state_hash": "abc123..."
    }
  },
  "nodes": [
    {"node_id": "Sector_A", "committed_causal_id": 3, "global_hash": "de35...", "batch_count": 3}
  ]
}
```

---

## Collection Methodology

1. **Throughput**: Event hooks (`on_transition()`, `on_batch()`) record timestamps in a rolling deque
2. **Latency**: `LatencyTracker` records per-stage timestamps and computes end-to-end
3. **Divergence**: `on_receipt()` checks consensus flag on each `PhysicalExecutionReceipt`
4. **State**: Read directly from `MultiZoneExecutor` — no copies, no mutations
5. **Cluster**: Read from `PhysicalExecutionHub.check_full_consensus()`

---

## Invariants

| ID | Name | Type | Description |
|---|---|---|---|
| O1 | Read-Only | GUARANTEE | Observer never modifies engine state |
| O2 | Deterministic Metrics | GUARANTEE | Same event sequence -> same metric values |
| O3 | Rolling Window | GUARANTEE | Throughput computed over max 1000 events |
| O4 | Structured Output | GUARANTEE | Dashboard output is JSON-serializable |
