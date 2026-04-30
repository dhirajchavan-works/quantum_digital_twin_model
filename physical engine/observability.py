"""
observability.py
=================
Phase 6 — System Observability Layer

Provides:
    - SystemMetrics: structured snapshot of system health
    - ObservabilityCollector: hooks into engines and hub, collects metrics
    - MetricsDashboardOutput: JSON-ready output for external dashboards

Metrics Tracked:
    - Throughput (transitions/sec, batches/sec)
    - Latency (avg, p50, p99, max)
    - Divergence rate (hash mismatches across nodes)
    - State hash evolution (per-batch)
    - Zone-level statistics
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from physical_engine.ship_state_vector import ShipState, ShipStateVector
from physical_engine.multi_zone_executor import MultiZoneExecutor, ZoneBatch
from physical_engine.execution_interface_v2 import (
    PhysicalExecutionHub,
    PhysicalExecutionReceipt,
)
from physical_engine.latency_ordering import LatencyTracker


# ---------------------------------------------------------------------------
# System Metrics Snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SystemMetrics:
    """
    Point-in-time snapshot of system health.
    All fields are deterministic given the system state.
    """
    # Throughput
    total_transitions: int
    total_batches: int
    throughput_transitions_per_sec: float
    throughput_batches_per_sec: float

    # Latency
    avg_latency_ms: float
    p50_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float

    # Divergence
    total_consensus_checks: int
    divergence_count: int
    divergence_rate: float          # divergence_count / total_consensus_checks

    # State
    active_zones: int
    global_state_hash: str
    batch_chain_hash: str

    # Nodes
    total_nodes: int
    consensus_status: bool

    # Timestamp (advisory)
    captured_at_monotonic: float

    def to_dict(self) -> dict:
        """Structured output for dashboard consumption."""
        return {
            "throughput": {
                "total_transitions": self.total_transitions,
                "total_batches": self.total_batches,
                "transitions_per_sec": round(self.throughput_transitions_per_sec, 4),
                "batches_per_sec": round(self.throughput_batches_per_sec, 4),
            },
            "latency": {
                "avg_ms": round(self.avg_latency_ms, 4),
                "p50_ms": round(self.p50_latency_ms, 4),
                "p99_ms": round(self.p99_latency_ms, 4),
                "max_ms": round(self.max_latency_ms, 4),
            },
            "divergence": {
                "total_checks": self.total_consensus_checks,
                "divergence_count": self.divergence_count,
                "divergence_rate": round(self.divergence_rate, 6),
            },
            "state": {
                "active_zones": self.active_zones,
                "global_hash": self.global_state_hash,
                "batch_chain_hash": self.batch_chain_hash,
            },
            "cluster": {
                "total_nodes": self.total_nodes,
                "consensus": self.consensus_status,
            },
        }


# ---------------------------------------------------------------------------
# Observability Collector
# ---------------------------------------------------------------------------

class ObservabilityCollector:
    """
    Collects and computes metrics from the physical engine ecosystem.

    This is a READ-ONLY observer — it does not modify any engine state.
    It hooks into existing data structures to compute metrics.
    """

    def __init__(self, hub: Optional[PhysicalExecutionHub] = None,
                 latency_tracker: Optional[LatencyTracker] = None):
        self._hub = hub
        self._latency_tracker = latency_tracker or LatencyTracker()
        self._start_time: float = time.monotonic()
        self._divergence_count: int = 0
        self._consensus_checks: int = 0
        self._transition_times: deque = deque(maxlen=1000)  # Rolling window
        self._batch_times: deque = deque(maxlen=1000)

    # -------------------------------------------------------------------
    # Event Hooks (called by the execution pipeline)
    # -------------------------------------------------------------------

    def on_transition(self):
        """Called after each transition is applied."""
        self._transition_times.append(time.monotonic())

    def on_batch(self):
        """Called after each batch is executed."""
        self._batch_times.append(time.monotonic())

    def on_receipt(self, receipt: PhysicalExecutionReceipt):
        """Called after each execution receipt is produced."""
        self._consensus_checks += 1
        if not receipt.consensus:
            self._divergence_count += 1

    def record_latency(self, causal_id: int, proposal_id: str,
                       submitted_at: float, sequenced_at: float,
                       executed_at: float, acked_at: float):
        """Record full latency data for an event."""
        self._latency_tracker.record_submission(causal_id, proposal_id, submitted_at)
        self._latency_tracker.record_sequencing(causal_id, sequenced_at)
        self._latency_tracker.record_execution(causal_id, executed_at)
        self._latency_tracker.record_ack(causal_id, acked_at)

    # -------------------------------------------------------------------
    # Metrics Snapshot
    # -------------------------------------------------------------------

    def collect(self, executor: Optional[MultiZoneExecutor] = None) -> SystemMetrics:
        """
        Collect a point-in-time SystemMetrics snapshot.

        Args:
            executor: Optional executor for state-level metrics.
                     If hub is set, uses the first node's executor.
        """
        now = time.monotonic()
        elapsed = max(now - self._start_time, 0.001)

        # Resolve executor
        if executor is None and self._hub and self._hub.nodes:
            executor = self._hub.nodes[0].executor

        # Throughput
        total_transitions = len(self._transition_times)
        total_batches = len(self._batch_times)
        trans_per_sec = total_transitions / elapsed
        batch_per_sec = total_batches / elapsed

        # Latency
        lat_stats = self._latency_tracker.get_latency_stats()

        # Divergence
        div_rate = 0.0
        if self._consensus_checks > 0:
            div_rate = self._divergence_count / self._consensus_checks

        # State
        active_zones = 0
        global_hash = ""
        batch_chain_hash = ""
        if executor:
            active_zones = len(executor.current_state)
            global_hash = executor.global_hash
            batch_chain_hash = executor.batch_chain_hash

        # Nodes
        total_nodes = len(self._hub.nodes) if self._hub else 0
        consensus_status = True
        if self._hub:
            consensus = self._hub.check_full_consensus()
            consensus_status = consensus["consensus"]

        return SystemMetrics(
            total_transitions=total_transitions,
            total_batches=total_batches,
            throughput_transitions_per_sec=trans_per_sec,
            throughput_batches_per_sec=batch_per_sec,
            avg_latency_ms=lat_stats["avg_ms"],
            p50_latency_ms=lat_stats["p50_ms"],
            p99_latency_ms=lat_stats["p99_ms"],
            max_latency_ms=lat_stats["max_ms"],
            total_consensus_checks=self._consensus_checks,
            divergence_count=self._divergence_count,
            divergence_rate=div_rate,
            active_zones=active_zones,
            global_state_hash=global_hash,
            batch_chain_hash=batch_chain_hash,
            total_nodes=total_nodes,
            consensus_status=consensus_status,
            captured_at_monotonic=now,
        )

    # -------------------------------------------------------------------
    # Dashboard Output
    # -------------------------------------------------------------------

    def dashboard_json(self, executor: Optional[MultiZoneExecutor] = None) -> dict:
        """
        Produce structured JSON output suitable for a dashboard.
        Includes per-zone breakdown if executor is available.
        """
        metrics = self.collect(executor)
        output = metrics.to_dict()

        # Add per-zone breakdown
        if executor:
            zones = {}
            for zone_id in executor.current_state.zone_ids():
                state = executor.current_state.get(zone_id)
                zones[zone_id] = {
                    "corrosion_depth": state.corrosion_depth,
                    "coating_thickness": state.coating_thickness,
                    "barnacle_density": state.barnacle_density,
                    "roughness": state.roughness,
                    "risk_score": state.risk_score,
                    "state_hash": state.state_hash()[:16] + "...",
                }
            output["zones"] = zones

        # Add node breakdown if hub exists
        if self._hub:
            output["nodes"] = self._hub.get_node_status()

        return output


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uuid
    from physical_engine.ship_state_vector import ShipState, ShipStateVector
    from physical_engine.transition_engine import TransitionInput
    from physical_engine.execution_interface_v2 import (
        PhysicalExecutionHub, PhysicalStateNode, PhysicalProposal,
    )

    print("=== observability.py — Self Test ===\n")

    # Set up hub with 3 nodes
    initial = ShipStateVector({
        "bow": ShipState.create("bow", 0.1, 4.5, 2.0, 0.3),
        "stern": ShipState.create("stern", 0.3, 3.0, 5.0, 0.8),
    })

    hub = PhysicalExecutionHub()
    for name in ["Node_A", "Node_B", "Node_C"]:
        hub.register_node(PhysicalStateNode(name, initial))

    collector = ObservabilityCollector(hub=hub)

    # Submit some proposals and track
    for i in range(5):
        t_sub = time.monotonic()
        p = PhysicalProposal(
            proposal_id=str(uuid.uuid4()),
            client_id="test_client",
            zone_transitions={
                "bow": TransitionInput("bow", 0.05, 0.02, 0.5, 0.01, 1.0),
            },
            transition_name="standard",
            submitted_at=t_sub,
        )
        receipt = hub.submit(p)
        t_ack = time.monotonic()

        collector.on_batch()
        collector.on_transition()
        collector.on_receipt(receipt)
        collector.record_latency(
            receipt.event.causal_id, receipt.event.proposal_id,
            t_sub, receipt.event.sequenced_at, t_ack - 0.0001, t_ack,
        )

    # Collect metrics
    dashboard = collector.dashboard_json()
    print(f"  Dashboard output:")
    for section, data in dashboard.items():
        if isinstance(data, dict):
            print(f"    {section}:")
            for k, v in data.items():
                if isinstance(v, dict):
                    print(f"      {k}: {{...}}")
                else:
                    print(f"      {k}: {v}")
        elif isinstance(data, list):
            print(f"    {section}: [{len(data)} items]")

    metrics = collector.collect()
    assert metrics.total_batches == 5
    assert metrics.total_nodes == 3
    assert metrics.consensus_status is True
    assert metrics.divergence_rate == 0.0
    print(f"\n  Divergence rate: {metrics.divergence_rate}")
    print(f"  Consensus: {metrics.consensus_status}")
    print(f"  Active zones: {metrics.active_zones}")

    print("\n✓ observability.py — All self-tests passed.")
