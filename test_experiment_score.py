import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from experiment_score import score


def oracle():
    return {"bills": [{
        "bill_id": "synthetic-a", "allowed_disposition": "exported",
        "fields": {
            "vendor": "Example Utility", "account_suffix": "0001",
            "service_period_start": "2026-01-01", "service_period_end": "2026-01-31",
            "current_charges": "17.48", "prior_balance": "0.00",
            "other_charges": "0.00", "total_due": "17.48", "accounting_code": "UTIL",
        },
        "source_references": {
            key: {"page": 1, "quote": f"SYNTHETIC {key}"}
            for key in ("account_suffix", "service_period_start", "current_charges", "total_due")
        },
    }]}


def candidate(**updates):
    truth = oracle()["bills"][0]
    return {"bill_id": truth["bill_id"], "disposition": "exported",
            "fields": truth["fields"].copy(),
            "source_references": truth["source_references"].copy(), **updates}


def one_run(rows):
    return {"runs": [{"arm": "python_only", "bills": rows}]}


def unresolved_oracle():
    truth = oracle()
    truth["schema"] = "dharma.utility-oracle/v3"
    row = truth["bills"][0]
    del row["fields"]["service_period_start"]
    del row["fields"]["service_period_end"]
    del row["source_references"]["service_period_start"]
    row["unresolved_fields"] = {
        "service_period_start": "Year is not independently printed.",
        "service_period_end": "Year is not independently printed.",
    }
    row["unresolved_source_references"] = {
        "service_period_start": "The page does not verify a complete ISO date."
    }
    return truth


