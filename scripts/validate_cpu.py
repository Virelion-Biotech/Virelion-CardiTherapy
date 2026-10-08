"""Run installed-package validation; generated paths are temporary, source hashes stable."""

import argparse
import hashlib
import tempfile
from pathlib import Path

from carditherapy.serialization import write_json
from carditherapy.validation import run_cpu_validation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("validation/cpu/results.json"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="carditherapy-cpu-") as directory:
        report = run_cpu_validation(Path(directory))
    root = Path(__file__).resolve().parents[1]
    report["source_sha256"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src/carditherapy").glob("*.py"))
    }
    write_json(args.output, report)
    print(report["computational_status"])
    return 0 if report["computational_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
