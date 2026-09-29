# Utility Bill Review: Deterministic Checks

The structured-field checker illustrates what ordinary code can verify after extraction. A separate experimental runner, `pdf_python_baseline.py`, can read PDFs with local Poppler and Tesseract tools, apply fixed label rules, and emit candidates for the offline three-arm scorer. Neither script independently verifies that OCR quotes are correct, retrieves bills from utility portals, nor approves/posts a bill.

The intended comparison is not "Python versus AI" as a winner-take-all claim. A production workflow may use deterministic parsing for stable formats, a bounded model for ambiguous pages, and independent validation plus human holds before export. The three approaches require a frozen, representative test set before accuracy, cost, or time savings can be claimed.

The repository-native [utility-bill-review skill](.agents/skills/utility-bill-review/SKILL.md) gives enrolled coding agents the source, hold, and disclosure rules. Its tracked source is not a signed Agent Fabric release; the installed managed package and knowledge catalog remain authoritative for a connected device.

## Run

```bash
python3 utility_bill_checks.py example.json
python3 -m unittest -v
```

For the **experimental Python-only arm**, install `pdfinfo`, `pdftotext`, `pdftoppm`, and `tesseract` locally, then use a private manifest outside this public checkout:

```bash
python3 pdf_python_baseline.py /private/bills/manifest.json --output /private/results/python-run.json
python3 experiment_score.py /private/results/oracle.json /private/results/python-run.json
```

The manifest has `{"bills":[{"bill_id":"synthetic-a","pdf":"bill.pdf"}],"vendor_codes":{"PPL":"ELEC","UGI":"GAS","Capital Region Water":"WATER"}}`. PDF paths resolve relative to the manifest. Vendor codes are fixed policy inputs, not answers copied from the oracle. The runner uses embedded PDF text when available; otherwise it renders each page and runs Tesseract with fixed modes. Each input produces an `exported`, `held`, or `failed` **simulation candidate**. `exported` means its fixed rules found all required fields and no hold, not that a payment or accounting export happened. Extraction failures remain in the denominator. The scorer checks those candidates against an independently reviewed answer key. Keep manifests, PDFs, OCR-derived quotes, run outputs, and the oracle private.

`example.json` is synthetic. The script returns `review_required` even when arithmetic passes. A source reference's presence is checked, but its text and page must be compared to the actual PDF by an independent reviewer or verified extraction process.

## Reviewed local CSV (experimental)

`reviewed_csv.py` turns hold-free PDF candidates into private CSV rows only after a separate source-confirmation decision. It does not send data to Dharma, AppFolio, or a payment system. Keep the manifest, candidate output, review decisions, and CSV **outside this public checkout**. The review manifest uses the same `bills` and `vendor_codes` as the PDF baseline plus an `allowed_accounting_codes` list. Give every bill one decision with its `bill_id`, matching `input_sha256`, `approved` boolean, `source_checked_against_original` boolean, safe `property_code`, allowed `accounting_code`, reviewer identifier, and timezone-qualified `reviewed_at`. If the selected code differs from the candidate's mapping, supply a nonempty `mapping_change_reason`. Use a distinct output path for each adjustment; existing CSV files are not overwritten.

```bash
python3 reviewed_csv.py /private/bills/review-manifest.json /private/results/python-run.json /private/reviews/decisions.json --output /private/results/reviewed-rows.csv
```

The command rechecks the PDF hash, required quotes against extracted page text, field arithmetic, prior/other-charge holds, duplicate documents, and spreadsheet-safe identifiers. A held bill never enters the CSV, even if a review decision says `approved`. Its JSON receipt reports held IDs and reasons without bill contents. The review decision is an attestation, not proof that a person actually inspected the page; an independent human review remains required for customer accounting use. OCR can disagree with the visible PDF even when machine quote matching passes. This CSV is not a certified AppFolio import template.

## Checks

- Monetary values have at most two fractional digits and reconcile exactly in cents.
- Account, service period, and source-reference placeholders are present.
- Prior balances, additional charges, negative current charges, missing values, and mismatches generate explicit holds.
- No private bills, full account numbers, addresses, credentials, or model outputs are included.

This is an educational reference, not a utility-vendor parser, AppFolio integration, or a Dharma production release. Do not use it to authorize payments or accounting postings.

## Compare three workflows fairly

