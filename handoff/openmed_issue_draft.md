## Proposal: Spanish CIF and NAF validators in `pii_i18n`

Hi, I contributed the date-shifting fixes in #604, #605 and #616. Before I write any code, I'd like to check whether this is wanted.

### Gap

`openmed/core/pii_i18n.py` already has Spanish DNI/NIE validators, an ES phone pattern and `validate_iban`. I could not find validators for two other Spanish identifiers that show up in clinical and administrative text:

| Identifier | Format | Check |
|---|---|---|
| **CIF** (legal-entity tax ID, e.g. hospital or insurer) | org letter + 7 digits + control char | Luhn-style weighted digit sum. The control is a digit for org letters `A B E H`, a letter for `N P Q R S W`, and either for the rest. |
| **NAF / Nº Seguridad Social** | 2-digit province + 8 digits + 2-digit control | `(province + number) mod 97 == control`. Province `01`-`53` or `66`, serial non-zero. |

Both are checksum-gated, so false positives are low.

### Reference implementation

I wrote stdlib-only versions with tests in a small prototype: https://github.com/otmanm/health-data-anonymiser (`validators.py`, `validate_nif_cif` and `validate_es_ssn`). I'm happy for you to reuse the logic or the test vectors under whatever licence fits.

### Caveats

- I validated the NAF rule against my own reading of the algorithm, not against an official test set. A maintainer or reviewer who knows the official spec should check it.
- The CIF org-letter rules (digit-only vs letter-only) follow the Agencia Tributaria description as I understand it. Edge categories need review.
- I haven't run this against real Spanish clinical text, so I can't claim anything about recall.

### Questions

1. Is a PR for these two validators in scope, and would you prefer them in `pii_i18n.py` or in a separate module?
2. Should they ship under the existing Spanish pattern group, or behind a flag?
3. Do you have a preferred source for test vectors?

I'll wait for a maintainer's go-ahead before opening a PR, since #1607 showed that unsolicited PRs get closed.
