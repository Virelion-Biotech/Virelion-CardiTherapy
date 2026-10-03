import pytest

from carditherapy import (
    ArtifactRef,
    InterventionArm,
    InterventionOutcome,
    InterventionPlan,
)


def test_plan_requires_endpoints() -> None:
    with pytest.raises(ValueError):
        InterventionPlan(
            plan_id="P1",
            arms=[InterventionArm(arm_id="control", label="Control")],
            endpoints=[],
        )


def test_plan_rejects_duplicate_arm_ids() -> None:
    with pytest.raises(ValueError):
        InterventionPlan(
            plan_id="P1",
            arms=[
                InterventionArm(arm_id="A", label="A"),
                InterventionArm(arm_id="A", label="A2"),
            ],
            endpoints=["ef"],
        )


def test_outcome_requires_value_or_artifact() -> None:
    with pytest.raises(ValueError):
        InterventionOutcome(
            arm_id="A",
            endpoint="ef",
        )


def test_artifact_ref_accepts_twin_state() -> None:
    ref = ArtifactRef(
        artifact_id="twin",
        kind="cardiac_state",
        uri="file:///state.json",
    )
    assert ref.artifact_id == "twin"