`experiment_score.py` is an offline scoring tool. It does not extract PDFs, call a model, confirm a source quote, or certify accuracy. Keep the answer key and run outputs private when using customer bills.

1. Freeze the expected bill inventory and have a person independently review each source PDF. Record the nine scored fields, the exact page and quote for four source references, and whether export is allowed or the bill must be held. Do not derive this key from any experiment arm.
2. Freeze the Python baseline version and fixed vendor-code mapping before the scored run. Run `pdf_python_baseline.py` on every bill. An extraction failure stays in the denominator. Its intentionally narrow label parser is a real but limited baseline, not a vendor-certified parser; tune it only on a separate development set.
3. Run the standalone model on the same bills with a frozen model, prompt, schema, timeout, and retry policy. Do not run the Python checks inside this arm.
4. Run the Dharma path on those same bills with a frozen workflow. Record every provider request and human review, including holds, timeouts, and reconciliation. The isolated staging worker has shown one Python-first unresolved-bill hold before model dispatch; a complete script-to-model-to-human export and automatic learning are not demonstrated by this repository.
5. Put each arm's candidate fields and disposition (`exported`, `held`, or `failed`) in one local `runs.json`. Score all arms with `python3 experiment_score.py oracle.json runs.json`. The JSON output reports missing bills, field and source-reference errors, safe and unsafe exports, duplicates, and holds. It labels cost/time inputs as **reported metrics**, not independently verified charges.

`oracle.json` has `bills`: each object needs a unique `bill_id`, `allowed_disposition` (`exported` or `held`), `fields` containing `vendor`, `account_suffix`, `service_period_start`, `service_period_end`, `current_charges`, `prior_balance`, `other_charges`, `total_due`, and `accounting_code`, plus `source_references` for `account_suffix`, `service_period_start`, `current_charges`, and `total_due`. Each reference should contain the independently reviewed `page` and `quote`. `runs.json` has `runs`: each object needs one unique `arm` (`python_only`, `llm_only`, or `dharma_hybrid`) and `bills` with `bill_id`, `disposition`, candidate `fields`, and candidate `source_references`. Optional `metrics` can carry actual cost, elapsed time, provider calls, and reviewer minutes, with their measurement source recorded separately.

A correct held bill is **not** a safe export. An unexpected or duplicate export is unsafe. A candidate quote that differs from the independent answer key makes an export unsafe even if all amounts match. For private evaluations, hash the frozen oracle, inputs, parser/model/workflow versions, and scored outputs; keep those receipts outside this public repository. The 98–99% aspiration is not an observed result from the small curated sample.

Scorer version 2 distinguishes an omitted field from an explicitly absent value: JSON `null` matches an oracle `null` (for example, no separately printed other charge), while `null` against a known amount is missing. Record the exact scorer version with every result; version 1 incorrectly marked matching `null` fields as missing.

## Unresolved Oracle Evidence

Do not use `null` to mean "not reviewed", infer a printed year, or invent a source quote to satisfy the scorer. Schema-less oracle inputs retain version 2 behavior and output. An oracle that explicitly declares `"schema": "dharma.utility-oracle/v3"` may record unresolved evidence in each bill as reason maps:

```json
{
  "unresolved_fields": {
    "service_period_start": "The year is not independently printed.",
    "service_period_end": "The year is not independently printed."
  },
  "unresolved_source_references": {
    "service_period_start": "The page does not verify the complete ISO date."
  }
}
```

This is a bill-level fragment, not a complete oracle. Omit these unresolved keys from that bill's `fields` and `source_references`; keep all other required verified values and references. Reasons must be nonempty strings of at most 500 characters using recognized field names. A key cannot assert verified truth and unresolved status simultaneously. `null` still means independently verified absence, not uncertainty.

Version 3 excludes explicitly unresolved truth from the scored-field/reference denominator and reports `unresolved_oracle_fields` and `unresolved_oracle_source_references` separately. Always publish these coverage counts with any accuracy result. An export with otherwise correct known evidence but unresolved truth is `unverifiable_exports`, never a `safe_exports` pass. A known field/reference error or an oracle-required hold remains an unsafe export. Missing bills remain in the bill denominator. Even an all-unresolved oracle cannot certify an export. Preserve the frozen oracle and its reasons before comparison; do not reclassify difficult fields after seeing one arm's output.
