"""Capture actual subprocess results without parsing terminal tables."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent

def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    entry = {"argv": argv, "cwd": str(cwd), "started_at": started,
             "finished_at": datetime.now(timezone.utc).isoformat(),
             "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    path = ROOT / "commands.json"
    entries = json.loads(path.read_text()) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries, indent=2) + "\n")
    return result

if __name__ == "__main__":
    completed = run(sys.argv[1:], ROOT)
    print(completed.stdout, end="")
    print(completed.stderr, end="", file=sys.stderr)
    raise SystemExit(completed.returncode)
