import unittest

from utility_bill_checks import check_bill, cents


def candidate(**updates):
    value = {
        "account": "example-account",
        "service_period_start": "2026-01-01",
        "service_period_end": "2026-01-31",
        "current_charges": "17.48",
        "prior_balance": "0.00",
        "other_charges": "0.00",
        "total_due": "17.48",
        "source_references": {field: {"page": 1, "quote": "Synthetic fixture"}
                              for field in ("account", "service_period", "current_charges", "total_due")},
    }
    value.update(updates)
    return value


class UtilityBillChecksTest(unittest.TestCase):
    def test_exact_arithmetic_is_consistent_but_still_requires_review(self):
        self.assertEqual(check_bill(candidate()), {"status": "review_required", "holds": [], "arithmetic_pass": True})

    def test_prior_balance_and_late_charge_are_held(self):
        result = check_bill(candidate(current_charges="16.81", prior_balance="100.25",
                                      other_charges="2.04", total_due="119.10"))
        self.assertTrue(result["arithmetic_pass"])
        self.assertIn("prior_balance_requires_review", result["holds"])
        self.assertIn("other_charges_require_review", result["holds"])

    def test_missing_source_and_wrong_total_are_held(self):
        result = check_bill(candidate(total_due="19.48", source_references={}))
        self.assertFalse(result["arithmetic_pass"])
        self.assertIn("amounts_do_not_reconcile", result["holds"])
        self.assertIn("source_unverified_total_due", result["holds"])

    def test_signed_credit_is_not_erased(self):
        result = check_bill(candidate(current_charges="-188.84", prior_balance="778.96",
                                      total_due="590.12"))
        self.assertTrue(result["arithmetic_pass"])
        self.assertIn("negative_current_charges_require_review", result["holds"])

    def test_rejects_invalid_money(self):
        self.assertIsNone(cents("1.234"))
        self.assertIsNone(cents("NaN"))
        self.assertIsNone(cents(True))


if __name__ == "__main__":
    unittest.main()
