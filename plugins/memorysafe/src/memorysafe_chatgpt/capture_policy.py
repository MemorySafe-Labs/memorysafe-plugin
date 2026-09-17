"""What automatic capture refuses, and why.

The guard this replaces tested the label, not the payload. It was a keyword regex
over phrases like "email address" and "home address", so it blocked someone
*saying* "email address" and saved an actual one:

    BLOCKED  "My card number is 4111 1111 1111 1111"   (a separate value check)
    ALLOWED  "Ankit's email is someone@example.com"
    ALLOWED  "Carla lives at 1250 Rue Sherbrooke Ouest, Montreal"

Both Elan and Lumi reviewed the fix and converged on two rules that are now the
shape of this module.

**Name the shape, never echo the value.** A refusal is recorded in
decision_events and surfaces in health and governance output. A reason that
quotes what it refused re-leaks the secret into the very log meant to prove we
did not keep it. Callers get a stable shape name they can act on; the payload
never leaves this function.

**Negative tests matter more than positive ones.** A false skip costs one
memory. A false save breaks a promise. But a detector that fires on every
version number, port, date or dollar amount makes automatic capture useless and
gets switched off, which costs every memory. Every pattern here is paired with
things it must not match, in tests/test_capture_policy.py.
"""

from __future__ import annotations

import re

# Talking *about* a sensitive category is still worth refusing: "my password is
# the usual one" carries no extractable value but signals the wrong kind of
# content. Kept from the original guard, now only one check among several.
_SENSITIVE_SUBJECT = re.compile(
    r"\b(?:password|passcode|one[- ]time code|otp|api key|secret key|private key|"
    r"access token|refresh token|credit card|debit card|card number|cvv|cvc|bank account|"
    r"routing number|social security|social insurance|passport|driver'?s? licen[cs]e|"
    r"date of birth|medical record|medication|allerg(?:y|ic)|therapy|therapist|"
    r"diagnos(?:is|ed))\b",
    re.IGNORECASE,
)

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]*[A-Za-z]{2,}\b")

# Requires punctuation or a country code. A bare ten-digit run is far more often
# an enterprise number, an order id or a timestamp than a phone number.
_PHONE = re.compile(
    r"(?:(?<!\d)\+\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?|(?<![\d.])\d{3}[ .-])\d{3}[ .-]\d{4}(?!\d)"
)

# A number, then a street word. "Suite 300" and "Highway 40" are excluded by
# requiring a thoroughfare noun rather than any capitalised word.
_STREET = re.compile(
    r"\b\d{1,6}\s+(?:[\w'’.-]+\s+){0,4}"
    r"(?:st\.?|street|rue|ave\.?|avenue|blvd\.?|boulevard|rd\.?|road|dr\.?|drive|"
    r"ln\.?|lane|way|court|ct\.?|place|pl\.?|chemin|croissant|terrasse)\b",
    re.IGNORECASE,
)

_POSTAL_CA = re.compile(r"\b[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d\b")
_POSTAL_US = re.compile(r"\b\d{5}-\d{4}\b")

# Canadian SIN / US SSN shapes. Both require the grouping punctuation, so a
# nine-digit registration number does not trip them.
_GOVERNMENT_ID = re.compile(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b|\b\d{3}-\d{2}-\d{4}\b")

# Token-shaped secrets: a recognised prefix, or a long unbroken high-entropy run.
_CREDENTIAL = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|ghs|ghu|xoxb|xoxp|AKIA|ASIA)[-_][A-Za-z0-9_-]{16,}\b"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)

_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn(digits: str) -> bool:
    """Card numbers check out; version strings, ports and order ids do not.

    Without this, any run of thirteen or more digits reads as a card. With it,
    the pattern costs one arithmetic pass and stops guessing.
    """

    total = 0
    for index, character in enumerate(reversed(digits)):
        value = int(character)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _payment_card(content: str) -> bool:
    for match in _CARD_CANDIDATE.finditer(content):
        digits = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


# Ordered: the first match wins, so the most specific and most costly-to-leak
# shapes are tested before the broader ones.
_SHAPES: tuple[tuple[str, object], ...] = (
    ("credential", _CREDENTIAL.search),
    ("payment_card", _payment_card),
    ("government_id", _GOVERNMENT_ID.search),
    ("email_address", _EMAIL.search),
    ("phone_number", _PHONE.search),
    ("street_address", _STREET.search),
    ("postal_code", lambda text: _POSTAL_CA.search(text) or _POSTAL_US.search(text)),
    ("sensitive_subject", _SENSITIVE_SUBJECT.search),
)

# Shown to the user and stored in decision_events. No entry interpolates content.
_REASONS: dict[str, str] = {
    "credential": (
        "Looks like a key, token or password. Automatic capture never stores "
        "credentials; nothing was saved."
    ),
    "payment_card": (
        "Looks like a payment card number. Automatic capture never stores payment "
        "details; nothing was saved."
    ),
    "government_id": (
        "Looks like a government identification number. Automatic capture never "
        "stores government IDs; nothing was saved."
    ),
    "email_address": (
        "Contains an email address. Automatic capture never stores contact "
        "details; ask me to remember it explicitly if you want it kept."
    ),
    "phone_number": (
        "Contains a phone number. Automatic capture never stores contact details; "
        "ask me to remember it explicitly if you want it kept."
    ),
    "street_address": (
        "Contains a street address. Automatic capture never stores precise "
        "locations; ask me to remember it explicitly if you want it kept."
    ),
    "postal_code": (
        "Contains a postal code. Automatic capture never stores precise "
        "locations; ask me to remember it explicitly if you want it kept."
    ),
    "sensitive_subject": (
        "Mentions a category we do not capture automatically — credentials, "
        "identity documents or health information. Nothing was saved."
    ),
    "safety_category": (
        "Safety or health-related details require an explicit remember request."
    ),
    "too_long": (
        "Automatic memories must be concise; the full message was not saved."
    ),
    "automatic_mode_off": "Automatic mode is off, so nothing was saved.",
}

MAX_AUTOMATIC_LENGTH = 500


def classify(content: str) -> str | None:
    """Return the name of the first refused shape, or None to allow.

    Only the shape name crosses this boundary. The caller never receives the
    matched text, so no refusal can be logged with the value that caused it.
    """

    for name, matches in _SHAPES:
        if matches(content):
            return name
    return None


def reason_for(shape: str) -> str:
    return _REASONS.get(
        shape, "Potentially sensitive information was not saved automatically."
    )


def skip_reason(content: str, category: str, automatic_mode: bool) -> tuple[str, str] | None:
    """(shape, reason) when automatic capture must refuse, else None.

    NOTE — one promise is not enforced here. The tool description says automatic
    capture never stores third-party personal details, and no pattern can decide
    that: "met Jean Tremblay, director at a bank, at Place Ville Marie" contains
    no email, phone or card. Lumi raised this and it is unresolved. Either a
    subject policy rejects likely named third-person facts, or the description
    narrows to what this module actually enforces. Carla decides; until then the
    promise is wider than the code, and this comment is the only honest record
    of that.
    """

    if not automatic_mode:
        return ("automatic_mode_off", _REASONS["automatic_mode_off"])
    if category == "safety":
        return ("safety_category", _REASONS["safety_category"])
    shape = classify(content)
    if shape is not None:
        return (shape, reason_for(shape))
    if len(content) > MAX_AUTOMATIC_LENGTH:
        return ("too_long", _REASONS["too_long"])
    return None
