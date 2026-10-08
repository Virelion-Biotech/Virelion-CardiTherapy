"""Generate the canonical notebook at an explicitly finalized source revision."""

import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.ref):
        raise ValueError("Provide a full immutable Git commit SHA")
    bootstrap = """import hashlib, json, pathlib, platform, subprocess, sys, tempfile, zipfile
SOURCE_REVISION = "__REVISION__"
work = pathlib.Path(tempfile.mkdtemp(prefix="carditherapy-cpu-"))
repo = work / "repo"
log = work / "execution.log"
def command(arguments, cwd=None):
    with log.open("a", encoding="utf-8") as handle:
        handle.write("\\n$ " + " ".join(map(str, arguments)) + "\\n")
        handle.flush()
        completed = subprocess.run(list(map(str, arguments)), cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    if completed.returncode:
        print(log.read_text()[-12000:])
        raise RuntimeError(f"Command failed ({completed.returncode}); log: {log}")
command(["git", "clone", "https://github.com/Virelion-Biotech/Virelion-CardiTherapy.git", repo])
command(["git", "checkout", "--detach", SOURCE_REVISION], cwd=repo)
observed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
assert observed == SOURCE_REVISION
command([sys.executable, "-m", "venv", work / "venv"])
python = work / "venv/bin/python"
cli = work / "venv/bin/carditherapy"
command([python, "-m", "pip", "install", "-e", ".[dev,cardiep]"], cwd=repo)
print("Installed pinned CardiTherapy and CardiEP. Running CPU verification.")
""".replace("__REVISION__", args.ref)
    execute = """try:
    command([python, "-m", "pytest", "-q", "--cov=carditherapy", "--cov-branch", "--cov-fail-under=95", "--cov-report=json:" + str(work / "coverage.json")], cwd=repo)
    command([python, "scripts/validate_cpu.py", "--output", work / "results.json"], cwd=repo)
    sample = work / "sample"
    sample_code = "from pathlib import Path; from carditherapy.validation import make_request; from carditherapy.serialization import write_json; root=Path(" + repr(str(sample)) + "); write_json(root/'request.json', make_request(root).model_dump(mode='json'))"
    command([python, "-c", sample_code], cwd=repo)
    command([cli, "doctor"], cwd=repo)
    command([cli, "validate", sample / "request.json"], cwd=repo)
    command([cli, "run", sample / "request.json", "--output", sample / "result.json"], cwd=repo)
    report = json.loads((work / "results.json").read_text())
    assert report["computational_status"] == "passed"
    print("Nine analytic experiments pass. Empirical status:", report["empirical_status"])
finally:
    environment = subprocess.run([python, "-m", "pip", "freeze"], capture_output=True, text=True)
    (work / "environment.txt").write_text(environment.stdout)
    (work / "source_revision.txt").write_text(SOURCE_REVISION + "\\nPython host: " + platform.python_version())
    files = [path for path in work.rglob("*") if path.is_file() and not path.is_relative_to(repo) and not path.is_relative_to(work/"venv")]
    manifest = {str(path.relative_to(work)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    (work / "checksums.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    archive = pathlib.Path.cwd() / "CardiTherapy_CPU_Validation_results.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in files + [work / "checksums.json"]:
            bundle.write(path, str(path.relative_to(work)))
        bundle.write(repo / "docs/CPU_AUDIT.md", "CPU_AUDIT.md")
    print("Results saved:", archive)
    try:
        from google.colab import files as colab_files
    except ImportError:
        print("Download the ZIP from your notebook file browser.")
    else:
        colab_files.download(str(archive))
"""
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "cells": [],
    }
    cells = [
        (
            "markdown",
            "# CardiTherapy CPU validation from scratch\n\nNo GPU or data upload required. Installs exact CardiTherapy and CardiEP commits in a fresh environment, runs the complete test suite and nine independent analytic experiments, then executes a real pacing request through the CLI. Downloads a ZIP with logs, coverage, numeric results, request/output artifacts, environment and checksums.\n\nThis verifies computation only. No measured patient pacing responses or clinical outcomes are validated. Posterior uncertainty is not propagated. Activation span is not measured ECG QRS duration.\n\nRun both code cells in order. A failed execution still packages available evidence in the final cell. Source revision: `"
            + args.ref
            + "`.",
        ),
        ("code", bootstrap),
        ("code", execute),
    ]
    for index, (kind, source) in enumerate(cells):
        cell = {
            "cell_type": kind,
            "id": f"carditherapy-{index}",
            "metadata": {},
            "source": source.splitlines(keepends=True),
        }
        if kind == "code":
            compile(source, "notebook-cell", "exec")
            cell.update({"execution_count": None, "outputs": []})
        notebook["cells"].append(cell)
    root = Path(__file__).resolve().parents[1] / "notebooks"
    root.mkdir(exist_ok=True)
    (root / "CardiTherapy_CPU_Validation.ipynb").write_text(json.dumps(notebook, indent=2) + "\n")


if __name__ == "__main__":
    main()
