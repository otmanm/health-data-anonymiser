"""Deterministic, checksum-validated recognizers for EU / Spanish identifiers.

NLM Scrubber is US-English / HIPAA-centric and does not understand Spanish or
EU-format identifiers. This module adds a small, high-precision layer of
recognizers that verify control digits/letters, so false positives are
near-zero. Pure-logic and stdlib-only — no tkinter, no third-party deps — so it
is trivially headless-testable.

Each ``find_*`` function returns a list of ``(start, end, matched_text)`` spans.
``apply_validators`` rewrites text, replacing validated spans with ``**TOKEN**``
placeholders that match the NLM Scrubber output format, so downstream diff and
report code picks them up for free.
"""

import re
from typing import Callable

# --- DNI / NIE control letter (mod-23) -------------------------------------
# The control letter is the (number mod 23)-th letter of this string.
_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
# NIE prefixes map to a leading digit before applying the DNI algorithm.
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}


def validate_dni(s: str) -> bool:
    """8 digits followed by a mod-23 control letter, e.g. ``12345678Z``."""
    s = s.upper().strip()
    if not re.fullmatch(r"\d{8}[A-Z]", s):
        return False
    number, letter = s[:8], s[8]
    return _DNI_LETTERS[int(number) % 23] == letter


def validate_nie(s: str) -> bool:
    """X/Y/Z prefix + 7 digits + control letter, e.g. ``X1234567L``."""
    s = s.upper().strip()
    if not re.fullmatch(r"[XYZ]\d{7}[A-Z]", s):
        return False
    number = _NIE_PREFIX[s[0]] + s[1:8]
    return _DNI_LETTERS[int(number) % 23] == s[8]


# --- NIF / CIF (legal-entity tax ID) ---------------------------------------
_CIF_ORG_LETTERS = "ABCDEFGHJNPQRSUVW"
# For CIFs whose control char is a letter, this string maps the digit to it.
_CIF_CONTROL_LETTERS = "JABCDEFGHI"


def validate_nif_cif(s: str) -> bool:
    """Validate a Spanish company tax ID (CIF), e.g. ``A58818501``.

    Format: an org-type letter, 7 digits, and a control char that is either a
    digit or a letter depending on the org type.
    """
    s = s.upper().strip()
    if not re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", s):
        return False
    org, digits, control = s[0], s[1:8], s[8]
    total = 0
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == 0:  # odd position (1-indexed): double and sum digits
            n *= 2
            n = n // 10 + n % 10
        total += n
    check_digit = (10 - (total % 10)) % 10
    check_letter = _CIF_CONTROL_LETTERS[check_digit]
    # Some org types require a digit control, some a letter; P/Q/S/N/W and a few
    # accept either. We accept if it matches the computed digit OR letter.
    if control.isdigit():
        return int(control) == check_digit
    return control == check_letter


# --- IBAN (pan-EU, mod-97) -------------------------------------------------
def validate_iban(s: str) -> bool:
    """Validate any IBAN via the ISO 7064 mod-97 check (==1).

    Whitespace and hyphens (common display separators for grouped IBANs) are
    stripped before validation; IBANs never legitimately contain either.
    """
    s = re.sub(r"[\s\-]", "", s.upper())
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    # Move the four initial characters to the end of the string.
    rearranged = s[4:] + s[:4]
    # Replace each letter with two digits: A=10, B=11, ..., Z=35.
    digits = "".join(
        str(int(ch, 36)) if ch.isalpha() else ch for ch in rearranged
    )
    return int(digits) % 97 == 1


# --- Spanish phone numbers -------------------------------------------------
def validate_es_phone(s: str) -> bool:
    """Spanish phone: optional +34/0034, then 9 digits starting 6/7/8/9."""
    digits = re.sub(r"[\s.\-]", "", s)
    digits = re.sub(r"^(\+34|0034)", "", digits)
    return bool(re.fullmatch(r"[6789]\d{8}", digits))


# --- Spanish social-security number ----------------------------------------
def validate_es_ssn(s: str) -> bool:
    """Spanish SSN: 2-digit province + 8-digit number + 2-digit control,
    validated as ``control == (province*10^7 + number) mod 97``."""
    digits = re.sub(r"[\s/\-]", "", s)
    if not re.fullmatch(r"\d{12}", digits):
        return False
    province, number, control = digits[:2], digits[2:10], digits[10:]
    base = int(province + number)
    return base % 97 == int(control)


# --- Finders: locate candidates, keep only checksum-valid ones -------------
def _make_finder(pattern: str, validator: Callable[[str], bool]) -> Callable[[str], list]:
    compiled = re.compile(pattern)

    def finder(text: str) -> list:
        spans = []
        for m in compiled.finditer(text):
            if validator(m.group(0)):
                spans.append((m.start(), m.end(), m.group(0)))
        return spans

    return finder


