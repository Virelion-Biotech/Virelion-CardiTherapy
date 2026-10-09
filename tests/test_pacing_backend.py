from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from carditherapy import (
    PACING_BACKEND_NAME,
    ArtifactRef,
    CardiEPPacingBackend,
    CardiTherapyService,
    Intervention,
    InterventionArm,
    InterventionPlan,
    InterventionRunRequest,
)


class _FakeEPAPI:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = []

    def simulate(self, payload):
        self.calls.append(payload)
        arm_index = len(self.calls) - 1
        summary = self.root / f"summary-{arm_index}.json"
        root_node = payload["settings"].get("root_node", 0)
        span = 120.0 - 10.0 * float(root_node)
        summary.write_text(
            json.dumps(
                {
                    "activation_min_ms": 5.0,
                    "activation_max_ms": 5.0 + span,
                    "activation_span_ms": span,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "contract_version": "1.0",
            "subject_id": payload["subject_id"],
            "backend": payload["backend"],
            "parameters": payload["parameters"],
            "outputs": [
                {
                    "artifact_id": f"summary-{arm_index}",
                    "kind": "ep_summary",
                    "uri": summary.resolve().as_uri(),
                    "sha256": hashlib.sha256(summary.read_bytes()).hexdigest(),
                    "metadata": {},
                }
            ],
            "validation_status": "software_checked",
            "warnings": [],
            "provenance": {"fake": True},
        }


def _request(tmp_path: Path) -> InterventionRunRequest:
    anatomy = tmp_path / "surface.json"
    anatomy.write_text("{}\n", encoding="utf-8")
    return InterventionRunRequest(
        subject_id="S1",
        backend=PACING_BACKEND_NAME,
        twin_state_ref=ArtifactRef(
            artifact_id="twin",
            kind="cardiac_state",
            uri="memory://state",
        ),
        baseline_refs=[
            ArtifactRef(
                artifact_id="surface",
                kind="surface_mesh",
                uri=anatomy.resolve().as_uri(),
                metadata={"coordinate_frame": "test"},
            )
        ],
        plan=InterventionPlan(
            plan_id="pacing-plan",
            endpoints=["activation_span_ms"],
            arms=[
                InterventionArm(
                    arm_id="control",
                    label="Baseline",
                    is_comparator=True,
                ),
                InterventionArm(
                    arm_id="paced",
                    label="Alternative pacing root",
                    interventions=[
                        Intervention(
                            intervention_id="pace-1",
                            kind="pacing",
                            target="surface vertex 2",
                            parameters={"root_node": 2},
                            model_service="CardiEP",
                            model_capability="ep.simulate",
                        )
                    ],
                ),
            ],
        ),
        settings={
            "ep_backend": "surface-eikonal-v1",
            "ep_parameters": {"isotropic_speed_cm_per_ms": 0.1},
            "ep_settings": {"root_node": 0},
        },
    )


def test_cardiep_pacing_backend_delegates_each_arm_and_returns_endpoints(
    tmp_path: Path,
) -> None:
    api = _FakeEPAPI(tmp_path)
    backend = CardiEPPacingBackend(api_factory=lambda: api)
    result = CardiTherapyService(
        backends=[backend],
        register_defaults=False,
    ).run(_request(tmp_path))

    assert result.backend == PACING_BACKEND_NAME
    assert result.validation_status == "software_checked"
    assert [item.arm_id for item in result.outcomes] == ["control", "paced"]
    assert all(item.endpoint_tier == "electrical" for item in result.outcomes)
    assert result.outcomes[0].value == pytest.approx(120.0)
    assert result.outcomes[1].value == pytest.approx(100.0)
    assert api.calls[0]["settings"]["root_node"] == 0
    assert api.calls[1]["settings"]["root_node"] == 2


def test_cardiep_pacing_backend_rejects_non_pacing_intervention(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    request.plan.arms[1].interventions[0].kind = "ablation"
    backend = CardiEPPacingBackend(api_factory=lambda: _FakeEPAPI(tmp_path))
    with pytest.raises(ValueError, match="pacing interventions only"):
        backend.run(request)


def test_cardiep_pacing_backend_rejects_clinical_or_unsupported_endpoints(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    request.plan.endpoints = ["mortality"]
    backend = CardiEPPacingBackend(api_factory=lambda: _FakeEPAPI(tmp_path))
    with pytest.raises(ValueError, match="activation timing endpoints"):
        backend.run(request)


def test_cardiep_pacing_backend_verifies_twin_state_and_posterior_lineage(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    state = tmp_path / "state.json"
    state.write_text('{"entity_id":"S1"}\n', encoding="utf-8")
    state_sha = hashlib.sha256(state.read_bytes()).hexdigest()
    posterior = tmp_path / "posterior.json"
    posterior.write_text('{"samples":[]}\n', encoding="utf-8")
    posterior_sha = hashlib.sha256(posterior.read_bytes()).hexdigest()

    request.twin_state_ref = ArtifactRef(
        artifact_id="state",
        kind="cardiac_state",
        uri=state.resolve().as_uri(),
        sha256=state_sha,
        metadata={"state_fingerprint": "fingerprint-1"},
    )
    request.posterior_ref = ArtifactRef(
        artifact_id="posterior",
        kind="posterior_samples",
        uri=posterior.resolve().as_uri(),
        sha256=posterior_sha,
    )

    result = CardiTherapyService(
        backends=[CardiEPPacingBackend(api_factory=lambda: _FakeEPAPI(tmp_path))],
        register_defaults=False,
    ).run(request)

    assert result.provenance["twin_state_artifact_id"] == "state"
    assert result.provenance["twin_state_sha256"] == state_sha
    assert result.provenance["twin_state_fingerprint"] == "fingerprint-1"
    assert result.provenance["posterior_artifact_id"] == "posterior"
    assert result.provenance["posterior_sha256"] == posterior_sha


def test_cardiep_pacing_backend_rejects_claimed_hash_mismatch(tmp_path: Path) -> None:
    request = _request(tmp_path)
    state = tmp_path / "state.json"
    state.write_text('{"entity_id":"S1"}\n', encoding="utf-8")
    request.twin_state_ref = ArtifactRef(
        artifact_id="state",
        kind="cardiac_state",
        uri=state.resolve().as_uri(),
        sha256="0" * 64,
    )
    backend = CardiEPPacingBackend(api_factory=lambda: _FakeEPAPI(tmp_path))
    with pytest.raises(RuntimeError, match="Twin state artifact failed SHA-256"):
        backend.run(request)
