"""Run real security assertions and save their observed outcomes. No external calls."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Results:
    def __init__(self):
        self.tests = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.failed):
            self.tests.append({
                "test": report.nodeid,
                "result": {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}[report.outcome],
                "phase": report.when,
                "seconds": round(report.duration, 4),
                "failure": str(report.longrepr) if report.failed else None,
            })


def main():
    results = Results()
    code = pytest.main([str(ROOT / "tests" / "test_security.py"), "-q", "--tb=short"], plugins=[results])
    summary = {key: sum(t["result"] == key for t in results.tests) for key in ("PASS", "FAIL", "SKIP")}
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "pytest_exit_code": int(code),
               "scope": "Local code and ASGI routes; synthetic model replies and database spies; no external calls",
               "summary": summary, "tests": results.tests}
    directory = ROOT / "results" / "security-tests"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "local-security-results.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nSECURITY RESULT: {summary['PASS']} PASS, {summary['FAIL']} FAIL, {summary['SKIP']} SKIP")
    print(f"Evidence: {path}")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
