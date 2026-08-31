import os
import json
import uuid
import subprocess

import psycopg2
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename

from drug_matcher import match_drug


app = Flask(__name__)

UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


DB_CONFIG = {
    "dbname": "prescriptrx",
    "user": "rxuser",
    "password": "RxUser@12345",
    "host": "localhost",
    "port": 5432,
}


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def run_ocr(image_path):
    """
    Run the installed Tesseract OCR engine.

    --psm 13 is suitable for a single handwritten
    medicine-word region.
    """

    command = [
        "tesseract",
        image_path,
        "stdout",
        "--psm",
        "13"
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Tesseract OCR failed: " + result.stderr
        )

    return result.stdout.strip()


def add_to_review_queue(ocr_text, matches):
    """
    Store uncertain OCR/drug-matching results
    in the PostgreSQL review_queue table.
    """

    confidence = 0.0

    if matches:
        confidence = matches[0]["confidence"]

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO review_queue
                (
                    raw_ocr_text,
                    top_matches,
                    ocr_confidence,
                    status
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    ocr_text,
                    json.dumps(matches),
                    confidence,
                    "pending"
                )
            )

        conn.commit()

    finally:
        conn.close()


@app.route("/", methods=["GET", "POST"])
def index():

    image_path = None
    message = None
    error = None

    ocr_text = None
    matches = []
    best_match = None

    if request.method == "POST":

        if "prescription" not in request.files:

            error = "Please select a prescription image."

        else:

            file = request.files["prescription"]

            if file.filename == "":

                error = "Please select a prescription image."

            elif not allowed_file(file.filename):

                error = "Only PNG, JPG and JPEG images are supported."

            else:

                try:

                    original_name = secure_filename(file.filename)

                    unique_name = (
                        str(uuid.uuid4()) + "_" + original_name
                    )

                    save_path = os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        unique_name
                    )

                    file.save(save_path)

                    image_path = "/static/uploads/" + unique_name

                    # -------------------------------------------------
                    # STEP 1: OCR
                    # -------------------------------------------------

                    ocr_text = run_ocr(save_path)

                    if not ocr_text:

                        error = "OCR could not recognize any text."

                    else:

                        # -------------------------------------------------
                        # STEP 2: DRUG MATCHING
                        # -------------------------------------------------

                        matches = match_drug(
                            ocr_text,
                            limit=5
                        )

                        if matches:

                            best_match = matches[0]

                            # -------------------------------------------------
                            # STEP 3: REVIEW QUEUE
                            # -------------------------------------------------

                            if best_match["confidence"] < 0.75:

                                add_to_review_queue(
                                    ocr_text,
                                    matches
                                )

                                message = (
                                    "Low-confidence result. "
                                    "The case has been added to the "
                                    "pharmacist review queue."
                                )

                            elif best_match["confidence"] < 0.90:

                                message = (
                                    "Possible medicine match found. "
                                    "Manual verification is recommended."
                                )

                            else:

                                message = (
                                    "Medicine identified with high confidence."
                                )

                        else:

                            add_to_review_queue(
                                ocr_text,
                                matches
                            )

                            message = (
                                "No reliable medicine match found. "
                                "The case has been added to the review queue."
                            )

                except Exception as exc:

                    error = str(exc)

    return render_template(
        "index.html",
        image_path=image_path,
        message=message,
        error=error,
        ocr_text=ocr_text,
        matches=matches,
        best_match=best_match
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
