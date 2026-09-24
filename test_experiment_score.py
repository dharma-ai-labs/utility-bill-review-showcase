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


class ExperimentScoreTest(unittest.TestCase):
    def test_correct_export(self):
        result = score(oracle(), one_run([candidate()]))["arms"]["python_only"]
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


if __name__ == "__main__":
    unittest.main()
