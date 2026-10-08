"""Independent analytic fixtures passed through the real CardiEP adapter."""

from __future__ import annotations

import hashlib
import math
from importlib.metadata import distribution
from pathlib import Path

from .models import ArtifactRef, InterventionRunRequest
from .serialization import write_json
from .service import CardiTherapyService

CARDIEP_REVISION = "2bcdd1ec2e282c1986d91459a0c39cea5b3ade15"


def _ref(path, artifact_id, kind):
    return ArtifactRef(
        artifact_id=artifact_id,
        kind=kind,
        uri=path.as_uri(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def make_request(root: Path, *, native=False, speed=0.1, unit="cm"):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    factor = {"cm": 1, "mm": 10}[unit]
    vertices = [[0, 0, 0], [factor, 0, 0], [0, factor, 0]]
    if native:
        vertices.append([0, 0, factor])
        payload = {
            "schema_version": "cardiep-geometry-v1",
            "coordinate_unit": unit,
            "node_xyz": vertices,
            "tetrahedra": [[0, 1, 2, 3]],
        }
    else:
        payload = {
            "schema_version": "cardiep-surface-v1",
            "coordinate_unit": unit,
            "vertices": vertices,
            "triangles": [[0, 1, 2]],
        }
    anatomy = root / "anatomy.json"
    state = root / "state.json"
    write_json(anatomy, payload)
    write_json(state, {"subject_id": "analytic-fixture", "status": "synthetic"})
    root_key = "root_nodes" if native else "root_node"
    return InterventionRunRequest.model_validate(
        {
            "subject_id": "analytic-fixture",
            "backend": "cardiep-pacing-v1",
            "twin_state_ref": _ref(state, "state", "cardiac_state").model_dump(),
            "baseline_refs": [
                _ref(anatomy, "anatomy", "tetra_mesh" if native else "surface_mesh").model_dump()
            ],
            "plan": {
                "plan_id": "analytic-pacing",
                "endpoints": ["activation_min_ms", "activation_max_ms", "activation_span_ms"],
                "arms": [
                    {"arm_id": "control", "label": "Root zero", "is_comparator": True},
                    {
                        "arm_id": "paced",
                        "label": "Root one",
                        "interventions": [
                            {
                                "intervention_id": "pace",
                                "kind": "pacing",
                                "target": "mesh root index 1",
                                "parameters": {root_key: [1] if native else 1},
                            }
                        ],
                    },
                ],
            },
            "settings": {
                "ep_backend": "numpy-eikonal-v1" if native else "surface-eikonal-v1",
                "ep_parameters": {"isotropic_speed_cm_per_ms": speed},
                "ep_parameter_units": {"isotropic_speed_cm_per_ms": "cm/ms"},
                "ep_settings": {
                    root_key: [0] if native else 0,
                    **({"with_ecg": False} if native else {}),
                    "output_dir": str(root / "outputs"),
                },
            },
        }
    )


def run_cpu_validation(root: Path):
    service = CardiTherapyService()
    checks = []
    for native in (False, True):
        for speed in (0.05, 0.1, 0.2):
            for unit in ("cm",) if native else ("cm", "mm"):
                request = make_request(
                    root / f"{native}-{speed}-{unit}", native=native, speed=speed, unit=unit
                )
                result = service.run(request)
                repeated = service.run(request)
                expected = {"control": 1 / speed, "paced": math.sqrt(2) / speed}
                error = max(
                    abs(
                        item.value
                        - (0 if item.endpoint == "activation_min_ms" else expected[item.arm_id])
                    )
                    for item in result.outcomes
                )
                identical = result.model_dump() == repeated.model_dump()
                passed = (
                    error < 1e-10 and identical and result.validation_status == "software_checked"
                )
                checks.append(
                    {
                        "delegate": request.settings["ep_backend"],
                        "speed_cm_per_ms": speed,
                        "coordinate_unit": unit,
                        "maximum_absolute_error_ms": error,
                        "deterministic": identical,
                        "passed": passed,
                        "outcomes": [
                            item.model_dump(mode="json", exclude={"artifact_ref"})
                            for item in result.outcomes
                        ],
                    }
                )
    import json

    import cardiep

    delegate_root = Path(cardiep.__file__).resolve().parent
    direct_url_text = distribution("virelion-cardiep").read_text("direct_url.json")
    vcs_info = json.loads(direct_url_text).get("vcs_info", {}) if direct_url_text else {}
    installed_commit = vcs_info.get("commit_id")
    if installed_commit is not None and installed_commit != CARDIEP_REVISION:
        raise ValueError("Installed CardiEP revision differs from configured validation pin")
    return {
        "schema_version": "carditherapy-cpu-validation-v1",
        "computational_status": "passed" if all(item["passed"] for item in checks) else "failed",
        "fixture_status": "synthetic analytic geometry; no patient data",
        "independent_reference": "direct Euclidean edge distance / isotropic speed; triangle and tetrahedron are complete graphs",
        "configured_cardiep_revision": CARDIEP_REVISION,
        "installed_cardiep_vcs_commit": installed_commit,
        "installed_cardiep_version": cardiep.__version__,
        "delegate_source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(delegate_root.glob("*.py"))
        },
        "checks": checks,
        "empirical_status": "not_validated",
        "limitations": [
            "Activation span is not measured ECG QRS duration.",
            "Posterior references do not propagate uncertainty.",
            "Twin-state references establish lineage, not a personalized electrophysiology model.",
            "No held-out observed pacing responses or clinical outcomes tested.",
            "Non-pacing therapy classes have contracts only, no executable validated backend.",
        ],
    }
