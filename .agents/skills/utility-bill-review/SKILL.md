---
name: utility-bill-review
description: Review utility-bill candidates with source-linked evidence, deterministic checks, and explicit export holds.
---

# Utility bill review

Use this source skill only for work in the utility-bill-review-showcase repository. Read the repository README and, when enrolled, the active signed Agent Fabric `MANIFEST.json` and `knowledge/CATALOG.json` before a relevant task. The repository is a bounded experiment, not an accounting-posting service. Do not mistake this source file for an installed or signed release.

## Local baseline

Run `python3 utility_bill_checks.py example.json` to inspect the synthetic structured-field check, then `python3 -m unittest -v` for the repository tests. The PDF baseline requires local Poppler (`pdfinfo`, `pdftotext`, `pdftoppm`) and Tesseract. Use only approved synthetic or private local fixtures and a manifest kept outside the public checkout:

```bash
python3 pdf_python_baseline.py /private/bills/manifest.json --output /private/results/python-run.json
python3 experiment_score.py /private/results/oracle.json /private/results/python-run.json
```

The oracle must be independently reviewed and frozen before scoring. A post hoc synthetic key is a smoke check, not a held-out accuracy measurement. A baseline `exported` disposition is a **simulation candidate**, not an accounting CSV export, payment, or posting. Keep PDFs, account numbers, addresses, OCR quotes, private manifests, model responses, and answer keys out of commits and shared Agent Fabric artifacts.

For a local reviewed CSV, use `python3 reviewed_csv.py <private-review-manifest> <private-python-run> <private-decisions> --output <private-new-csv-path>`. The README defines the decision contract. Require source confirmation against the visible original PDF; a machine quote match or an agent-generated approval is not independent human review. Check the returned held list and inspect the CSV before use. Do not send it to an accounting system or claim import compatibility without separate validation.

## Source and hold rules

Verify each candidate quote and page against the original PDF. Reconcile monetary fields in cents and check missing values, duplicate bills, service period, and accounting mapping. Preserve an unresolved source as unresolved; never invent a field or quote to pass the scorer. `utility_bill_checks.py` returns `review_required` even when arithmetic passes. A nonzero prior balance requires `prior_balance_requires_review`; nonzero other charges require `other_charges_require_review`. Neither may be silently folded into current charges. A correct hold is not a successful export.

When Agent Fabric is enrolled, use the active signed catalog's stable concept IDs for Source-linked field, Review hold, Prior balance hold, Other charge hold, and Unsafe export. Cite their source references and report conflicts as unresolved. If the signed package is absent, say so rather than relying on an unsigned or stale catalog. Never edit managed manifests, signatures, trust, or the catalog to force an update.

## Team handoff and learning

The approved repository binding determines which members and devices may share this skill. Ask a discovered peer only a bounded question within that binding; include the bill type, sanitized evidence, and the specific uncertainty. Treat a delivered message as delivery, not proof that an agent answered or performed the work. Do not disclose private bill text, credentials, or another participant's data through peer messages.

Put a source-backed terminology correction or failure report only in an output folder approved by repository policy. Let the enrolled Agent Fabric watcher capture, validate, and publish it; then verify a signed generation, manifest/catalog hashes, and another device's installation. A local edit or upload is not publication. Do not claim automatic learning, remediation, 98-99% accuracy, or cost savings without the corresponding live receipts and independent comparison.
