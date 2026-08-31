import os
import json
import uuid
import subprocess

import psycopg2
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from drug_matcher import match_drug


app = Flask(__name__)
load_dotenv()
# ============================================================
# UPLOAD CONFIGURATION
# ============================================================

UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT","5432"),
}


# ============================================================
# FILE CONFIGURATION
# ============================================================

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}


def allowed_file(filename):
    """Check whether uploaded file is an allowed image."""

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


# ============================================================
# OCR
# ============================================================

def run_ocr(image_path):
    """
    Run Tesseract OCR.

    PSM 13 is used for a single handwritten
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


# ============================================================
# REVIEW QUEUE
# ============================================================

def add_to_review_queue(ocr_text, matches):
    """
    Add an uncertain OCR/drug matching result
    to the pharmacist review queue.
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


# ============================================================
# MAIN APPLICATION
# ============================================================

@app.route("/", methods=["GET", "POST"])
def index():

    image_path = None
    message = None
    error = None

    ocr_text = None
    matches = []
    best_match = None

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    if request.method == "POST":

        # ----------------------------------------------------
        # CHECK FILE
        # ----------------------------------------------------

        if "prescription" not in request.files:

            error = "Please select a prescription image."

        else:

            file = request.files["prescription"]

            if file.filename == "":

                error = "Please select a prescription image."

            elif not allowed_file(file.filename):

                error = (
                    "Only PNG, JPG and JPEG images "
                    "are supported."
                )

            else:

                try:

                    # ------------------------------------------------
                    # SAVE IMAGE
                    # ------------------------------------------------

                    original_name = secure_filename(
                        file.filename
                    )

                    unique_name = (
                        str(uuid.uuid4())
                        + "_"
                        + original_name
                    )

                    save_path = os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        unique_name
                    )

                    file.save(save_path)

                    image_path = (
                        "/static/uploads/"
                        + unique_name
                    )

                    # ------------------------------------------------
                    # STEP 1: OCR
                    # ------------------------------------------------

                    ocr_text = run_ocr(save_path)

                    if not ocr_text:

                        error = (
                            "OCR could not recognize "
                            "any text."
                        )

                    else:

                        # --------------------------------------------
                        # STEP 2: DRUG MATCHING
                        # --------------------------------------------

                        matches = match_drug(
                            ocr_text,
                            limit=5
                        )

                        # --------------------------------------------
                        # NO MATCH
                        # --------------------------------------------

                        if not matches:

                            add_to_review_queue(
                                ocr_text,
                                matches
                            )

                            message = (
                                "No reliable medicine match "
                                "was found. The case has been "
                                "added to the pharmacist "
                                "review queue."
                            )

                        else:

                            best_match = matches[0]

                            confidence = (
                                best_match["confidence"]
                            )

                            # ----------------------------------------
                            # HIGH CONFIDENCE
                            # ----------------------------------------
                            # 90% or higher:
                            # Automatically accepted.
                            # ----------------------------------------

                            if confidence >= 0.90:

                                message = (
                                    "Medicine identified "
                                    "with high confidence."
                                )

                            # ----------------------------------------
                            # REVIEW
                            # ----------------------------------------
                            # 75% - 89.99%:
                            # Send to pharmacist.
                            # ----------------------------------------

                            elif confidence >= 0.75:

                                add_to_review_queue(
                                    ocr_text,
                                    matches
                                )

                                message = (
                                    "Possible medicine match "
                                    "found. The case has been "
                                    "added to the pharmacist "
                                    "review queue."
                                )

                            # ----------------------------------------
                            # LOW CONFIDENCE
                            # ----------------------------------------
                            # Below 75%:
                            # Send to pharmacist.
                            # ----------------------------------------

                            else:

                                add_to_review_queue(
                                    ocr_text,
                                    matches
                                )

                                message = (
                                    "Low-confidence medicine "
                                    "match. The case has been "
                                    "added to the pharmacist "
                                    "review queue."
                                )

                except Exception as exc:

                    error = str(exc)

    # ========================================================
    # RENDER UI
    # ========================================================

    return render_template(
        "index.html",
        image_path=image_path,
        message=message,
        error=error,
        ocr_text=ocr_text,
        matches=matches,
        best_match=best_match
    )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
