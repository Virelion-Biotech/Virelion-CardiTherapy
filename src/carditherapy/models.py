from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    kind: str
    uri: str
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intervention_id: str
    kind: Literal[
        "pacing",
        "ablation",
        "pharmacologic",
        "device",
        "regenerative",
        "surgical",
        "custom",
    ]
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    model_service: str | None = None
    model_capability: str | None = None


class InterventionArm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: str
    label: str
    interventions: list[Intervention] = Field(default_factory=list)
    is_comparator: bool = False


class InterventionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    arms: list[InterventionArm]
    endpoints: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_plan(self) -> InterventionPlan:
        if not self.arms:
            raise ValueError("At least one intervention arm is required")
        if not self.endpoints:
            raise ValueError("At least one endpoint is required")
        arm_ids = [arm.arm_id for arm in self.arms]
        if len(arm_ids) != len(set(arm_ids)):
            raise ValueError("Intervention arm IDs must be unique")
        intervention_ids = [
            item.intervention_id for arm in self.arms for item in arm.interventions
        ]
        if len(intervention_ids) != len(set(intervention_ids)):
            raise ValueError("Intervention IDs must be unique across the plan")
        return self


class InterventionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: str
    endpoint: str
    value: float | None = None
    unit: str | None = None
    artifact_ref: ArtifactRef | None = None
    uncertainty_ref: ArtifactRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_value_or_artifact(self) -> InterventionOutcome:
        if self.value is None and self.artifact_ref is None:
            raise ValueError("Outcome requires a scalar value or artifact reference")
        return self


class InterventionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    backend: str
    twin_state_ref: ArtifactRef
    plan: InterventionPlan
    posterior_ref: ArtifactRef | None = None
    baseline_refs: list[ArtifactRef] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class InterventionRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0"
    subject_id: str
    backend: str
    plan_id: str
    outcomes: list[InterventionOutcome] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    validation_status: Literal[
        "unvalidated",
        "software_checked",
        "numerically_checked",
        "empirically_checked",
    ] = "unvalidated"
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
