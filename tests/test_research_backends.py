from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy

import pytest

from carditherapy import CardiTherapyService, GraphAblationBackend, PharmacologyBackend
from carditherapy.ablation_backend import lesion_nodes, propagate, validate_graph
from carditherapy.models import ArtifactRef, Intervention, InterventionRunRequest
from carditherapy.pharmacology_backend import (
    concentration,
    dose_schedule,
    hill_block,
    simulate_pk,
    validate_model,
)
from carditherapy.research import finish, index, number, read_ref


def graph():
    return {
        "subject_id": "synthetic",
        "nodes_mm": [[i, 0, 0] for i in range(5)],
        "edges": [[0, 1, 1], [1, 2, 1], [2, 3, 1], [3, 4, 1], [0, 4, 10]],
        "roots": [{"node": 0, "time_ms": 0}],
    }


def pk():
    return {
        "subject_id": "synthetic",
        "volume_L": 10,
        "clearance_L_h": 2,
        "molecular_weight_g_mol": 500,
        "unbound_fraction": 0.5,
        "channels": {"IKr": {"ic50_uM": 1, "hill": 1, "source": "synthetic verification"}},
        "parameter_source": "synthetic verification",
    }


def artifact(tmp_path, name, data, kind):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return {
        "artifact_id": name,
        "kind": kind,
        "uri": path.as_uri(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def request(tmp_path, backend="graph-ablation-v1"):
    is_graph = backend == "graph-ablation-v1"
    data = graph() if is_graph else pk()
    return InterventionRunRequest(
        subject_id="synthetic",
        backend=backend,
        twin_state_ref=artifact(
            tmp_path, "state.json", {"subject_id": "synthetic"}, "cardiac_state"
        ),
        baseline_refs=[
            artifact(
                tmp_path,
                "model.json",
                data,
                "therapy_conduction_graph" if is_graph else "therapy_pkpd_model",
            )
        ],
        plan={
            "plan_id": "verification",
            "arms": [
                {"arm_id": "control", "label": "No intervention", "is_comparator": True},
                {
                    "arm_id": "treated",
                    "label": "Model perturbation",
                    "interventions": [
                        {
                            "intervention_id": "i",
                            "kind": "ablation" if is_graph else "pharmacologic",
                            "target": "conduction_graph" if is_graph else "iv_bolus",
                            "parameters": {"lesion_nodes": [2]}
                            if is_graph
                            else {"doses": [{"time_h": 0, "amount_mg": 10}]},
                        }
                    ],
                },
            ],
            "endpoints": [
                "lesion_node_fraction",
                "viable_reached_fraction",
                "unreachable_viable_nodes",
                "activation_span_reachable_ms",
            ]
            if is_graph
            else [
                "plasma_cmax_mg_L",
                "plasma_auc_mg_h_L",
                "unbound_cmax_uM",
                "terminal_amount_mg",
                "eliminated_amount_mg",
                "sampled_peak_block_IKr",
            ],
        },
        settings={
            "output_dir": str(tmp_path / "outputs"),
            **({} if is_graph else {"sample_times_h": [0, 1, 2, 5]}),
        },
    )


@pytest.mark.parametrize("backend", ["graph-ablation-v1", "iv-pkpd-v1"])
def test_research_end_to_end(tmp_path, backend):
    req = request(tmp_path, backend)
    result = CardiTherapyService().run(req)
    assert len(result.outcomes) == len(req.plan.arms) * len(req.plan.endpoints)
    assert (
        result.validation_status == "software_checked"
        and not result.provenance["patient_validated"]
    )
    assert not result.provenance["uncertainty_propagated"]
    assert all(v.endpoint_scope == "model_proxy" for v in result.outcomes)
    assert result.provenance["therapy_request"] == req.model_dump(mode="json")
    for ref in result.artifacts:
        payload, digest = read_ref(ref, "synthetic")
        assert digest == ref.sha256
        assert payload["endpoint_scope"] == "model_proxy"
    values = {v.endpoint: v.value for v in result.outcomes if v.arm_id == "treated"}
    if backend == "graph-ablation-v1":
        assert values["activation_span_reachable_ms"] == 11
        assert values["lesion_node_fraction"] == 0.2
    else:
        assert values["plasma_cmax_mg_L"] == 1
        assert values["sampled_peak_block_IKr"] == 0.5
        assert values["terminal_amount_mg"] + values["eliminated_amount_mg"] == pytest.approx(10)


def test_graph_against_independent_floyd_warshall():
    import random

    rng = random.Random(41)
    for _ in range(10):
        data = graph()
        data["edges"] = [
            [i, j, rng.uniform(0.5, 3)]
            for i in range(5)
            for j in range(i + 1, 5)
            if rng.random() < 0.7
        ]
        adjacency = validate_graph(data)
        removed = {2}
        _, trace = propagate(adjacency, data["roots"], removed)
        distances = [[0.0 if i == j else math.inf for j in range(5)] for i in range(5)]
        for a, b, cost in data["edges"]:
            if a not in removed and b not in removed:
                distances[a][b] = distances[b][a] = cost
        for k in range(5):
            for i in range(5):
                for j in range(5):
                    distances[i][j] = min(distances[i][j], distances[i][k] + distances[k][j])
        for i, arrival in enumerate(trace["activation_ms"]):
            if i in removed or not math.isfinite(distances[0][i]):
                assert arrival is None
            else:
                assert arrival == pytest.approx(distances[0][i])


def test_isolated_tissue_and_delayed_roots():
    data = graph()
    data["edges"] = data["edges"][:-1]
    metrics, trace = propagate(validate_graph(data), data["roots"], {2})
    assert metrics["viable_reached_fraction"] == 0.5 and metrics["unreachable_viable_nodes"] == 2
    assert trace["activation_ms"] == [0, 1, None, None, None]
    data["roots"].append({"node": 4, "time_ms": 3})
    metrics, trace = propagate(validate_graph(data), data["roots"], {2})
    assert metrics["viable_reached_fraction"] == 1 and trace["activation_ms"][3] == 4
    with pytest.raises(ValueError, match="root"):
        propagate(validate_graph(data), data["roots"], {0})
    with pytest.raises(ValueError, match="overflow"):
        propagate([[(1, 1e308)], [(2, 1e308)], []], [{"node": 0, "time_ms": 0}], set())


def test_spherical_lesion_selection():
    intervention = Intervention(
        intervention_id="i",
        kind="ablation",
        target="conduction_graph",
        parameters={"center_mm": [2, 0, 0], "radius_mm": 1},
    )
    assert lesion_nodes(intervention, graph()["nodes_mm"]) == {1, 2, 3}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda g: g.update(extra=1),
        lambda g: g.update(nodes_mm=[]),
        lambda g: g["nodes_mm"].__setitem__(0, [0, 0]),
        lambda g: g["nodes_mm"].__setitem__(0, [1e7, 0, 0]),
        lambda g: g["nodes_mm"].__setitem__(0, [1, 0, 0]),
        lambda g: g.update(edges=[]),
        lambda g: g["edges"].__setitem__(0, [0, 1]),
        lambda g: g["edges"].__setitem__(0, [0, 0, 1]),
        lambda g: g["edges"].append([1, 0, 1]),
        lambda g: g["edges"].__setitem__(0, [0, 1, 0]),
        lambda g: g.update(roots=[]),
        lambda g: g["roots"].__setitem__(0, {"node": 0}),
        lambda g: g["roots"].append({"node": 0, "time_ms": 2}),
    ],
)
def test_bad_graph(mutate):
    data = graph()
    mutate(data)
    with pytest.raises(ValueError):
        validate_graph(data)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"lesion_nodes": []},
        {"lesion_nodes": [True]},
        {"lesion_nodes": [2, 2]},
        {"center_mm": [0, 0], "radius_mm": 1},
        {"center_mm": [100, 0, 0], "radius_mm": 0.1},
        {"center_mm": [0, 0, 0], "radius_mm": 0},
    ],
)
def test_bad_lesion(params):
    intervention = Intervention(
        intervention_id="i", kind="ablation", target="conduction_graph", parameters=params
    )
    with pytest.raises(ValueError):
        lesion_nodes(intervention, graph()["nodes_mm"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "surgical"),
        ("target", "heart"),
        ("model_service", "CardiEP"),
        ("model_capability", "ep.simulate"),
    ],
)
def test_bad_ablation_target(field, value):
    intervention = Intervention(
        intervention_id="i",
        kind="ablation",
        target="conduction_graph",
        parameters={"lesion_nodes": [2]},
    )
    setattr(intervention, field, value)
    with pytest.raises(ValueError):
        lesion_nodes(intervention, graph()["nodes_mm"])


