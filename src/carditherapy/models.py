from __future__ import annotations

import json
import math
import string
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def require_json_and_identifiers(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"{name} must not be blank")
        json.dumps(self.model_dump(mode="python"), allow_nan=False)
        return self


class ArtifactRef(ContractModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    kind: str
    uri: str
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    coordinate_frame: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def valid_hash(cls, value):
        if value is not None and any(c not in string.hexdigits for c in value):
            raise ValueError("sha256 must be hexadecimal")
        return None if value is None else value.lower()


class Intervention(ContractModel):
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


class InterventionArm(ContractModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: str
    label: str
    interventions: list[Intervention] = Field(default_factory=list)
    is_comparator: bool = False

    @field_validator("is_comparator", mode="before")
    @classmethod
    def strict_comparator(cls, value):
        if not isinstance(value, bool):
            raise ValueError("is_comparator must be boolean")  # noqa: TRY004 - Pydantic validation error
        return value


class InterventionPlan(ContractModel):
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
        if any(not item.strip() for item in self.endpoints):
            raise ValueError("Endpoints must not be blank")
        if len(self.endpoints) != len(set(self.endpoints)):
            raise ValueError("Endpoints must be unique")
        arm_ids = [arm.arm_id for arm in self.arms]
        if len(arm_ids) != len(set(arm_ids)):
            raise ValueError("Intervention arm IDs must be unique")
        intervention_ids = [item.intervention_id for arm in self.arms for item in arm.interventions]
        if len(intervention_ids) != len(set(intervention_ids)):
            raise ValueError("Intervention IDs must be unique across the plan")
        return self


class InterventionOutcome(ContractModel):
    model_config = ConfigDict(extra="forbid")

    arm_id: str
    endpoint: str
    endpoint_scope: Literal["model_proxy", "patient_outcome"] = "model_proxy"
    endpoint_tier: Literal[
        "electrical",
        "acute_mechanical",
        "remodeling",
        "clinical",
        "pharmacology_proxy",
        "unspecified",
    ] = "unspecified"
    value: float | None = None
    unit: str | None = None
    artifact_ref: ArtifactRef | None = None
    uncertainty_ref: ArtifactRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("value", mode="before")
    @classmethod
    def finite_number(cls, value):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Outcome value must be a finite number")
        return value

    @model_validator(mode="after")
    def require_value_or_artifact(self) -> InterventionOutcome:
        if self.value is None and self.artifact_ref is None:
            raise ValueError("Outcome requires a scalar value or artifact reference")
        return self


class InterventionRunRequest(ContractModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    backend: str
    twin_state_ref: ArtifactRef
    plan: InterventionPlan
    posterior_ref: ArtifactRef | None = None
    baseline_refs: list[ArtifactRef] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_artifact_ids(self):
        refs = [self.twin_state_ref, *self.baseline_refs]
        if self.posterior_ref is not None:
            refs.append(self.posterior_ref)
        ids = [item.artifact_id for item in refs]
        if len(ids) != len(set(ids)):
            raise ValueError("Input artifact IDs must be unique")
        return self


class InterventionRunResult(ContractModel):
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
