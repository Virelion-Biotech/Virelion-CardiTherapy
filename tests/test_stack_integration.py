import pytest

pytest.importorskip("cardiep")

from carditherapy.validation import run_cpu_validation


def test_actual_cardiep_matches_independent_analytic_reference(tmp_path):
    report = run_cpu_validation(tmp_path)
    assert report["computational_status"] == "passed"
    assert len(report["checks"]) == 9
    assert all(item["deterministic"] for item in report["checks"])
    assert report["empirical_status"] == "not_validated"


def test_validation_rejects_observed_wrong_dependency_commit(tmp_path, monkeypatch):
    class WrongDistribution:
        def read_text(self, name):
            assert name == "direct_url.json"
            return '{"vcs_info":{"commit_id":"wrong"}}'

    monkeypatch.setattr("carditherapy.validation.distribution", lambda name: WrongDistribution())
    with pytest.raises(ValueError, match="revision differs"):
        run_cpu_validation(tmp_path)
