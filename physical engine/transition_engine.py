"""
transition_engine.py
=====================
Phase 2 — Deterministic Transition Engine

Converts input → transition → state mutation with:
    - TransitionInput: typed specification of physical rates and time delta
    - TransitionFunction: pure function (ShipState, TransitionInput) → ShipState
    - TransitionRecord: immutable record of every state change
    - DeterministicTransitionEngine: manages transitions with hash-chain integrity

Guarantees:
    - Every transition is a pure function (no side effects, no randomness)
    - Every transition is recorded as a frozen TransitionRecord
    - Hash chain: each record includes hash of previous record
    - Replay: given same inputs in same order → identical final state
"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from physical_engine.ship_state_vector import (
    ShipState,
    ShipStateVector,
    compute_risk_score,
    HASH_PRECISION,
    FLOAT_FMT,
)


# ---------------------------------------------------------------------------
# Transition Input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionInput:
    """
    Typed specification of physical rates applied to a single zone.

    Fields:
        zone_id                    : str   — Target zone
        corrosion_rate             : float — mm/time_unit  (≥ 0)
        coating_degradation_rate   : float — mm/time_unit  (≥ 0)
        barnacle_growth_rate       : float — units·m⁻²/time_unit  (≥ 0)
        roughness_rate             : float — index/time_unit (can be negative for polishing)
        dt                         : float — Time delta in time_units  (> 0)

    All rates are physical: non-negative except roughness_rate (polishing allowed).
    """
    zone_id: str
    corrosion_rate: float
    coating_degradation_rate: float
    barnacle_growth_rate: float
    roughness_rate: float
    dt: float

    def __post_init__(self):
        if not self.zone_id:
            raise ValueError("zone_id must be non-empty")
        if self.corrosion_rate < 0:
            raise ValueError(f"corrosion_rate must be ≥ 0, got {self.corrosion_rate}")
        if self.coating_degradation_rate < 0:
            raise ValueError(f"coating_degradation_rate must be ≥ 0, got {self.coating_degradation_rate}")
        if self.barnacle_growth_rate < 0:
            raise ValueError(f"barnacle_growth_rate must be ≥ 0, got {self.barnacle_growth_rate}")
        if self.dt <= 0:
            raise ValueError(f"dt must be > 0, got {self.dt}")

    def input_hash(self) -> str:
        """Deterministic hash of this input for chaining."""
        h = hashlib.sha256()
        h.update(self.zone_id.encode("utf-8"))
        for val in (self.corrosion_rate, self.coating_degradation_rate,
                    self.barnacle_growth_rate, self.roughness_rate, self.dt):
            h.update(format(val, FLOAT_FMT).encode("utf-8"))
        return h.hexdigest()

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "corrosion_rate": self.corrosion_rate,
            "coating_degradation_rate": self.coating_degradation_rate,
            "barnacle_growth_rate": self.barnacle_growth_rate,
            "roughness_rate": self.roughness_rate,
            "dt": self.dt,
        }


# ---------------------------------------------------------------------------
# Physics Transition Functions (pure, deterministic)
# ---------------------------------------------------------------------------

def standard_physical_transition(state: ShipState, inp: TransitionInput) -> ShipState:
    """
    The canonical deterministic physics transition.

    Equations:
        Δcorrosion_depth  = corrosion_rate × dt
        Δcoating_thickness = -coating_degradation_rate × dt  (clamped ≥ 0)
        Δbarnacle_density = barnacle_growth_rate × dt
        Δroughness        = roughness_rate × dt              (clamped ≥ 0)
        risk_score        = recomputed from new physical values

    This function is PURE: no side effects, no I/O, no randomness.
    Same (state, inp) → same output, always.
    """
    new_corrosion = state.corrosion_depth + inp.corrosion_rate * inp.dt
    new_coating = max(0.0, state.coating_thickness - inp.coating_degradation_rate * inp.dt)
    new_barnacle = max(0.0, state.barnacle_density + inp.barnacle_growth_rate * inp.dt)
    new_roughness = max(0.0, state.roughness + inp.roughness_rate * inp.dt)

    return ShipState.create(
        zone_id=state.zone_id,
        corrosion_depth=new_corrosion,
        coating_thickness=new_coating,
        barnacle_density=new_barnacle,
        roughness=new_roughness,
    )


def accelerated_corrosion_transition(state: ShipState, inp: TransitionInput) -> ShipState:
    """
    Accelerated corrosion model: corrosion rate increases as coating decreases.

    Δcorrosion = corrosion_rate × dt × (1 + 1/max(coating, ε))

    This models the physical reality that exposed steel corrodes faster.
    """
    coating_factor = 1.0 + 1.0 / max(state.coating_thickness, 1e-6)
    new_corrosion = state.corrosion_depth + inp.corrosion_rate * inp.dt * coating_factor
    new_coating = max(0.0, state.coating_thickness - inp.coating_degradation_rate * inp.dt)
    new_barnacle = max(0.0, state.barnacle_density + inp.barnacle_growth_rate * inp.dt)
    new_roughness = max(0.0, state.roughness + inp.roughness_rate * inp.dt)

    return ShipState.create(
        zone_id=state.zone_id,
        corrosion_depth=new_corrosion,
        coating_thickness=new_coating,
        barnacle_density=new_barnacle,
        roughness=new_roughness,
    )


# Type alias for transition functions
TransitionFunction = Callable[[ShipState, TransitionInput], ShipState]


# ---------------------------------------------------------------------------
# Transition Record (immutable, hashable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionRecord:
    """
    Immutable record of a single state transition.

    Fields:
        sequence_id     : int   — Monotonically increasing per-zone sequence
        zone_id         : str   — Which zone was transitioned
        input_hash      : str   — Hash of the TransitionInput
        pre_state_hash  : str   — Hash of state before transition
        post_state_hash : str   — Hash of state after transition
        prev_record_hash: str   — Hash of the previous TransitionRecord (chain)
        record_hash     : str   — Hash of THIS record (self-referential integrity)
        transition_name : str   — Name of the transition function used
    """
    sequence_id: int
    zone_id: str
    input_hash: str
    pre_state_hash: str
    post_state_hash: str
    prev_record_hash: str
    record_hash: str
    transition_name: str

    @staticmethod
    def compute_record_hash(sequence_id: int, zone_id: str,
                            input_hash: str, pre_hash: str,
                            post_hash: str, prev_hash: str,
                            transition_name: str) -> str:
        """Deterministic hash of the record fields."""
        h = hashlib.sha256()
        h.update(str(sequence_id).encode("utf-8"))
        h.update(zone_id.encode("utf-8"))
        h.update(input_hash.encode("utf-8"))
        h.update(pre_hash.encode("utf-8"))
        h.update(post_hash.encode("utf-8"))
        h.update(prev_hash.encode("utf-8"))
        h.update(transition_name.encode("utf-8"))
        return h.hexdigest()

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "zone_id": self.zone_id,
            "input_hash": self.input_hash,
            "pre_state_hash": self.pre_state_hash,
            "post_state_hash": self.post_state_hash,
            "prev_record_hash": self.prev_record_hash,
            "record_hash": self.record_hash,
            "transition_name": self.transition_name,
        }


# ---------------------------------------------------------------------------
# Deterministic Transition Engine
# ---------------------------------------------------------------------------

class DeterministicTransitionEngine:
    """
    Core engine that applies transitions and maintains a hash chain.

    Responsibilities:
        1. Register named transition functions
        2. Apply transitions to ShipState, producing new ShipState
        3. Log every transition as a TransitionRecord with hash chain
        4. Support replay: given ordered inputs, reproduce identical state

    Invariants:
        - Sequence ID is monotonically increasing (starts at 1)
        - Hash chain is unbroken: each record references the previous
        - No transition is applied without being logged
        - Same inputs in same order → same final state and same hash chain
    """

    # Genesis hash — the "previous record hash" for the very first record
    GENESIS_HASH = "0" * 64

    def __init__(self):
        self._transition_fns: Dict[str, TransitionFunction] = {}
        self._records: List[TransitionRecord] = []
        self._sequence_counter: int = 0

        # Register built-in transitions
        self.register_transition("standard", standard_physical_transition)
        self.register_transition("accelerated_corrosion", accelerated_corrosion_transition)

    # -------------------------------------------------------------------
    # Registration
    # -------------------------------------------------------------------

    def register_transition(self, name: str, fn: TransitionFunction):
        """Register a named transition function."""
        if name in self._transition_fns:
            raise ValueError(f"Transition '{name}' already registered")
        self._transition_fns[name] = fn

    def get_registered_transitions(self) -> List[str]:
        """Return names of all registered transition functions."""
        return sorted(self._transition_fns.keys())

    # -------------------------------------------------------------------
    # Core Transition
    # -------------------------------------------------------------------

    def apply(self, state: ShipState, inp: TransitionInput,
              transition_name: str = "standard") -> Tuple[ShipState, TransitionRecord]:
        """
        Apply a named transition to a ShipState.

        Args:
            state:           Current zone state
            inp:             Transition input (rates + dt)
            transition_name: Name of the registered transition function

        Returns:
            (new_state, record) — the evolved state and the transition record

        Raises:
            ValueError if transition_name is not registered
            ValueError if inp.zone_id doesn't match state.zone_id
        """
        if transition_name not in self._transition_fns:
            raise ValueError(
                f"Unknown transition '{transition_name}'. "
                f"Registered: {self.get_registered_transitions()}"
            )
        if inp.zone_id != state.zone_id:
            raise ValueError(
                f"Input zone_id '{inp.zone_id}' ≠ state zone_id '{state.zone_id}'"
            )

        # Execute the pure transition function
        fn = self._transition_fns[transition_name]
        new_state = fn(state, inp)

        # Build the record
        self._sequence_counter += 1
        prev_hash = (
            self._records[-1].record_hash
            if self._records
            else self.GENESIS_HASH
        )

        record_hash = TransitionRecord.compute_record_hash(
            sequence_id=self._sequence_counter,
            zone_id=state.zone_id,
            input_hash=inp.input_hash(),
            pre_hash=state.state_hash(),
            post_hash=new_state.state_hash(),
            prev_hash=prev_hash,
            transition_name=transition_name,
        )

        record = TransitionRecord(
            sequence_id=self._sequence_counter,
            zone_id=state.zone_id,
            input_hash=inp.input_hash(),
            pre_state_hash=state.state_hash(),
            post_state_hash=new_state.state_hash(),
            prev_record_hash=prev_hash,
            record_hash=record_hash,
            transition_name=transition_name,
        )

        self._records.append(record)
        return new_state, record

    # -------------------------------------------------------------------
    # Record Access
    # -------------------------------------------------------------------

    @property
    def records(self) -> List[TransitionRecord]:
        """Return the full transition record chain (read-only copy)."""
        return list(self._records)

    @property
    def chain_hash(self) -> str:
        """Return the hash of the last record (tip of the chain)."""
        return self._records[-1].record_hash if self._records else self.GENESIS_HASH

    @property
    def sequence_count(self) -> int:
        """Number of transitions applied."""
        return self._sequence_counter

    # -------------------------------------------------------------------
    # Chain Verification
    # -------------------------------------------------------------------

    def verify_chain_integrity(self) -> Tuple[bool, Optional[str]]:
        """
        Verify the hash chain is unbroken.

        Returns:
            (is_valid, error_message) — True if chain is intact
        """
        prev_hash = self.GENESIS_HASH
        for i, record in enumerate(self._records):
            if record.prev_record_hash != prev_hash:
                return False, (
                    f"Chain break at sequence_id={record.sequence_id}: "
                    f"expected prev_hash={prev_hash[:16]}..., "
                    f"got {record.prev_record_hash[:16]}..."
                )

            expected = TransitionRecord.compute_record_hash(
                record.sequence_id, record.zone_id,
                record.input_hash, record.pre_state_hash,
                record.post_state_hash, record.prev_record_hash,
                record.transition_name,
            )
            if record.record_hash != expected:
                return False, (
                    f"Record hash mismatch at sequence_id={record.sequence_id}: "
                    f"expected={expected[:16]}..., got={record.record_hash[:16]}..."
                )

            prev_hash = record.record_hash

        return True, None

    def get_records_for_zone(self, zone_id: str) -> List[TransitionRecord]:
        """Return all transition records for a specific zone."""
        return [r for r in self._records if r.zone_id == zone_id]


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== transition_engine.py — Self Test ===\n")

    # Create initial state
    state = ShipState.create("bow", corrosion_depth=0.1, coating_thickness=5.0,
                             barnacle_density=1.0, roughness=0.2)
    print(f"  Initial: {state}")

    # Create transition input
    inp = TransitionInput(
        zone_id="bow",
        corrosion_rate=0.05,
        coating_degradation_rate=0.02,
        barnacle_growth_rate=0.5,
        roughness_rate=0.01,
        dt=1.0,
    )
    print(f"  Input:   rate={inp.corrosion_rate}, dt={inp.dt}")

    # Apply standard transition
    engine = DeterministicTransitionEngine()
    new_state, record = engine.apply(state, inp, "standard")
    print(f"  After:   {new_state}")
    print(f"  Record:  seq={record.sequence_id}, chain_tip={record.record_hash[:16]}...")

    # Apply again
    inp2 = TransitionInput(
        zone_id="bow",
        corrosion_rate=0.05,
        coating_degradation_rate=0.02,
        barnacle_growth_rate=0.5,
        roughness_rate=0.01,
        dt=1.0,
    )
    new_state2, record2 = engine.apply(new_state, inp2, "standard")
    print(f"  After 2: {new_state2}")

    # Verify chain
    valid, err = engine.verify_chain_integrity()
    assert valid, f"Chain integrity failed: {err}"
    print(f"  Chain integrity: VALID ✓")

    # Replay test: create fresh engine, apply same inputs → same result
    engine2 = DeterministicTransitionEngine()
    replay_state = state
    replay_state, _ = engine2.apply(replay_state, inp, "standard")
    replay_state, _ = engine2.apply(replay_state, inp2, "standard")
    assert replay_state.state_hash() == new_state2.state_hash(), "Replay hash mismatch!"
    assert engine2.chain_hash == engine.chain_hash, "Chain hash mismatch!"
    print(f"  Replay determinism: VERIFIED ✓")

    print("\n✓ transition_engine.py — All self-tests passed.")
