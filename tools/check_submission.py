"""Check a local trial receipt and its evidence links; never execute its contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


def read(path: Path) -> Any:
    """Read strict JSON, rejecting duplicate keys and nonfinite numbers."""

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def bad(value: str) -> None:
        raise ValueError(f"Nonfinite number: {value}")

    result = json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=bad)

    def finite(value: Any) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite numeric overflow")
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)

    finite(result)
    return result


def pointer(value: Any, fragment: str) -> Any:
    """Resolve a JSON pointer without evaluating record text."""
    if not fragment:
        return value
    if not fragment.startswith("/"):
        raise ValueError("Evidence fragment must be a JSON pointer")
    for part in fragment[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise ValueError("Invalid array index")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def local_file(base: Path, relative: str, allowed_root: Path) -> Path:
    """Allow local reviewed files only, including resolving symlinks."""
    if not relative or Path(relative).is_absolute() or "://" in relative:
        raise ValueError("Expected a relative local path")
    path = (base / relative).resolve()
    if not path.is_relative_to(allowed_root.resolve()) or not path.is_file():
        raise ValueError(f"Evidence outside allowed root or missing: {relative}")
    return path


def validate(receipt: Path, task: Path, allowed_root: Path) -> dict[str, Any]:
    """Check shape, input digests, candidate coverage and resolvable evidence.

    This is a receipt check, not an independent policy verdict or attestation.
    Unknown measurements and failed checks are legitimate recorded findings.
    """
    data, contract = read(receipt), read(task / "contract.json")
    if not isinstance(data, dict) or not isinstance(contract, dict):
        raise ValueError("Receipt and contract must be objects")
    required = {
        "record_version",
        "track",
        "condition",
        "contract_sha256",
        "reference_id",
        "input_sha256",
        "release_executed",
        "candidates",
    }
    if required - data.keys():
        raise ValueError(f"Missing fields: {sorted(required - data.keys())}")
    if data["record_version"] != "trial-decisions-1":
        raise ValueError("Unsupported record version")
    if data["track"] not in {"integration", "evaluation"}:
        raise ValueError("Unknown track")
    if data["condition"] not in {"stdlib", "routeval"}:
        raise ValueError("Unknown condition")
    if data["release_executed"] is not False:
        raise ValueError("Trial must record release_executed=false")
    if data["contract_sha256"] != hashlib.sha256((task / "contract.json").read_bytes()).hexdigest():
        raise ValueError("Contract digest mismatch")
    if data["track"] != ("integration" if "policies" in contract else "evaluation"):
        raise ValueError("Track differs from the supplied contract")
    if not isinstance(data["reference_id"], str) or not data["reference_id"]:
        raise ValueError("Reference identity required")
    hashes = data["input_sha256"]
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Input hashes required")
    for name, digest in hashes.items():
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Invalid SHA-256")
        # Task basenames are accepted; nested paths are relative to the receipt.
        base = task if Path(name).name == name else receipt.parent
        path = local_file(base, name, allowed_root)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Input digest mismatch: {name}")
    candidates = data["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Candidate list required")
    expected = contract.get("policies", contract.get("candidates"))
    ids = [c["candidate_id"] for c in candidates]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError("Candidate population incomplete or duplicated")
    link_count = 0
    cache: dict[Path, Any] = {}

    def evidence_file(name: str) -> Path:
        # Both task-relative input filenames and receipt-relative result paths
        # were permitted by the frozen submission instructions.
        base = task if name in hashes and Path(name).name == name else receipt.parent
        return local_file(base, name, allowed_root)

    for candidate in candidates:
        if candidate["recommendation"] not in {"accept", "reject", "invalid"}:
            raise ValueError("Unknown recommendation")
        if not isinstance(candidate.get("observations"), dict):
            raise ValueError("Observations required")
        if not isinstance(candidate.get("limitations"), list):
            raise ValueError("Limitations list required")
        checks = candidate.get("checks")
        if not isinstance(checks, dict) or not checks:
            raise ValueError("Checks required")
        for check in checks.values():
            if not isinstance(check, dict) or check.get("status") not in {
                "pass",
                "fail",
                "unavailable",
            }:
                raise ValueError("Invalid check")
            if not {"observed", "required", "evidence"} <= check.keys():
                raise ValueError("Incomplete check record")
            if not isinstance(check["evidence"], list) or not check["evidence"]:
                raise ValueError("Evidence required")
            for link in check["evidence"]:
                name, separator, fragment = link.partition("#")
                path = evidence_file(name)
                if separator:
                    if path not in cache:
                        cache[path] = read(path)
                    pointer(cache[path], fragment)
                link_count += 1
        if not isinstance(candidate.get("artifacts"), list) or not candidate["artifacts"]:
            raise ValueError("Artifacts required")
        for name in candidate["artifacts"]:
            evidence_file(name)
    return {
        "receipt_checks": "pass",
        "candidates": len(candidates),
        "input_digests": len(hashes),
        "evidence_links": link_count,
        "scope": (
            "Shape, local links and recorded input digests; "
            "policy semantics and authenticity unchecked"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument(
        "--allowed-root",
        type=Path,
        required=True,
        help="Reviewed common ancestor of task inputs and result files",
    )
    args = parser.parse_args()
    try:
        result = validate(
            args.receipt.resolve(), args.task_dir.resolve(), args.allowed_root.resolve()
        )
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as error:
        print(json.dumps({"receipt_checks": "fail", "reason": str(error)}))
        return 3
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