def test_pk_closed_form_repeated_bolus_and_grid_independence():
    model = pk()
    doses = [(0, 10), (2, 20)]
    metrics, trace = simulate_pk(model, doses, [0, 5])
    assert trace["time_h"] == [0, 2, 5]
    assert metrics["plasma_cmax_mg_L"] == pytest.approx(math.exp(-0.4) + 2)
    assert metrics["plasma_auc_mg_h_L"] == pytest.approx(
        5 * (1 - math.exp(-1)) + 10 * (1 - math.exp(-0.6))
    )
    assert metrics["terminal_amount_mg"] == pytest.approx(10 * math.exp(-1) + 20 * math.exp(-0.6))
    refined, _ = simulate_pk(model, doses, [i / 100 for i in range(501)])
    assert metrics == refined
    assert concentration(model, [(2, 10)], 1) == (0, 0, 0)
    assert hill_block(0, 1, 1) == 0 and hill_block(1, 1, 2) == 0.5
    assert hill_block(1e-300, 1e300, 2) == 0 and hill_block(1e300, 1e-300, 2) == 1


@pytest.mark.parametrize("effect_rate", [0.1, 0.2, 0.20000000000001, 0.5])
def test_effect_compartment_convolution(effect_rate):
    model = pk()
    model["effect_rate_h_inv"] = effect_rate
    t = 3
    k = 0.2
    expected = (
        effect_rate * t * math.exp(-k * t)
        if abs(effect_rate - k) < 1e-12
        else effect_rate * (math.exp(-k * t) - math.exp(-effect_rate * t)) / (effect_rate - k)
    )
    assert concentration(model, [(0, 10)], t)[2] == pytest.approx(expected, rel=1e-12)
    assert concentration(model, [(0, 10)], 0)[2] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(extra=1),
        lambda p: p.pop("volume_L"),
        lambda p: p.update(volume_L=0),
        lambda p: p.update(clearance_L_h=True),
        lambda p: p.update(unbound_fraction=1.1),
        lambda p: p.update(parameter_source=""),
        lambda p: p.update(effect_rate_h_inv=0),
        lambda p: p.update(channels={}),
        lambda p: p["channels"].update({"wrong!": {}}),
        lambda p: p["channels"]["IKr"].update(source=""),
        lambda p: p.update(volume_L=1e-308, clearance_L_h=1e308),
    ],
)
def test_bad_pk_model(mutate):
    model = pk()
    mutate(model)
    with pytest.raises(ValueError):
        validate_model(model)


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"doses": []},
        {"doses": [{}]},
        {"doses": [{"time_h": 6, "amount_mg": 10}]},
        {"doses": [{"time_h": 0, "amount_mg": 0}]},
    ],
)
def test_bad_doses(parameters):
    intervention = Intervention(
        intervention_id="i", kind="pharmacologic", target="iv_bolus", parameters=parameters
    )
    with pytest.raises(ValueError):
        dose_schedule(intervention, 5)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "regenerative"),
        ("target", "oral"),
        ("model_service", "CardiEP"),
        ("model_capability", "ep.simulate"),
    ],
)
def test_bad_pharmacology_target(field, value):
    intervention = Intervention(
        intervention_id="i",
        kind="pharmacologic",
        target="iv_bolus",
        parameters={"doses": [{"time_h": 0, "amount_mg": 10}]},
    )
    setattr(intervention, field, value)
    with pytest.raises(ValueError):
        dose_schedule(intervention, 5)


