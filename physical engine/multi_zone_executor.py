"""
multi_zone_executor.py
=======================
Phase 3 — Multi-Zone State Execution

Manages deterministic evolution of ALL ship zones as an atomic unit.

Guarantees:
    - All zones update in sorted zone_id order (deterministic)
    - Batch transitions are atomic: all-or-nothing
    - No cross-zone inconsistency: single ShipStateVector updated atomically
    - Full replay support: given ordered ZoneBatch list → identical final state
    - Each batch is hashed and logged for provability
"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from physical_engine.ship_state_vector import ShipState, ShipStateVector, FLOAT_FMT
from physical_engine.transition_engine import (
    TransitionInput,
    TransitionRecord,
    DeterministicTransitionEngine,
)


# ---------------------------------------------------------------------------
# Zone Batch Record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZoneBatch:
    """
    Immutable record of a multi-zone batch transition.

    A batch applies transitions to one or more zones atomically.
    The batch hash covers all zone transitions and the pre/post global hashes.
    """
    batch_id: int
    zone_transitions: tuple          # Tuple of (zone_id, TransitionInput) — frozen
    pre_global_hash: str
    post_global_hash: str
    transition_records: tuple        # Tuple of TransitionRecord from the engine
    batch_hash: str
    prev_batch_hash: str

    @staticmethod
    def compute_batch_hash(batch_id: int, pre_hash: str, post_hash: str,
                           transition_hashes: List[str], prev_batch_hash: str) -> str:
        """Deterministic hash of the entire batch."""
        h = hashlib.sha256()
        h.update(str(batch_id).encode("utf-8"))
        h.update(pre_hash.encode("utf-8"))
        h.update(post_hash.encode("utf-8"))
        for th in transition_hashes:
            h.update(th.encode("utf-8"))
        h.update(prev_batch_hash.encode("utf-8"))
        return h.hexdigest()

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "zones_affected": [zt[0] for zt in self.zone_transitions],
            "pre_global_hash": self.pre_global_hash,
            "post_global_hash": self.post_global_hash,
            "batch_hash": self.batch_hash,
            "prev_batch_hash": self.prev_batch_hash,
            "transition_count": len(self.transition_records),
        }


# ---------------------------------------------------------------------------
# Multi-Zone Executor
# ---------------------------------------------------------------------------

class MultiZoneExecutor:
    """
    Manages the complete ship state across all zones.

    Core Loop:
        1. Receive a dict of {zone_id: TransitionInput}
        2. Process zones in SORTED zone_id order (deterministic)
        3. Apply each transition via DeterministicTransitionEngine
        4. Update ShipStateVector atomically
        5. Log as ZoneBatch with hash chain

    Invariants:
        - Zone processing order: always sorted(zone_id)
        - Batch atomicity: if any zone transition fails, none are applied
        - Batch chain: each batch references the previous batch hash
        - State consistency: ShipStateVector is always in a valid state
    """

    GENESIS_BATCH_HASH = "0" * 64

    def __init__(self, initial_state: ShipStateVector,
                 transition_engine: Optional[DeterministicTransitionEngine] = None):
        self._state = initial_state
        self._engine = transition_engine or DeterministicTransitionEngine()
        self._batches: List[ZoneBatch] = []
        self._batch_counter: int = 0

    # -------------------------------------------------------------------
    # State Access
    # -------------------------------------------------------------------

    @property
    def current_state(self) -> ShipStateVector:
        """Return the current state vector (read-only reference)."""
        return self._state

    @property
    def global_hash(self) -> str:
        """Return the current global state hash."""
        return self._state.global_hash()

    def get_zone(self, zone_id: str) -> Optional[ShipState]:
        """Get current state of a specific zone."""
        return self._state.get(zone_id)

    # -------------------------------------------------------------------
    # Batch Execution
    # -------------------------------------------------------------------

    def execute_batch(self, transitions: Dict[str, TransitionInput],
                      transition_name: str = "standard") -> ZoneBatch:
        """
        Execute a batch of zone transitions atomically.

        Args:
            transitions:     {zone_id: TransitionInput} — one input per zone to update
            transition_name: Name of the transition function to use for ALL zones

        Returns:
            ZoneBatch record

        Raises:
            ValueError if any zone_id is not in the state vector
            ValueError if TransitionInput.zone_id doesn't match
        """
        # Validate all zone IDs before applying anything (atomicity)
        for zone_id, inp in transitions.items():
            if zone_id not in self._state:
                raise ValueError(f"Zone '{zone_id}' not in state vector")
            if inp.zone_id != zone_id:
                raise ValueError(f"Input zone_id '{inp.zone_id}' ≠ key '{zone_id}'")

        pre_hash = self._state.global_hash()

        # Process in SORTED order — this is the determinism guarantee
        zone_updates: Dict[str, ShipState] = {}
        records: List[TransitionRecord] = []
        ordered_transitions: List[Tuple[str, TransitionInput]] = []

        for zone_id in sorted(transitions.keys()):
            inp = transitions[zone_id]
            current_zone_state = self._state.get(zone_id)

            # Apply through the transition engine (logs the record, builds chain)
            new_zone_state, record = self._engine.apply(
                current_zone_state, inp, transition_name
            )

            zone_updates[zone_id] = new_zone_state
            records.append(record)
            ordered_transitions.append((zone_id, inp))

        # Atomic state update
        self._state = self._state.with_updated_zones(zone_updates)
        post_hash = self._state.global_hash()

        # Build batch record
        self._batch_counter += 1
        prev_batch_hash = (
            self._batches[-1].batch_hash
            if self._batches
            else self.GENESIS_BATCH_HASH
        )

        batch_hash = ZoneBatch.compute_batch_hash(
            batch_id=self._batch_counter,
            pre_hash=pre_hash,
            post_hash=post_hash,
            transition_hashes=[r.record_hash for r in records],
            prev_batch_hash=prev_batch_hash,
        )

        batch = ZoneBatch(
            batch_id=self._batch_counter,
            zone_transitions=tuple(ordered_transitions),
            pre_global_hash=pre_hash,
            post_global_hash=post_hash,
            transition_records=tuple(records),
            batch_hash=batch_hash,
            prev_batch_hash=prev_batch_hash,
        )

        self._batches.append(batch)
        return batch

    # -------------------------------------------------------------------
    # Batch Access
    # -------------------------------------------------------------------

    @property
    def batches(self) -> List[ZoneBatch]:
        """Return the full batch history."""
        return list(self._batches)

    @property
    def batch_count(self) -> int:
        """Number of batches executed."""
        return self._batch_counter

    @property
    def batch_chain_hash(self) -> str:
        """Hash of the latest batch (tip of the batch chain)."""
        return self._batches[-1].batch_hash if self._batches else self.GENESIS_BATCH_HASH

    def get_batch(self, batch_id: int) -> Optional[ZoneBatch]:
        """Retrieve a specific batch by ID."""
        for b in self._batches:
            if b.batch_id == batch_id:
                return b
        return None

    def get_batch_slice(self, from_id: int, to_id: int) -> List[ZoneBatch]:
        """Get a range of batches (inclusive)."""
        return [b for b in self._batches if from_id <= b.batch_id <= to_id]

    # -------------------------------------------------------------------
    # Replay
    # -------------------------------------------------------------------

    @staticmethod
    def replay(initial_state: ShipStateVector,
               inputs_sequence: List[Dict[str, TransitionInput]],
               transition_name: str = "standard") -> "MultiZoneExecutor":
        """
        Replay a sequence of batch inputs from an initial state.
        Returns a new MultiZoneExecutor with the replayed state.

        This is the core PROOF mechanism:
            same initial_state + same inputs → same final state + same hashes
        """
        executor = MultiZoneExecutor(initial_state)
        for batch_inputs in inputs_sequence:
            executor.execute_batch(batch_inputs, transition_name)
        return executor

    # -------------------------------------------------------------------
    # Verification
    # -------------------------------------------------------------------

    def verify_batch_chain(self) -> Tuple[bool, Optional[str]]:
        """Verify the batch chain is unbroken."""
        prev_hash = self.GENESIS_BATCH_HASH
        for batch in self._batches:
            if batch.prev_batch_hash != prev_hash:
                return False, (
                    f"Batch chain break at batch_id={batch.batch_id}: "
                    f"expected prev={prev_hash[:16]}..., got={batch.prev_batch_hash[:16]}..."
                )

            expected = ZoneBatch.compute_batch_hash(
                batch.batch_id, batch.pre_global_hash, batch.post_global_hash,
                [r.record_hash for r in batch.transition_records],
                batch.prev_batch_hash,
            )
            if batch.batch_hash != expected:
                return False, (
                    f"Batch hash mismatch at batch_id={batch.batch_id}"
                )

            prev_hash = batch.batch_hash
        return True, None

    def verify_cross_zone_consistency(self) -> Tuple[bool, Optional[str]]:
        """
        Verify that the current state vector's global hash matches
        the post_global_hash of the latest batch.
        """
        if not self._batches:
            return True, None

        latest_post = self._batches[-1].post_global_hash
        current = self._state.global_hash()
        if latest_post != current:
            return False, (
                f"Cross-zone inconsistency: latest batch post_hash={latest_post[:16]}... "
                f"≠ current state hash={current[:16]}..."
            )
        return True, None


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== multi_zone_executor.py — Self Test ===\n")

    # Initialize 4 zones
    initial = ShipStateVector({
        "bow":       ShipState.create("bow", 0.1, 4.5, 2.0, 0.3),
        "stern":     ShipState.create("stern", 0.3, 3.0, 5.0, 0.8),
        "port":      ShipState.create("port", 0.05, 5.0, 0.5, 0.1),
        "starboard": ShipState.create("starboard", 0.2, 4.0, 3.0, 0.5),
    })
    print(f"  Initial state: {initial}")
    print(f"  Initial hash:  {initial.global_hash()[:24]}...")

    executor = MultiZoneExecutor(initial)

    # Batch 1: update bow and stern
    batch1 = executor.execute_batch({
        "bow": TransitionInput("bow", 0.05, 0.02, 0.5, 0.01, 1.0),
        "stern": TransitionInput("stern", 0.08, 0.03, 0.3, 0.02, 1.0),
    })
    print(f"\n  Batch 1: {batch1.to_dict()}")

    # Batch 2: update all zones
    batch2 = executor.execute_batch({
        "bow": TransitionInput("bow", 0.05, 0.02, 0.5, 0.01, 1.0),
        "stern": TransitionInput("stern", 0.08, 0.03, 0.3, 0.02, 1.0),
        "port": TransitionInput("port", 0.03, 0.01, 0.2, 0.005, 1.0),
        "starboard": TransitionInput("starboard", 0.06, 0.025, 0.4, 0.015, 1.0),
    })
    print(f"  Batch 2: {batch2.to_dict()}")

    # Verify chains
    valid, err = executor.verify_batch_chain()
    assert valid, f"Batch chain invalid: {err}"
    print(f"\n  Batch chain: VALID ✓")

    valid2, err2 = executor.verify_cross_zone_consistency()
    assert valid2, f"Cross-zone consistency invalid: {err2}"
    print(f"  Cross-zone consistency: VALID ✓")

    # Replay test
    replay_exec = MultiZoneExecutor.replay(initial, [
        {
            "bow": TransitionInput("bow", 0.05, 0.02, 0.5, 0.01, 1.0),
            "stern": TransitionInput("stern", 0.08, 0.03, 0.3, 0.02, 1.0),
        },
        {
            "bow": TransitionInput("bow", 0.05, 0.02, 0.5, 0.01, 1.0),
            "stern": TransitionInput("stern", 0.08, 0.03, 0.3, 0.02, 1.0),
            "port": TransitionInput("port", 0.03, 0.01, 0.2, 0.005, 1.0),
            "starboard": TransitionInput("starboard", 0.06, 0.025, 0.4, 0.015, 1.0),
        },
    ])
    assert replay_exec.global_hash == executor.global_hash, "Replay hash mismatch!"
    assert replay_exec.batch_chain_hash == executor.batch_chain_hash, "Replay chain mismatch!"
    print(f"  Replay determinism: VERIFIED ✓")

    print(f"\n  Final state: {executor.current_state}")
    print(f"  Final hash:  {executor.global_hash[:24]}...")

    print("\n✓ multi_zone_executor.py — All self-tests passed.")
