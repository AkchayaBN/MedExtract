import unittest
from unittest.mock import patch

import drug_matcher
import psycopg2


def make_drug(drug_id, name, generic):
    return {
        "id": drug_id,
        "drug_name": name,
        "generic_name": generic,
        "dosage_form": "Tablet",
        "ndc_code": "00000-0000",
        "normalized_name": drug_matcher.normalize_text(name),
        "normalized_generic": drug_matcher.normalize_text(generic),
    }


class DrugMatcherTests(unittest.TestCase):
    def setUp(self):
        self.original_drugs = drug_matcher.DRUGS

    def tearDown(self):
        drug_matcher.DRUGS = self.original_drugs

    def test_normalize_text_handles_common_ocr_substitutions(self):
        self.assertEqual(
            drug_matcher.normalize_text("  M|LBA-0  "),
            "milba-o",
        )

    def test_short_input_cannot_reach_review_threshold(self):
        drug = make_drug(1, "Multaq", "Dronedarone")

        score = drug_matcher.calculate_score("mul", drug)

        self.assertLessEqual(score, 0.74)
        self.assertEqual(drug_matcher.get_confidence_status(score), "LOW")

    def test_confidence_status_boundaries(self):
        self.assertEqual(drug_matcher.get_confidence_status(0.90), "HIGH")
        self.assertEqual(drug_matcher.get_confidence_status(0.75), "REVIEW")
        self.assertEqual(drug_matcher.get_confidence_status(0.7499), "LOW")

    def test_match_drug_uses_cached_catalogue_and_orders_results(self):
        drug_matcher.DRUGS = [
            make_drug(1, "Aspirin", "Acetylsalicylic acid"),
            make_drug(2, "Amoxicillin", "Amoxicillin"),
        ]

        matches = drug_matcher.match_drug("aspirin", limit=2)

        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0]["drug_name"], "Aspirin")
        self.assertEqual(matches[0]["status"], "HIGH")

    def test_database_connection_error_has_a_safe_message(self):
        with patch.object(
            drug_matcher.psycopg2,
            "connect",
            side_effect=psycopg2.OperationalError(),
        ):
            with self.assertRaisesRegex(
                drug_matcher.DrugCatalogueUnavailableError,
                "Drug matching is unavailable",
            ):
                drug_matcher.get_drugs()


if __name__ == "__main__":
    unittest.main()