@pytest.mark.parametrize("backend", ["graph-ablation-v1", "iv-pkpd-v1"])
@pytest.mark.parametrize(
    "change",
    [
        "posterior",
        "bad_setting",
        "no_output",
        "empty_output",
        "bad_endpoint",
        "extra_ref",
        "wrong_kind",
        "no_comparator",
        "comparator_intervention",
        "empty_active",
        "subject",
        "sha",
        "missing_subject",
        "nonobject",
    ],
)
def test_invalid_research_request(tmp_path, backend, change):
    req = request(tmp_path, backend)
    if change == "posterior":
        req.posterior_ref = ArtifactRef(
            artifact_id="posterior", kind="posterior", uri="memory://posterior"
        )
    if change == "bad_setting":
        req.settings["unknown"] = 1
    if change == "no_output":
        req.settings.pop("output_dir")
    if change == "empty_output":
        req.settings["output_dir"] = " "
    if change == "bad_endpoint":
        req.plan.endpoints = ["survival"]
    if change == "extra_ref":
        req.baseline_refs.append(ArtifactRef(artifact_id="extra", kind="other", uri="memory://x"))
    if change == "wrong_kind":
        req.baseline_refs[0].kind = "other"
    if change == "no_comparator":
        req.plan.arms[0].is_comparator = False
    if change == "comparator_intervention":
        req.plan.arms[0].interventions = deepcopy(req.plan.arms[1].interventions)
        req.plan.arms[0].interventions[0].intervention_id = "other"
    if change == "empty_active":
        req.plan.arms[1].interventions = []
    if change == "subject":
        req.baseline_refs[0].metadata["subject_id"] = "other"
    if change == "sha":
        req.baseline_refs[0].sha256 = "0" * 64
    if change in {"missing_subject", "nonobject"}:
        data = graph() if backend == "graph-ablation-v1" else pk()
        if change == "missing_subject":
            data.pop("subject_id")
        else:
            data = []
        req.baseline_refs = [
            ArtifactRef.model_validate(
                artifact(tmp_path, "model.json", data, req.baseline_refs[0].kind)
            )
        ]
    with pytest.raises((ValueError, TypeError)):
        CardiTherapyService().run(req)
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("times", [None, [], [1, 2], [0, 0, 1], [0, 2, 1], [0, True]])
def test_bad_times(tmp_path, times):
    req = request(tmp_path, "iv-pkpd-v1")
    req.settings["sample_times_h"] = times
    with pytest.raises(ValueError):
        CardiTherapyService().run(req)
    assert not (tmp_path / "outputs").exists()


