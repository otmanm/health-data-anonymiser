"""Unit tests for validators.py — deterministic EU/Spain identifier recognizers.

These run fully headless (no tkinter, no network). The point of the feature is
the checksum gate, so the tests assert that valid control digits/letters are
accepted and near-miss invalid ones are rejected.

Run with:  python3 -m unittest test_validators -v
"""

import unittest

from validators import (
    EU_TOKENS,
    EU_VALIDATORS,
    apply_validators,
    find_dni,
    find_iban,
    validate_dni,
    validate_es_phone,
    validate_es_ssn,
    validate_iban,
    validate_nie,
    validate_nif_cif,
)


class TestDni(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(validate_dni("12345678Z"))

    def test_lowercase_letter_accepted(self):
        self.assertTrue(validate_dni("12345678z"))

    def test_wrong_control_letter(self):
        self.assertFalse(validate_dni("12345678A"))

    def test_too_short(self):
        self.assertFalse(validate_dni("1234567Z"))

    def test_non_numeric(self):
        self.assertFalse(validate_dni("1234567XZ"))


class TestNie(unittest.TestCase):
    def test_valid(self):
        # X1234567 -> 01234567 mod 23 = 10 -> 'L'
        self.assertTrue(validate_nie("X1234567L"))

    def test_wrong_control_letter(self):
        self.assertFalse(validate_nie("X1234567A"))

    def test_bad_prefix(self):
        self.assertFalse(validate_nie("A1234567L"))


class TestNifCif(unittest.TestCase):
    def test_valid_letter_control(self):
        # A58818501 is a well-known valid CIF example.
        self.assertTrue(validate_nif_cif("A58818501"))

    def test_wrong_control(self):
        self.assertFalse(validate_nif_cif("A58818500"))

    def test_bad_format(self):
        self.assertFalse(validate_nif_cif("12345678Z"))


class TestIban(unittest.TestCase):
    def test_valid_spanish(self):
        self.assertTrue(validate_iban("ES9121000418450200051332"))

    def test_valid_with_spaces(self):
        self.assertTrue(validate_iban("ES91 2100 0418 4502 0005 1332"))

    def test_one_digit_flipped(self):
        self.assertFalse(validate_iban("ES9121000418450200051333"))

    def test_bad_format(self):
        self.assertFalse(validate_iban("1234567890"))

    def test_finder_grouped_iban(self):
        # Real IBANs are usually written in 4-char groups. The finder must catch
        # the spaced form and report a span covering exactly the IBAN, not the
        # trailing word. This is the regression guard for the original gap where
        # find_iban's regex allowed no whitespace.
        text = "Pago a ES91 2100 0418 4502 0005 1332 hoy"
        spans = find_iban(text)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0][2], "ES91 2100 0418 4502 0005 1332")
        # The matched span ends right before " hoy".
        self.assertEqual(text[spans[0][0]:spans[0][1]], "ES91 2100 0418 4502 0005 1332")

    def test_finder_dash_grouped_iban(self):
        spans = find_iban("IBAN: ES91-2100-0418-4502-0005-1332.")
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0][2], "ES91-2100-0418-4502-0005-1332")

    def test_finder_compact_iban_still_found(self):
        spans = find_iban("Transferir a ES9121000418450200051332 hoy")
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0][2], "ES9121000418450200051332")

    def test_finder_grouped_one_digit_flipped_rejected(self):
        # The mod-97 gate must still reject a grouped near-miss.
        self.assertEqual(find_iban("Pago a ES91 2100 0418 4502 0005 1333 hoy"), [])

    def test_apply_replaces_grouped_iban_as_single_token(self):
        text = "Pago a ES91 2100 0418 4502 0005 1332 hoy"
        out, counts = apply_validators(text, {"iban"})
        self.assertEqual(out, "Pago a **IBAN** hoy")
        self.assertEqual(counts["iban"], 1)


class TestEsPhone(unittest.TestCase):
    def test_valid_plain(self):
        self.assertTrue(validate_es_phone("612345678"))

    def test_valid_with_prefix(self):
        self.assertTrue(validate_es_phone("+34 612 345 678"))

    def test_wrong_leading_digit(self):
        self.assertFalse(validate_es_phone("512345678"))

    def test_too_short(self):
        self.assertFalse(validate_es_phone("61234567"))


class TestEsSsn(unittest.TestCase):
    def test_valid(self):
        # Construct a control that satisfies base % 97 == control.
        province, number = "28", "12345678"
        base = int(province + number)
        control = f"{base % 97:02d}"
        self.assertTrue(validate_es_ssn(province + number + control))

    def test_wrong_control(self):
        province, number = "28", "12345678"
        base = int(province + number)
        bad = f"{(base % 97 + 1) % 97:02d}"
        self.assertFalse(validate_es_ssn(province + number + bad))


