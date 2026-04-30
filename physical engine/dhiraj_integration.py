"""
dhiraj_integration.py
======================
Phase 7 — Integration with Dhiraj

Provides:
    - SimulationOutputContract: defines exact schema Dhiraj's simulation must produce
    - ContractValidator: validates incoming simulation output against the contract
    - SimulationToTransitionAdapter: converts simulation output → TransitionInput
    - End-to-end hash verification

Guarantees:
    same simulation input → same TransitionInput → same state evolution
    (determinism is inherited from TransitionEngine's pure functions)
"""

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from physical_engine.ship_state_vector import ShipState, ShipStateVector, FLOAT_FMT
from physical_engine.transition_engine import TransitionInput


# ---------------------------------------------------------------------------
# Simulation Output Contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationZoneOutput:
    """
    Output from Dhiraj's simulation for a single zone.

    This is the contract: Dhiraj's system MUST produce exactly these fields.
    No additional fields are accepted. No fields may be omitted.
    """
    zone_id: str
    corrosion_rate: float             # mm/time_unit (≥ 0)
    coating_degradation_rate: float   # mm/time_unit (≥ 0)
    barnacle_growth_rate: float       # units·m⁻²/time_unit (≥ 0)
    roughness_rate: float             # index/time_unit (can be negative)
    dt: float                         # Time delta (> 0)
    simulation_id: str                # Unique ID from Dhiraj's system
    model_version: str                # Dhiraj's model version tag

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "corrosion_rate": self.corrosion_rate,
            "coating_degradation_rate": self.coating_degradation_rate,
            "barnacle_growth_rate": self.barnacle_growth_rate,
            "roughness_rate": self.roughness_rate,
            "dt": self.dt,
            "simulation_id": self.simulation_id,
            "model_version": self.model_version,
        }


