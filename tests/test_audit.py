import copy
import hashlib
import json

import pytest
from test_pacing_backend import _FakeEPAPI, _request

from carditherapy import ArtifactRef, CardiEPPacingBackend, CardiTherapyService
from carditherapy.models import InterventionOutcome, InterventionRunResult
from carditherapy.serialization import loads, write_json
from carditherapy.service import ReadinessError


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "12"])
def test_scalar_outcomes_reject_non_numbers(value):
    with pytest.raises(ValueError):
        InterventionOutcome(arm_id="A", endpoint="time", value=value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_id", ""),
        ("uri", " "),
        ("sha256", "z" * 64),
        ("metadata", {"value": float("inf")}),
    ],
)
def test_artifact_contract(field, value):
    payload = {"artifact_id": "A", "kind": "state", "uri": "memory://state"}
    payload[field] = value
    with pytest.raises(ValueError):
        ArtifactRef(**payload)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'])
def test_strict_json(text):
    with pytest.raises(ValueError):
        loads(text)


def test_atomic_write_preserves_previous_on_failure(tmp_path):
    path = tmp_path / "result.json"
    write_json(path, {"ok": True})
    with pytest.raises(ValueError):
        write_json(path, {"bad": float("nan")})
    assert loads(path.read_text()) == {"ok": True}
    assert not list(tmp_path.glob(".carditherapy-*"))


@pytest.mark.parametrize(
    "mutation", ["plan", "missing", "extra", "duplicate", "lineage", "subject", "backend"]
)
def test_service_rejects_untrustworthy_results(tmp_path, mutation):
    request = _request(tmp_path)
    outcomes = [
        InterventionOutcome(arm_id=arm.arm_id, endpoint="activation_span_ms", value=100)
        for arm in request.plan.arms
    ]
    result = InterventionRunResult(
        subject_id="S1", backend=request.backend, plan_id=request.plan.plan_id, outcomes=outcomes
    )
    if mutation == "plan":
        result.plan_id = "other"
    if mutation == "subject":
        result.subject_id = "other"
    if mutation == "backend":
        result.backend = "other"
    if mutation == "missing":
        result.outcomes.pop()
    if mutation == "extra":
        result.outcomes[0].endpoint = "mortality"
    if mutation == "duplicate":
        result.outcomes.append(result.outcomes[0])
    if mutation == "lineage":
        result.provenance["twin_state_artifact_id"] = "other"

    class Backend:
        name = request.backend

        def available(self):
            return True

        def run(self, req):
            return result

    with pytest.raises(ReadinessError):
        CardiTherapyService([Backend()], register_defaults=False).run(request)


def test_service_request_mutation_isolated(tmp_path):
    request = _request(tmp_path)
    original = copy.deepcopy(request.model_dump())

    class Backend:
        name = request.backend

        def available(self):
            return True

        def run(self, req):
            req.settings.clear()
            return InterventionRunResult(
                subject_id=req.subject_id,
                backend=req.backend,
                plan_id=req.plan.plan_id,
                outcomes=[
                    InterventionOutcome(arm_id=a.arm_id, endpoint=e, value=0)
                    for a in req.plan.arms
                    for e in req.plan.endpoints
                ],
            )

    result = CardiTherapyService([Backend()], register_defaults=False).run(request)
    assert request.model_dump() == original
    assert result.provenance["therapy_request"]["settings"] == original["settings"]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_endpoint",
        "blank_endpoint",
        "comparator_intervention",
        "empty_active",
        "root_conflict",
        "service",
        "parameters",
        "ep_settings",
    ],
)
def test_preflight_before_any_simulation(tmp_path, mutation):
    request = _request(tmp_path)
    intervention = request.plan.arms[1].interventions[0]
    if mutation == "duplicate_endpoint":
        request.plan.endpoints *= 2
    if mutation == "blank_endpoint":
        request.plan.endpoints = [" "]
    if mutation == "comparator_intervention":
        request.plan.arms[1].is_comparator = True
    if mutation == "empty_active":
        request.plan.arms[1].interventions = []
    if mutation == "root_conflict":
        intervention.parameters = {"root_nodes": [2]}
    if mutation == "service":
        intervention.model_service = "Other"
    if mutation == "parameters":
        request.settings["ep_parameters"] = {"speed": True}
    if mutation == "ep_settings":
        request.settings["ep_settings"] = [1]
    api = _FakeEPAPI(tmp_path)
    with pytest.raises((ValueError, TypeError)):
        CardiEPPacingBackend(lambda: api).run(request)
    assert not api.calls


@pytest.mark.parametrize(
    "mutation", ["nan", "string", "negative", "inconsistent", "duplicate_key", "propagation"]
)
def test_invalid_delegate_summary(tmp_path, mutation):
    payload = {"activation_span_ms": 10, "activation_min_ms": 0, "activation_max_ms": 10}
    if mutation == "nan":
        payload["activation_span_ms"] = float("nan")
    if mutation == "string":
        payload["activation_span_ms"] = "10"
    if mutation == "negative":
        payload["activation_span_ms"] = -10
    if mutation == "inconsistent":
        payload["activation_max_ms"] = 11
    if mutation == "propagation":
        payload["propagation"] = None
    path = tmp_path / "summary.json"
    text = json.dumps(payload)
    if mutation == "duplicate_key":
        text = text[:-1] + ', "activation_span_ms": 11}'
    path.write_text(text)
    with pytest.raises((ValueError, TypeError)):
        CardiEPPacingBackend._summary(
            {"outputs": [{"artifact_id": "summary", "kind": "ep_summary", "uri": path.as_uri()}]}
        )


def test_anatomy_hash_verified_before_simulation(tmp_path):
    request = _request(tmp_path)
    request.baseline_refs[0].sha256 = "0" * 64
    api = _FakeEPAPI(tmp_path)
    with pytest.raises(RuntimeError, match="Anatomy"):
        CardiEPPacingBackend(lambda: api).run(request)
    assert not api.calls


def test_overwritten_delegate_artifact_fails(tmp_path):
    class OverwritingAPI(_FakeEPAPI):
        def simulate(self, payload):
            result = super().simulate(payload)
            from pathlib import Path

            original = Path(result["outputs"][0]["uri"].removeprefix("file://"))
            common = self.root / "same.json"
            common.write_bytes(original.read_bytes())
            result["outputs"][0]["uri"] = common.as_uri()
            return result

    with pytest.raises(RuntimeError, match="Final summary"):
        CardiEPPacingBackend(lambda: OverwritingAPI(tmp_path)).run(_request(tmp_path))


def test_posterior_is_lineage_only(tmp_path):
    request = _request(tmp_path)
    path = tmp_path / "posterior.json"
    path.write_text("{}")
    request.posterior_ref = ArtifactRef(
        artifact_id="post",
        kind="posterior",
        uri=path.as_uri(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    result = CardiEPPacingBackend(lambda: _FakeEPAPI(tmp_path)).run(request)
    assert result.provenance["uncertainty_propagated"] is False
    assert any("no posterior uncertainty" in item for item in result.warnings)
