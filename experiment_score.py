"""Score three utility-bill workflows against one independently reviewed answer key.

This offline scorer never reads PDFs or calls a model. The answer key and run
files may contain private bill data: keep them out of this public repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FIELDS = (
    "vendor", "account_suffix", "service_period_start", "service_period_end",
    "current_charges", "prior_balance", "other_charges", "total_due",
    "accounting_code",
)
SOURCE_FIELDS = ("account_suffix", "service_period_start", "current_charges", "total_due")
ARMS = ("python_only", "llm_only", "dharma_hybrid")
DISPOSITIONS = ("exported", "held", "failed")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _rows(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be an array of objects")
    return value


def score(oracle: dict[str, Any], runs: dict[str, Any]) -> dict[str, Any]:
    expected = _rows(oracle.get("bills"), "oracle.bills")
    expected_by_id: dict[str, dict[str, Any]] = {}
    for row in expected:
        bill_id = row.get("bill_id")
        if not isinstance(bill_id, str) or not bill_id or bill_id in expected_by_id:
            raise ValueError("oracle bill_id must be a unique nonempty string")
        if row.get("allowed_disposition") not in ("exported", "held"):
            raise ValueError(f"{bill_id}: allowed_disposition must be exported or held")
        fields = _mapping(row.get("fields"), f"{bill_id}.fields")
        refs = _mapping(row.get("source_references"), f"{bill_id}.source_references")
        if any(field not in fields for field in FIELDS):
            raise ValueError(f"{bill_id}: oracle is missing a scored field")
        if any(field not in refs for field in SOURCE_FIELDS):
            raise ValueError(f"{bill_id}: oracle is missing a source reference")
        expected_by_id[bill_id] = row

    results: dict[str, Any] = {}
    seen_arms: set[str] = set()
    for run in _rows(runs.get("runs"), "runs.runs"):
        arm = run.get("arm")
        if arm not in ARMS or arm in seen_arms:
            raise ValueError("each run must have a unique recognized arm")
        seen_arms.add(arm)
        candidates = _rows(run.get("bills"), f"{arm}.bills")
        by_id: dict[str, dict[str, Any]] = {}
        duplicate_rows = 0
        unexpected_rows = 0
        unsafe_exports = 0
        for candidate in candidates:
            bill_id = candidate.get("bill_id")
            if not isinstance(bill_id, str) or not bill_id:
                raise ValueError(f"{arm}: bill_id must be a nonempty string")
            if candidate.get("disposition") not in DISPOSITIONS:
                raise ValueError(f"{arm}/{bill_id}: invalid disposition")
            if bill_id in by_id:
                duplicate_rows += 1
                if candidate["disposition"] == "exported":
                    unsafe_exports += 1
                continue
            if bill_id not in expected_by_id:
                unexpected_rows += 1
                if candidate["disposition"] == "exported":
                    unsafe_exports += 1
                continue
            by_id[bill_id] = candidate

        counts = {
            "expected_bills": len(expected_by_id), "returned_bills": len(by_id),
            "missing_bills": len(expected_by_id) - len(by_id),
            "duplicate_rows": duplicate_rows, "unexpected_rows": unexpected_rows,
            "correct_fields": 0, "missing_fields": 0, "incorrect_fields": 0,
            "source_matches": 0, "source_missing": 0, "source_mismatches": 0,
            "safe_exports": 0, "unsafe_exports": unsafe_exports,
            "holds": 0, "failures": 0,
        }
        for bill_id, truth in expected_by_id.items():
            candidate = by_id.get(bill_id)
            if candidate is None:
                counts["missing_fields"] += len(FIELDS)
                counts["source_missing"] += len(SOURCE_FIELDS)
                continue
            disposition = candidate["disposition"]
            if disposition == "held":
                counts["holds"] += 1
            elif disposition == "failed":
                counts["failures"] += 1
            fields = _mapping(candidate.get("fields", {}), f"{arm}/{bill_id}.fields")
            refs = _mapping(candidate.get("source_references", {}),
                            f"{arm}/{bill_id}.source_references")
            bill_correct = True
            for field in FIELDS:
                if field not in fields or fields[field] is None or fields[field] == "":
                    counts["missing_fields"] += 1
                    bill_correct = False
                elif fields[field] == truth["fields"][field]:
                    counts["correct_fields"] += 1
                else:
                    counts["incorrect_fields"] += 1
                    bill_correct = False
            for field in SOURCE_FIELDS:
                if field not in refs:
                    counts["source_missing"] += 1
                    bill_correct = False
                elif refs[field] == truth["source_references"][field]:
                    counts["source_matches"] += 1
                else:
                    counts["source_mismatches"] += 1
                    bill_correct = False
            if disposition == "exported":
                if bill_correct and truth["allowed_disposition"] == "exported":
                    counts["safe_exports"] += 1
                else:
                    counts["unsafe_exports"] += 1
        metrics = _mapping(run.get("metrics", {}), f"{arm}.metrics")
        results[arm] = {**counts, "reported_metrics": metrics}
    if not seen_arms:
        raise ValueError("at least one run is required")
    return {"scoring_version": 1, "arms": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle", type=Path, help="independently reviewed private answer key")
    parser.add_argument("runs", type=Path, help="frozen outputs for one or more experiment arms")
    args = parser.parse_args()
    oracle = _mapping(json.loads(args.oracle.read_text(encoding="utf-8")), "oracle")
    runs = _mapping(json.loads(args.runs.read_text(encoding="utf-8")), "runs")
    print(json.dumps(score(oracle, runs), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