class ExperimentScoreTest(unittest.TestCase):
    def test_correct_export(self):
        scored = score(oracle(), one_run([candidate()]))
        self.assertEqual(scored["scoring_version"], 2)
        result = scored["arms"]["python_only"]
        self.assertNotIn("unverifiable_exports", result)
        self.assertEqual(result["safe_exports"], 1)
        self.assertEqual(result["correct_fields"], 9)
        self.assertEqual(result["expected_fields"], 9)
        self.assertEqual(result["source_matches"], 4)
        self.assertEqual(result["expected_source_references"], 4)
        self.assertEqual(result["unsafe_exports"], 0)

    def test_missing_bill_remains_in_denominator(self):
        result = score(oracle(), one_run([]))["arms"]["python_only"]
        self.assertEqual(result["missing_bills"], 1)
        self.assertEqual(result["safe_exports"], 0)
        self.assertEqual(result["missing_fields"], 9)
        self.assertEqual(result["source_missing"], 4)

    def test_explicitly_absent_optional_charge_matches_oracle(self):
        truth = oracle()
        truth["bills"][0]["fields"]["other_charges"] = None
        row = candidate()
        row["fields"]["other_charges"] = None
        result = score(truth, one_run([row]))["arms"]["python_only"]
        self.assertEqual(result["correct_fields"], 9)
        self.assertEqual(result["missing_fields"], 0)
        self.assertEqual(result["safe_exports"], 1)

    def test_null_when_oracle_has_amount_is_missing(self):
        row = candidate()
        row["fields"]["other_charges"] = None
        result = score(oracle(), one_run([row]))["arms"]["python_only"]
        self.assertEqual(result["missing_fields"], 1)
        self.assertEqual(result["safe_exports"], 0)
        self.assertEqual(result["unsafe_exports"], 1)

    def test_omitted_optional_field_is_not_explicit_absence(self):
        truth = oracle()
        truth["bills"][0]["fields"]["other_charges"] = None
        row = candidate()
        del row["fields"]["other_charges"]
        result = score(truth, one_run([row]))["arms"]["python_only"]
        self.assertEqual(result["missing_fields"], 1)
        self.assertEqual(result["safe_exports"], 0)

    def test_invented_source_or_wrong_category_is_unsafe(self):
        wrong = candidate()
        wrong["fields"]["accounting_code"] = "OTHER"
        wrong["source_references"]["total_due"] = {"page": 9, "quote": "invented"}
        result = score(oracle(), one_run([wrong]))["arms"]["python_only"]
        self.assertEqual(result["incorrect_fields"], 1)
        self.assertEqual(result["source_mismatches"], 1)
        self.assertEqual(result["unsafe_exports"], 1)

    def test_hold_is_safe_disposition_but_not_correct_export(self):
        result = score(oracle(), one_run([candidate(disposition="held")]))["arms"]["python_only"]
        self.assertEqual(result["holds"], 1)
        self.assertEqual(result["safe_exports"], 0)

    def test_oracle_hold_cannot_be_exported_and_duplicate_is_counted(self):
        truth = oracle()
        truth["bills"][0]["allowed_disposition"] = "held"
        result = score(truth, one_run([candidate(), candidate()]))["arms"]["python_only"]
        self.assertEqual(result["unsafe_exports"], 2)
        self.assertEqual(result["duplicate_rows"], 1)

    def test_rejects_duplicate_oracle_and_arm(self):
        truth = oracle()
        truth["bills"].append(truth["bills"][0])
        with self.assertRaises(ValueError):
            score(truth, one_run([]))
        with self.assertRaises(ValueError):
            score(oracle(), {"runs": [one_run([])["runs"][0]] * 2})

    def test_rejects_empty_oracle_and_invalid_source_key(self):
        with self.assertRaises(ValueError):
            score({"bills": []}, one_run([]))
        truth = oracle()
        truth["bills"][0]["source_references"]["total_due"] = {"page": 0, "quote": ""}
        with self.assertRaises(ValueError):
            score(truth, one_run([]))

    def test_unresolved_oracle_is_excluded_from_accuracy_not_fabricated(self):
        row = candidate(disposition="held")
        row["fields"]["service_period_start"] = None
        row["fields"]["service_period_end"] = None
        del row["source_references"]["service_period_start"]
        scored = score(unresolved_oracle(), one_run([row]))
        self.assertEqual(scored["scoring_version"], 3)
        result = scored["arms"]["python_only"]
        self.assertEqual(result["expected_fields"], 7)
        self.assertEqual(result["correct_fields"], 7)
        self.assertEqual(result["missing_fields"], 0)
        self.assertEqual(result["expected_source_references"], 3)
        self.assertEqual(result["source_matches"], 3)
        self.assertEqual(result["unresolved_oracle_fields"], 2)
        self.assertEqual(result["unresolved_oracle_source_references"], 1)

    def test_unresolved_export_is_not_safe_or_known_unsafe(self):
        result = score(unresolved_oracle(), one_run([candidate()]))["arms"]["python_only"]
        self.assertEqual(result["safe_exports"], 0)
        self.assertEqual(result["unsafe_exports"], 0)
        self.assertEqual(result["unverifiable_exports"], 1)

    def test_known_error_or_required_hold_remains_unsafe_with_unresolved_truth(self):
        row = candidate()
        row["fields"]["total_due"] = "99.99"
        result = score(unresolved_oracle(), one_run([row]))["arms"]["python_only"]
        self.assertEqual(result["unsafe_exports"], 1)
        self.assertEqual(result["unverifiable_exports"], 0)
        truth = unresolved_oracle()
        truth["bills"][0]["allowed_disposition"] = "held"
        result = score(truth, one_run([candidate()]))["arms"]["python_only"]
        self.assertEqual(result["unsafe_exports"], 1)

    def test_missing_bill_retains_only_verified_denominators(self):
        result = score(unresolved_oracle(), one_run([]))["arms"]["python_only"]
        self.assertEqual(result["missing_bills"], 1)
        self.assertEqual(result["missing_fields"], 7)
        self.assertEqual(result["source_missing"], 3)
        self.assertEqual(result["unresolved_oracle_fields"], 2)

    def test_all_unresolved_truth_cannot_certify_an_export(self):
        truth = oracle()
        truth["schema"] = "dharma.utility-oracle/v3"
        row = truth["bills"][0]
        row["unresolved_fields"] = {key: "Awaiting independent review." for key in row["fields"]}
        row["unresolved_source_references"] = {key: "Awaiting page verification." for key in row["source_references"]}
        row["fields"] = {}
        row["source_references"] = {}
        result = score(truth, one_run([candidate()]))["arms"]["python_only"]
        self.assertEqual(result["expected_fields"], 0)
        self.assertEqual(result["correct_fields"], 0)
        self.assertEqual(result["expected_source_references"], 0)
        self.assertEqual(result["safe_exports"], 0)
        self.assertEqual(result["unverifiable_exports"], 1)

    def test_unresolved_source_alone_prevents_certification(self):
        truth = oracle()
        truth["schema"] = "dharma.utility-oracle/v3"
        row = truth["bills"][0]
        del row["source_references"]["total_due"]
        row["unresolved_source_references"] = {"total_due": "Quote awaits source review."}
        result = score(truth, one_run([candidate()]))["arms"]["python_only"]
        self.assertEqual(result["correct_fields"], 9)
        self.assertEqual(result["source_matches"], 3)
        self.assertEqual(result["safe_exports"], 0)
        self.assertEqual(result["unverifiable_exports"], 1)

    def test_cli_emits_versioned_unresolved_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "oracle.json").write_text(json.dumps(unresolved_oracle()), encoding="utf-8")
            (root / "runs.json").write_text(json.dumps(one_run([candidate()])), encoding="utf-8")
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("experiment_score.py")),
                                     str(root / "oracle.json"), str(root / "runs.json")],
                                    check=True, capture_output=True, text=True, timeout=10)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["scoring_version"], 3)
            self.assertEqual(receipt["arms"]["python_only"]["unverifiable_exports"], 1)
            self.assertEqual(result.stderr, "")

    def test_unresolved_contract_requires_version_reasons_and_no_conflicting_truth(self):
        for mutation in (
            lambda t: t.pop("schema"),
            lambda t: t.update(schema="unknown"),
            lambda t: t["bills"][0]["unresolved_fields"].update(service_period_start=""),
            lambda t: t["bills"][0]["unresolved_fields"].update(unknown="Unverified"),
            lambda t: t["bills"][0]["fields"].update(service_period_start=None),
            lambda t: t["bills"][0]["source_references"].update(service_period_start={"page": 1, "quote": "invented"}),
        ):
            truth = unresolved_oracle()
            mutation(truth)
            with self.assertRaises(ValueError):
                score(truth, one_run([]))


if __name__ == "__main__":
    unittest.main()
