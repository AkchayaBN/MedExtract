import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as prescription_app


def make_match(confidence):
    return [{
        "id": 1,
        "drug_name": "ExampleDrug",
        "generic_name": "ExampleGeneric",
        "dosage_form": "Tablet",
        "ndc_code": "00000-0000",
        "confidence": confidence,
        "status": (
            "HIGH" if confidence >= 0.90
            else "REVIEW" if confidence >= 0.75
            else "LOW"
        ),
    }]


class ReviewQueueRoutingTests(unittest.TestCase):
    def setUp(self):
        self.upload_directory = tempfile.TemporaryDirectory(
            dir=Path(__file__).parent,
        )
        self.original_upload_folder = prescription_app.app.config["UPLOAD_FOLDER"]
        self.original_testing = prescription_app.app.config.get("TESTING")
        prescription_app.app.config.update(
            TESTING=True,
            UPLOAD_FOLDER=self.upload_directory.name,
        )
        self.client = prescription_app.app.test_client()

    def tearDown(self):
        prescription_app.app.config["UPLOAD_FOLDER"] = self.original_upload_folder
        prescription_app.app.config["TESTING"] = self.original_testing
        self.upload_directory.cleanup()

    def submit_prescription(self, matches):
        with patch.object(prescription_app, "run_ocr", return_value="ocr text"):
            with patch.object(prescription_app, "match_drug", return_value=matches):
                with patch.object(prescription_app, "add_to_review_queue") as add_to_queue:
                    response = self.client.post(
                        "/",
                        data={"prescription": (io.BytesIO(b"image"), "rx.png")},
                        content_type="multipart/form-data",
                    )

        return response, add_to_queue

    def test_high_confidence_match_is_not_queued(self):
        matches = make_match(0.90)

        response, add_to_queue = self.submit_prescription(matches)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"high confidence", response.data.lower())
        add_to_queue.assert_not_called()

    def test_review_confidence_match_is_queued(self):
        matches = make_match(0.75)

        response, add_to_queue = self.submit_prescription(matches)

        self.assertEqual(response.status_code, 200)
        add_to_queue.assert_called_once_with("ocr text", matches)

    def test_low_confidence_match_is_queued(self):
        matches = make_match(0.7499)

        response, add_to_queue = self.submit_prescription(matches)

        self.assertEqual(response.status_code, 200)
        add_to_queue.assert_called_once_with("ocr text", matches)

    def test_no_match_is_queued(self):
        response, add_to_queue = self.submit_prescription([])

        self.assertEqual(response.status_code, 200)
        add_to_queue.assert_called_once_with("ocr text", [])

    def test_missing_tesseract_has_an_actionable_message(self):
        with patch.object(
            prescription_app.subprocess,
            "run",
            side_effect=FileNotFoundError(),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "not installed or is not available on PATH",
            ):
                prescription_app.run_ocr("prescription.png")


if __name__ == "__main__":
    unittest.main()
