"""Unit tests for validators.py — deterministic EU/Spain identifier recognizers.

These run fully headless (no tkinter, no network). The point of the feature is
the checksum gate, so the tests assert that valid control digits/letters are
accepted and near-miss invalid ones are rejected.

Run with:  python3 -m unittest test_validators -v
"""

import unittest

from validators import (
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


if __name__ == "__main__":
    unittest.main()
