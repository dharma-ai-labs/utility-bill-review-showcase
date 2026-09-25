import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdf_python_baseline import extract_pages, parse_pages, run_manifest


SYNTHETIC_PAGE = """PPL Electric Utilities
Account Number: 0000-1234
Service Period: 01/01/2026 to 01/31/2026
Total Current Charges $17.48
Previous Balance $0.00
Other Charges $0.00
Total Amount Due $17.48
"""


class PdfPythonBaselineTest(unittest.TestCase):
    def test_complete_synthetic_bill_produces_source_linked_candidate(self):
        fields, refs, holds = parse_pages([SYNTHETIC_PAGE], {"PPL": "ELEC"})
        self.assertEqual(holds, [])
        self.assertEqual(fields["account_suffix"], "1234")
        self.assertEqual(fields["service_period_start"], "2026-01-01")
        self.assertEqual(fields["total_due"], "17.48")
        self.assertEqual(refs["total_due"], {"page": 1, "quote": "Total Amount Due $17.48"})

    def test_prior_balance_is_held_even_when_arithmetic_reconciles(self):
        page = SYNTHETIC_PAGE.replace("Previous Balance $0.00", "Previous Balance $2.00") \
            .replace("Total Amount Due $17.48", "Total Amount Due $19.48")
        fields, _, holds = parse_pages([page], {"PPL": "ELEC"})
        self.assertEqual(fields["total_due"], "19.48")
        self.assertIn("prior_balance_requires_review", holds)

    def test_missing_and_ambiguous_labels_are_held(self):
        page = SYNTHETIC_PAGE.replace("Total Amount Due $17.48", "")
        page += "Current Charges $17.48\n"
        _, refs, holds = parse_pages([page], {"PPL": "ELEC"})
        self.assertNotIn("total_due", refs)
        self.assertIn("missing_or_ambiguous_fields", holds)

    def test_unknown_vendor_and_unmapped_code_are_held(self):
        page = SYNTHETIC_PAGE.replace("PPL Electric Utilities", "Other Company")
        _, _, holds = parse_pages([page], {"PPL": "ELEC"})
        self.assertIn("vendor_missing_or_ambiguous", holds)
        self.assertIn("accounting_code_unmapped", holds)

    def test_uncommaed_four_digit_amount_is_parsed(self):
        page = SYNTHETIC_PAGE.replace("$17.48", "$1000.00")
        fields, _, holds = parse_pages([page], {"PPL": "ELEC"})
        self.assertEqual(fields["current_charges"], "1000.00")
        self.assertEqual(holds, [])

    def test_account_line_with_second_label_is_held(self):
        page = SYNTHETIC_PAGE.replace("Account Number: 0000-1234",
                                      "Account Number: 0000-1234 Rate Schedule 567")
        fields, _, holds = parse_pages([page], {"PPL": "ELEC"})
        self.assertIsNone(fields["account_suffix"])
        self.assertIn("missing_account", holds)

    def test_each_input_remains_in_output_on_extraction_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("pdf_python_baseline.extract_pages", side_effect=ValueError("bad_pdf")):
                result = run_manifest({"bills": [{"bill_id": "a", "pdf": "a.pdf"}],
                                       "vendor_codes": {"PPL": "ELEC"}}, Path(temp))
        row = result["runs"][0]["bills"][0]
        self.assertEqual(row["disposition"], "failed")
        self.assertEqual(row["diagnostics"]["failure"], "ValueError")

    def test_complete_extraction_produces_experimental_export_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bill.pdf"
            path.write_bytes(b"%PDF-1.4\nsynthetic fixture")
            with patch("pdf_python_baseline.extract_pages", return_value=([SYNTHETIC_PAGE], ["embedded_text"])):
                result = run_manifest({"bills": [{"bill_id": "a", "pdf": "bill.pdf"}],
                                       "vendor_codes": {"PPL": "ELEC"}}, Path(temp))
        row = result["runs"][0]["bills"][0]
        self.assertEqual(row["disposition"], "exported")
        self.assertEqual(row["diagnostics"]["holds"], [])
        self.assertEqual(row["diagnostics"]["extraction_methods"], ["embedded_text"])

    def test_scanned_page_uses_fixed_ocr_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bill.pdf"
            path.write_bytes(b"%PDF-1.4\nsynthetic fixture")

            def fake_run(args, **_kwargs):
                if args[0] == "pdfinfo":
                    return "Pages: 1\n"
                if args[0] == "pdftotext":
                    return "\n"
                if args[0] == "tesseract":
                    return "short" if args[-1] == "6" else SYNTHETIC_PAGE
                return ""

            with patch("pdf_python_baseline._run", side_effect=fake_run):
                pages, methods = extract_pages(path)
        self.assertEqual(pages, [SYNTHETIC_PAGE])
        self.assertEqual(methods, ["tesseract_psm11"])

    def test_oversize_page_count_fails_boundedly(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bill.pdf"
            path.write_bytes(b"%PDF-1.4\nsynthetic fixture")
            with patch("pdf_python_baseline._run", return_value="Pages: 21\n"):
                with self.assertRaisesRegex(ValueError, "unsupported_page_count"):
                    extract_pages(path)

    def test_duplicate_bill_id_is_rejected(self):
        with self.assertRaises(ValueError):
            run_manifest({"bills": [{"bill_id": "a", "pdf": "a.pdf"},
                                    {"bill_id": "a", "pdf": "b.pdf"}],
                          "vendor_codes": {}}, Path("."))


if __name__ == "__main__":
    unittest.main()
