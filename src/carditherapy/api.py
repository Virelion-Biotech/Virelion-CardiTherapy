from __future__ import annotations

from typing import Any

from .models import InterventionRunRequest
from .service import CardiTherapyService


class TherapyAPI:
    capabilities = ("therapy.health", "therapy.run")

    def __init__(self, service: CardiTherapyService | None = None) -> None:
        self.service = service or CardiTherapyService()

    def health(self) -> dict[str, Any]:
        return {
            "service": "CardiTherapy",
            "status": "ok",
            "backends": self.service.backends(),
            "backend_availability": self.service.backend_availability(),
            "backend_details": self.service.backend_details(),
            "capabilities": list(self.capabilities),
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = InterventionRunRequest.model_validate(payload)
        return self.service.run(request).model_dump(mode="json")
