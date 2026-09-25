"""Fixed, local PDF/OCR arm for the offline utility-bill experiment.

This produces candidate rows, not accounting instructions. OCR text and source
quotes may be wrong; the independent experiment oracle decides correctness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from utility_bill_checks import check_bill


MAX_PDF_BYTES = 25_000_000
MAX_PAGES = 20
MIN_TEXT_CHARS = 80
VENDORS = {
    "PPL": re.compile(r"\bPPL(?:\s+Electric)?(?:\s+Utilities)?\b", re.I),
    "UGI": re.compile(r"\bUGI(?:\s+Utilities)?\b", re.I),
    "Capital Region Water": re.compile(r"\bCapital\s+Region\s+Water\b", re.I),
}
LABELS = {
    "current_charges": re.compile(
        r"^\s*(?:total\s+)?(?:current\s+charges|new\s+charges|current\s+bill)\b", re.I),
    "prior_balance": re.compile(
        r"^\s*(?:previous|prior)\s+balance\b", re.I),
    "other_charges": re.compile(
        r"^\s*(?:other\s+charges|additional\s+charges|late\s+fees?)\b", re.I),
    "total_due": re.compile(
        r"^\s*(?:total\s+(?:amount\s+)?due|amount\s+due|total\s+due\s+now)\b", re.I),
}
ACCOUNT_LABEL = re.compile(r"^\s*(?:account(?:\s+(?:number|no\.?|#))?|acct(?:\s+#)?)\s*[:#-]?\s*", re.I)
PERIOD_LABEL = re.compile(r"^\s*(?:service|billing)\s+period\b", re.I)
MONEY = re.compile(r"(?<![\d.])-?\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)")
DATE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b")


def _run(args: list[str], *, timeout: int = 30) -> str:
    result = subprocess.run(args, check=True, capture_output=True, timeout=timeout)
    return result.stdout.decode("utf-8", errors="replace")


def extract_pages(path: Path) -> tuple[list[str], list[str]]:
    if path.suffix.lower() != ".pdf" or not path.is_file() or path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("invalid_or_oversize_pdf")
    info = _run(["pdfinfo", str(path)])
    match = re.search(r"^Pages:\s*(\d+)\s*$", info, re.M)
    if not match or not 1 <= int(match.group(1)) <= MAX_PAGES:
        raise ValueError("unsupported_page_count")
    pages: list[str] = []
    methods: list[str] = []
    with tempfile.TemporaryDirectory(prefix="utility-ocr-") as temp:
        for page in range(1, int(match.group(1)) + 1):
            text = _run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"])
            method = "embedded_text"
            if len(text.strip()) < MIN_TEXT_CHARS:
                prefix = Path(temp) / f"page-{page}"
                _run(["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile",
                      "-scale-to", "2000", "-png", str(path), str(prefix)], timeout=60)
                text = _run(["tesseract", str(prefix) + ".png", "stdout", "--psm", "6"], timeout=60)
                method = "tesseract_psm6"
                if len(text.strip()) < MIN_TEXT_CHARS:
                    alternate = _run(["tesseract", str(prefix) + ".png", "stdout", "--psm", "11"], timeout=60)
                    if len(alternate.strip()) > len(text.strip()):
                        text, method = alternate, "tesseract_psm11"
            pages.append(text[:200_000])
            methods.append(method)
    return pages, methods


def _date(value: str) -> str | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
                "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _unique_match(lines: list[tuple[int, str]], pattern: re.Pattern[str],
                  extractor: Any) -> tuple[Any, dict[str, Any] | None]:
    matches = []
    for page, line in lines:
        matched = pattern.match(line)
        if matched:
            value = extractor(line[matched.end():])
            if value is not None:
                matches.append((value, {"page": page, "quote": line.strip()}))
    return matches[0] if len(matches) == 1 else (None, None)


def _money(tail: str) -> str | None:
    amounts = MONEY.findall(tail)
    return amounts[0].replace("$", "").replace(",", "").replace(" ", "") if len(amounts) == 1 else None


def _account(tail: str) -> str | None:
    if not re.fullmatch(r"\s*[*Xx#\d-]{4,32}\s*", tail):
        return None
    digits = re.sub(r"\D", "", tail)
    return digits[-4:] if 4 <= len(digits) <= 24 else None


def _period(tail: str) -> tuple[str, str] | None:
    dates = [_date(value) for value in DATE.findall(tail)]
    return (dates[0], dates[1]) if len(dates) == 2 and all(dates) and dates[0] <= dates[1] else None


def parse_pages(pages: list[str], vendor_codes: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    lines = [(page, line.strip()) for page, text in enumerate(pages, start=1)
             for line in text.splitlines() if line.strip()]
    all_text = "\n".join(pages)
    detected = [vendor for vendor, pattern in VENDORS.items() if pattern.search(all_text)]
    vendor = detected[0] if len(detected) == 1 else None
    fields: dict[str, Any] = {"vendor": vendor, "accounting_code": vendor_codes.get(vendor) if vendor else None}
    refs: dict[str, Any] = {}
    holds = []
    if len(detected) != 1:
        holds.append("vendor_missing_or_ambiguous")
    account, ref = _unique_match(lines, ACCOUNT_LABEL, _account)
    fields["account_suffix"] = account
    if ref:
        refs["account_suffix"] = ref
    period, ref = _unique_match(lines, PERIOD_LABEL, _period)
    fields["service_period_start"] = period[0] if period else None
    fields["service_period_end"] = period[1] if period else None
    if ref:
        refs["service_period_start"] = ref
    for field, pattern in LABELS.items():
        fields[field], ref = _unique_match(lines, pattern, _money)
        if ref:
            refs[field] = ref
    if not fields["accounting_code"]:
        holds.append("accounting_code_unmapped")
    required_refs = ("account_suffix", "service_period_start", "current_charges", "total_due")
    if any(value is None for value in fields.values()) or any(key not in refs for key in required_refs):
        holds.append("missing_or_ambiguous_fields")
    checked = check_bill({
        "account": account,
        "service_period_start": fields["service_period_start"],
        "service_period_end": fields["service_period_end"],
        **{key: fields[key] for key in LABELS},
        "source_references": {
            "account": refs.get("account_suffix"),
            "service_period": refs.get("service_period_start"),
            "current_charges": refs.get("current_charges"),
            "total_due": refs.get("total_due"),
        },
    })
    holds.extend(checked["holds"])
    return fields, refs, sorted(set(holds))


def run_manifest(manifest: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    bills = manifest.get("bills")
    codes = manifest.get("vendor_codes")
    if not isinstance(bills, list) or not bills or not isinstance(codes, dict) \
            or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in codes.items()):
        raise ValueError("manifest requires bills and vendor_codes")
    rows = []
    seen: set[str] = set()
    for bill in bills:
        if not isinstance(bill, dict) or not isinstance(bill.get("bill_id"), str) \
                or not bill["bill_id"] or bill["bill_id"] in seen or not isinstance(bill.get("pdf"), str):
            raise ValueError("each bill requires a unique bill_id and pdf path")
        seen.add(bill["bill_id"])
        path = (base_dir / bill["pdf"]).resolve()
        row: dict[str, Any] = {"bill_id": bill["bill_id"], "disposition": "failed",
                               "fields": {}, "source_references": {}}
        try:
            pages, methods = extract_pages(path)
            row["fields"], row["source_references"], holds = parse_pages(pages, codes)
            row["disposition"] = "held" if holds else "exported"
            row["diagnostics"] = {"holds": holds, "page_count": len(pages),
                                  "extraction_methods": methods,
                                  "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            row["diagnostics"] = {"failure": type(exc).__name__}
        rows.append(row)
    return {"runs": [{"arm": "python_only", "bills": rows}]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="private bill inventory and fixed vendor-code mapping")
    parser.add_argument("--output", type=Path, required=True, help="private scorer-compatible output")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output.write_text(json.dumps(run_manifest(manifest, args.manifest.parent), indent=2) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
