"""
ship_state_vector.py
=====================
Phase 1 — Formal State Vector Definition

Defines the strict, typed, hashable ShipState and ShipStateVector.

ShipState:
    A single hull zone's physical state at a point in time.
    Frozen dataclass — immutable after construction.

ShipStateVector:
    An ordered collection of ShipState objects keyed by zone_id.
    Deterministic iteration (sorted by zone_id) and global hash.

Guarantees:
    - No ambiguity: every field has a fixed type and precision contract
    - Fixed schema: exactly 6 fields per zone, no optional/nullable fields
    - Hashable: deterministic SHA-256 at 8-decimal fixed precision
    - Immutable: frozen dataclass with no mutation methods
"""

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Precision Constants
# ---------------------------------------------------------------------------

HASH_PRECISION = 8          # Decimal places for hash string encoding
FLOAT_FMT = f".{HASH_PRECISION}f"


# ---------------------------------------------------------------------------
# Risk Score Computation (deterministic, pure function)
# ---------------------------------------------------------------------------

# Weights for the risk score formula — tunable but fixed at compile time
_W_CORROSION = 0.35
_W_COATING_INV = 0.25
_W_BARNACLE = 0.20
_W_ROUGHNESS = 0.20
_COATING_EPSILON = 1e-6     # Prevents division by zero


def compute_risk_score(corrosion_depth: float,
                       coating_thickness: float,
                       barnacle_density: float,
                       roughness: float) -> float:
    """
    Deterministic risk score computation.

    Formula:
        risk = w1 * corrosion_depth
             + w2 * (1 / max(coating_thickness, ε))
             + w3 * barnacle_density
             + w4 * roughness

    Returns a non-negative float. Higher = worse condition.
    """
    coating_inv = 1.0 / max(coating_thickness, _COATING_EPSILON)
    raw = (
        _W_CORROSION * corrosion_depth
        + _W_COATING_INV * coating_inv
        + _W_BARNACLE * barnacle_density
        + _W_ROUGHNESS * roughness
    )
    return round(raw, HASH_PRECISION)


