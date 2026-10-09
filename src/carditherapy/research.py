"""Shared strict input and artifact handling for numerical intervention experiments."""

from __future__ import annotations

import hashlib
import math
import tempfile
from pathlib import Path

from .models import ArtifactRef, InterventionOutcome, InterventionRunResult
from .pacing_backend import _local_path
from .serialization import loads, write_json


def number(value, label, *, positive=False, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value < minimum or (positive and value <= 0):
        raise ValueError(f"{label} is outside its supported range")
    return float(value)


def index(value, size, label="node"):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < size:
        raise ValueError(f"{label} must be an integer in [0, {size})")
    return value


def read_ref(ref, subject):
    raw = _local_path(ref.uri).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if ref.sha256 is not None and ref.sha256 != digest:
        raise ValueError("Input artifact SHA-256 mismatch")
    data = loads(raw)
    if not isinstance(data, dict):
        raise TypeError("Research input artifact must contain a JSON object")
    if (
        data.get("subject_id", subject) != subject
        or ref.metadata.get("subject_id", subject) != subject
    ):
        raise ValueError("Input artifact belongs to a different subject")
    return data, digest


def prepare(request, name, kind, endpoints, settings):
    if request.backend != name:
        raise ValueError("Request backend does not match research backend")
    if request.posterior_ref is not None:
        raise ValueError("This backend does not propagate posterior uncertainty")
    if set(request.settings) - settings or "output_dir" not in request.settings:
        raise ValueError("Unsupported settings or missing output_dir")
    output_dir = request.settings["output_dir"]
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise ValueError("output_dir must be a nonblank path string")
    if set(request.plan.endpoints) - endpoints:
        raise ValueError("Unsupported endpoint; this backend provides model proxies only")
    if len(request.baseline_refs) != 1 or request.baseline_refs[0].kind != kind:
        raise ValueError(f"Exactly one {kind} baseline artifact is required")
    if len(request.plan.arms) > 32 or sum(arm.is_comparator for arm in request.plan.arms) != 1:
        raise ValueError("Research experiments require exactly one comparator and at most 32 arms")
    for arm in request.plan.arms:
        if (arm.is_comparator and arm.interventions) or (
            not arm.is_comparator and len(arm.interventions) != 1
        ):
            raise ValueError("Comparator must be empty; active arms require one intervention")
    _, state_sha = read_ref(request.twin_state_ref, request.subject_id)
    data, input_sha = read_ref(request.baseline_refs[0], request.subject_id)
    if data.get("subject_id") != request.subject_id:
        raise ValueError("Baseline model requires explicit matching subject_id")
    return data, {
        "twin_state_sha256": state_sha,
        "baseline_model_sha256": input_sha,
        "patient_validated": False,
        "uncertainty_propagated": False,
        "twin_state_usage": "verified lineage; baseline model provides scientific parameters",
    }


def finish(request, arms, provenance, warning, scopes, units):
    # All numerical arms and input checks complete before publishing any artifacts.
    for ref, key in [
        (request.twin_state_ref, "twin_state_sha256"),
        (request.baseline_refs[0], "baseline_model_sha256"),
    ]:
        if read_ref(ref, request.subject_id)[1] != provenance[key]:
            raise ValueError("Input artifact changed during experiment")
    for _, metrics, _ in arms:
        if not all(math.isfinite(metrics[endpoint]) for endpoint in request.plan.endpoints):
            raise ValueError("Nonfinite numerical endpoint")
    output_dir = Path(request.settings["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=request.backend + "-", dir=output_dir))
    comparator = next(arm.arm_id for arm in request.plan.arms if arm.is_comparator)
    by_arm = {arm_id: metrics for arm_id, metrics, _ in arms}
    outcomes = []
    artifacts = []
    for position, (arm_id, metrics, payload) in enumerate(arms):
        path = directory / f"arm-{position}.json"
        payload.update(
            subject_id=request.subject_id,
            backend=request.backend,
            arm_id=arm_id,
            patient_validated=False,
            endpoint_scope="model_proxy",
            warnings=[warning],
        )
        write_json(path, payload)
        ref = ArtifactRef(
            artifact_id=f"{request.backend}:{request.plan.plan_id}:arm-{position}",
            kind="therapy_model_trace",
            uri=path.as_uri(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        artifacts.append(ref)
        for endpoint in request.plan.endpoints:
            value = metrics[endpoint]
            outcomes.append(
                InterventionOutcome(
                    arm_id=arm_id,
                    endpoint=endpoint,
                    value=value,
                    unit=units[endpoint],
                    artifact_ref=ref,
                    endpoint_scope="model_proxy",
                    endpoint_tier="electrical"
                    if request.backend == "graph-ablation-v1"
                    else "pharmacology_proxy",
                    metadata={
                        "domain": scopes[endpoint],
                        "comparator_arm_id": comparator,
                        "difference_from_comparator": value - by_arm[comparator][endpoint],
                        "patient_validated": False,
                    },
                )
            )
    return InterventionRunResult(
        subject_id=request.subject_id,
        backend=request.backend,
        plan_id=request.plan.plan_id,
        outcomes=outcomes,
        artifacts=artifacts,
        validation_status="software_checked",
        warnings=[warning],
        provenance=provenance,
    )
