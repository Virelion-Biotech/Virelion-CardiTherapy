import pytest
from pydantic import ValidationError
from carditherapy import (
    ArtifactRef, CardiTherapyService, Intervention, InterventionOutcome,
    InterventionPlan, InterventionArm, InterventionRunRequest, RegenerativeInterventionSpec,
)
from carditherapy.backends import BackendUnavailable

def base_spec(**kw):
    value=dict(
      modality="modified_mrna",intervention_domain="myocardial_regeneration",
      target="MYC/CCNT1",mechanism="transient expression perturbation",
      dose=1.0,dose_unit="ug",route="intramyocardial",
      source_maturity="preclinical",source_record_ids=["paper-1"],
      source_provenance=[{"source_identifier":"DOI:10.1000/x","source_type":"peer_reviewed","source_url":"https://example.org/x","source_sha256":"a"*64}],
      comparator_definition={"type":"matched_control","description":"vehicle control"},
      uncertainty_reference={"status":"not_characterized","reason":"no calibrated uncertainty available"},
      calibration_status="none",calibration_evidence=[],model_supported_endpoints=[],
      model_limitations=["No validated regenerative backend; no clinical efficacy inference"],
      payload="synthetic mRNA payload description",expression_window="transient, measured in source",tissue_targeting="local injection"
    )
    value.update(kw); return value

def test_modified_mrna_contract_is_valid_and_non_executable():
    spec=RegenerativeInterventionSpec(**base_spec())
    item=Intervention(intervention_id="tx-1",kind="regenerative",target="myocardium",regenerative_spec=spec)
    assert item.regenerative_spec.modality=="modified_mrna"

def test_aav_requires_capsid_promoter_and_biodistribution():
    with pytest.raises(ValidationError,match="aav_gene_delivery requires"):
        RegenerativeInterventionSpec(**base_spec(modality="aav_gene_delivery",capsid=None,promoter=None,biodistribution=None,immunogenicity=None))

def test_rnai_requires_target_chemistry_and_pd():
    with pytest.raises(ValidationError,match="rna_interference requires"):
        RegenerativeInterventionSpec(**base_spec(modality="rna_interference",target_transcript_or_protein=None,chemistry=None,pharmacodynamic_readouts=[]))

def test_vascular_graft_is_a_separate_surgical_domain():
    spec=RegenerativeInterventionSpec(**base_spec(modality="vascular_tissue_engineered_graft",intervention_domain="vascular_surgical",graft_material="decellularized vessel",product_identity="vascular graft",manufacturing={"process":"defined"},potency={"assay":"patency"},patency_outcomes=["primary patency"]))
    item=Intervention(intervention_id="graft-1",kind="surgical",target="vascular graft",regenerative_spec=spec)
    assert item.regenerative_spec.intervention_domain=="vascular_surgical"

def test_model_endpoint_requires_calibration_evidence():
    with pytest.raises(ValidationError,match="model endpoints require declared calibration evidence"):
        RegenerativeInterventionSpec(**base_spec(model_supported_endpoints=["ventricular_function"]))
    calibrated=RegenerativeInterventionSpec(**base_spec(calibration_status="model_proxy_calibrated",calibration_evidence=[{"dataset":"paired calibration set","source_record_id":"cal-1"}],model_supported_endpoints=["ventricular_function"]))
    assert calibrated.model_supported_endpoints==["ventricular_function"]

def test_lvef_cannot_be_relabelled_as_new_myocardium():
    with pytest.raises(ValidationError,match="LVEF is a ventricular-function endpoint"):
        InterventionOutcome(arm_id="treated",endpoint="lvef_change",endpoint_domain="cardiomyocyte_number",value=0.1,unit="fraction")

def test_model_proxy_cannot_claim_new_myocardium_or_clinical_benefit():
    with pytest.raises(ValidationError,match="model-proxy outcomes"):
        InterventionOutcome(arm_id="treated",endpoint="new_myocardium",value=1,unit="count",endpoint_domain="cardiomyocyte_number")
    with pytest.raises(ValidationError,match="model-proxy outcomes"):
        InterventionOutcome(arm_id="treated",endpoint="clinical_benefit",value=1,unit="score")

def test_unregistered_regenerative_backend_fails_closed():
    spec=RegenerativeInterventionSpec(**base_spec())
    request=InterventionRunRequest(
      subject_id="SYNTH-1",backend="regenerative-unregistered",
      twin_state_ref=ArtifactRef(artifact_id="twin",kind="cardiac_state",uri="file:///tmp/twin.json"),
      plan=InterventionPlan(plan_id="P1",arms=[InterventionArm(arm_id="active",label="Active",interventions=[Intervention(intervention_id="tx",kind="regenerative",target="myocardium",regenerative_spec=spec)])],endpoints=["ventricular_function"])
    )
    with pytest.raises(BackendUnavailable):
        CardiTherapyService().run(request)
