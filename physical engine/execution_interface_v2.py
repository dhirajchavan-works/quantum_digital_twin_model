"""
execution_interface_v2.py
==========================
Phase 4 — Distributed Execution Interface Upgrade

Enhanced API that provides:
    - Multi-client safe deterministic batching
    - Conflict-free proposal merging via causal_id assignment
    - Idempotent proposals (duplicate proposal_id rejected)
    - Full state, replay, and hash endpoints
    - Integration with MultiZoneExecutor + hub consensus

This module is standalone — does not modify execution_interface.py.
"""

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from physical_engine.ship_state_vector import ShipState, ShipStateVector
from physical_engine.transition_engine import (
    TransitionInput,
    DeterministicTransitionEngine,
)
from physical_engine.multi_zone_executor import MultiZoneExecutor, ZoneBatch


# ---------------------------------------------------------------------------
# Distributed Physical Node
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PhysicalProposal:
    """
    A client's request to update the physical state.
    Has NO authority until sequenced by the hub.
    """
    proposal_id: str              # Client-generated unique ID (idempotency key)
    client_id: str                # Which client submitted this
    zone_transitions: dict        # {zone_id: TransitionInput.to_dict()}
    transition_name: str          # Which physics function to use
    submitted_at: float           # Monotonic timestamp (advisory only)


@dataclass(frozen=True)
class SequencedPhysicalEvent:
    """
    Hub-stamped physical event with global causal_id.
    This is the authoritative instruction.
    """
    causal_id: int
    proposal_id: str
    client_id: str
    zone_transitions: Dict[str, TransitionInput]
    transition_name: str
    sequenced_at: float


@dataclass(frozen=True)
class PhysicalAck:
    """Acknowledgement from a node after applying a physical event."""
    causal_id: int
    proposal_id: str
    node_id: str
    global_state_hash: str
    batch_chain_hash: str
    ack_type: str                 # "APPLIED" | "REJECTED"
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.ack_type == "APPLIED"


@dataclass
class PhysicalExecutionReceipt:
    """Complete record of one physical event's lifecycle."""
    event: SequencedPhysicalEvent
    acks: List[PhysicalAck]
    consensus: bool
    global_hash: str

    @property
    def all_applied(self) -> bool:
        return all(a.ok for a in self.acks)

    @property
    def any_rejected(self) -> bool:
        return any(a.ack_type == "REJECTED" for a in self.acks)


# ---------------------------------------------------------------------------
# Physical State Node
# ---------------------------------------------------------------------------

class PhysicalStateNode:
    """
    A distributed node that holds a local MultiZoneExecutor.
    Executes sequenced physical events and reports acks.
    """

    def __init__(self, node_id: str, initial_state: ShipStateVector):
        self.node_id = node_id
        self.executor = MultiZoneExecutor(initial_state)
        self.next_expected_causal_id: int = 1
        self._ack_log: List[PhysicalAck] = []

    def execute_event(self, event: SequencedPhysicalEvent) -> PhysicalAck:
        """Execute a sequenced event and return an ack."""
        # Causal ordering check
        if event.causal_id < self.next_expected_causal_id:
            # Duplicate / old event
            return PhysicalAck(
                causal_id=event.causal_id,
                proposal_id=event.proposal_id,
                node_id=self.node_id,
                global_state_hash=self.executor.global_hash,
                batch_chain_hash=self.executor.batch_chain_hash,
                ack_type="APPLIED",  # Already applied
            )

        self.next_expected_causal_id = event.causal_id + 1

        try:
            batch = self.executor.execute_batch(
                event.zone_transitions, event.transition_name
            )
            ack = PhysicalAck(
                causal_id=event.causal_id,
                proposal_id=event.proposal_id,
                node_id=self.node_id,
                global_state_hash=self.executor.global_hash,
                batch_chain_hash=self.executor.batch_chain_hash,
                ack_type="APPLIED",
            )
        except Exception as e:
            ack = PhysicalAck(
                causal_id=event.causal_id,
                proposal_id=event.proposal_id,
                node_id=self.node_id,
                global_state_hash=self.executor.global_hash,
                batch_chain_hash=self.executor.batch_chain_hash,
                ack_type="REJECTED",
                error=str(e),
            )

        self._ack_log.append(ack)
        return ack

    @property
    def committed_causal_id(self) -> int:
        return self.next_expected_causal_id - 1


# ---------------------------------------------------------------------------
# Physical Execution Hub
# ---------------------------------------------------------------------------

