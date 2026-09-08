import json
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432"),
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def add_to_review_queue(raw_ocr_text, top_matches, ocr_confidence):
    """
    Add an uncertain OCR result to the pharmacist review queue.

    Parameters:
        raw_ocr_text: Original OCR output.
        top_matches: List of drug candidates from drug_matcher.py.
        ocr_confidence: OCR/matching confidence score.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_queue
                (
                    raw_ocr_text,
                    top_matches,
                    ocr_confidence,
                    status
                )
                VALUES (%s, %s, %s, 'pending')
                RETURNING id;
                """,
                (
                    raw_ocr_text,
                    json.dumps(top_matches),
                    ocr_confidence
                )
            )

            queue_id = cur.fetchone()[0]

        conn.commit()

        return queue_id

    finally:
        conn.close()


def get_pending_reviews():
    """
    Return all pending pharmacist reviews.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    raw_ocr_text,
                    top_matches,
                    ocr_confidence,
                    status,
                    pharmacist_note,
                    created_at
                FROM review_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC;
                """
            )

            rows = cur.fetchall()

        return rows

    finally:
        conn.close()


def approve_review(queue_id, pharmacist_note=""):
    """
    Mark a review as approved.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_queue
                SET
                    status = 'approved',
                    pharmacist_note = %s
                WHERE id = %s;
                """,
                (pharmacist_note, queue_id)
            )

        conn.commit()

    finally:
        conn.close()


def reject_review(queue_id, pharmacist_note=""):
    """
    Mark a review as rejected.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_queue
                SET
                    status = 'rejected',
                    pharmacist_note = %s
                WHERE id = %s;
                """,
                (pharmacist_note, queue_id)
            )

        conn.commit()

    finally:
        conn.close()


def print_pending_reviews():
    """
    Display pending reviews in a readable format.
    """

    reviews = get_pending_reviews()

    print("\n" + "=" * 70)
    print("PENDING PHARMACIST REVIEW QUEUE")
    print("=" * 70)

    if not reviews:
        print("No pending reviews.")
        return

    for review in reviews:

        queue_id = review[0]
        raw_text = review[1]
        matches = review[2]
        confidence = review[3]
        status = review[4]
        note = review[5]
        created = review[6]

        print("\nReview ID:", queue_id)
        print("OCR Text:", raw_text)
        print("Confidence:", confidence)
        print("Status:", status)
        print("Created:", created)

        print("\nTop Candidates:")

        if matches:
            for i, match in enumerate(matches, start=1):
                print(
                    f"  {i}. "
                    f"{match.get('drug_name', 'Unknown')} | "
                    f"{match.get('generic_name', 'Unknown')} | "
                    f"{match.get('confidence', 0):.2f}%"
                )

        if note:
            print("Pharmacist Note:", note)

        print("-" * 70)


if __name__ == "__main__":

    print_pending_reviews()
