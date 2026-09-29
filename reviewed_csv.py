"""Create local CSV rows only from source-confirmed, hold-free PDF candidates.

This is a reviewed CSV for a demo, not an accounting-system import or payment.
The reviewer must inspect the original PDF; machine quote matching cannot
prove that embedded text or OCR represents the visible page correctly.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pdf_python_baseline import MAX_PDF_BYTES, VENDORS, extract_pages
from utility_bill_checks import check_bill


SOURCE_FIELDS = ("account_suffix", "service_period_start", "current_charges", "total_due")
CSV_FIELDS = (
    "bill_id", "vendor", "account_suffix", "property_code", "service_period_start",
    "service_period_end", "current_charges", "prior_balance", "other_charges",
    "total_due", "accounting_code", "mapping_change_reason", "source_pdf_sha256",
    "reviewer", "reviewed_at",
)
SAFE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MONEY = re.compile(r"^-?\d{1,12}\.\d{2}$")


def _private_path(path: Path) -> None:
    repository = Path(__file__).resolve().parent
    if path.resolve().is_relative_to(repository):
        raise ValueError("private_input_or_output_required_outside_public_repository")


def _safe_code(value: Any) -> bool:
    return isinstance(value, str) and SAFE_CODE.fullmatch(value) is not None


def _review_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _safe_note(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value.strip()) <= 500 \
        and value.lstrip()[0] not in "=+-@" \
        and not any(ord(char) < 32 for char in value)


def _source_matches(path: Path, refs: dict[str, Any]) -> bool:
    pages, _ = extract_pages(path)
    for field in SOURCE_FIELDS:
        ref = refs.get(field)
        if not isinstance(ref, dict) or type(ref.get("page")) is not int \
                or not isinstance(ref.get("quote"), str) or not ref["quote"].strip():
            return False
        page = ref["page"]
        if page < 1 or page > len(pages) or ref["quote"] not in {
                line.strip() for line in pages[page - 1].splitlines()}:
            return False
    return True


def build_reviewed_rows(manifest: dict[str, Any], runs: dict[str, Any],
                        approvals: dict[str, Any], base_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    bills = manifest.get("bills")
    arms = runs.get("runs")
    decisions = approvals.get("decisions")
    allowed_codes = manifest.get("allowed_accounting_codes")
    if not isinstance(bills, list) or not bills or not isinstance(arms, list) or len(arms) != 1 \
            or not isinstance(arms[0], dict) or arms[0].get("arm") != "python_only" \
            or not isinstance(decisions, list) \
            or not isinstance(allowed_codes, list) or not allowed_codes \
            or not all(_safe_code(code) for code in allowed_codes):
        raise ValueError("invalid_review_inputs")

    inventory = {}
    for bill in bills:
        if not isinstance(bill, dict) or not _safe_code(bill.get("bill_id")) \
                or not isinstance(bill.get("pdf"), str) or bill["bill_id"] in inventory:
            raise ValueError("invalid_or_duplicate_inventory")
        inventory[bill["bill_id"]] = (base_dir / bill["pdf"]).resolve()

    candidates = {}
    if not isinstance(arms[0].get("bills"), list):
        raise ValueError("invalid_candidate_list")
    for row in arms[0]["bills"]:
        if not isinstance(row, dict) or row.get("bill_id") not in inventory \
                or row["bill_id"] in candidates:
            raise ValueError("unknown_or_duplicate_candidate")
        candidates[row["bill_id"]] = row
    if set(candidates) != set(inventory):
        raise ValueError("missing_candidate")

    by_id = {}
    for decision in decisions:
        if not isinstance(decision, dict) or decision.get("bill_id") not in inventory \
                or decision["bill_id"] in by_id:
            raise ValueError("unknown_or_duplicate_review")
        by_id[decision["bill_id"]] = decision
    if set(by_id) != set(inventory):
        raise ValueError("missing_review")

    rows: list[dict[str, str]] = []
    held: list[dict[str, str]] = []
    seen_hashes: set[str] = set()
    for bill_id, path in inventory.items():
        candidate = candidates[bill_id]
        decision = by_id[bill_id]
        diagnostics = candidate.get("diagnostics")
        fields = candidate.get("fields")
        refs = candidate.get("source_references")
        if not isinstance(diagnostics, dict) or not isinstance(fields, dict) \
                or not isinstance(refs, dict):
            held.append({"bill_id": bill_id, "reason": "invalid_candidate"})
            continue
        if not path.is_file() or path.suffix.lower() != ".pdf" \
                or path.stat().st_size > MAX_PDF_BYTES:
            held.append({"bill_id": bill_id, "reason": "source_missing"})
            continue
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if source_hash in seen_hashes:
            held.append({"bill_id": bill_id, "reason": "duplicate_document"})
            continue
        seen_hashes.add(source_hash)
        if source_hash != diagnostics.get("input_sha256") \
                or source_hash != decision.get("input_sha256"):
            held.append({"bill_id": bill_id, "reason": "source_changed"})
            continue
        if candidate.get("disposition") != "exported" or diagnostics.get("holds") \
                or diagnostics.get("failure"):
            held.append({"bill_id": bill_id, "reason": "candidate_held_or_failed"})
            continue
        if decision.get("approved") is not True:
            held.append({"bill_id": bill_id, "reason": "review_not_approved"})
            continue
        code = decision.get("accounting_code")
        if fields.get("vendor") not in VENDORS \
                or not isinstance(fields.get("account_suffix"), str) \
                or not re.fullmatch(r"\d{4}", fields["account_suffix"]) \
                or not _iso_date(fields.get("service_period_start")) \
                or not _iso_date(fields.get("service_period_end")) \
                or fields["service_period_start"] > fields["service_period_end"] \
                or not all(isinstance(fields.get(key), str) and MONEY.fullmatch(fields[key])
                           for key in ("current_charges", "prior_balance", "other_charges", "total_due")):
            held.append({"bill_id": bill_id, "reason": "invalid_candidate_fields"})
            continue
        if not _safe_code(decision.get("property_code")) or code not in allowed_codes \
                or not _safe_code(decision.get("reviewer")) \
                or not _review_time(decision.get("reviewed_at")) \
                or decision.get("source_checked_against_original") is not True:
            held.append({"bill_id": bill_id, "reason": "review_incomplete"})
            continue
        if code != fields.get("accounting_code") and not _safe_note(decision.get("mapping_change_reason")):
            held.append({"bill_id": bill_id, "reason": "mapping_change_unexplained"})
            continue
        checked = check_bill({
            "account": fields.get("account_suffix"),
            "service_period_start": fields.get("service_period_start"),
            "service_period_end": fields.get("service_period_end"),
            "current_charges": fields.get("current_charges"),
            "prior_balance": fields.get("prior_balance"),
            "other_charges": fields.get("other_charges"),
            "total_due": fields.get("total_due"),
            "source_references": {
                "account": refs.get("account_suffix"),
                "service_period": refs.get("service_period_start"),
                "current_charges": refs.get("current_charges"),
                "total_due": refs.get("total_due"),
            },
        })
        if checked["holds"]:
            held.append({"bill_id": bill_id, "reason": "deterministic_hold"})
            continue
        try:
            matches = _source_matches(path, refs)
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            matches = False
        if not matches or hashlib.sha256(path.read_bytes()).hexdigest() != source_hash:
            held.append({"bill_id": bill_id, "reason": "source_quote_mismatch"})
            continue
        rows.append({
            "bill_id": bill_id,
            "vendor": str(fields["vendor"]),
            "account_suffix": str(fields["account_suffix"]),
            "property_code": decision["property_code"],
            "service_period_start": str(fields["service_period_start"]),
            "service_period_end": str(fields["service_period_end"]),
            "current_charges": str(fields["current_charges"]),
            "prior_balance": str(fields["prior_balance"]),
            "other_charges": str(fields["other_charges"]),
            "total_due": str(fields["total_due"]),
            "accounting_code": code,
            "mapping_change_reason": decision.get("mapping_change_reason", "") if code != fields.get("accounting_code") else "",
            "source_pdf_sha256": source_hash,
            "reviewer": decision["reviewer"],
            "reviewed_at": decision["reviewed_at"],
        })
    return rows, held


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("runs", type=Path)
    parser.add_argument("approvals", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.manifest, args.runs, args.approvals, args.output):
        _private_path(path)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    approvals = json.loads(args.approvals.read_text(encoding="utf-8"))
    rows, held = build_reviewed_rows(manifest, runs, approvals, args.manifest.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"reviewed_rows": len(rows), "held": held, "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