class PhysicalExecutionHub:
    """
    The authoritative hub for distributed physical state management.

    Responsibilities:
        1. Accept PhysicalProposals from clients
        2. Assign monotonically increasing causal_ids (strict ordering)
        3. Deliver SequencedPhysicalEvents to all nodes
        4. Collect acks and verify consensus
        5. Reject duplicate proposal_ids (idempotency)
        6. Halt on any rejection or divergence

    Multi-Client Safety:
        - Proposals from different clients are serialized through causal_id
        - No two proposals get the same causal_id
        - Order is determined by hub reception order, not client timestamp
    """

    def __init__(self, halt_on_rejection: bool = True,
                 halt_on_divergence: bool = True):
        self.nodes: List[PhysicalStateNode] = []
        self._global_causal_id: int = 1
        self._event_log: List[SequencedPhysicalEvent] = []
        self._receipts: List[PhysicalExecutionReceipt] = []
        self._seen_proposals: Set[str] = set()
        self.halt_on_rejection = halt_on_rejection
        self.halt_on_divergence = halt_on_divergence
        self._halted: bool = False
        self._halt_reason: Optional[str] = None

        # Delayed delivery support
        self._held_events: Dict[str, List[SequencedPhysicalEvent]] = {}

    # -------------------------------------------------------------------
    # Node Registration
    # -------------------------------------------------------------------

    def register_node(self, node: PhysicalStateNode):
        """Register a distributed node."""
        self.nodes.append(node)
        self._held_events[node.node_id] = []

    # -------------------------------------------------------------------
    # Proposal Submission
    # -------------------------------------------------------------------

    def submit(self, proposal: PhysicalProposal,
               delay_nodes: Optional[List[str]] = None) -> PhysicalExecutionReceipt:
        """
        Submit a proposal for sequencing and execution.

        Multi-client safe:
            - Proposals are serialized by causal_id assignment
            - Duplicate proposal_ids are rejected (idempotency)

        Args:
            proposal:    Client-submitted proposal
            delay_nodes: Nodes to hold event for (simulate delay)

        Returns:
            PhysicalExecutionReceipt with full trace

        Raises:
            RuntimeError if hub is halted
            ValueError if proposal_id is duplicate
        """
        if self._halted:
            raise RuntimeError(f"Hub HALTED: {self._halt_reason}")

        # Idempotency check
        if proposal.proposal_id in self._seen_proposals:
            raise ValueError(
                f"Duplicate proposal_id: {proposal.proposal_id}. "
                "Each proposal must have a unique ID."
            )
        self._seen_proposals.add(proposal.proposal_id)

        # Parse zone transitions
        zone_transitions: Dict[str, TransitionInput] = {}
        for zone_id, inp_data in proposal.zone_transitions.items():
            if isinstance(inp_data, TransitionInput):
                zone_transitions[zone_id] = inp_data
            elif isinstance(inp_data, dict):
                zone_transitions[zone_id] = TransitionInput(
                    zone_id=zone_id,
                    corrosion_rate=inp_data.get("corrosion_rate", 0.0),
                    coating_degradation_rate=inp_data.get("coating_degradation_rate", 0.0),
                    barnacle_growth_rate=inp_data.get("barnacle_growth_rate", 0.0),
                    roughness_rate=inp_data.get("roughness_rate", 0.0),
                    dt=inp_data.get("dt", 1.0),
                )
            else:
                raise ValueError(f"Invalid transition data for zone '{zone_id}'")

        # Sequence
        event = SequencedPhysicalEvent(
            causal_id=self._global_causal_id,
            proposal_id=proposal.proposal_id,
            client_id=proposal.client_id,
            zone_transitions=zone_transitions,
            transition_name=proposal.transition_name,
            sequenced_at=time.monotonic(),
        )
        self._global_causal_id += 1
        self._event_log.append(event)

        delay_nodes = delay_nodes or []

        # Deliver to nodes
        acks: List[PhysicalAck] = []
        for node in self.nodes:
            if node.node_id in delay_nodes:
                self._held_events[node.node_id].append(event)
                continue

            ack = node.execute_event(event)
            acks.append(ack)

            if ack.ack_type == "REJECTED" and self.halt_on_rejection:
                self._halt(
                    f"Node {node.node_id} REJECTED causal_id={event.causal_id}: {ack.error}"
                )

        # Check consensus
        hashes = set(a.global_state_hash for a in acks if a.ok)
        consensus = len(hashes) <= 1

        if not consensus and self.halt_on_divergence:
            self._halt(
                f"Divergence at causal_id={event.causal_id}: "
                f"{len(hashes)} unique hashes"
            )

        receipt = PhysicalExecutionReceipt(
            event=event,
            acks=acks,
            consensus=consensus,
            global_hash=acks[0].global_state_hash if acks else "",
        )
        self._receipts.append(receipt)
        return receipt

    def release_held_events(self, node_id: str) -> List[PhysicalAck]:
        """Release delayed events to a specific node."""
        if self._halted:
            raise RuntimeError(f"Hub HALTED: {self._halt_reason}")

        node = self._find_node(node_id)
        if not node:
            raise ValueError(f"Node {node_id} not registered")

        held = self._held_events.get(node_id, [])
        acks = []
        for event in held:
            ack = node.execute_event(event)
            acks.append(ack)
            if ack.ack_type == "REJECTED" and self.halt_on_rejection:
                self._halt(f"Node {node_id} REJECTED held event causal_id={event.causal_id}")
                break
        self._held_events[node_id] = []
        return acks

    # -------------------------------------------------------------------
    # State Queries
    # -------------------------------------------------------------------

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> Optional[str]:
        return self._halt_reason

    @property
    def next_causal_id(self) -> int:
        return self._global_causal_id

    def get_event_log(self) -> List[SequencedPhysicalEvent]:
        return list(self._event_log)

    def get_receipts(self) -> List[PhysicalExecutionReceipt]:
        return list(self._receipts)

    def check_full_consensus(self) -> dict:
        """Check if all nodes agree on state."""
        hashes = {n.node_id: n.executor.global_hash for n in self.nodes}
        unique = set(hashes.values())
        return {
            "consensus": len(unique) <= 1,
            "unique_hashes": list(unique),
            "node_hashes": hashes,
            "total_nodes": len(self.nodes),
        }

    def get_node_status(self) -> List[dict]:
        return [
            {
                "node_id": n.node_id,
                "committed_causal_id": n.committed_causal_id,
                "global_hash": n.executor.global_hash[:16] + "...",
                "batch_count": n.executor.batch_count,
            }
            for n in self.nodes
        ]

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _halt(self, reason: str):
        self._halted = True
        self._halt_reason = reason

    def _find_node(self, node_id: str) -> Optional[PhysicalStateNode]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== execution_interface_v2.py — Self Test ===\n")

    # Initialize 4 zones across 3 nodes
    initial = ShipStateVector({
        "bow": ShipState.create("bow", 0.1, 4.5, 2.0, 0.3),
        "stern": ShipState.create("stern", 0.3, 3.0, 5.0, 0.8),
        "port": ShipState.create("port", 0.05, 5.0, 0.5, 0.1),
        "starboard": ShipState.create("starboard", 0.2, 4.0, 3.0, 0.5),
    })

    hub = PhysicalExecutionHub(halt_on_rejection=True, halt_on_divergence=True)
    for name in ["Sector_A", "Sector_B", "Sector_C"]:
        node = PhysicalStateNode(name, initial)
        hub.register_node(node)

    # Client 1 submits a proposal
    p1 = PhysicalProposal(
        proposal_id=str(uuid.uuid4()),
        client_id="client_1",
        zone_transitions={
            "bow": TransitionInput("bow", 0.05, 0.02, 0.5, 0.01, 1.0),
            "stern": TransitionInput("stern", 0.08, 0.03, 0.3, 0.02, 1.0),
        },
        transition_name="standard",
        submitted_at=time.monotonic(),
    )
    r1 = hub.submit(p1)
    print(f"  Receipt 1: causal_id={r1.event.causal_id}, consensus={r1.consensus}, "
          f"all_applied={r1.all_applied}")

    # Client 2 submits a concurrent proposal (serialized by hub)
    p2 = PhysicalProposal(
        proposal_id=str(uuid.uuid4()),
        client_id="client_2",
        zone_transitions={
            "port": TransitionInput("port", 0.03, 0.01, 0.2, 0.005, 1.0),
            "starboard": TransitionInput("starboard", 0.06, 0.025, 0.4, 0.015, 1.0),
        },
        transition_name="standard",
        submitted_at=time.monotonic(),
    )
    r2 = hub.submit(p2)
    print(f"  Receipt 2: causal_id={r2.event.causal_id}, consensus={r2.consensus}, "
          f"all_applied={r2.all_applied}")

    # Check consensus
    consensus = hub.check_full_consensus()
    print(f"\n  Full consensus: {consensus['consensus']}")
    assert consensus["consensus"], "All 3 nodes must agree!"

    # Verify idempotency — duplicate proposal_id should raise
    try:
        hub.submit(p1)
        assert False, "Should have raised ValueError for duplicate proposal"
    except ValueError as e:
        print(f"  Idempotency check: BLOCKED ✓ ({e})")

    # Node status
    for ns in hub.get_node_status():
        print(f"  {ns['node_id']}: committed={ns['committed_causal_id']}, "
              f"hash={ns['global_hash']}")

    print("\n✓ execution_interface_v2.py — All self-tests passed.")
