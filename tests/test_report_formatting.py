import unittest

import app


class ReportFormattingTests(unittest.TestCase):
    def test_ultrasound_report_neck_heading_extracts_findings(self):
        report_text = (
            "Ultrasound Report – Neck\n"
            "\uf0b7 Thyroid gland is normal in size.\n"
            "\uf0b7 Cervical vessels are unremarkable.\n"
            "Impression:\n"
            "\uf0b7 Normal ultrasound findings."
        )

        self.assertEqual(
            app.extract_findings(report_text),
            [
                "Thyroid gland is normal in size.",
                "Cervical vessels are unremarkable.",
            ],
        )

    def test_generic_sonography_heading_extracts_findings(self):
        report_text = (
            "SONOGRAPHY OF THYROID\n"
            "\uf0b7 Thyroid gland is normal in size.\n"
            "\uf0b7 No focal lesion is seen.\n"
            "CONCLUSION:\n"
            "\uf0b7 Normal study."
        )

        self.assertEqual(
            app.extract_findings(report_text),
            [
                "Thyroid gland is normal in size.",
                "No focal lesion is seen.",
            ],
        )

    def test_report_title_does_not_become_a_finding(self):
        report_text = (
            "RADIOLOGY EXAMINATION REPORT\n"
            "Patient Name: Example\n"
            "MRN: 12345\n"
            "Ultrasound Report - Neck\n"
            "Thyroid gland is normal. · Cervical vessels are unremarkable.\n"
            "Impression:\n"
            "Normal study."
        )

        self.assertEqual(
            app.extract_findings(report_text),
            [
                "Thyroid gland is normal.",
                "Cervical vessels are unremarkable.",
            ],
        )

    def test_partial_pdf_text_uses_ocr(self):
        self.assertTrue(app.should_use_ocr("Patient Name: Example"))

        complete_text = (
            "Patient Name: Example\n"
            "FINDINGS\n"
            + ("The thyroid appears normal. " * 10)
        )
        self.assertFalse(app.should_use_ocr(complete_text))

    def test_pdf_bullets_become_separate_findings(self):
        report_text = (
            "\uf0b7 First finding. \uf0b7 Second finding. "
            "\uf0b7 Third finding."
        )

        self.assertEqual(
            app.split_findings(report_text),
            ["First finding.", "Second finding.", "Third finding."],
        )


if __name__ == "__main__":
    unittest.main()