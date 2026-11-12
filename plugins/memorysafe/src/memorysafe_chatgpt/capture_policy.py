"""What automatic capture refuses, and why.

The guard this replaces tested the label, not the payload. It was a keyword regex
over phrases like "email address" and "home address", so it blocked someone
*saying* "email address" and saved an actual one:

    BLOCKED  "My card number is 4111 1111 1111 1111"   (a separate value check)
    ALLOWED  "Her email is someone@example.com"
    ALLOWED  "She lives at 1 Example Street, Montreal"

Two reviewers converged on two rules that are now the shape of this module.

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
    r"diagnos(?:is|ed)|"
    # The same subjects in French and Portuguese: none of them was recognised, so "mot de
    # passe", "numéro de sécurité sociale" and "senha" were saved.
    r"mot de passe|carte de cr[ée]dit|passeport|permis de conduire|date de naissance|"
    r"s[ée]curit[ée] sociale|assurance sociale|num[ée]ro d'assurance|dossier m[ée]dical|"
    r"senha|cart[ãa]o de cr[ée]dito|passaporte|data de nascimento|contrase[ñn]a)\b",
    re.IGNORECASE,
)

# A health condition or treatment said of a person: "I have type 2 diabetes", "her son takes
# methylphenidate for ADHD". The subject list above only knew the words medication, allergy,
# therapy and diagnosis, so a condition named outright was saved. A verb of having or taking
# must sit near the term, so "the diabetes dashboard ships in May" is still a project fact.
_HEALTH_TERM = (
    r"(?:adhd|diabet\w*|insulin|asthma\w*|cancer|chemo\w*|hiv|autis\w*|depress(?:ion|ed)|bipolar|"
    r"epilep\w*|pregnan\w*|migraines?|antidepressants?|seizures?|ptsd|dementia|alzheimer\w*|"
    r"dialysis|anxiety disorder|blood pressure|cholesterol|chronic pain|eating disorder|"
    r"methylphenidate|metformin|ritalin|adderall|vyvanse|prozac|zoloft|xanax|warfarin|statins?)"
)
_HEALTH_OF_A_PERSON = re.compile(
    r"(?:\b(?:ha(?:s|ve|d)|take[sn]?|taking|took|prescribed|diagnosed|suffer\w*|lives? with|living with|"
    r"is|am|was|on|treated for|manag\w+)\b|['’](?:m|s|ve|d)\b)[^.!?]{0,60}\b" + _HEALTH_TERM + r"\b"
    r"|\b" + _HEALTH_TERM + r"\b[^.!?]{0,40}\b(?:diagnosis|medication|meds|prescription|treatment|flare|episode)s?\b"
    # A dose is a prescription whatever the drug is called; an operation someone had; and the
    # commonest ways of saying either in French and Portuguese (all missed in review).
    r"|\b(?:take[sn]?|taking|took|prescribed|on|prends?|tomo|toma)\b[^.!?]{0,30}\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|µg)\b"
    r"|\b(?:had|have|having|need(?:s|ed)?|after|since|before)\b[^.!?]{0,30}\b(?:surgery|operation|chemo\w*|biopsy)\b"
    r"|\b(?:sous traitement|en traitement|trait[ée]e? pour|em tratamento|fa[çc]o tratamento)\b"
    r"|\b(?:j'ai|je suis|je souffre|tenho|sofro|estou)\b[^.!?]{0,40}\b(?:asthme|asma|diab[èée]t\w*|hypertension|"
    r"hipertens\w+|enceinte|gr[áa]vida|d[ée]pression|depress[ãa]o|[ée]pilep\w+|cancer|c[âa]ncer)\b",
    re.IGNORECASE,
)
# Seven digits are a phone number only next to a word that says so; alone they are a
# ticket, a part number or a date range.
_PHONE_WORD = re.compile(
    r"\b(?:cell|mobile|phone|tel|telephone|text me|call me|reach me|whatsapp|num[ée]ro|celular|t[ée]l[ée]phone)\b"
    r"[^.!?]{0,30}(?<![\d-])\d{3}[-. ]\d{4}(?![\d-])",
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
#
# The noun alone was not enough: "There are 2 ways to drive the build", "Release 3 is on
# the road map", "5 minutes drive from the office" and "12 services in the court booking
# app" were all refused as street addresses, and a detector that fires on ordinary project
# sentences gets automatic mode switched off. A street has a name, so the word before the
# noun must be capitalised or an ordinal ("1 Example Street", "40 5th Avenue"); in French
# the noun comes first and the name after it ("12 rue Sainte-Catherine").
_STREET_NOUN = (
    r"(?:[Ss]t\.?|[Ss]treet|[Aa]ve\.?|[Aa]venue|[Bb]lvd\.?|[Bb]oulevard|[Rr]d\.?|[Rr]oad|[Dd]r\.?|"
    r"[Dd]rive|[Ll]n\.?|[Ll]ane|[Ww]ay|[Cc]ourt|[Cc]t\.?|[Pp]lace|[Pp]l\.?|[Cc]roissant|[Tt]errasse)"
)
_STREET = re.compile(
    r"\b\d{1,6}[A-Za-z]?\s+(?:[\w'’.-]+\s+){0,3}(?:[A-ZÀ-Ý][\w'’.-]*|\d+(?:st|nd|rd|th|e|re))\s+" + _STREET_NOUN + r"(?![\w-])"
    r"|\b\d{1,6},?\s+(?i:rue|boul\.?|boulevard|avenue|av\.?|chemin|ch\.|place|croissant|terrasse|rua|avenida)"
    r"\s+(?:(?:de|du|des|da|do|la|le|les|l['’])\s*)*[A-ZÀ-Ý]"
)

_POSTAL_CA = re.compile(r"\b[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d\b")
_POSTAL_US = re.compile(r"\b\d{5}-\d{4}\b")

# Canadian SIN / US SSN shapes. Both require the grouping punctuation, so a
# nine-digit registration number does not trip them. Brazil's CPF has its own punctuation,
# and an IBAN its country code, check digits and four-character groups.
_GOVERNMENT_ID = re.compile(
    r"\b\d{3}[ -]\d{3}[ -]\d{3}\b|\b\d{3}-\d{2}-\d{4}\b|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")

# Token-shaped secrets, matched by their issuer's prefix: distinctive enough to be near
# zero false positives on ordinary prose, where an entropy test flags every long id.
#
# The first version required "-" or "_" after every prefix, so an AWS key id
# (which has neither) was saved, and it knew nothing of GitHub's
# fine-grained tokens, Google keys, Authorization headers, the other Slack prefixes, npm
# tokens or a connection string with its password in it. The importer shares this module
# as its only gate before a file is uploaded.
_CREDENTIAL = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|ghs|ghu|ghr|xoxa|xoxb|xoxp|xoxr|xoxs)[-_][A-Za-z0-9_-]{16,}\b"
    r"|\bA(?:KIA|SIA|ROA|IDA|GPA|NPA|NVA|IPA)[0-9A-Z]{16}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}\b"
    r"|\bnpm_[A-Za-z0-9]{30,}\b"
    r"|\bAIza[0-9A-Za-z_-]{30,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    r"|\b[a-z][a-z0-9+.-]{1,15}://[^\s:/@]{1,64}:[^\s/@]{3,}@[\w.-]+"
    # A webhook address is its own password: whoever has the URL can post.
    r"|\bhttps?://(?:hooks\.[\w.-]+|[\w.-]*webhook[\w.-]*)/\S{16,}"
    # "the login is admin / hunter2": a name and a password either side of a slash.
    r"|\b(?:log-?in|credentials?|username|identifiants?|mdp)\b[^.!?]{0,40}\b\S{3,}\s+/\s+\S{6,}"
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
    ("government_id", lambda text: _GOVERNMENT_ID.search(text) or _IBAN.search(text)),
    ("email_address", _EMAIL.search),
    ("phone_number", lambda text: _PHONE.search(text) or _PHONE_WORD.search(text)),
    ("street_address", _STREET.search),
    ("postal_code", lambda text: _POSTAL_CA.search(text) or _POSTAL_US.search(text)),
    ("sensitive_subject", lambda text: _SENSITIVE_SUBJECT.search(text) or _HEALTH_OF_A_PERSON.search(text)),
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

# ---------------------------------------------------------------------------
# Passing remarks. The shapes above ask "is this safe to keep"; nothing asked "is this
# worth keeping". Automatic capture stored whatever it was handed: how the person felt
# that day, a request to redo the last step, the assistant's guess at what they wanted.
# The prompt hook was worse, because it saves without the model: a "never mind" and a
# "don't do that yet" became protected preferences and were then carried into every later
# session as standing orders.
#
# The same two rules hold. A shape name, never the text. And a false refusal must stay
# rare, because one that fires on real preferences gets automatic mode switched off, so
# each shape below is something a pattern can actually see:
#
#   question          it ends with a question mark
#   acknowledgement   a short reply that opens with one ("thanks", "sounds good")
#   about_the_chat    the assistant describing the conversation or its own work
#   assistant_guess   the assistant's reading of the person ("the user seems...")
#   passing_state     true only at the moment it was said ("right now", "today")
#   one_off           an instruction scoped to this one piece of work ("for now", "yet")
#
# A standing marker ("always", "from now on", "by default") overrules passing_state and
# one_off: "starting today we use pnpm" is a rule, not a remark. Anything these shapes do
# not recognise is kept, as before. An explicit "remember this" never comes here at all.
_STANDING = re.compile(
    r"\b(?:always|never(?!\s?mind)|from now on|from today|starting (?:today|now|this)|as of (?:today|now)|"
    r"going forward(?!\s+with)|by default|every time|whenever|in (?:the )?future|as a rule|in general|"
    r"permanently|d[ée]sormais|toujours|jamais|sempre|nunca|a partir de)\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"\?\s*$")
# "no anglicisms in the copy, ok?" asks nothing: the question mark belongs to the tag.
_TAG_QUESTION = re.compile(
    r",\s*(?:ok(?:ay)?|right|yeah|yes|no|got it|understood|d'accord|hein|non|t[áa]|n[ée]|certo|entendido)\s*\?\s*$",
    re.IGNORECASE,
)
# An acknowledgement is the whole message, not its first word. The first version took any
# message of up to eight words that opened with one of these, and so declined short standing
# rules that begin "no ...", "lol ..." or "right, ..." (found in review, 10 Nov 2026). "no"
# on its own opens a prohibition
# as often as a reply, so it is not in the list; "never mind" takes back what came before it
# whatever follows.
_ACKNOWLEDGEMENT = re.compile(
    r"^\W*(?:ok(?:ay)?|k|thanks?(?: you)?|thx|ty|got it|sounds good|great|perfect|cool|nice|sure|yes|yep|yeah|"
    r"nope|no thanks|no worries|no problem|lol|haha+|hmm+|wow|awesome|good|fine|done|right|alright|all right|"
    r"makes sense|will do|np|merci|d'accord|obrigad[oa]|valeu)\b",
    re.IGNORECASE,
)
_NEVER_MIND = re.compile(r"^\W*never ?mind\b", re.IGNORECASE)
ACKNOWLEDGEMENT_MAX_WORDS = 4
_ABOUT_THE_CHAT = re.compile(
    r"^\W*(?:(?:we|i|the user and i)\s+(?:just\s+|already\s+|have\s+|had\s+)*"
    r"(?:discussed|talked about|went over|covered|chatted about|were talking about|was explaining)\b"
    r"|(?:in|during|earlier in)\s+(?:this|our|the)\s+(?:conversation|chat|session|call|thread)\b"
    r"|(?:the\s+)?user\s+(?:asked|requested|wanted|wants)\s+(?:me|the assistant|for|to|about|if|whether|how|why|what)\b"
    # The assistant reporting its own work. In the first person only when the object is a
    # piece of the conversation ("I rewrote the email"), because "I created the company in
    # 2019" is the person talking about their life.
    r"|(?:the\s+)?assistant\s+(?:has\s+|have\s+|just\s+|already\s+|will\s+)*\w+"
    r"|i(?:\s+have|'ve|\s+just|\s+already)*\s+(?:updated|fixed|created|added|implemented|ran|wrote|rewrote|"
    r"refactored|changed|explained|suggested|recommended|generated|summari[sz]ed|answered|drafted|edited|"
    r"reviewed|noted|recalculated|translated|reformatted|corrected|shortened|checked)\s+(?:\w+\s+){0,3}?"
    r"(?:your|email|paragraph|draft|summary|response|answer|code|function|file|readme|typo|tests?|script|"
    r"section|sentence|message|document|slide|abstract|report|query|table|list|preferences|it|that|this)\b"
    r"|summary\s*:"
    r"|(?:the\s+)?user\s+(?:said|says)\s+(?:hello|hi|thanks|thank you|goodbye|bye|ok|okay|yes|no)\b"
    r"|(?:the\s+)?user\s+(?:liked|agreed|thanked|approved|accepted|rejected|prefers|preferred|chose|picked|wants)\b"
    r"[^.!?]{0,60}\b(?:the|this|that)\s+(?:(?:first|second|third|last|latter|former|previous|above)\s+)?"
    r"(?:option|draft|version|one|approach|suggestion|response|answer|paragraph|reply|summary|idea)\b"
    r"|(?:the\s+)?user\s+(?:is|was)\s+(?:currently\s+|now\s+|just\s+|still\s+)?(?:looking at|debugging|asking|"
    r"waiting|trying|running|reading|reviewing|checking|testing|editing|fixing|typing|viewing|wondering|"
    r"in a (?:meeting|call))\b"
    r"|(?:this|the)\s+(?:conversation|chat|session)\s+(?:is|was|covered|focused)\b"
    r"|something about\b|the thing (?:we|you|i)\b)",
    re.IGNORECASE,
)
_ASSISTANT_GUESS = re.compile(
    r"^\W*(?:(?:the\s+)?user\s+(?:seems|appears|might|may|is probably|is likely|probably|likely|sounds|looks|"
    r"could be|must be)\b|it\s+(?:seems|sounds|looks)\s+like\s+(?:the\s+)?user\b|"
    r"(?:the\s+)?user\s+is\s+(?:interested|curious|frustrated|confused|happy|unhappy|worried|unsure)\b|"
    r"(?:the\s+)?user(?:'s|’s)?\b[^.!?]{0,80}\b(?:appears? to|seems? to|is probably|are probably|probably|"
    r"presumably|apparently|is likely|are likely)\b)",
    re.IGNORECASE,
)
_PASSING_STATE = re.compile(
    r"\b(?:right now|at the moment|at this moment|for the moment|just now|today|tonight|tomorrow|yesterday|"
    r"this (?:morning|afternoon|evening)|in a (?:minute|sec|second|bit|moment)|later today|earlier today|"
    r"brb|aujourd'hui|ce soir|demain|hoje|amanh[ãa]|neste momento|en ce moment|en train de|"
    r"this week|in (?:an?|\d+|ten|five|twenty|thirty|a few|a couple of) (?:hours?|minutes?|mins?)|"
    r"in the next (?:\d+|few|couple of|ten|twenty|thirty) (?:hours?|minutes?|mins?)|until \d{1,2}(?::\d{2})?(?:\s?[ap]m)?)\b"
    r"|\b(?:is|are) (?:compiling|loading|downloading|uploading|installing|rendering|deploying|running)\b"
    r"|^\W*(?:running|trying|compiling|testing|checking|waiting|reading|looking)\b"
    r"|\b\d{1,3}\s?% (?:complete|done|finished)\b|\bis at \d{1,3}\s?%"
    r"|^\W*(?:i'm|i am|im|i feel|feeling)\s+(?:so\s+|really\s+|very\s+|a bit\s+|pretty\s+)?"
    r"(?:tired|hungry|busy|exhausted|sick|bored|confused|stuck|back|here|ready|done|late|sleepy|stressed|"
    r"annoyed|frustrated|swamped|distracted|lost)\b",
    re.IGNORECASE,
)
_ONE_OFF = re.compile(
    r"\b(?:for now|this time|just this once|just once|(?:for|in|on) this (?:run|task|session|pr|commit|branch|"
    r"file|one|call|draft|version|test|step|handout|slide|doc|document|email|paragraph|page|section|chart|"
    r"figure|table|sheet|presentation|deck|post|message|reply|report|essay|letter)|until i (?:say|tell)|not yet|"
    r"scratch that|ignore that|forget (?:that|it)|real quick|one sec|hold on|hang on|"
    r"try (?:that |it |this )?again|once more)\b"
    r"|^\W*please\s+(?:fix|make|rewrite|shorten|translate|summari[sz]e|explain|show|give|open|close|send|run|"
    r"check|redo|undo|retry|rename|delete|remove|add|update|change|write|create)\b"
    r"|\byet\s*[.!]?\s*$"
    r"|^\W*(?:let'?s|let me|lemme)\b"
    r"|^\W*(?:please\s+)?(?:can you\s+|could you\s+)?(?:make|fix|rewrite|shorten|translate|summari[sz]e|explain|"
    r"show|give|open|close|send|run|try|check|look at|redo|undo|retry|rename|delete|remove)\s+"
    r"(?:me\s+)?(?:this|that|it|these|those|the (?:above|last|previous|same))\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

_REMARK_REASON = (
    "Reads like a passing remark, not a lasting fact, so it was not saved. "
    "Ask me to remember it if you want it kept."
)
_REASONS.update({
    "question": "A question, not a fact, so nothing was saved.",
    "acknowledgement": _REMARK_REASON,
    "about_the_chat": "Describes this conversation, not a lasting fact about you or your work, so it was not saved.",
    "assistant_guess": "An assistant's guess about you, not something you said, so it was not saved.",
    "passing_state": _REMARK_REASON,
    "one_off": _REMARK_REASON,
})
REMARK_SHAPES = frozenset({"question", "acknowledgement", "about_the_chat", "assistant_guess", "passing_state", "one_off"})


def remark(content: str) -> str | None:
    """The name of the passing-remark shape `content` has, or None when it reads as a fact.

    Like classify(), only the shape name leaves this function. Unlike classify(), None is
    the answer for anything it does not recognise: this is a filter for remarks a pattern
    can see, not a judge of what matters.
    """

    text = " ".join(content.split())
    words = len(_WORD.findall(text))
    if _QUESTION.search(text) and not _TAG_QUESTION.search(text):
        return "question"
    if _ASSISTANT_GUESS.search(text):
        return "assistant_guess"
    if _ABOUT_THE_CHAT.search(text):
        return "about_the_chat"
    standing = bool(_STANDING.search(text))
    if not standing and (
        (words <= ACKNOWLEDGEMENT_MAX_WORDS and _ACKNOWLEDGEMENT.search(text))
        or (words <= 8 and _NEVER_MIND.search(text))
    ):
        return "acknowledgement"
    if standing:
        return None
    if _ONE_OFF.search(text):
        return "one_off"
    if _PASSING_STATE.search(text):
        return "passing_state"
    return None

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

    Not enforced here: whether a fact is about another person. No pattern can decide
    that -- "met Jean Tremblay, director at a bank, at Place Ville Marie" contains no
    email, phone or card. A reviewer raised it, and the product owner chose to narrow the
    promise rather than add a detector that would also skip useful facts about the
    user's own colleagues and family. The assistant is still instructed not to submit
    such facts, and the Privacy Policy (since 0.3) says plainly that this module does not
    enforce it. If this module ever starts enforcing it, change the policy too.
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
    shape = remark(content)
    if shape is not None:
        return (shape, reason_for(shape))
    return None
