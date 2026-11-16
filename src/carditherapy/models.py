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


class RegenerativeInterventionSpec(ContractModel):
    """Evidence- and calibration-gated description of a non-executable intervention."""
    model_config = ConfigDict(extra="forbid")
    modality: Literal["aav_gene_delivery","circular_rna","modified_mrna","rna_interference","cell_derived_product","vascular_tissue_engineered_graft"]
    intervention_domain: Literal["myocardial_regeneration","genetic_disease_modification","cell_derived_repair","vascular_surgical"]
    target: str
    mechanism: str
    dose: float = Field(gt=0)
    dose_unit: str
    route: str
    source_maturity: Literal["preclinical","clinical","regulatory","company_reported","unknown"]
    source_record_ids: list[str] = Field(min_length=1)
    source_provenance: list[dict[str, Any]] = Field(min_length=1)
    comparator_definition: dict[str, Any]
    uncertainty_reference: dict[str, Any]
    calibration_status: Literal["none","model_proxy_calibrated","empirically_calibrated"] = "none"
    calibration_evidence: list[dict[str, Any]] = Field(default_factory=list)
    model_supported_endpoints: list[Literal["target_engagement","expression","biodistribution","ventricular_function","fibrosis","cardiomyocyte_proliferation","cytokinesis","cardiomyocyte_number","arrhythmia","toxicity","graft_patency","graft_outcomes"]] = Field(default_factory=list)
    model_limitations: list[str] = Field(min_length=1)
    capsid: str | None = None
    promoter: str | None = None
    payload: str | None = None
    biodistribution: dict[str, Any] | None = None
    immunogenicity: dict[str, Any] | None = None
    expression_window: str | None = None
    tissue_targeting: str | None = None
    target_transcript_or_protein: str | None = None
    chemistry: str | None = None
    pharmacodynamic_readouts: list[str] = Field(default_factory=list)
    cell_source: str | None = None
    product_identity: str | None = None
    manufacturing: dict[str, Any] | None = None
    potency: dict[str, Any] | None = None
    proposed_mechanism: str | None = None
    graft_material: str | None = None
    patency_outcomes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_modality_contract(self):
        required = {
            "aav_gene_delivery": ("capsid","promoter","payload","biodistribution","immunogenicity"),
            "circular_rna": ("payload","expression_window","tissue_targeting"),
            "modified_mrna": ("payload","expression_window","tissue_targeting"),
            "rna_interference": ("target_transcript_or_protein","chemistry","pharmacodynamic_readouts"),
            "cell_derived_product": ("cell_source","product_identity","manufacturing","potency","proposed_mechanism"),
            "vascular_tissue_engineered_graft": ("graft_material","product_identity","manufacturing","potency","patency_outcomes"),
        }[self.modality]
        missing=[name for name in required if not getattr(self,name)]
        if missing: raise ValueError(f"{self.modality} requires: {', '.join(missing)}")
        if self.modality=="vascular_tissue_engineered_graft" and self.intervention_domain!="vascular_surgical":
            raise ValueError("vascular grafts must remain in the separate vascular_surgical domain")
        if self.modality!="vascular_tissue_engineered_graft" and self.intervention_domain=="vascular_surgical":
            raise ValueError("vascular_surgical domain is reserved for vascular graft interventions")
        if not self.comparator_definition: raise ValueError("comparator_definition is required")
        if not self.uncertainty_reference: raise ValueError("uncertainty_reference is required")
        if any(not str(x).strip() for x in self.model_limitations): raise ValueError("model_limitations must not contain blanks")
        for i, source in enumerate(self.source_provenance):
            for key in ("source_identifier","source_type","source_url","source_sha256"):
                if not isinstance(source.get(key),str) or not source[key].strip(): raise ValueError(f"source_provenance[{i}].{key} is required")
            digest=source["source_sha256"]
            if len(digest)!=64 or any(ch not in string.hexdigits for ch in digest): raise ValueError(f"source_provenance[{i}].source_sha256 must be SHA-256")
        if self.model_supported_endpoints and (self.calibration_status=="none" or not self.calibration_evidence):
            raise ValueError("model endpoints require declared calibration evidence")
        if self.calibration_status=="empirically_calibrated" and not self.calibration_evidence:
            raise ValueError("empirical calibration status requires calibration_evidence")
        return self


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
    regenerative_spec: RegenerativeInterventionSpec | None = None

    @model_validator(mode="after")
    def require_modality_contract(self):
        if self.kind in {"regenerative", "surgical"} and self.regenerative_spec is None:
            raise ValueError("regenerative/surgical interventions require regenerative_spec")
        if self.kind not in {"regenerative", "surgical"} and self.regenerative_spec is not None:
            raise ValueError("regenerative_spec is only valid for regenerative/surgical interventions")
        if self.regenerative_spec is not None and self.kind == "surgical" and self.regenerative_spec.modality != "vascular_tissue_engineered_graft":
            raise ValueError("surgical regenerative spec currently supports vascular graft class only")
        if self.regenerative_spec is not None and self.kind == "regenerative" and self.regenerative_spec.modality == "vascular_tissue_engineered_graft":
            raise ValueError("vascular grafts must use kind=surgical and vascular_surgical domain")
        return self


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
    endpoint_domain: Literal["unspecified","target_engagement","expression","biodistribution","ventricular_function","fibrosis","cell_cycle_entry","cytokinesis","cardiomyocyte_number","arrhythmia","toxicity","vascular_graft"] = "unspecified"
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
        endpoint=self.endpoint.casefold().replace("-", "_").replace(" ", "_")
        if ("ejection_fraction" in endpoint or endpoint in {"lvef","lvef_change"}) and self.endpoint_domain not in {"ventricular_function","unspecified"}:
            raise ValueError("LVEF is a ventricular-function endpoint, not cardiomyocyte generation or clinical benefit")
        if endpoint in {"new_myocardium","new_cardiomyocytes","cardiomyocyte_generation"} and self.endpoint_domain not in {"cardiomyocyte_number","cytokinesis"}:
            raise ValueError("new myocardium claims require direct cell-generation endpoint domain")
        if self.endpoint_scope=="model_proxy" and endpoint in {"clinical_benefit","patient_benefit","new_myocardium","new_cardiomyocytes","cardiomyocyte_generation"}:
            raise ValueError("model-proxy outcomes cannot be labelled clinical benefit or new myocardium")
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
