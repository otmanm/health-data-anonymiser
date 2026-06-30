# Health Data Anonymiser

Offline prototype for cleaning sensitive health notes before they leave the machine.

This repo is my first public artifact in healthcare data privacy: a local macOS prototype for removing protected health information from clinical notes before the text reaches an external model, SaaS tool, or shared workflow.

It is not a medical device, not a compliance guarantee, and not a replacement for expert privacy review.

## Project intent

The original idea was broader than a single local tool.

Health data does not look the same everywhere. Forms, identifiers, dates, languages, and privacy rules vary by country and region. I wanted to explore a health data anonymiser that could eventually reason across the contexts most relevant to my own work and life: Europe, the United States, Belgium, Spain, Morocco, and adjacent multilingual workflows.

That larger ambition is not fully implemented in this repo. The public prototype is the first step: clean sensitive health text locally, prove the data minimisation principle, and avoid sending raw clinical notes into external systems by default. The **EU/Spain identifier validators** described below (DNI, NIE, NIF/CIF, IBAN, Spanish phone/SSN) are the first concrete step past the US-centric HIPAA baseline.

## Current status

This project is now part of a broader healthcare data privacy track.

After building this prototype, I began contributing to [OpenMed](https://github.com/maziyarpanahi/openmed), a larger open-source local-first healthcare project. My contributions there focus on de-identification reliability, date handling, test coverage, and privacy edge cases.

## Relationship to OpenMed

This repo is a small standalone prototype.

OpenMed is the larger ecosystem where I now contribute to production-grade healthcare tooling. My work there includes fixes and issue analysis around medical date de-identification, interval preservation, deterministic behavior, and CI coverage.

I did not build OpenMed and I do not own it. I built this prototype first, then found a stronger open-source project working on the same problem and started contributing where the work could matter more.

## OpenMed contribution direction

My contribution direction is deliberately boring:

- date handling
- format preservation
- deterministic behavior
- CI coverage
- privacy edge cases

These are small-looking problems with large privacy implications: in clinical text, dates can identify people, break timelines, or create misleading de-identified records.

---

## The prototype: NLM Scrubber wrapper

A native-feeling macOS GUI wrapper around **NLM Scrubber** — the NIH's
HIPAA Safe Harbor de-identification tool. Drag in clinical notes, get
anonymized text out, then safely paste it into ChatGPT/Claude/etc.

**100 % local.**  Notes never leave your Mac. The only network traffic is
the one-time download of the NLM Scrubber binary from `lhncbc.nlm.nih.gov`.

### What it does

- Accepts **`.txt`**, **`.md`**, **`.pdf`**, and **`.docx`** input — single
  files or whole folders.
- Runs NLM Scrubber to remove or replace 18+ categories of PHI (names,
  dates, IDs, locations, contact info, ages over 89, etc.).
- Shows a **side-by-side diff** of original vs. anonymized text with
  changes highlighted, plus a **summary report** of how many tokens were
  redacted by category.
- **"Copy anonymized to clipboard"** button — paste straight into your AI
  chat with one click.
- Lets you toggle individual PHI detectors (e.g. keep cities, redact only
  patient names) right in the UI.
- **EU / Spain identifiers** — a second pass of deterministic,
  checksum-validated recognizers (DNI, NIE, NIF/CIF, IBAN, Spanish phone,
  Spanish SSN) that NLM Scrubber's US-centric rules miss. Because each
  match is verified against its control digit/letter, false positives are
  near-zero. Toggleable in the UI; no new dependencies.
- Optional **surrogate replacement**: instead of `**NAME**` placeholders,
  PHI is swapped for plausible fakes (better for human-readable output).
- Auto-downloads the NLM Scrubber binary on first run; SHA-256 checksum
  verification supported (set `SCRUBBER_SHA256` in the script).

### What's required

- macOS (or Linux — the same GUI runs anywhere Tk does).
- Python 3.9+. macOS ships with one (`/usr/bin/python3`), or install from
  python.org.
- **For PDF input only:** `pdftotext` (poppler). Install once:
  `brew install poppler`. DOCX needs nothing — it's parsed with stdlib.
- **For scanned PDFs (no text layer):** the app falls back to OCR via
  `pdftoppm` + `tesseract`. Install once:
  `brew install poppler tesseract`.
- **For macOS:** NLM publishes Linux/Windows binaries; if no native macOS
  binary exists in their distribution, you'll need Docker or a Linux VM
  to actually execute the scrubber. The app detects this and tells you.

No `pip install` is required to run the script directly. Optional
`py2app` is only needed to build a double-clickable `.app` bundle.

### Running it

Three ways, easiest first:

1. **Double-click `run.command`** in Finder. (First time: right-click →
   Open to bypass Gatekeeper.)
2. **Terminal:** `python3 nlm_scrubber_mac_gui.py`
3. **Build a real `.app`:** `./build_app.sh` → `dist/NLM Scrubber.app`
   (drag into Applications). The .app registers as a handler for
   txt/md/pdf/docx so you can drag files onto its Dock icon.

### Tests

```
python3 -m unittest discover -p "test_*.py" -v
```

96 unit tests covering the pure-logic functions: file gathering, DOCX
extraction, PDF OCR fallback, scrubber URL discovery, OS-aware binary
selection, config generation with detector overrides and custom
dictionaries, settings persistence, partial-output cleanup, checksum
verification, and the EU/Spain identifier validators (DNI/NIE/NIF/IBAN/
phone/SSN checksum logic, including grouped/spaced IBAN recovery). tkinter
is stubbed at the module level so tests run headless in CI.

GitHub Actions runs the suite on Ubuntu and macOS across Python 3.9,
3.11, and 3.12 (see `.github/workflows/tests.yml`).

### Project layout

```
nlm_scrubber_mac_gui.py   the GUI and orchestration logic
validators.py             EU/Spain identifier recognizers (checksum-validated)
test_nlm_scrubber.py      unit tests for the GUI logic (headless)
test_validators.py        unit tests for the validators
run.command               double-clickable launcher (no install)
setup.py                  py2app config for the .app bundle
build_app.sh              one-shot .app build script
```

### Limitations / honest gaps

This tool is a prototype. Do not use it as your only privacy control for
real patient data. Always review outputs manually. De-identification
reduces risk, but it does not eliminate all re-identification risk.

- **macOS native binary:** NLM Scrubber's official distribution may only
  ship Linux/Windows binaries. The app detects "Exec format" errors and
  surfaces them clearly, but on Apple Silicon you'll still need Docker
  or a Linux VM to run the scrubber itself. Wrap the binary in Docker
  Desktop's `linux/amd64` image as a workaround.
- **PDF text extraction quality** depends on `pdftotext` first and
  falls back to OCR (Tesseract) for scanned PDFs. OCR accuracy is
  best for clean 300+ DPI scans; expect noise for low-quality faxes
  or unusual fonts.
- **DOCX extraction** uses the document body only (no headers, footers,
  comments, or tracked changes).
- The redaction report only counts `**TOKEN**` markers. When surrogate
  replacement is enabled the report will be empty by design — use the
  Preview tab's diff highlighting instead.

## License

See [LICENSE](LICENSE).
