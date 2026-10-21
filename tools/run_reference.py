"""Replay a preserved participant solution on fixed synthetic learning fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("track", choices=("integration", "evaluation"))
    parser.add_argument("condition", choices=("stdlib", "routeval"))
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory, never an existing result"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Output already exists; choose a new directory to preserve prior evidence")
    if args.condition == "routeval":
        import routeval

        if routeval.__version__ != "0.1.1":
            parser.error("Install routeval==0.1.1 for this recorded pilot")
    output.mkdir(parents=True)
    task = REPO / "tasks" / args.track
    source = REPO / "solutions" / args.track / args.condition
    solution = output / "implementation"
    solution.mkdir()
    for path in source.glob("*.py"):
        shutil.copyfile(path, solution / path.name)
    contract = json.loads((task / "contract.json").read_text())
    commands: list[dict[str, Any]] = []

    def command(argv: list[str]) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
        commands.append(
            {
                "argv": argv,
                "cwd": str(REPO),
                "exit": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        )
        write(output / "replay-commands.json", commands)
        if proc.returncode not in (0, 1, 3):
            raise RuntimeError(f"Command failed with exit {proc.returncode}: {proc.stderr}")
        return proc

    if args.track == "integration":
        results, reference = [], None
        policies = [contract["reference_policy"]] + [
            p for p in contract["policies"] if p != contract["reference_policy"]
        ]
        for policy in policies:
            if args.condition == "routeval":
                dest = output / policy
                argv = [
                    sys.executable,
                    str(solution / "runner.py"),
                    "--task-dir",
                    str(task),
                    "--policy",
                    policy,
                    "--output",
                    str(dest),
                ]
            else:
                argv = [
                    sys.executable,
                    str(solution / "evaluate.py"),
                    "--task-dir",
                    str(task),
                    "--policy",
                    policy,
                    "--out-dir",
                    str(output),
                ]
            if reference:
                argv += ["--reference", str(reference)]
            proc = command(argv)
            if args.condition == "routeval":
                result = json.loads((dest / "result.json").read_text())
                artifact = Path(json.loads((dest / "run-location.json").read_text())["artifact"])
                commands.append(json.loads((dest / "native-comparison-command.json").read_text()))
            else:
                value = json.loads(proc.stdout)
                result, artifact = value["candidate"], output / value["artifact"]
                # The original single-policy CLI uses basenames. Here every
                # artifact shares the receipt directory, preserving those links.
            results.append(result)
            if policy == contract["reference_policy"]:
                reference = artifact
        hashes = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(task.iterdir())
            if p.is_file()
        }
        write(
            output / "submission.json",
            {
                "record_version": "trial-decisions-1",
                "track": args.track,
                "condition": args.condition,
                "contract_sha256": hashes["contract.json"],
                "reference_id": contract["reference_policy"],
                "input_sha256": hashes,
                "release_executed": False,
                "candidates": results,
            },
        )
    else:
        flag = "--out-dir" if args.condition == "routeval" else "--output-dir"
        argv = [
            sys.executable,
            str(solution / "consumer.py"),
            "--task-dir",
            str(task),
            flag,
            str(output),
        ]
        if args.condition == "routeval":
            argv += ["--routeval", str(Path(sys.executable).with_name("routeval"))]
        command(argv)
        native_commands = solution / "commands.json"
        if native_commands.exists():
            commands.extend(json.loads(native_commands.read_text()))
    receipt = json.loads((output / "submission.json").read_text())
    write(output / "replay-commands.json", commands)
    write(
        output / "replay.json",
        {
            "kind": "chair-authored reproduction wrapper; not a fresh agent trial",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "collection_complete": True,
            "release_executed": False,
            "batch_exit_rule": "0 means result collection completed, not policy approval",
        },
    )
    for candidate in receipt["candidates"]:
        print(candidate["candidate_id"], candidate["recommendation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
