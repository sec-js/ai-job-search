import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.verify_pdf import (
    VerificationError,
    check_ats_parseability,
    extract_text_layer,
    find_ats_issues,
    parse_page_count,
    run_tool,
    verify_pdf,
)


class ParsePageCountTests(unittest.TestCase):
    def test_parses_pdfinfo_page_count(self):
        self.assertEqual(parse_page_count("Title: Example\nPages:          2\n"), 2)

    def test_rejects_output_without_page_count(self):
        with self.assertRaisesRegex(VerificationError, "did not contain a page count"):
            parse_page_count("Title: Example\n")


class VerifyPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf = Path(self.temp_dir.name) / "example.pdf"
        self.pdf.touch()

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tools.verify_pdf._extract_pypdf", return_value=None)
    @patch("tools.verify_pdf.run_tool")
    def test_accepts_expected_pages_and_text(self, mock_run_tool, _pypdf):
        mock_run_tool.side_effect = [
            "Professional\nExperience   [your.email@example.com]\n",
            "Pages:          2\n",
        ]

        verify_pdf(
            self.pdf,
            expected_pages=2,
            min_chars=20,
            required_text=("Professional Experience", "[your.email@example.com]"),
        )

    @patch("tools.verify_pdf._extract_pypdf", return_value=None)
    @patch("tools.verify_pdf.run_tool")
    def test_rejects_wrong_page_count(self, mock_run_tool, _pypdf):
        mock_run_tool.side_effect = ["ok", "Pages:          3\n"]

        with self.assertRaisesRegex(VerificationError, "expected 2 page.*found 3"):
            verify_pdf(self.pdf, expected_pages=2)

    @patch("tools.verify_pdf._extract_pypdf", return_value=None)
    @patch("tools.verify_pdf.run_tool")
    def test_rejects_too_little_extractable_text(self, mock_run_tool, _pypdf):
        mock_run_tool.side_effect = ["short", "Pages:          1\n"]

        with self.assertRaisesRegex(VerificationError, "expected at least 20"):
            verify_pdf(self.pdf, min_chars=20)

    @patch("tools.verify_pdf._extract_pypdf", return_value=None)
    @patch("tools.verify_pdf.run_tool")
    def test_rejects_missing_required_text(self, mock_run_tool, _pypdf):
        mock_run_tool.side_effect = [
            "Readable text, but not the expected section.",
            "Pages:          1\n",
        ]

        with self.assertRaisesRegex(VerificationError, "Professional Experience"):
            verify_pdf(self.pdf, required_text=("Professional Experience",))

    def test_rejects_missing_pdf(self):
        with self.assertRaisesRegex(VerificationError, "PDF does not exist"):
            verify_pdf(Path(self.temp_dir.name) / "missing.pdf")

    @patch("tools.verify_pdf._extract_pypdf", return_value=("Hello ATS body", 1))
    def test_pypdf_is_preferred_over_poppler(self, _pypdf):
        text, pages, extractor = extract_text_layer(self.pdf)
        self.assertEqual(extractor, "pypdf")
        self.assertEqual(text, "Hello ATS body")
        self.assertEqual(pages, 1)

    @patch("tools.verify_pdf._extract_pypdf", return_value=None)
    @patch("tools.verify_pdf.run_tool")
    def test_falls_back_to_pdftotext(self, mock_run_tool, _pypdf):
        mock_run_tool.side_effect = ["poppler text", "Pages:          2\n"]
        text, pages, extractor = extract_text_layer(self.pdf)
        self.assertEqual(extractor, "pdftotext")
        self.assertEqual(text, "poppler text")
        self.assertEqual(pages, 2)
        self.assertEqual(mock_run_tool.call_args_list[0][0][0][:3], ["pdftotext", "-layout", "-enc"])

    @patch("tools.verify_pdf._extract_pypdf", return_value=("Clean ATS text 2016-2024", 1))
    def test_check_ats_passes_clean_text(self, _pypdf):
        verify_pdf(self.pdf, check_ats=True, check_dates=True)

    @patch("tools.verify_pdf._extract_pypdf", return_value=("Broken (cid:9) text", 1))
    def test_check_ats_rejects_cid_markers(self, _pypdf):
        with self.assertRaisesRegex(VerificationError, r"\(cid:\*\)"):
            verify_pdf(self.pdf, check_ats=True)

    @patch("tools.verify_pdf._extract_pypdf", return_value=("Role 2016\u20132024 Company", 1))
    def test_check_dates_rejects_en_dash_ranges(self, _pypdf):
        with self.assertRaisesRegex(VerificationError, "en-dash"):
            verify_pdf(self.pdf, check_dates=True)


class AtsParseabilityTests(unittest.TestCase):
    def test_find_ats_issues_flags_cid_markers(self):
        issues = find_ats_issues("Role title (cid:12) and more (cid:34)")
        self.assertEqual(len(issues), 1)
        self.assertIn("(cid:*)", issues[0])

    def test_find_ats_issues_flags_replacement_characters(self):
        issues = find_ats_issues("K\u00f8benhavn \ufffd Denmark")
        self.assertEqual(len(issues), 1)
        self.assertIn("replacement", issues[0])

    def test_find_ats_issues_flags_en_dash_date_ranges(self):
        issues = find_ats_issues("Engineer 2016\u20132024 Acme", check_garbled=False, check_dates=True)
        self.assertEqual(len(issues), 1)
        self.assertIn("en-dash", issues[0])

    def test_find_ats_issues_accepts_ascii_hyphen_dates(self):
        issues = find_ats_issues("Engineer 2016-2024 Acme", check_garbled=False, check_dates=True)
        self.assertEqual(issues, [])

    def test_check_ats_parseability_raises_on_issues(self):
        with self.assertRaisesRegex(VerificationError, "replacement"):
            check_ats_parseability("broken \ufffd text")


class RunToolTests(unittest.TestCase):
    @patch("tools.verify_pdf.subprocess.run", side_effect=FileNotFoundError)
    def test_reports_missing_poppler_command(self, _mock_run):
        with self.assertRaisesRegex(VerificationError, "pip install pypdf"):
            run_tool(["pdftotext", "example.pdf", "-"])

    @patch("tools.verify_pdf.subprocess.run")
    def test_reports_unreadable_pdf(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["pdfinfo", "example.pdf"], stderr="invalid PDF"
        )

        with self.assertRaisesRegex(VerificationError, "invalid PDF"):
            run_tool(["pdfinfo", "example.pdf"])


if __name__ == "__main__":
    unittest.main()