class TestFinders(unittest.TestCase):
    def test_find_dni_in_sentence(self):
        text = "Paciente con DNI 12345678Z ingresado."
        spans = find_dni(text)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0][2], "12345678Z")

    def test_find_dni_ignores_invalid(self):
        text = "Numero aleatorio 12345678A sin sentido."
        self.assertEqual(find_dni(text), [])

    def test_find_iban_in_sentence(self):
        text = "Transferir a ES9121000418450200051332 hoy."
        spans = find_iban(text)
        self.assertEqual(len(spans), 1)


class TestApplyValidators(unittest.TestCase):
    def _all_keys(self) -> set:
        return {key for key, _, _, _ in EU_VALIDATORS}

    def test_replaces_validated_spans(self):
        text = "DNI 12345678Z, IBAN ES9121000418450200051332, tel 612345678"
        out, counts = apply_validators(text, self._all_keys())
        self.assertIn("**ES_DNI**", out)
        self.assertIn("**IBAN**", out)
        self.assertIn("**ES_PHONE**", out)
        self.assertEqual(counts["es_dni"], 1)
        self.assertEqual(counts["iban"], 1)
        self.assertEqual(counts["es_phone"], 1)

    def test_leaves_surrounding_text_intact(self):
        text = "Hola 12345678Z adios"
        out, _ = apply_validators(text, {"es_dni"})
        self.assertEqual(out, "Hola **ES_DNI** adios")

    def test_disabled_validator_not_applied(self):
        text = "DNI 12345678Z"
        out, counts = apply_validators(text, set())  # nothing enabled
        self.assertEqual(out, text)
        self.assertEqual(counts["es_dni"], 0)

    def test_no_false_positive_on_plain_text(self):
        text = "The quick brown fox jumps over the lazy dog."
        out, counts = apply_validators(text, self._all_keys())
        self.assertEqual(out, text)
        self.assertEqual(sum(counts.values()), 0)

    def test_multiple_same_type(self):
        text = "DNI 12345678Z y otro 11111111H"
        out, counts = apply_validators(text, {"es_dni"})
        self.assertEqual(counts["es_dni"], 2)
        self.assertNotIn("12345678Z", out)
        self.assertNotIn("11111111H", out)

    def test_multiline_all_caught(self):
        text = "DNI 12345678Z\nIBAN ES9121000418450200051332\ntel 612345678"
        out, counts = apply_validators(text, self._all_keys())
        self.assertEqual(out, "DNI **ES_DNI**\nIBAN **IBAN**\ntel **ES_PHONE**")
        self.assertEqual(counts["es_dni"], 1)
        self.assertEqual(counts["iban"], 1)
        self.assertEqual(counts["es_phone"], 1)

    def test_distinct_types_no_collision(self):
        # A valid DNI, NIE, and NIF/CIF in one string must each map to their own
        # token — the finders must not poach each other's matches.
        text = "DNI 12345678Z NIE X1234567L CIF A58818501"
        out, counts = apply_validators(text, {"es_dni", "es_nie", "es_nif"})
        self.assertEqual(out, "DNI **ES_DNI** NIE **ES_NIE** CIF **ES_NIF**")
        self.assertEqual(counts["es_dni"], 1)
        self.assertEqual(counts["es_nie"], 1)
        self.assertEqual(counts["es_nif"], 1)

    def test_overlap_resolution_single_replacement(self):
        # Two enabled finders could each match within the same region; overlap
        # resolution must keep one span, never double-wrap.
        text = "IBAN ES9121000418450200051332 fin"
        out, counts = apply_validators(text, self._all_keys())
        self.assertEqual(out.count("**IBAN**"), 1)
        self.assertNotIn("****", out)  # no nested/double replacement
        self.assertEqual(sum(counts.values()), 1)


class TestEuTokens(unittest.TestCase):
    def test_tokens_match_registry(self):
        # EU_TOKENS must contain exactly one token per registered validator, so the
        # GUI report router (which imports EU_TOKENS) can never drift from the
        # tokens apply_validators actually emits.
        self.assertEqual(len(EU_TOKENS), len(EU_VALIDATORS))
        for token in ("ES_DNI", "ES_NIE", "ES_NIF", "IBAN", "ES_PHONE", "ES_SSN"):
            self.assertIn(token, EU_TOKENS)


if __name__ == "__main__":
    unittest.main()