# ---------------------------------------------------------------------------
# ShipState — Single Zone Physical State
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShipState:
    """
    Immutable physical state of a single ship hull zone.

    Fields:
        zone_id            : str   — Unique zone identifier (e.g. "bow", "stern")
        corrosion_depth    : float — Cumulative corrosion depth in mm
        coating_thickness  : float — Remaining coating thickness in mm (≥ 0)
        barnacle_density   : float — Organism density in units/m² (≥ 0)
        roughness          : float — Surface roughness index (≥ 0)
        risk_score         : float — Computed risk metric (deterministic)

    Invariants:
        - coating_thickness ≥ 0
        - barnacle_density ≥ 0
        - roughness ≥ 0
        - risk_score = f(corrosion_depth, coating_thickness, barnacle_density, roughness)
    """
    zone_id: str
    corrosion_depth: float
    coating_thickness: float
    barnacle_density: float
    roughness: float
    risk_score: float

    def __post_init__(self):
        """Validate physical constraints at construction time."""
        if not self.zone_id or not isinstance(self.zone_id, str):
            raise ValueError(f"zone_id must be a non-empty string, got: {self.zone_id!r}")
        if self.coating_thickness < 0:
            raise ValueError(f"coating_thickness must be ≥ 0, got: {self.coating_thickness}")
        if self.barnacle_density < 0:
            raise ValueError(f"barnacle_density must be ≥ 0, got: {self.barnacle_density}")
        if self.roughness < 0:
            raise ValueError(f"roughness must be ≥ 0, got: {self.roughness}")

    # -------------------------------------------------------------------
    # Factory
    # -------------------------------------------------------------------

    @staticmethod
    def create(zone_id: str,
               corrosion_depth: float = 0.0,
               coating_thickness: float = 5.0,
               barnacle_density: float = 0.0,
               roughness: float = 0.0) -> "ShipState":
        """
        Factory that auto-computes risk_score from physical parameters.
        This is the ONLY sanctioned way to construct a ShipState from raw values.
        """
        risk = compute_risk_score(corrosion_depth, coating_thickness,
                                  barnacle_density, roughness)
        return ShipState(
            zone_id=zone_id,
            corrosion_depth=corrosion_depth,
            coating_thickness=coating_thickness,
            barnacle_density=barnacle_density,
            roughness=roughness,
            risk_score=risk,
        )

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Deterministic dictionary representation."""
        return {
            "zone_id": self.zone_id,
            "corrosion_depth": self.corrosion_depth,
            "coating_thickness": self.coating_thickness,
            "barnacle_density": self.barnacle_density,
            "roughness": self.roughness,
            "risk_score": self.risk_score,
        }

    @staticmethod
    def from_dict(d: dict) -> "ShipState":
        """Reconstruct from dictionary. Recomputes risk_score for integrity."""
        return ShipState.create(
            zone_id=d["zone_id"],
            corrosion_depth=d["corrosion_depth"],
            coating_thickness=d["coating_thickness"],
            barnacle_density=d["barnacle_density"],
            roughness=d["roughness"],
        )

    # -------------------------------------------------------------------
    # Hash
    # -------------------------------------------------------------------

    def state_hash(self) -> str:
        """
        Deterministic SHA-256 hash of this zone's state.
        Uses fixed-precision float formatting to avoid cross-platform drift.
        """
        h = hashlib.sha256()
        h.update(self.zone_id.encode("utf-8"))
        fields = (
            self.corrosion_depth,
            self.coating_thickness,
            self.barnacle_density,
            self.roughness,
            self.risk_score,
        )
        for val in fields:
            h.update(format(val, FLOAT_FMT).encode("utf-8"))
        return h.hexdigest()

    # -------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ShipState(zone={self.zone_id}, "
            f"corr={self.corrosion_depth:{FLOAT_FMT}}, "
            f"coat={self.coating_thickness:{FLOAT_FMT}}, "
            f"barn={self.barnacle_density:{FLOAT_FMT}}, "
            f"rough={self.roughness:{FLOAT_FMT}}, "
            f"risk={self.risk_score:{FLOAT_FMT}})"
        )


# ---------------------------------------------------------------------------
# ShipStateVector — Multi-Zone Ordered Collection
# ---------------------------------------------------------------------------

class ShipStateVector:
    """
    Ordered collection of ShipState objects, keyed by zone_id.

    Guarantees:
        - Iteration always in sorted zone_id order
        - Global hash is deterministic and ordering-independent
          (sorted internally, so insertion order is irrelevant)
        - No zone can be silently overwritten — explicit API only
    """

    def __init__(self, zones: Optional[Dict[str, ShipState]] = None):
        self._zones: Dict[str, ShipState] = {}
        if zones:
            for zid in sorted(zones.keys()):
                state = zones[zid]
                if state.zone_id != zid:
                    raise ValueError(
                        f"Zone key '{zid}' does not match state.zone_id '{state.zone_id}'"
                    )
                self._zones[zid] = state

    # -------------------------------------------------------------------
    # Accessors
    # -------------------------------------------------------------------

    def get(self, zone_id: str) -> Optional[ShipState]:
        """Retrieve state for a specific zone. Returns None if not found."""
        return self._zones.get(zone_id)

    def get_all(self) -> Dict[str, ShipState]:
        """Return a copy of all zones in sorted order."""
        return {k: self._zones[k] for k in sorted(self._zones.keys())}

    def zone_ids(self) -> List[str]:
        """Return sorted list of zone IDs."""
        return sorted(self._zones.keys())

    def __len__(self) -> int:
        return len(self._zones)

    def __contains__(self, zone_id: str) -> bool:
        return zone_id in self._zones

    # -------------------------------------------------------------------
    # Mutation (returns new vector — originals are immutable)
    # -------------------------------------------------------------------

    def with_updated_zone(self, new_state: ShipState) -> "ShipStateVector":
        """
        Returns a NEW ShipStateVector with the specified zone replaced.
        The original vector is NOT modified.
        """
        if new_state.zone_id not in self._zones:
            raise ValueError(f"Zone '{new_state.zone_id}' does not exist in this vector")
        new_zones = dict(self._zones)
        new_zones[new_state.zone_id] = new_state
        return ShipStateVector(new_zones)

    def with_updated_zones(self, updates: Dict[str, ShipState]) -> "ShipStateVector":
        """
        Returns a NEW ShipStateVector with multiple zones replaced.
        All updates are applied atomically.
        """
        new_zones = dict(self._zones)
        for zid, state in updates.items():
            if zid not in self._zones:
                raise ValueError(f"Zone '{zid}' does not exist in this vector")
            if state.zone_id != zid:
                raise ValueError(f"Zone key '{zid}' ≠ state.zone_id '{state.zone_id}'")
            new_zones[zid] = state
        return ShipStateVector(new_zones)

    # -------------------------------------------------------------------
    # Hash
    # -------------------------------------------------------------------

    def global_hash(self) -> str:
        """
        Deterministic SHA-256 hash of the entire state vector.
        Iterates zones in sorted order — insertion order is irrelevant.
        """
        h = hashlib.sha256()
        for zid in sorted(self._zones.keys()):
            zone_hash = self._zones[zid].state_hash()
            h.update(zid.encode("utf-8"))
            h.update(zone_hash.encode("utf-8"))
        return h.hexdigest()

    # -------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Deterministic dictionary of all zones."""
        return {zid: self._zones[zid].to_dict() for zid in sorted(self._zones.keys())}

    @staticmethod
    def from_dict(d: dict) -> "ShipStateVector":
        """Reconstruct from dictionary."""
        zones = {}
        for zid, zdata in d.items():
            zones[zid] = ShipState.from_dict(zdata)
        return ShipStateVector(zones)

    # -------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------

    def __repr__(self) -> str:
        zone_strs = ", ".join(
            f"{zid}: risk={self._zones[zid].risk_score:{FLOAT_FMT}}"
            for zid in sorted(self._zones.keys())
        )
        return f"ShipStateVector({{{zone_strs}}})"


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== ship_state_vector.py — Self Test ===\n")

    # Create zones
    bow = ShipState.create("bow", corrosion_depth=0.1, coating_thickness=4.5,
                           barnacle_density=2.0, roughness=0.3)
    stern = ShipState.create("stern", corrosion_depth=0.3, coating_thickness=3.0,
                             barnacle_density=5.0, roughness=0.8)
    port = ShipState.create("port", corrosion_depth=0.05, coating_thickness=5.0,
                            barnacle_density=0.5, roughness=0.1)
    starboard = ShipState.create("starboard", corrosion_depth=0.2, coating_thickness=4.0,
                                  barnacle_density=3.0, roughness=0.5)

    print(f"  {bow}")
    print(f"  {stern}")
    print(f"  {port}")
    print(f"  {starboard}")

    # Build vector
    vec = ShipStateVector({
        "bow": bow, "stern": stern, "port": port, "starboard": starboard
    })
    print(f"\n  Vector: {vec}")
    print(f"  Global hash: {vec.global_hash()[:24]}...")

    # Verify round-trip serialization
    d = vec.to_dict()
    vec2 = ShipStateVector.from_dict(d)
    assert vec.global_hash() == vec2.global_hash(), "Round-trip hash mismatch!"

    # Verify immutability: update returns new vector
    new_bow = ShipState.create("bow", corrosion_depth=0.5, coating_thickness=3.0,
                               barnacle_density=4.0, roughness=0.6)
    vec3 = vec.with_updated_zone(new_bow)
    assert vec.global_hash() != vec3.global_hash(), "Update should produce different hash!"
    assert vec.get("bow").corrosion_depth == 0.1, "Original should be unchanged!"
    assert vec3.get("bow").corrosion_depth == 0.5, "New vector should have update!"

    # Hash determinism
    h1 = vec.global_hash()
    h2 = vec.global_hash()
    assert h1 == h2, "Hash should be deterministic!"

    print("\n✓ ship_state_vector.py — All self-tests passed.")