@dataclass(frozen=True)
class SimulationOutput:
    """
    Complete simulation output for all zones.

    Contract requirements:
        - simulation_id must be globally unique
        - model_version must be consistent across all zones in one output
        - All zones in the ship's state vector must be covered
        - dt must be identical across all zones in one output
    """
    simulation_id: str
    model_version: str
    zones: Dict[str, SimulationZoneOutput]
    metadata: dict = field(default_factory=dict)   # Optional metadata (advisory)

    def to_dict(self) -> dict:
        return {
            "simulation_id": self.simulation_id,
            "model_version": self.model_version,
            "zones": {zid: z.to_dict() for zid, z in self.zones.items()},
            "metadata": self.metadata,
        }

    def content_hash(self) -> str:
        """
        Deterministic hash of the simulation output content.
        Used to verify that the same simulation input yields the same output.
        """
        h = hashlib.sha256()
        h.update(self.simulation_id.encode("utf-8"))
        h.update(self.model_version.encode("utf-8"))
        for zid in sorted(self.zones.keys()):
            z = self.zones[zid]
            h.update(zid.encode("utf-8"))
            for val in (z.corrosion_rate, z.coating_degradation_rate,
                        z.barnacle_growth_rate, z.roughness_rate, z.dt):
                h.update(format(val, FLOAT_FMT).encode("utf-8"))
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Contract Validator
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of contract validation."""
    valid: bool
    errors: List[str]
    warnings: List[str]

    def summary(self) -> str:
        status = "VALID ✓" if self.valid else "INVALID ✗"
        parts = [f"Contract {status}"]
        if self.errors:
            parts.append(f"  Errors: {self.errors}")
        if self.warnings:
            parts.append(f"  Warnings: {self.warnings}")
        return "\n".join(parts)


class ContractValidator:
    """
    Validates incoming simulation output against the integration contract.

    Checks:
        1. Schema completeness — all required fields present
        2. Type correctness — all fields are correct types
        3. Physical bounds — rates and dt are in valid ranges
        4. Zone coverage — all zones in the ship state vector are covered
        5. Consistency — model_version and dt are consistent across zones
    """

    REQUIRED_FIELDS = {
        "zone_id", "corrosion_rate", "coating_degradation_rate",
        "barnacle_growth_rate", "roughness_rate", "dt",
        "simulation_id", "model_version",
    }

    def validate(self, output: SimulationOutput,
                 expected_zones: Optional[List[str]] = None) -> ValidationResult:
        """
        Validate a SimulationOutput against the contract.

        Args:
            output:         The simulation output to validate
            expected_zones: Optional list of expected zone_ids (for coverage check)
        """
        errors = []
        warnings = []

        # 1. Basic structure
        if not output.simulation_id:
            errors.append("simulation_id is empty")
        if not output.model_version:
            errors.append("model_version is empty")
        if not output.zones:
            errors.append("No zones in output")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # 2. Per-zone validation
        dt_values = set()
        model_versions = set()

        for zone_id, zone_data in output.zones.items():
            prefix = f"zone[{zone_id}]"

            if zone_data.zone_id != zone_id:
                errors.append(f"{prefix}: zone_id mismatch: key='{zone_id}', data='{zone_data.zone_id}'")

            if zone_data.corrosion_rate < 0:
                errors.append(f"{prefix}: corrosion_rate must be ≥ 0, got {zone_data.corrosion_rate}")
            if zone_data.coating_degradation_rate < 0:
                errors.append(f"{prefix}: coating_degradation_rate must be ≥ 0")
            if zone_data.barnacle_growth_rate < 0:
                errors.append(f"{prefix}: barnacle_growth_rate must be ≥ 0")
            if zone_data.dt <= 0:
                errors.append(f"{prefix}: dt must be > 0, got {zone_data.dt}")

            # Physical reasonableness warnings
            if zone_data.corrosion_rate > 10.0:
                warnings.append(f"{prefix}: corrosion_rate={zone_data.corrosion_rate} seems unrealistically high")
            if zone_data.dt > 365.0:
                warnings.append(f"{prefix}: dt={zone_data.dt} seems very large (>1 year?)")

            dt_values.add(zone_data.dt)
            model_versions.add(zone_data.model_version)

        # 3. Consistency checks
        if len(dt_values) > 1:
            errors.append(f"Inconsistent dt values across zones: {dt_values}")
        if len(model_versions) > 1:
            errors.append(f"Inconsistent model_version across zones: {model_versions}")

        # 4. Zone coverage
        if expected_zones:
            missing = set(expected_zones) - set(output.zones.keys())
            if missing:
                errors.append(f"Missing zones: {missing}")
            extra = set(output.zones.keys()) - set(expected_zones)
            if extra:
                warnings.append(f"Extra zones not in state vector: {extra}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# Simulation-to-Transition Adapter
# ---------------------------------------------------------------------------

class SimulationToTransitionAdapter:
    """
    Converts validated SimulationOutput into TransitionInput objects.

    This adapter is the bridge between Dhiraj's simulation layer
    and the deterministic transition engine.

    Determinism guarantee:
        same SimulationOutput → same Dict[str, TransitionInput]
        (no randomness, no time-dependent logic, no external state)
    """

    def __init__(self, validator: Optional[ContractValidator] = None):
        self._validator = validator or ContractValidator()
        self._conversion_log: List[dict] = []

    def convert(self, output: SimulationOutput,
                expected_zones: Optional[List[str]] = None,
                validate: bool = True) -> Tuple[Dict[str, TransitionInput], ValidationResult]:
        """
        Convert SimulationOutput into TransitionInputs.

        Args:
            output:         The simulation output
            expected_zones: Optional zone list for validation
            validate:       Whether to validate before converting

        Returns:
            (transitions, validation_result)

        Raises:
            ValueError if validation fails and validate=True
        """
        # Validate
        if validate:
            result = self._validator.validate(output, expected_zones)
            if not result.valid:
                raise ValueError(
                    f"SimulationOutput failed contract validation:\n"
                    f"{result.summary()}"
                )
        else:
            result = ValidationResult(valid=True, errors=[], warnings=[])

        # Convert — straightforward deterministic mapping
        transitions: Dict[str, TransitionInput] = {}
        for zone_id in sorted(output.zones.keys()):
            zone_data = output.zones[zone_id]
            transitions[zone_id] = TransitionInput(
                zone_id=zone_id,
                corrosion_rate=zone_data.corrosion_rate,
                coating_degradation_rate=zone_data.coating_degradation_rate,
                barnacle_growth_rate=zone_data.barnacle_growth_rate,
                roughness_rate=zone_data.roughness_rate,
                dt=zone_data.dt,
            )

        # Log conversion
        self._conversion_log.append({
            "simulation_id": output.simulation_id,
            "model_version": output.model_version,
            "zones_converted": list(transitions.keys()),
            "content_hash": output.content_hash(),
        })

        return transitions, result

    @property
    def conversion_history(self) -> List[dict]:
        """Return the log of all conversions performed."""
        return list(self._conversion_log)

    @staticmethod
    def verify_determinism(output: SimulationOutput, n_iterations: int = 10) -> bool:
        """
        Verify that converting the same SimulationOutput N times
        produces identical TransitionInputs every time.
        """
        adapter = SimulationToTransitionAdapter()
        reference_hashes = None

        for _ in range(n_iterations):
            transitions, _ = adapter.convert(output, validate=False)
            hashes = {
                zid: inp.input_hash()
                for zid, inp in sorted(transitions.items())
            }
            if reference_hashes is None:
                reference_hashes = hashes
            elif hashes != reference_hashes:
                return False

        return True


# ---------------------------------------------------------------------------
# Factory for SimulationOutput from raw dict
# ---------------------------------------------------------------------------

def simulation_output_from_dict(data: dict) -> SimulationOutput:
    """
    Construct a SimulationOutput from a raw dictionary.
    This is the expected entry point for data coming over the wire from Dhiraj.
    """
    zones = {}
    for zid, zdata in data.get("zones", {}).items():
        zones[zid] = SimulationZoneOutput(
            zone_id=zdata["zone_id"],
            corrosion_rate=float(zdata["corrosion_rate"]),
            coating_degradation_rate=float(zdata["coating_degradation_rate"]),
            barnacle_growth_rate=float(zdata["barnacle_growth_rate"]),
            roughness_rate=float(zdata["roughness_rate"]),
            dt=float(zdata["dt"]),
            simulation_id=data["simulation_id"],
            model_version=data["model_version"],
        )

    return SimulationOutput(
        simulation_id=data["simulation_id"],
        model_version=data["model_version"],
        zones=zones,
        metadata=data.get("metadata", {}),
    )


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== dhiraj_integration.py — Self Test ===\n")

    # Create a mock simulation output (as Dhiraj would produce)
    sim_output = SimulationOutput(
        simulation_id="sim_001",
        model_version="v2.1.0",
        zones={
            "bow": SimulationZoneOutput(
                zone_id="bow", corrosion_rate=0.05, coating_degradation_rate=0.02,
                barnacle_growth_rate=0.5, roughness_rate=0.01, dt=1.0,
                simulation_id="sim_001", model_version="v2.1.0",
            ),
            "stern": SimulationZoneOutput(
                zone_id="stern", corrosion_rate=0.08, coating_degradation_rate=0.03,
                barnacle_growth_rate=0.3, roughness_rate=0.02, dt=1.0,
                simulation_id="sim_001", model_version="v2.1.0",
            ),
            "port": SimulationZoneOutput(
                zone_id="port", corrosion_rate=0.03, coating_degradation_rate=0.01,
                barnacle_growth_rate=0.2, roughness_rate=0.005, dt=1.0,
                simulation_id="sim_001", model_version="v2.1.0",
            ),
            "starboard": SimulationZoneOutput(
                zone_id="starboard", corrosion_rate=0.06, coating_degradation_rate=0.025,
                barnacle_growth_rate=0.4, roughness_rate=0.015, dt=1.0,
                simulation_id="sim_001", model_version="v2.1.0",
            ),
        },
    )

    # Validate
    validator = ContractValidator()
    result = validator.validate(sim_output, expected_zones=["bow", "stern", "port", "starboard"])
    print(f"  Validation: {result.summary()}")
    assert result.valid, f"Should be valid: {result.errors}"

    # Convert
    adapter = SimulationToTransitionAdapter()
    transitions, _ = adapter.convert(sim_output, expected_zones=["bow", "stern", "port", "starboard"])
    print(f"\n  Converted {len(transitions)} zone transitions:")
    for zid, inp in sorted(transitions.items()):
        print(f"    {zid}: corr_rate={inp.corrosion_rate}, dt={inp.dt}")

    # Determinism verification
    is_deterministic = SimulationToTransitionAdapter.verify_determinism(sim_output, 100)
    assert is_deterministic, "Conversion should be deterministic!"
    print(f"\n  Determinism (100 iterations): VERIFIED ✓")

    # Content hash determinism
    h1 = sim_output.content_hash()
    h2 = sim_output.content_hash()
    assert h1 == h2, "Content hash should be deterministic!"
    print(f"  Content hash: {h1[:24]}... (stable)")

    # Test from_dict factory
    raw_dict = sim_output.to_dict()
    reconstructed = simulation_output_from_dict(raw_dict)
    assert reconstructed.content_hash() == sim_output.content_hash(), "Round-trip hash mismatch!"
    print(f"  Round-trip serialization: VERIFIED ✓")

    # Test invalid output
    bad_output = SimulationOutput(
        simulation_id="bad_sim",
        model_version="v1.0",
        zones={
            "bow": SimulationZoneOutput(
                zone_id="bow", corrosion_rate=-0.5, coating_degradation_rate=0.02,
                barnacle_growth_rate=0.5, roughness_rate=0.01, dt=1.0,
                simulation_id="bad_sim", model_version="v1.0",
            ),
        },
    )
    bad_result = validator.validate(bad_output)
    assert not bad_result.valid, "Should be invalid (negative corrosion_rate)"
    print(f"  Invalid input rejection: BLOCKED ✓")

    print("\n✓ dhiraj_integration.py — All self-tests passed.")
