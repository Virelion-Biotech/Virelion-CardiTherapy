import json
import runpy
import sys

import pytest
from test_pacing_backend import _FakeEPAPI, _request

from carditherapy import CardiEPPacingBackend, CardiTherapyService
from carditherapy.api import TherapyAPI
from carditherapy.cli import main
from carditherapy.models import ArtifactRef
from carditherapy.pacing_backend import _local_path, _verify_local_ref


def test_health_reports_executable_availability():
    service = CardiTherapyService()
    health = TherapyAPI(service).health()
    assert health["backends"] == ["cardiep-pacing-v1"]
    assert health["backend_availability"] == service.backend_availability()


def test_cli_doctor_and_module(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["carditherapy", "doctor"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("carditherapy", run_name="__main__")
    assert exc.value.code == 0


def test_cli_run_validate_and_errors(tmp_path, monkeypatch, capsys):
    request = _request(tmp_path)
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    output = tmp_path / "result.json"
    service = CardiTherapyService(
        [CardiEPPacingBackend(lambda: _FakeEPAPI(tmp_path))], register_defaults=False
    )
    monkeypatch.setattr("carditherapy.cli.TherapyAPI", lambda: TherapyAPI(service))
    monkeypatch.setattr(sys, "argv", ["carditherapy", "validate", str(path)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["carditherapy", "run", str(path), "--output", str(output)])
    assert main() == 0
    assert json.loads(output.read_text())["plan_id"] == request.plan.plan_id
    monkeypatch.setattr(sys, "argv", ["carditherapy", "run", str(path), "--output", str(path)])
    assert main() == 2
    assert path.read_text() == request.model_dump_json()
    path.write_text('{"x":NaN}')
    assert main() == 2
    assert "carditherapy:" in capsys.readouterr().err


@pytest.mark.parametrize("uri", ["https://example.com/file", "file://remote.example/file"])
def test_local_uri_rejects_remote(uri):
    with pytest.raises(ValueError):
        _local_path(uri)


def test_remote_reference_with_claimed_hash_fails():
    ref = ArtifactRef(artifact_id="remote", kind="state", uri="memory://state", sha256="0" * 64)
    with pytest.raises(RuntimeError):
        _verify_local_ref(ref, label="State")


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"outputs": []},
        {"outputs": [{"artifact_id": "missing", "kind": "ep_summary", "uri": "/no/such/file"}]},
        {
            "outputs": [
                {"artifact_id": "missing", "kind": "ep_summary", "uri": "/no/such/file"},
                {"artifact_id": "missing", "kind": "ep_summary", "uri": "/no/such/file"},
            ]
        },
    ],
)
def test_absent_or_ambiguous_summary(result):
    with pytest.raises((TypeError, RuntimeError, FileNotFoundError)):
        CardiEPPacingBackend._summary(result)


@pytest.mark.parametrize("payload", [[], {}, {"activation_span_ms": 1}])
def test_summary_missing_timing(tmp_path, payload):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(payload))
    with pytest.raises((TypeError, RuntimeError)):
        CardiEPPacingBackend._summary(
            {"outputs": [{"artifact_id": "s", "kind": "ep_summary", "uri": path.as_uri()}]}
        )


def test_summary_hash_mismatch(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text("{}")
    with pytest.raises(RuntimeError, match="SHA-256"):
        CardiEPPacingBackend._summary(
            {
                "outputs": [
                    {
                        "artifact_id": "s",
                        "kind": "ep_summary",
                        "uri": path.as_uri(),
                        "sha256": "0" * 64,
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "no_anatomy",
        "no_backend",
        "no_parameters",
        "invalid_units",
        "empty_parameters",
        "multiple_interventions",
        "unsupported_parameters",
        "coordinate_conflict",
    ],
)
def test_invalid_pacing_configuration(tmp_path, mutation):
    request = _request(tmp_path)
    if mutation == "no_anatomy":
        request.baseline_refs = []
    if mutation == "no_backend":
        request.settings.pop("ep_backend")
    if mutation == "no_parameters":
        request.settings.pop("ep_parameters")
    if mutation == "invalid_units":
        request.settings["ep_parameter_units"] = [1]
    if mutation == "empty_parameters":
        request.plan.arms[1].interventions[0].parameters = {}
    if mutation == "multiple_interventions":
        other = request.plan.arms[1].interventions[0].model_copy(deep=True)
        other.intervention_id = "second"
        request.plan.arms[1].interventions.append(other)
    if mutation == "unsupported_parameters":
        request.plan.arms[1].interventions[0].parameters = {"dose": 1}
    if mutation == "coordinate_conflict":
        request.baseline_refs[0].coordinate_frame = "other"
    api = _FakeEPAPI(tmp_path)
    with pytest.raises((ValueError, TypeError)):
        CardiEPPacingBackend(lambda: api).run(request)
    assert not api.calls


@pytest.mark.parametrize(
    "mutation", ["subject", "backend", "status", "summary_subject", "duplicate_artifact"]
)
def test_delegate_result_validation(tmp_path, mutation):
    class BadAPI(_FakeEPAPI):
        def simulate(self, payload):
            result = super().simulate(payload)
            if mutation == "subject":
                result["subject_id"] = "other"
            if mutation == "backend":
                result["backend"] = "other"
            if mutation == "status":
                result["validation_status"] = "perfect"
            if mutation == "summary_subject":
                from pathlib import Path

                path = Path(result["outputs"][0]["uri"].removeprefix("file://"))
                data = json.loads(path.read_text())
                data["subject_id"] = "other"
                path.write_text(json.dumps(data))
                result["outputs"][0]["sha256"] = None
            if mutation == "duplicate_artifact":
                result["outputs"][0]["artifact_id"] = "same"
            return result

    with pytest.raises((ValueError, RuntimeError)):
        CardiEPPacingBackend(lambda: BadAPI(tmp_path)).run(_request(tmp_path))


def test_backend_registration_is_explicit():
    service = CardiTherapyService()
    with pytest.raises(ValueError, match="already registered"):
        service.register_backend(CardiEPPacingBackend())

    class Blank:
        name = " "

    with pytest.raises(ValueError, match="blank"):
        service.register_backend(Blank())


def test_cli_protects_input_artifacts(tmp_path, monkeypatch):
    request = _request(tmp_path)
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    from pathlib import Path

    anatomy = Path(request.baseline_refs[0].uri.removeprefix("file://"))
    monkeypatch.setattr(sys, "argv", ["carditherapy", "run", str(path), "--output", str(anatomy)])
    assert main() == 2
    assert anatomy.read_text() == "{}\n"


@pytest.mark.parametrize(
    "name,value", [("unknown", 1), ("ep_backend", True), ("ep_parameter_units", [])]
)
def test_unusable_settings_fail_before_delegate(tmp_path, name, value):
    request = _request(tmp_path)
    request.settings[name] = value
    api = _FakeEPAPI(tmp_path)
    with pytest.raises((ValueError, TypeError)):
        CardiEPPacingBackend(lambda: api).run(request)
    assert not api.calls


def test_optional_backend_missing_is_reported(monkeypatch):
    import builtins

    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "cardiep":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    backend = CardiEPPacingBackend()
    assert not backend.available()
    from carditherapy.backends import BackendUnavailable

    with pytest.raises(BackendUnavailable):
        backend._api()
