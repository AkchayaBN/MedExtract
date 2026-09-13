"""
ai_client.py
============
Thin wrapper around the Google Gemini API (generativelanguage.googleapis.com).

Reads the API key from the GEMINI_API_KEY environment variable (loaded from
a local .env file via python-dotenv - see .env.example). No key is ever
hardcoded here.

Get a key at: https://aistudio.google.com/app/apikey
"""

import json
import os
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

# Transient Gemini errors worth a short retry before giving up - 503 means
# "model overloaded, try again shortly" and 429 is rate-limiting; both
# usually clear up within a couple of seconds.
RETRYABLE_HTTP_CODES = (429, 503)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# "gemini-flash-latest" is a Google-maintained alias that always points at
# their current fast/cheap general model, so this doesn't need to be
# updated by hand as Google ships new versions. Override via env var if
# you want to pin a specific version.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiConfigError(RuntimeError):
    """Raised when the Gemini API key/config is missing or invalid."""


class GeminiRequestError(RuntimeError):
    """Raised when the Gemini API call itself fails (network, quota, etc.)."""


def ask_gemini(system_instruction, user_message, temperature=0.2, max_output_tokens=800):
    """
    Send a single-turn request to the Gemini API.

    system_instruction: string describing the assistant's role/context/data
                         (this is where we inject the report/report-history
                         JSON so the model answers grounded in real data).
    user_message: the person's raw question.

    Returns the model's text reply. Raises GeminiConfigError / GeminiRequestError
    on failure so callers can show a clear message instead of a stack trace.
    """
    if not GEMINI_API_KEY:
        raise GeminiConfigError(
            "GEMINI_API_KEY is not set. Add it to a .env file in the project "
            "root (see .env.example) and restart the app. Get a key at "
            "https://aistudio.google.com/app/apikey"
        )

    url = GEMINI_ENDPOINT.format(model=GEMINI_MODEL)

    payload = {
        "system_instruction": {
            "parts": [{"text": system_instruction}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": user_message}]}
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }

    request_body = json.dumps(payload).encode("utf-8")

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        request = urllib.request.Request(
            url + "?key=" + GEMINI_API_KEY,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")

            if exc.code in (400, 403):
                raise GeminiConfigError(
                    "Gemini rejected the request (HTTP {}). This usually means "
                    "the API key is invalid, restricted, or doesn't have the "
                    "Generative Language API enabled. Details: {}".format(
                        exc.code, error_body
                    )
                )

            last_error = GeminiRequestError(
                "Gemini API call failed (HTTP {}): {}".format(exc.code, error_body)
            )

            if exc.code in RETRYABLE_HTTP_CODES and attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

            if exc.code in RETRYABLE_HTTP_CODES:
                # Retries exhausted on a transient error - surface a friendly
                # message instead of the raw Gemini error payload.
                return (
                    "The chatbot model is temporarily overloaded on Google's "
                    "side. Please try asking again in a few seconds."
                )

            raise last_error
        except urllib.error.URLError as exc:
            raise GeminiRequestError("Could not reach Gemini API: {}".format(exc.reason))
    else:
        # Loop exhausted without a `break` (shouldn't normally happen since
        # the retryable branch above returns early, but guards against it).
        if last_error:
            raise last_error

    try:
        candidates = body.get("candidates", [])
        if not candidates:
            block_reason = body.get("promptFeedback", {}).get("blockReason")
            if block_reason:
                return (
                    "The model declined to answer that question "
                    "(reason: {}).".format(block_reason)
                )
            raise GeminiRequestError("Gemini returned no candidates: {}".format(body))

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        return text or "The model returned an empty response."
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiRequestError(
            "Unexpected Gemini response shape: {} ({})".format(body, exc)
        )
