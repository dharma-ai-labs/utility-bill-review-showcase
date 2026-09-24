"""Deterministic, dependency-free checks for extracted utility-bill fields.

This intentionally does not claim to read scanned PDFs. A caller supplies
candidate fields and source references; missing evidence is held for review.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


MONEY_FIELDS = ("current_charges", "prior_balance", "other_charges", "total_due")
SOURCE_FIELDS = ("account", "service_period", "current_charges", "total_due")


def cents(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount.as_tuple().exponent < -2:
        return None
    return int(amount * 100)


def check_bill(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return auditable holds; never infer absent amounts or approve a bill."""
    holds: list[str] = []
    values = {field: cents(candidate.get(field)) for field in MONEY_FIELDS}
    for field in MONEY_FIELDS:
        if values[field] is None:
            holds.append(f"missing_or_invalid_{field}")
    references = candidate.get("source_references")
    if not isinstance(references, dict):
        references = {}
    for field in SOURCE_FIELDS:
        ref = references.get(field)
        if not isinstance(ref, dict) or not isinstance(ref.get("page"), int) or ref["page"] < 1 \
                or not isinstance(ref.get("quote"), str) or not ref["quote"].strip():
            holds.append(f"source_unverified_{field}")
    if not candidate.get("account"):
        holds.append("missing_account")
    if not candidate.get("service_period_start") or not candidate.get("service_period_end"):
        holds.append("missing_service_period")
    if all(value is not None for value in values.values()):
        if values["current_charges"] + values["prior_balance"] \
                + values["other_charges"] != values["total_due"]:
            holds.append("amounts_do_not_reconcile")
        if values["prior_balance"] != 0:
            holds.append("prior_balance_requires_review")
        if values["other_charges"] != 0:
            holds.append("other_charges_require_review")
        if values["current_charges"] < 0:
            holds.append("negative_current_charges_require_review")
    return {"status": "review_required", "holds": holds, "arithmetic_pass": "amounts_do_not_reconcile" not in holds
            and all(value is not None for value in values.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="JSON candidate; no raw PDF is uploaded")
    args = parser.parse_args()
    value = json.loads(args.candidate.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        parser.error("candidate must be a JSON object")
    print(json.dumps(check_bill(value), sort_keys=True))


if __name__ == "__main__":
    main()
