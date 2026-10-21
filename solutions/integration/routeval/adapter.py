"""Map the recorded support app into Routeval's public Decision interface."""
from __future__ import annotations

import importlib.util
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

from routeval import Decision


def bill(entries: list[dict[str, Any]]) -> tuple[float | None, float, int]:
    """Return whole bill only if complete, known subtotal, and missing count."""
    known = Decimal(0)
    unknown = 0
    for entry in entries:
        value = entry.get("usd")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            unknown += 1
        elif not math.isfinite(value) or value < 0:
            unknown += 1
        else:
            known += Decimal(str(value))
    if not entries:
        unknown += 1
    return (None if unknown else float(known), float(known), unknown)


class SupportAdapter:
    """Preserve original outputs and every original charge, including failures."""

    def __init__(self, task_dir: Path, policy: str) -> None:
        spec = importlib.util.spec_from_file_location(
            "assigned_support_app", task_dir / "support_app.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load assigned app")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.process = module.process
        self.policy = policy
        self.attempts: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> Decision:
        attempt: dict[str, Any] = {
            "attempt_id": f"{self.policy}:{request['ticket_id']}",
            "golden_id": request["ticket_id"],
            "request": request,
        }
        self.attempts.append(attempt)
        try:
            original = self.process(request, self.policy)
            entries = original["billing"]["entries"]
            whole, known, unknown = bill(entries)
            attempt.update(original=original, whole_cost_usd=whole,
                           known_partial_charges_usd=known,
                           unknown_billing_entries=unknown)
            return Decision(
                answer=original["payload"]["response"],
                route=original["execution"]["route"],
                error=original["execution"]["error"],
                cost_usd=whole,
                stages={"app": {"original": original},
                        "billing": {"known_subtotal_usd": known,
                                    "unknown_entries": unknown}},
            )
        except Exception as exc:
            attempt.update(adapter_error=f"{type(exc).__name__}: {exc}",
                           whole_cost_usd=None, known_partial_charges_usd=0,
                           unknown_billing_entries=None)
            return Decision(answer=None, route=None, cost_usd=None,
                            error=attempt["adapter_error"])
