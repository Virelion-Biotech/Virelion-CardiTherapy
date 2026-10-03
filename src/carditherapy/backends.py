from __future__ import annotations

from typing import Protocol

from .models import InterventionRunRequest, InterventionRunResult


class TherapyBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def run(self, request: InterventionRunRequest) -> InterventionRunResult: ...


class BackendUnavailable(RuntimeError):
    pass
