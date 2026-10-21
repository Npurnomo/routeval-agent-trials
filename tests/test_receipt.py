"""Exercise receipt corruption and local-file boundaries, without policy claims."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "receipt", Path(__file__).parents[1] / "tools/check_submission.py"
)
assert SPEC and SPEC.loader
receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt)


class ReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.task = self.root / "task"
        self.task.mkdir()
        self.out = self.root / "out"
        self.out.mkdir()
        self.contract = self.task / "contract.json"
        self.contract.write_text('{"policies":["x"]}')
        (self.out / "evidence.json").write_text('{"a/b":{"~value":[null,0]}}')
        self.path = self.out / "submission.json"
        self.data = {
            "record_version": "trial-decisions-1",
            "track": "integration",
            "condition": "stdlib",
            "reference_id": "x",
            "contract_sha256": hashlib.sha256(self.contract.read_bytes()).hexdigest(),
            "input_sha256": {
                "contract.json": hashlib.sha256(self.contract.read_bytes()).hexdigest()
            },
            "release_executed": False,
            "candidates": [
                {
                    "candidate_id": "x",
                    "recommendation": "invalid",
                    "observations": {"total_cost_usd": None},
                    "limitations": [],
                    "artifacts": ["evidence.json"],
                    "checks": {
                        "billing": {
                            "status": "unavailable",
                            "observed": None,
                            "required": 0,
                            "evidence": ["evidence.json#/a~1b/~0value/0"],
                        }
                    },
                }
            ],
        }

    def run_check(self, data: dict | None = None) -> dict:
        self.path.write_text(json.dumps(self.data if data is None else data))
        return receipt.validate(self.path, self.task, self.root)

    def test_unknown_measurement_and_failed_policy_are_valid_receipts(self) -> None:
        self.assertEqual(self.run_check()["receipt_checks"], "pass")

    def test_input_tampering(self) -> None:
        (self.task / "extra.json").write_text("1")
        self.data["input_sha256"]["extra.json"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.run_check()

    def test_candidate_omission_or_duplicate(self) -> None:
        for candidates in ([], self.data["candidates"] * 2):
            broken = deepcopy(self.data)
            broken["candidates"] = candidates
            with self.assertRaises(ValueError):
                self.run_check(broken)

    def test_missing_check_field(self) -> None:
        del self.data["candidates"][0]["checks"]["billing"]["required"]
        with self.assertRaisesRegex(ValueError, "Incomplete check"):
            self.run_check()

    def test_task_relative_input_evidence(self) -> None:
        self.data["candidates"][0]["checks"]["billing"]["evidence"] = ["contract.json#/policies/0"]
        self.assertEqual(self.run_check()["receipt_checks"], "pass")

    def test_broken_pointer_and_negative_index(self) -> None:
        for link in ("evidence.json#/missing", "evidence.json#/a~1b/~0value/-1"):
            self.data["candidates"][0]["checks"]["billing"]["evidence"] = [link]
            with self.assertRaises((KeyError, ValueError)):
                self.run_check()

    def test_absolute_network_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "outside.json"
            outside.write_text("{}")
            (self.out / "escape.json").symlink_to(outside)
            for name in (str(outside), "https://example.com/file", "escape.json"):
                with self.assertRaises(ValueError):
                    receipt.local_file(self.out, name, self.root)

    def test_strict_json(self) -> None:
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e9999}'):
            self.path.write_text(text)
            with self.assertRaises(ValueError):
                receipt.read(self.path)

    def test_trial_cannot_release(self) -> None:
        self.data["release_executed"] = True
        with self.assertRaisesRegex(ValueError, "release_executed"):
            self.run_check()


if __name__ == "__main__":
    unittest.main()
