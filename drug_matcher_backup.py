import re
import psycopg2
from rapidfuzz import fuzz


DB_CONFIG = {
    "dbname": "prescriptrx",
    "user": "rxuser",
    "password": "RxUser@12345",
    "host": "localhost",
    "port": 5432,
}


# Confidence thresholds
HIGH_CONFIDENCE = 0.90
REVIEW_CONFIDENCE = 0.75


def normalize_text(text):
    """Normalize OCR text and medicine names."""

    if not text:
        return ""

    text = str(text).lower().strip()

    # Common OCR cleanup
    text = text.replace("|", "i")
    text = text.replace("0", "o")

    # Keep letters, numbers and spaces
    text = re.sub(r"[^a-z0-9\s-]", " ", text)

    # Remove repeated whitespace
    text = re.sub(r"\s+", " ", text)

    return text


def get_drugs():
    """Load medicine records from PostgreSQL."""

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    drug_name,
                    generic_name,
                    dosage_form,
                    ndc_code
                FROM drugs
                WHERE drug_name IS NOT NULL
            """)

            return cursor.fetchall()

    finally:
        conn.close()


def calculate_score(ocr_text, drug_name, generic_name):
    """
    Calculate medicine matching confidence.

    Very short OCR strings are not allowed to generate
    artificially high confidence through partial matching.
    """

    ocr = normalize_text(ocr_text)
    name = normalize_text(drug_name)
    generic = normalize_text(generic_name)

    if not ocr or len(ocr) < 3:
        return 0.0

    name_ratio = fuzz.ratio(ocr, name) / 100.0
    name_partial = fuzz.partial_ratio(ocr, name) / 100.0

    if generic:
        generic_ratio = fuzz.ratio(ocr, generic) / 100.0
    else:
        generic_ratio = 0.0

    # Exact/overall name similarity is primary.
    score = (
        name_ratio * 0.70 +
        generic_ratio * 0.30
    )

    # Partial matching is useful only when OCR is reasonably long.
    if len(ocr) >= 5:
        score = max(score, name_partial * 0.85)

    return round(min(score, 1.0), 4)


def get_confidence_status(score):
    """Convert confidence into a safe decision."""

    if score >= 0.90:
        return "HIGH"

    if score >= 0.75:
        return "REVIEW"

    return "LOW"


def match_drug(ocr_text, limit=5):
    """Return the best medicine candidates."""

    normalized_ocr = normalize_text(ocr_text)

    if not normalized_ocr:
        return []

    drugs = get_drugs()

    results = []

    for drug in drugs:

        drug_id = drug[0]
        drug_name = drug[1]
        generic_name = drug[2]
        dosage_form = drug[3]
        ndc_code = drug[4]

        score = calculate_score(
            normalized_ocr,
            drug_name,
            generic_name
        )

        results.append({
            "id": drug_id,
            "drug_name": drug_name,
            "generic_name": generic_name,
            "dosage_form": dosage_form,
            "ndc_code": ndc_code,
            "confidence": score,
            "status": get_confidence_status(score)
        })

    results.sort(
        key=lambda item: item["confidence"],
        reverse=True
    )

    return results[:limit]


def print_matches(ocr_text, matches):
    """Print matching results."""

    print()
    print("=" * 65)
    print(f"OCR TEXT: {ocr_text}")
    print("=" * 65)

    if not matches:
        print("No medicine matches found.")
        return

    best = matches[0]

    print()
    print("BEST MATCH")
    print("-" * 65)
    print(f"Medicine:   {best['drug_name']}")
    print(f"Generic:    {best['generic_name']}")
    print(f"Dosage:     {best['dosage_form']}")
    print(f"NDC:        {best['ndc_code']}")
    print(f"Confidence: {best['confidence']:.2%}")
    print(f"Status:     {best['status']}")

    print()
    print("TOP CANDIDATES")
    print("-" * 65)

    for index, match in enumerate(matches, 1):

        print(
            f"{index}. {match['drug_name']} "
            f"| {match['generic_name']} "
            f"| {match['confidence']:.2%} "
            f"| {match['status']}"
        )


if __name__ == "__main__":

    # Test cases
    test_inputs = [
        "Aceta",
        "Paracetamol",
        "Acthar"
    ]

    for test_text in test_inputs:

        try:
            matches = match_drug(test_text)
            print_matches(test_text, matches)

        except Exception as error:
            print()
            print("ERROR:")
            print(error)
