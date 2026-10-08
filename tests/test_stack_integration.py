import pytest

pytest.importorskip("cardiep")

from carditherapy.validation import run_cpu_validation


def test_actual_cardiep_matches_independent_analytic_reference(tmp_path):
    report = run_cpu_validation(tmp_path)
    assert report["computational_status"] == "passed"
    assert len(report["checks"]) == 9
    assert all(item["deterministic"] for item in report["checks"])
    assert report["empirical_status"] == "not_validated"