def test_run_effect_compartment(tmp_path):
    req = request(tmp_path, "iv-pkpd-v1")
    model = pk()
    model["effect_rate_h_inv"] = 0.5
    req.baseline_refs = [
        ArtifactRef.model_validate(artifact(tmp_path, "model.json", model, "therapy_pkpd_model"))
    ]
    result = CardiTherapyService().run(req)
    assert result.provenance["effect_site"] == "first-order effect compartment"
    assert (
        0
        < next(
            v.value
            for v in result.outcomes
            if v.arm_id == "treated" and v.endpoint == "sampled_peak_block_IKr"
        )
        < 0.5
    )


@pytest.mark.parametrize("value", [True, "1", math.inf, math.nan, -1, 0])
def test_numeric_validation(value):
    with pytest.raises(ValueError):
        number(value, "value", positive=True)


@pytest.mark.parametrize("value", [True, 1.0, -1, 5])
def test_index_validation(value):
    with pytest.raises(ValueError):
        index(value, 5)


def test_input_subject_and_type(tmp_path):
    for data in [[], {"subject_id": "other"}]:
        ref = ArtifactRef.model_validate(artifact(tmp_path, "input.json", data, "model"))
        with pytest.raises((ValueError, TypeError)):
            read_ref(ref, "synthetic")


def test_input_changed_before_publication(tmp_path):
    req = request(tmp_path)
    with pytest.raises(ValueError, match="changed"):
        finish(req, [], {"twin_state_sha256": "0" * 64}, "warning", {}, {})
    assert not (tmp_path / "outputs").exists()


def test_all_arms_validated_before_execution(tmp_path):
    req = request(tmp_path)
    req.plan.arms[1].interventions[0].parameters = {"lesion_nodes": [0]}
    with pytest.raises(ValueError, match="root"):
        CardiTherapyService().run(req)
    assert not (tmp_path / "outputs").exists()


