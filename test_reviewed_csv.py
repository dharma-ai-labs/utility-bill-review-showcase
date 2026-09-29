import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reviewed_csv import _private_path, build_reviewed_rows


HASH = "a" * 64


def fixture():
    manifest = {
        "bills": [{"bill_id": "synthetic_1", "pdf": "bill.pdf"}],
        "allowed_accounting_codes": ["UTILITIES", "WATER_01"],
    }
    row = {
        "bill_id": "synthetic_1",
        "disposition": "exported",
        "fields": {
            "vendor": "PPL", "accounting_code": "UTILITIES", "account_suffix": "5678",
            "service_period_start": "2026-09-01", "service_period_end": "2026-09-20",
            "current_charges": "42.50", "prior_balance": "0.00",
            "other_charges": "0.00", "total_due": "42.50",
        },
        "source_references": {
            field: {"page": 1, "quote": f"source {field}"}
            for field in ("account_suffix", "service_period_start", "current_charges", "total_due")
        },
        "diagnostics": {"input_sha256": HASH, "holds": []},
    }
    runs = {"runs": [{"arm": "python_only", "bills": [row]}]}
    approvals = {"decisions": [{
        "bill_id": "synthetic_1", "input_sha256": HASH, "approved": True,
        "source_checked_against_original": True, "property_code": "P001",
        "accounting_code": "UTILITIES", "reviewer": "fixture_reviewer",
        "reviewed_at": "2026-09-29T19:00:00Z",
    }]}
    return manifest, runs, approvals


class ReviewedCsvTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / "bill.pdf").write_bytes(b"synthetic")
        self.inputs = fixture()

    def review(self):
        with patch("reviewed_csv.hashlib.sha256") as digest, patch(
                "reviewed_csv._source_matches", return_value=True):
            digest.return_value.hexdigest.return_value = HASH
            return build_reviewed_rows(*self.inputs, self.base)

    def test_confirmed_clean_candidate_creates_one_row(self):
        rows, held = self.review()
        self.assertEqual(len(rows), 1)
        self.assertEqual(held, [])
        self.assertEqual(rows[0]["accounting_code"], "UTILITIES")

    def test_prior_balance_stays_held_even_with_approval(self):
        self.inputs[1]["runs"][0]["bills"][0]["fields"]["prior_balance"] = "10.00"
        self.inputs[1]["runs"][0]["bills"][0]["fields"]["total_due"] = "52.50"
        rows, held = self.review()
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "deterministic_hold")

    def test_mapping_adjustment_requires_reason(self):
        decision = self.inputs[2]["decisions"][0]
        decision["accounting_code"] = "WATER_01"
        rows, held = self.review()
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "mapping_change_unexplained")
        decision["mapping_change_reason"] = "Reviewed property code mapping"
        rows, held = self.review()
        self.assertEqual(held, [])
        self.assertEqual(rows[0]["accounting_code"], "WATER_01")
        decision["mapping_change_reason"] = "=HYPERLINK(1)"
        rows, held = self.review()
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "mapping_change_unexplained")

    def test_formula_and_changed_source_are_held(self):
        self.inputs[2]["decisions"][0]["property_code"] = "=HYPERLINK(1)"
        rows, held = self.review()
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "review_incomplete")
        self.inputs[2]["decisions"][0]["property_code"] = "P001"
        self.inputs[2]["decisions"][0]["input_sha256"] = "b" * 64
        rows, held = self.review()
        self.assertEqual(held[0]["reason"], "source_changed")

    def test_unknown_duplicate_and_unreviewed_rejected(self):
        self.inputs[1]["runs"][0]["bills"].append(self.inputs[1]["runs"][0]["bills"][0])
        with self.assertRaisesRegex(ValueError, "duplicate_candidate"):
            self.review()
        self.inputs[1]["runs"][0]["bills"].pop()
        self.inputs[2]["decisions"].clear()
        with self.assertRaisesRegex(ValueError, "missing_review"):
            self.review()

    def test_quote_mismatch_and_duplicate_document_are_held(self):
        with patch("reviewed_csv.hashlib.sha256") as digest, patch(
                "reviewed_csv._source_matches", return_value=False):
            digest.return_value.hexdigest.return_value = HASH
            rows, held = build_reviewed_rows(*self.inputs, self.base)
        self.assertEqual(rows, [])
        self.assertEqual(held[0]["reason"], "source_quote_mismatch")

        manifest, runs, approvals = self.inputs
        manifest["bills"].append({"bill_id": "synthetic_2", "pdf": "bill.pdf"})
        second = {**runs["runs"][0]["bills"][0], "bill_id": "synthetic_2"}
        runs["runs"][0]["bills"].append(second)
        approvals["decisions"].append({**approvals["decisions"][0], "bill_id": "synthetic_2"})
        rows, held = self.review()
        self.assertEqual(len(rows), 1)
        self.assertEqual(held[0]["reason"], "duplicate_document")

    def test_private_path_rejects_repository_output(self):
        with self.assertRaisesRegex(ValueError, "private_input_or_output"):
            _private_path(Path(__file__).resolve().parent / "reviewed.csv")


if __name__ == "__main__":
    unittest.main()
