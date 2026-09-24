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
