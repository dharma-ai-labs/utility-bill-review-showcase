# Utility Bill Review: Deterministic Checks

This small Python example illustrates what ordinary code can verify after a bill has been extracted into structured fields. It uses only the standard library. It does **not** read a PDF, run OCR, verify that a quoted line appears on a source page, classify an accounting code, or automatically approve/post a bill.

The intended comparison is not "Python versus AI" as a winner-take-all claim. A production workflow may use deterministic parsing for stable formats, a bounded model for ambiguous pages, and independent validation plus human holds before export. The three approaches require a frozen, representative test set before accuracy, cost, or time savings can be claimed.

## Run

```bash
python3 utility_bill_checks.py example.json
python3 -m unittest -v
```

`example.json` is synthetic. The script returns `review_required` even when arithmetic passes. A source reference's presence is checked, but its text and page must be compared to the actual PDF by an independent reviewer or verified extraction process.

## Checks

- Monetary values have at most two fractional digits and reconcile exactly in cents.
- Account, service period, and source-reference placeholders are present.
- Prior balances, additional charges, negative current charges, missing values, and mismatches generate explicit holds.
- No private bills, full account numbers, addresses, credentials, or model outputs are included.

This is an educational reference, not a utility-vendor parser, AppFolio integration, or a Dharma production release. Do not use it to authorize payments or accounting postings.

## Compare three workflows fairly

`experiment_score.py` is an offline scoring tool. It does not extract PDFs, call a model, confirm a source quote, or certify accuracy. Keep the answer key and run outputs private when using customer bills.

1. Freeze the expected bill inventory and have a person independently review each source PDF. Record the nine scored fields, the exact page and quote for four source references, and whether export is allowed or the bill must be held. Do not derive this key from any experiment arm.
2. Run a **complete** fixed Python extraction/parser and these checks on every bill. An extraction failure stays in the denominator. This repository only publishes the checks; it does not supply that parser or OCR.
3. Run the standalone model on the same bills with a frozen model, prompt, schema, timeout, and retry policy. Do not run the Python checks inside this arm.
4. Run the Dharma path on those same bills with a frozen workflow. Record every provider request and human review, including holds, timeouts, and reconciliation. Today's hosted path is model-first; script-first routing and automatic learning are not demonstrated by this repository.
5. Put each arm's candidate fields and disposition (`exported`, `held`, or `failed`) in one local `runs.json`. Score all arms with `python3 experiment_score.py oracle.json runs.json`. The JSON output reports missing bills, field and source-reference errors, safe and unsafe exports, duplicates, and holds. It labels cost/time inputs as **reported metrics**, not independently verified charges.

`oracle.json` has `bills`: each object needs a unique `bill_id`, `allowed_disposition` (`exported` or `held`), `fields` containing `vendor`, `account_suffix`, `service_period_start`, `service_period_end`, `current_charges`, `prior_balance`, `other_charges`, `total_due`, and `accounting_code`, plus `source_references` for `account_suffix`, `service_period_start`, `current_charges`, and `total_due`. Each reference should contain the independently reviewed `page` and `quote`. `runs.json` has `runs`: each object needs one unique `arm` (`python_only`, `llm_only`, or `dharma_hybrid`) and `bills` with `bill_id`, `disposition`, candidate `fields`, and candidate `source_references`. Optional `metrics` can carry actual cost, elapsed time, provider calls, and reviewer minutes, with their measurement source recorded separately.

A correct held bill is **not** a safe export. An unexpected or duplicate export is unsafe. A candidate quote that differs from the independent answer key makes an export unsafe even if all amounts match. For private evaluations, hash the frozen oracle, inputs, parser/model/workflow versions, and scored outputs; keep those receipts outside this public repository. The 98–99% aspiration is not an observed result from the small curated sample.