# Word-boundary-anchored candidate patterns. The checksum gate inside each
# finder rejects coincidental matches, so the patterns can be permissive.
find_dni = _make_finder(r"\b\d{8}[A-Za-z]\b", validate_dni)
find_nie = _make_finder(r"\b[XYZxyz]\d{7}[A-Za-z]\b", validate_nie)
find_nif_cif = _make_finder(r"\b[A-HJNPQRSUVWa-hjnpqrsuvw]\d{7}[0-9A-Ja-j]\b", validate_nif_cif)


# IBAN needs a bespoke finder: real IBANs are usually written in space-separated
# 4-char groups ("ES91 2100 0418 4502 0005 1332"), but a permissive regex that
# allows spaces is greedy and would swallow the following word, making the mod-97
# check fail and the IBAN get missed. So we grab a permissive candidate, then
# right-trim trailing tokens until validate_iban passes (or the candidate is too
# short), reporting a span that covers exactly the real IBAN.
_IBAN_CANDIDATE = re.compile(r"\b[A-Za-z]{2}\d{2}(?:[ \-]?[A-Za-z0-9]){11,40}")


def find_iban(text: str) -> list:
    spans = []
    for m in _IBAN_CANDIDATE.finditer(text):
        candidate = m.group(0)
        # Drop trailing separators, then whole space/dash-delimited tokens,
        # re-validating after each trim. Shortest valid IBAN is 15 chars.
        while candidate:
            trimmed = candidate.rstrip(" -")
            if validate_iban(trimmed):
                spans.append((m.start(), m.start() + len(trimmed), trimmed))
                break
            cut = max(trimmed.rfind(" "), trimmed.rfind("-"))
            if cut == -1:
                break
            candidate = trimmed[:cut]
    return spans


# Leading separator lives inside the prefix group so a bare number doesn't
# consume the whitespace that precedes it (e.g. "tel 612..." keeps its space).
find_es_phone = _make_finder(r"(?:(?:\+34|0034)[\s.\-]?)?[6789]\d{2}[\s.\-]?\d{3}[\s.\-]?\d{3}\b", validate_es_phone)
find_es_ssn = _make_finder(r"\b\d{2}[\s/\-]?\d{8}[\s/\-]?\d{2}\b", validate_es_ssn)


# Registry mirrors PHI_DETECTORS shape: (key, label, default_enabled, finder).
EU_VALIDATORS: list[tuple[str, str, bool, Callable[[str], list]]] = [
    ("es_dni", "Spanish DNI", True, find_dni),
    ("es_nie", "Spanish NIE", True, find_nie),
    ("es_nif", "Spanish NIF/CIF", True, find_nif_cif),
    ("iban", "IBAN (EU)", True, find_iban),
    ("es_phone", "Spanish phone", True, find_es_phone),
    ("es_ssn", "Spanish SSN", True, find_es_ssn),
]

# Placeholder token emitted per validator key (matches **TOKEN** scrubber style).
_TOKEN_BY_KEY = {
    "es_dni": "ES_DNI",
    "es_nie": "ES_NIE",
    "es_nif": "ES_NIF",
    "iban": "IBAN",
    "es_phone": "ES_PHONE",
    "es_ssn": "ES_SSN",
}

# Public set of the placeholder tokens this module emits. Importers (e.g. the GUI
# report) should use this rather than re-listing the tokens, so the two never drift.
EU_TOKENS = frozenset(_TOKEN_BY_KEY.values())


def apply_validators(text: str, enabled: set) -> tuple:
    """Replace validated EU/Spain identifiers with ``**TOKEN**`` placeholders.

    *enabled* is a set of validator keys (from EU_VALIDATORS) to run. Spans are
    collected from all enabled finders, overlaps are dropped (first match by
    start offset wins), and replacements are applied right-to-left so earlier
    offsets stay valid. Returns ``(new_text, counts)`` where *counts* maps each
    validator key to the number of replacements made.
    """
    counts: dict = {key: 0 for key, _, _, _ in EU_VALIDATORS}
    spans: list = []  # (start, end, key)
    for key, _, _, finder in EU_VALIDATORS:
        if key not in enabled:
            continue
        for start, end, _matched in finder(text):
            spans.append((start, end, key))

    # Resolve overlaps: sort by start, then keep a span only if it doesn't
    # overlap one we've already accepted.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    accepted: list = []
    last_end = -1
    for start, end, key in spans:
        if start >= last_end:
            accepted.append((start, end, key))
            last_end = end

    # Apply right-to-left.
    for start, end, key in sorted(accepted, key=lambda s: s[0], reverse=True):
        text = text[:start] + f"**{_TOKEN_BY_KEY[key]}**" + text[end:]
        counts[key] += 1

    return text, counts
