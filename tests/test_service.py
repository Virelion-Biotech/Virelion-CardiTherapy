import pytest

from carditherapy import (
    ArtifactRef,
    CardiTherapyService,
    InterventionArm,
    InterventionPlan,
    InterventionRunRequest,
)
from carditherapy.backends import BackendUnavailable


def test_service_fails_closed_without_backend() -> None:
    request = InterventionRunRequest(
        subject_id="S1",
        backend="missing",
        twin_state_ref=ArtifactRef(
            artifact_id="twin",
            kind="cardiac_state",
            uri="file:///state.json",
        ),
        plan=InterventionPlan(
            plan_id="P1",
            arms=[InterventionArm(arm_id="control", label="Control", is_comparator=True)],
            endpoints=["ejection_fraction"],
        ),
    )
    with pytest.raises(BackendUnavailable):
        CardiTherapyService().run(request)
