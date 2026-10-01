from __future__ import annotations

from .backends import BackendUnavailable, TherapyBackend
from .models import InterventionRunRequest, InterventionRunResult


class ReadinessError(RuntimeError):
    pass


class CardiTherapyService:
    def __init__(self) -> None:
        self._backends: dict[str, TherapyBackend] = {}

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
        return result
