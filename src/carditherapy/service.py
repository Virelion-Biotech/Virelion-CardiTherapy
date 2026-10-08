from __future__ import annotations

from .backends import BackendUnavailable, TherapyBackend
from .models import InterventionRunRequest, InterventionRunResult


class ReadinessError(RuntimeError):
    pass


class CardiTherapyService:
    def __init__(
        self,
        backends: list[TherapyBackend] | None = None,
        *,
        register_defaults: bool = True,
    ) -> None:
        self._backends: dict[str, TherapyBackend] = {}
        if register_defaults:
            from .pacing_backend import CardiEPPacingBackend

            self.register_backend(CardiEPPacingBackend())
            from .ablation_backend import GraphAblationBackend
            from .pharmacology_backend import PharmacologyBackend

            self.register_backend(GraphAblationBackend())
            self.register_backend(PharmacologyBackend())
        for backend in backends or []:
            self.register_backend(backend)

    def register_backend(self, backend: TherapyBackend) -> None:
        if not isinstance(backend.name, str) or not backend.name.strip():
            raise ValueError("Backend name must not be blank")
        if backend.name in self._backends:
            raise ValueError(f"Backend already registered: {backend.name}")
        self._backends[backend.name] = backend

    def backends(self) -> list[str]:
        return sorted(self._backends)

    def backend_availability(self) -> dict[str, bool]:
        return {name: backend.available() for name, backend in sorted(self._backends.items())}

    def backend_details(self):
        return {
            name: backend.describe()
            if hasattr(backend, "describe")
            else {"name": name, "scientific_scope": "unspecified"}
            for name, backend in sorted(self._backends.items())
        }

    def _backend(self, name: str) -> TherapyBackend:
        backend = self._backends.get(name)
        if backend is None or not backend.available():
            raise BackendUnavailable(f"CardiTherapy backend unavailable: {name}")
        return backend

    def run(self, request: InterventionRunRequest) -> InterventionRunResult:
        # Revalidate mutable models at the trust boundary; delegate a separate copy.
        request = InterventionRunRequest.model_validate(request.model_dump(mode="python"))
        snapshot = request.model_dump(mode="json")
        result = self._backend(request.backend).run(request.model_copy(deep=True))
        result = InterventionRunResult.model_validate(result.model_dump(mode="python"))
        if (
            any(item.endpoint_scope == "patient_outcome" for item in result.outcomes)
            and result.validation_status != "empirically_checked"
        ):
            raise ReadinessError("Patient outcomes require empirical validation")
        if result.subject_id != request.subject_id:
            raise ReadinessError("Backend returned intervention results for a different subject")
        if result.backend != request.backend:
            raise ReadinessError("Backend result identifier does not match request backend")
        if result.plan_id != request.plan.plan_id:
            raise ReadinessError("Backend returned results for a different plan")
        expected = {
            (arm.arm_id, endpoint)
            for arm in request.plan.arms
            for endpoint in request.plan.endpoints
        }
        observed = [(item.arm_id, item.endpoint) for item in result.outcomes]
        if len(observed) != len(set(observed)) or set(observed) != expected:
            raise ReadinessError(
                "Backend must return exactly one outcome per requested arm/endpoint"
            )
        lineage = {
            "twin_state_artifact_id": request.twin_state_ref.artifact_id,
            "baseline_artifact_ids": [item.artifact_id for item in request.baseline_refs],
        }
        for prefix, ref in (
            ("twin_state", request.twin_state_ref),
            ("posterior", request.posterior_ref),
        ):
            if ref is not None:
                lineage[f"{prefix}_artifact_id"] = ref.artifact_id
                if ref.sha256 is not None:
                    lineage[f"{prefix}_sha256"] = ref.sha256
        for key, value in lineage.items():
            if key in result.provenance and result.provenance[key] != value:
                raise ReadinessError(f"Backend returned conflicting lineage: {key}")
        ids = [item.artifact_id for item in result.artifacts]
        if len(ids) != len(set(ids)):
            raise ReadinessError("Result artifact IDs must be unique")
        import hashlib
        import json

        result.provenance["therapy_request_sha256"] = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest()
        result.provenance["therapy_request"] = snapshot
        from . import __version__

        result.provenance["carditherapy_version"] = __version__

        result.provenance.setdefault("twin_state_artifact_id", request.twin_state_ref.artifact_id)
        if request.twin_state_ref.sha256 is not None:
            result.provenance.setdefault("twin_state_sha256", request.twin_state_ref.sha256)
        result.provenance.setdefault(
            "baseline_artifact_ids",
            [item.artifact_id for item in request.baseline_refs],
        )
        if request.posterior_ref is not None:
            result.provenance.setdefault("posterior_artifact_id", request.posterior_ref.artifact_id)
            if request.posterior_ref.sha256 is not None:
                result.provenance.setdefault("posterior_sha256", request.posterior_ref.sha256)
        return result
