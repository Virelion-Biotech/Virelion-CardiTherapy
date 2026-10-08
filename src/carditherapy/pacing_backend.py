from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .backends import BackendUnavailable
from .models import (
    ArtifactRef,
    InterventionOutcome,
    InterventionRunRequest,
    InterventionRunResult,
)

PACING_BACKEND_NAME = "cardiep-pacing-v1"

_SUPPORTED_ENDPOINTS = {
    "activation_span_ms",
    "activation_min_ms",
    "activation_max_ms",
}
_PACING_SETTING_KEYS = {
    "root_node",
    "root_nodes",
    "root_activation_ms",
    "purkinje_root_distance_cm",
    "auto_root_count",
}


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"CardiTherapy pacing requires local EP artifacts, got {uri!r}")
    if parsed.scheme == "file" and parsed.netloc not in {"", "localhost"}:
        raise ValueError("Remote file URI authorities are not supported")
    if parsed.scheme == "file" and (parsed.query or parsed.fragment):
        raise ValueError("File artifact URIs must not contain a query or fragment")
    raw = unquote(parsed.path) if parsed.scheme == "file" else uri
    return Path(raw).expanduser().resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_local_ref(ref: ArtifactRef, *, label: str) -> str | None:
    parsed = urlparse(ref.uri)
    if parsed.scheme not in {"", "file"}:
        if ref.sha256 is not None:
            raise RuntimeError(
                f"{label} declares SHA-256 but cannot be verified from non-local URI {ref.uri!r}"
            )
        return None
    path = _local_path(ref.uri)
    if not path.is_file():
        raise FileNotFoundError(f"{label} artifact does not exist: {path}")
    observed = _sha256(path)
    if ref.sha256 is not None and observed.lower() != ref.sha256.lower():
        raise RuntimeError(f"{label} artifact failed SHA-256 verification")
    return observed