def test_direct_backend_wrong_identifier(tmp_path):
    req = request(tmp_path)
    req.backend = "other"
    with pytest.raises(ValueError, match="backend"):
        GraphAblationBackend().run(req)


def test_pk_nonfinite_computation():
    model = pk()
    model["volume_L"] = 1e-308
    with pytest.raises((ValueError, OverflowError)):
        concentration(model, [(0, 1e308)], 0)
    with pytest.raises((ValueError, OverflowError)):
        simulate_pk(model, [(0, 1e308), (0, 1e308)], [0, 1])


def test_pk_missing_baseline(tmp_path):
    req = request(tmp_path, "iv-pkpd-v1")
    req.baseline_refs = []
    with pytest.raises(ValueError):
        PharmacologyBackend().run(req)


def test_patient_outcome_claim_requires_empirical_status(tmp_path):
    from carditherapy.models import InterventionOutcome, InterventionRunResult
    from carditherapy.service import ReadinessError

    class UnvalidatedPatientBackend:
        name = "graph-ablation-v1"

        def available(self):
            return True

        def run(self, req):
            return InterventionRunResult(
                subject_id=req.subject_id,
                backend=self.name,
                plan_id=req.plan.plan_id,
                validation_status="software_checked",
                outcomes=[
                    InterventionOutcome(
                        arm_id="treated",
                        endpoint="survival",
                        value=1,
                        endpoint_scope="patient_outcome",
                    )
                ],
            )

    service = CardiTherapyService([UnvalidatedPatientBackend()], register_defaults=False)
    assert service.backend_details()["graph-ablation-v1"]["scientific_scope"] == "unspecified"
    with pytest.raises(ReadinessError, match="empirical"):
        service.run(request(tmp_path))


def test_health_exposes_scientific_scope():
    from carditherapy.api import TherapyAPI

    health = TherapyAPI().health()
    assert set(health["backend_details"]) == set(health["backends"])
    assert all(not v["patient_validated"] for v in health["backend_details"].values())
    assert all(v["endpoint_scope"] == "model_proxy" for v in health["backend_details"].values())


def test_invalid_endpoint_fails_before_publication(tmp_path):
    req = request(tmp_path)
    provenance = {
        "twin_state_sha256": req.twin_state_ref.sha256,
        "baseline_model_sha256": req.baseline_refs[0].sha256,
    }
    metrics = {endpoint: 1.0 for endpoint in req.plan.endpoints}
    metrics[req.plan.endpoints[0]] = math.inf
    with pytest.raises(ValueError, match="Nonfinite"):
        finish(req, [("control", metrics, {})], provenance, "warning", {}, {})
    assert not (tmp_path / "outputs").exists()


def test_nonfinite_pk_metrics_and_conservation_guard(monkeypatch):
    import carditherapy.pharmacology_backend as module

    model = pk()
    model["clearance_L_h"] = 1e-308
    with pytest.raises(ValueError, match="Nonfinite"):
        simulate_pk(model, [(0, 10)], [0, 1])
    model = pk()
    monkeypatch.setattr(module.math, "expm1", lambda x: 0.0)
    with pytest.raises(ValueError, match="conservation"):
        simulate_pk(model, [(0, 10)], [0, 1])


def test_input_changed_during_pk_preflight(tmp_path, monkeypatch):
    import carditherapy.research as module

    req = request(tmp_path, "iv-pkpd-v1")
    original = module.read_ref
    calls = 0

    def changed(ref, subject):
        nonlocal calls
        calls += 1
        data, digest = original(ref, subject)
        return data, "0" * 64 if calls == 3 else digest

    monkeypatch.setattr(module, "read_ref", changed)
    with pytest.raises(ValueError, match="changed"):
        PharmacologyBackend().run(req)
    assert not (tmp_path / "outputs").exists()


def test_independent_intervention_harness():
    pytest.importorskip("scipy")
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "therapy_validation", Path(__file__).parents[1] / "scripts/validate_interventions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.verify()
    assert (
        report["computational_status"] == "passed" and report["empirical_status"] == "not_validated"
    )
