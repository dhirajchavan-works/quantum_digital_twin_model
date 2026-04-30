# Execution Interface V2 — Phase 4 Specification

**Module**: `physical_engine/execution_interface_v2.py`
**Date**: 2026-04-04
**Status**: SEALED

---

## Overview

The V2 execution interface provides a distributed physical state management layer with:
- Multi-client safe proposal submission
- Deterministic batching via causal_id serialization
- Conflict-free proposal merging
- Idempotent proposal handling

---

## Architecture

```
Client_1 ──┐
Client_2 ──┤──> PhysicalExecutionHub ──> [Node_A, Node_B, Node_C]
Client_3 ──┘                                     |
                                              consensus
```

---

## Protocol Messages

### PhysicalProposal (client -> hub)

| Field | Type | Description |
|---|---|---|
| `proposal_id` | `str` | Client-generated unique ID (idempotency key) |
| `client_id` | `str` | Which client submitted |
| `zone_transitions` | `dict` | {zone_id: TransitionInput} |
| `transition_name` | `str` | Which physics function |
| `submitted_at` | `float` | Monotonic timestamp (advisory) |

### SequencedPhysicalEvent (hub -> nodes)

| Field | Type | Description |
|---|---|---|
| `causal_id` | `int` | Hub-assigned, monotonically increasing |
| `proposal_id` | `str` | From the original proposal |
| `client_id` | `str` | From the original proposal |
| `zone_transitions` | `dict` | Parsed TransitionInput objects |
| `transition_name` | `str` | Which physics function |
| `sequenced_at` | `float` | When hub sequenced it |

### PhysicalAck (node -> hub)

| Field | Type | Description |
|---|---|---|
| `causal_id` | `int` | Which event was executed |
| `proposal_id` | `str` | Original proposal ID |
| `node_id` | `str` | Which node reports |
| `global_state_hash` | `str` | Node's state hash after execution |
| `batch_chain_hash` | `str` | Node's batch chain hash |
| `ack_type` | `str` | "APPLIED" or "REJECTED" |

---

## Multi-Client Safety

1. **Serialization**: Proposals from ANY client get a globally unique causal_id
2. **No collision**: Two proposals never get the same causal_id
3. **Order by reception**: Hub reception order determines execution order
4. **Client timestamp irrelevant**: Timestamps are advisory only

## Conflict-Free Merging

- Client_1 updates zones A,B while Client_2 updates zones C,D
- Both proposals get distinct causal_ids (e.g., 5 and 6)
- Node executes 5 first, then 6 — deterministic
- If both update zone A, order is determined by causal_id assignment

## Idempotency

```python
# Second submission with same proposal_id -> ValueError
hub.submit(same_proposal)  # raises ValueError("Duplicate proposal_id")
```

---

## Halt Conditions

The hub halts (stops accepting proposals) on:
1. **Rejection**: Any node returns `ack_type="REJECTED"`
2. **Divergence**: Nodes produce different `global_state_hash` values

---

## Invariants

| ID | Name | Type | Description |
|---|---|---|---|
| D1 | Causal Serialization | GUARANTEE | Every proposal gets unique, monotonic causal_id |
| D2 | Idempotency | GUARANTEE | Duplicate proposal_id rejected |
| D3 | Consensus Check | GUARANTEE | All nodes must agree on hash after each event |
| D4 | Halt on Rejection | GUARANTEE | Hub halts if any node rejects |
| D5 | Halt on Divergence | GUARANTEE | Hub halts if nodes diverge |
| D6 | No Bypass | PROHIBITION | No state change outside the hub protocol |