class CardiEPPacingBackend:
    """Pacing intervention backend delegated to CardiEP.

    This backend changes only activation-root settings. It does not model device
    hardware, capture thresholds, hemodynamic benefit, arrhythmia termination,
    or clinical outcomes.
    """

    name = PACING_BACKEND_NAME

    def __init__(self, api_factory: Callable[[], Any] | None = None) -> None:
        self._api_factory = api_factory

    def describe(self):
        return {
            "name": self.name,
            "intervention_kinds": ["pacing"],
            "endpoints": sorted(_SUPPORTED_ENDPOINTS),
            "endpoint_scope": "model_proxy",
            "requires": "CardiEP anatomy and fixed EP parameters",
            "patient_validated": False,
            "model": "CardiEP activation-root perturbation",
        }

    def _api(self) -> Any:
        if self._api_factory is not None:
            return self._api_factory()
        try:
            from cardiep import EPAPI
        except Exception as exc:  # pragma: no cover - depends on optional stack install
            raise BackendUnavailable(
                "cardiep-pacing-v1 requires Virelion-CardiEP to be installed"
            ) from exc
        return EPAPI()

    def available(self) -> bool:
        if self._api_factory is not None:
            return True
        try:
            from cardiep import EPAPI  # noqa: F401
        except (ImportError, ModuleNotFoundError):
            return False
        return True

    @staticmethod
    def _anatomy_ref(request: InterventionRunRequest) -> dict[str, Any]:
        candidates = [
            item
            for item in request.baseline_refs
            if item.kind
            in {
                "ep_anatomy",
                "surface_mesh",
                "tetra_mesh",
                "ventricular_mesh",
                "anatomy",
            }
        ]
        if len(candidates) != 1:
            raise ValueError(
                "cardiep-pacing-v1 requires exactly one EP anatomy artifact in baseline_refs"
            )
        item = candidates[0]
        coordinate_frame = item.coordinate_frame or item.metadata.get("coordinate_frame")
        if item.coordinate_frame is not None and item.metadata.get("coordinate_frame") not in {
            None,
            item.coordinate_frame,
        }:
            raise ValueError("Conflicting anatomy coordinate frames")
        return {
            "artifact_id": item.artifact_id,
            "kind": item.kind,
            "uri": item.uri,
            "sha256": item.sha256,
            "coordinate_frame": (None if coordinate_frame is None else str(coordinate_frame)),
            "metadata": dict(item.metadata),
        }

    @staticmethod
    def _summary(result: dict[str, Any]) -> tuple[dict[str, float], ArtifactRef]:
        raw_outputs = result.get("outputs")
        if not isinstance(raw_outputs, list):
            raise TypeError("CardiEP pacing result is missing outputs")
        summaries = [
            item
            for item in raw_outputs
            if isinstance(item, dict) and item.get("kind") == "ep_summary"
        ]
        if len(summaries) != 1:
            raise RuntimeError("CardiEP pacing result did not emit ep_summary")
        summary = summaries[0]
        declared_ref = ArtifactRef.model_validate(summary)
        path = _local_path(str(summary["uri"]))
        if not path.is_file():
            raise FileNotFoundError(path)
        expected = declared_ref.sha256
        observed_sha = _sha256(path)
        if expected and observed_sha != expected.lower():
            raise RuntimeError("CardiEP pacing summary failed SHA-256 verification")
        from .serialization import loads

        payload = loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("CardiEP pacing summary must be a JSON object")

        propagation = payload.get("propagation", {})
        if not isinstance(propagation, dict):
            raise TypeError("CardiEP propagation summary must be an object")
        span = payload.get(
            "activation_span_ms",
            propagation.get("qrs_activation_span_ms"),
        )
        minimum = payload.get(
            "activation_min_ms",
            propagation.get("activation_min_ms"),
        )
        maximum = payload.get(
            "activation_max_ms",
            propagation.get("activation_max_ms"),
        )
        values = {
            "activation_span_ms": span,
            "activation_min_ms": minimum,
            "activation_max_ms": maximum,
        }
        if any(value is None for value in values.values()):
            raise RuntimeError(
                "CardiEP ep_summary lacks activation timing endpoints required by cardiep-pacing-v1"
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values.values()
        ):
            raise ValueError("Activation timing endpoints must be finite numbers")
        normalized = {name: float(value) for name, value in values.items()}
        if (
            maximum < minimum
            or span < 0
            or not math.isclose(span, maximum - minimum, rel_tol=1e-9, abs_tol=1e-9)
        ):
            raise ValueError("Activation timing endpoints are inconsistent")
        return normalized, ArtifactRef(
            artifact_id=declared_ref.artifact_id,
            kind=declared_ref.kind,
            uri=declared_ref.uri,
            sha256=observed_sha,
            coordinate_frame=declared_ref.coordinate_frame,
            metadata=declared_ref.metadata,
        )

    @staticmethod
    def _arm_settings(
        request: InterventionRunRequest,
        interventions: list[Any],
    ) -> dict[str, Any]:
        settings = dict(request.settings.get("ep_settings") or {})
        if not interventions:
            return settings
        if len(interventions) != 1:
            raise ValueError("cardiep-pacing-v1 supports at most one pacing intervention per arm")
        intervention = interventions[0]
        if intervention.kind != "pacing":
            raise ValueError("cardiep-pacing-v1 accepts pacing interventions only")
        unknown = sorted(set(intervention.parameters) - _PACING_SETTING_KEYS)
        if unknown:
            raise ValueError("Unsupported pacing parameter(s): " + ", ".join(unknown))
        if not intervention.parameters:
            raise ValueError("Pacing intervention requires explicit root settings")
        settings.update(intervention.parameters)
        return settings

    def run(self, request: InterventionRunRequest) -> InterventionRunResult:
        request = InterventionRunRequest.model_validate(request.model_dump(mode="python"))
        unknown_settings = sorted(
            set(request.settings)
            - {"ep_backend", "ep_parameters", "ep_parameter_units", "ep_settings"}
        )
        if unknown_settings:
            raise ValueError("Unsupported pacing request settings: " + ", ".join(unknown_settings))
        unsupported = sorted(set(request.plan.endpoints) - _SUPPORTED_ENDPOINTS)
        if unsupported:
            raise ValueError(
                "cardiep-pacing-v1 supports only activation timing endpoints; "
                "unsupported: " + ", ".join(unsupported)
            )
        ep_backend = request.settings.get("ep_backend", "")
        if not isinstance(ep_backend, str) or not ep_backend.strip():
            raise ValueError("settings.ep_backend is required")
        ep_backend = ep_backend.strip()
        ep_parameters = request.settings.get("ep_parameters")
        if not isinstance(ep_parameters, dict) or not ep_parameters:
            raise ValueError("settings.ep_parameters must be a non-empty object")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in ep_parameters.values()
        ):
            raise ValueError("EP parameters must be finite numbers")
        if not isinstance(request.settings.get("ep_settings", {}), dict):
            raise TypeError("settings.ep_settings must be an object")
        units = request.settings.get("ep_parameter_units", {})
        if not isinstance(units, dict):
            raise TypeError("settings.ep_parameter_units must be an object")
        anatomy_ref = self._anatomy_ref(request)
        anatomy_item = next(
            item for item in request.baseline_refs if item.artifact_id == anatomy_ref["artifact_id"]
        )
        anatomy_ref["sha256"] = _verify_local_ref(anatomy_item, label="Anatomy")
        state_sha256 = _verify_local_ref(request.twin_state_ref, label="Twin state")
        posterior_sha256 = None
        if request.posterior_ref is not None:
            posterior_sha256 = _verify_local_ref(
                request.posterior_ref,
                label="Posterior",
            )
        api = self._api()

        # Validate all arms before starting a partially executable experiment.
        arm_settings = []
        for arm in request.plan.arms:
            if arm.is_comparator and arm.interventions:
                raise ValueError("Pacing comparators must have no interventions")
            if not arm.is_comparator and not arm.interventions:
                raise ValueError("Active pacing arms require one intervention")
            for intervention in arm.interventions:
                if intervention.model_service not in {
                    None,
                    "CardiEP",
                } or intervention.model_capability not in {None, "ep.simulate"}:
                    raise ValueError("Pacing intervention must target CardiEP ep.simulate")
            settings = self._arm_settings(request, arm.interventions)
            roots = set(settings) & {"root_node", "root_nodes", "auto_root_count"}
            if len(roots) > 1:
                raise ValueError("Conflicting pacing root selectors")
            arm_settings.append(settings)

        outcomes: list[InterventionOutcome] = []
        artifacts: list[ArtifactRef] = []
        warnings = [
            (
                "cardiep-pacing-v1 is a research simulation of activation-root changes; "
                "it does not predict clinical pacing benefit."
            )
        ]
        if state_sha256 is None:
            warnings.append(
                "Twin state is a non-local reference; its bytes were not verified or consumed by CardiEP."
            )
        if request.posterior_ref is not None:
            warnings.append(
                "Posterior is retained as lineage only; no posterior uncertainty is propagated."
            )
        arm_provenance: list[dict[str, Any]] = []
        validation_statuses: list[str] = []

        for arm, settings in zip(request.plan.arms, arm_settings):
            result = api.simulate(
                {
                    "subject_id": request.subject_id,
                    "anatomy_ref": anatomy_ref,
                    "backend": ep_backend,
                    "parameters": {
                        "values": {str(key): float(value) for key, value in ep_parameters.items()},
                        "units": {str(key): str(value) for key, value in units.items()},
                        "source": "fixed",
                    },
                    "observations": [],
                    "settings": settings,
                }
            )
            if result.get("subject_id") != request.subject_id:
                raise RuntimeError("CardiEP returned a different subject")
            if result.get("backend") != ep_backend:
                raise RuntimeError("CardiEP returned a different EP backend")
            if result.get("validation_status", "unvalidated") not in {
                "unvalidated",
                "software_checked",
                "numerically_checked",
                "empirically_checked",
            }:
                raise ValueError("CardiEP returned an unknown validation status")
            values, summary_ref = self._summary(result)
            from .serialization import loads

            summary_payload = loads(_local_path(summary_ref.uri).read_text(encoding="utf-8"))
            for key, expected in (("subject_id", request.subject_id), ("backend", ep_backend)):
                if key in summary_payload and summary_payload[key] != expected:
                    raise RuntimeError(f"CardiEP summary returned a different {key}")
            arm_artifacts = []
            for raw in result["outputs"]:
                artifact = ArtifactRef.model_validate(raw)
                digest = _verify_local_ref(artifact, label="Delegate output")
                if digest is None:
                    raise ValueError("Pacing delegate outputs must be local files")
                artifact.sha256 = digest
                if any(
                    item.artifact_id == artifact.artifact_id and item != artifact
                    for item in artifacts
                ):
                    raise RuntimeError("CardiEP returned conflicting artifact IDs across arms")
                artifacts.append(artifact)
                arm_artifacts.append(artifact.model_dump(mode="json"))
            validation_statuses.append(str(result.get("validation_status", "unvalidated")))
            for endpoint in request.plan.endpoints:
                outcomes.append(
                    InterventionOutcome(
                        arm_id=arm.arm_id,
                        endpoint=endpoint,
                        value=values[endpoint],
                        unit="ms",
                        artifact_ref=summary_ref,
                        metadata={
                            "domain": "activation",
                            "patient_validated": False,
                            "model_service": "CardiEP",
                            "ep_backend": ep_backend,
                            "intervention_ids": [
                                item.intervention_id for item in arm.interventions
                            ],
                        },
                    )
                )
            warnings.extend(str(item) for item in result.get("warnings") or [])
            arm_provenance.append(
                {
                    "arm_id": arm.arm_id,
                    "ep_backend": ep_backend,
                    "ep_settings": settings,
                    "outputs": arm_artifacts,
                    "ep_provenance": dict(result.get("provenance") or {}),
                }
            )

        validation_status = (
            "software_checked"
            if validation_statuses
            and all(
                item
                in {
                    "software_checked",
                    "numerically_checked",
                    "empirically_checked",
                }
                for item in validation_statuses
            )
            else "unvalidated"
        )
        deduplicated_artifacts = {item.artifact_id: item for item in artifacts}
        for artifact in artifacts:
            _verify_local_ref(artifact, label="Final summary")
        return InterventionRunResult(
            subject_id=request.subject_id,
            backend=self.name,
            plan_id=request.plan.plan_id,
            outcomes=outcomes,
            artifacts=list(deduplicated_artifacts.values()),
            validation_status=validation_status,
            warnings=list(dict.fromkeys(warnings)),
            provenance={
                "engine": "Virelion-CardiTherapy",
                "delegate_service": "Virelion-CardiEP",
                "delegate_backend": ep_backend,
                "twin_state_artifact_id": request.twin_state_ref.artifact_id,
                "twin_state_sha256": state_sha256,
                "twin_state_fingerprint": request.twin_state_ref.metadata.get("state_fingerprint"),
                "posterior_artifact_id": (
                    None if request.posterior_ref is None else request.posterior_ref.artifact_id
                ),
                "posterior_sha256": posterior_sha256,
                "anatomy_sha256": anatomy_ref["sha256"],
                "uncertainty_propagated": False,
                "arms": arm_provenance,
                "scientific_status": (
                    "model-dependent pacing activation experiment; "
                    "not clinical treatment prediction"
                ),
            },
        )
