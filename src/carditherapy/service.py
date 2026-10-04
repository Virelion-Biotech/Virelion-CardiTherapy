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
        for backend in backends or []:
            self.register_backend(backend)

    def register_backend(self, backend: TherapyBackend) -> None:
        self._backends[backend.name] = backend

    def backends(self) -> list[str]:
        return sorted(self._backends)

    def _backend(self, name: str) -> TherapyBackend:
        backend = self._backends.get(name)
        if backend is None or not backend.available():
            raise BackendUnavailable(f"CardiTherapy backend unavailable: {name}")
        return backend

    def run(self, request: InterventionRunRequest) -> InterventionRunResult:
        result = self._backend(request.backend).run(request)
        if result.subject_id != request.subject_id:
            raise ReadinessError("Backend returned intervention results for a different subject")
        if result.backend != request.backend:
            raise ReadinessError("Backend result identifier does not match request backend")

        result.provenance.setdefault(
            "twin_state_artifact_id", request.twin_state_ref.artifact_id
        )
        if request.twin_state_ref.sha256 is not None:
            result.provenance.setdefault(
                "twin_state_sha256", request.twin_state_ref.sha256
            )
        result.provenance.setdefault(
            "baseline_artifact_ids",
            [item.artifact_id for item in request.baseline_refs],
        )
        if request.posterior_ref is not None:
            result.provenance.setdefault(
                "posterior_artifact_id", request.posterior_ref.artifact_id
            )
            if request.posterior_ref.sha256 is not None:
                result.provenance.setdefault(
                    "posterior_sha256", request.posterior_ref.sha256
                )
        return result
