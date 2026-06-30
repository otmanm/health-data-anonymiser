# Run with: python3 nlm_scrubber_mac_gui.py
# Requires Python 3.9+ (macOS default), no extra installs needed.
"""
Native-feeling macOS GUI wrapper for NLM Scrubber (Linux CLI version).
"""

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional
import zipfile
from urllib import request
from urllib.error import URLError, HTTPError

from validators import EU_VALIDATORS, apply_validators

APP_TITLE = "NLM Scrubber (macOS GUI Wrapper)"
DEFAULT_SCRUBBER_URL = "https://lhncbc.nlm.nih.gov/scrubber/files/scrubber.19.0403L.zip"
# SHA-256 digest of the expected zip. Set to None to skip verification.
# Update this whenever DEFAULT_SCRUBBER_URL changes.
SCRUBBER_SHA256: Optional[str] = None
SCRUBBER_DIR = os.path.expanduser("~/.nlm_scrubber")
SCRUBBER_ZIP = os.path.join(SCRUBBER_DIR, "scrubber.zip")
CONFIG_FILE = os.path.join(SCRUBBER_DIR, "config.txt")
SETTINGS_FILE = os.path.join(SCRUBBER_DIR, "settings.json")
USER_DICT_FILE = os.path.join(SCRUBBER_DIR, "user_dict.txt")

SUPPORTED_EXTS = {".txt", ".md", ".pdf", ".docx"}
TEXT_EXTS = {".txt", ".md"}

# Candidate scrubber binary filenames in NLM's distribution zip.
# Ordered: the platform-preferred name appears first via scrubber_binary_candidates().
_BIN_NAMES_BY_SYSTEM: dict[str, tuple[str, ...]] = {
    "Darwin": ("scrubber.osx", "scrubber.mac", "scrubber.macos"),
    "Linux": ("scrubber.lnx", "scrubber.linux"),
    "Windows": ("scrubber.win.exe", "scrubber.exe"),
}
_ALL_BIN_NAMES: tuple[str, ...] = tuple(
    name for names in _BIN_NAMES_BY_SYSTEM.values() for name in names
)


def scrubber_binary_candidates() -> tuple[str, ...]:
    """Return candidate binary filenames, OS-preferred first, then all others as fallback."""
    preferred = _BIN_NAMES_BY_SYSTEM.get(platform.system(), ())
    return preferred + tuple(n for n in _ALL_BIN_NAMES if n not in preferred)


def scrubber_bin_path() -> str:
    """Path to the installed scrubber binary for the current OS."""
    return os.path.join(SCRUBBER_DIR, scrubber_binary_candidates()[0])


# Kept for backwards compatibility with existing imports / tests.
SCRUBBER_BIN = scrubber_bin_path()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def is_supported_file(path: str) -> bool:
    _, ext = os.path.splitext(path.lower())
    return ext in SUPPORTED_EXTS


def validate_path(path: str) -> bool:
    if not path:
        return False
    return os.path.exists(path)


def open_in_finder(path: str) -> None:
    try:
        subprocess.run(["open", path], check=False)
    except Exception:
        return


def verify_checksum(path: str, expected_sha256: str) -> bool:
    """Return True if the SHA-256 digest of *path* matches *expected_sha256*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected_sha256.lower()


def get_latest_scrubber_url(log_cb: Callable[[str], None]) -> str:
    try:
        with request.urlopen("https://lhncbc.nlm.nih.gov/scrubber/") as response:
            html = response.read().decode("utf-8", errors="ignore")
        # Use single backslashes in raw strings: \s = whitespace, \. = literal dot.
        # The original code had doubled backslashes (\\.) which matched a literal
        # backslash followed by any character — a bug that prevented URL detection.
        # Pattern mirrors the real filename format: scrubber.MAJOR.BUILDL.zip
        urls = re.findall(r'https?://[^"\s]*scrubber\.\d+\.\d+L\.zip', html)
        if not urls:
            return DEFAULT_SCRUBBER_URL

        def version_key(url: str) -> tuple[int, int]:
            # URL format: scrubber.MAJOR.BUILDL.zip  e.g. scrubber.19.0403L.zip
            match = re.search(r'scrubber\.(\d+)\.(\d+)L\.zip', url)
            return (int(match.group(1)), int(match.group(2))) if match else (0, 0)

        latest = max(urls, key=version_key)
        if latest != DEFAULT_SCRUBBER_URL:
            log_cb(f"Found newer scrubber package: {latest}")
        return latest
    except Exception as err:
        log_cb(f"Could not check for newer scrubber packages: {err}")
        return DEFAULT_SCRUBBER_URL


def find_installed_binary() -> Optional[str]:
    """Return the path of an already-installed scrubber binary, OS-preferred."""
    for name in scrubber_binary_candidates():
        candidate = os.path.join(SCRUBBER_DIR, name)
        if os.path.exists(candidate):
            return candidate
    return None


def run_with_docker(
    binary: str,
    config_file: str,
    input_dir: str,
    output_dir: str,
    log_cb: Callable[[str], None],
    cancel_event: threading.Event,
) -> Optional[subprocess.Popen]:
    """Return a Popen running the scrubber inside Docker, or None on failure.

    Mounts SCRUBBER_DIR as /scrubber, input_dir as /input (ro), and
    output_dir as /output inside an ubuntu:22.04 container.  The config
    file is rewritten with these container-internal paths before launch.
    """
    try:
        check = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        if check.returncode != 0:
            log_cb("Docker is not running. Start Docker Desktop and retry.")
            return None
    except FileNotFoundError:
        log_cb("Docker not found. Install Docker Desktop from docker.com.")
        return None
    except subprocess.TimeoutExpired:
        log_cb("docker info timed out — Docker may not be running.")
        return None

    # Rewrite config so paths are valid inside the container.
    docker_config = os.path.join(SCRUBBER_DIR, "config_docker.txt")
    try:
        with open(config_file, encoding="utf-8") as f:
            cfg = f.read()
        cfg = cfg.replace(f"input_dir={input_dir}", "input_dir=/input")
        cfg = cfg.replace(f"output_dir={output_dir}", "output_dir=/output")
        if "user_dictionary_file=" in cfg:
            cfg = re.sub(
                r"user_dictionary_file=.*",
                f"user_dictionary_file=/scrubber/{os.path.basename(USER_DICT_FILE)}",
                cfg,
            )
        with open(docker_config, "w", encoding="utf-8") as f:
            f.write(cfg)
    except OSError as err:
        log_cb(f"Could not write Docker config: {err}")
        return None

    bin_name = os.path.basename(binary)
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{SCRUBBER_DIR}:/scrubber",
        "-v", f"{input_dir}:/input:ro",
        "-v", f"{output_dir}:/output",
        "ubuntu:22.04",
        f"/scrubber/{bin_name}", "/scrubber/config_docker.txt",
    ]
    log_cb("Launching scrubber via Docker: " + " ".join(cmd))
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as err:
        log_cb(f"Failed to start Docker container: {err}")
        return None


def _locate_extracted_binary() -> Optional[str]:
    """Walk SCRUBBER_DIR after extraction and return a usable binary path.

    Prefers an OS-matching binary name; falls back to any known scrubber binary.
    Moves the chosen binary to SCRUBBER_DIR root for stable invocation.
    """
    preferred = scrubber_binary_candidates()
    found: dict[str, str] = {}
    for root, _, files in os.walk(SCRUBBER_DIR):
        for name in files:
            if name in _ALL_BIN_NAMES and name not in found:
                found[name] = os.path.join(root, name)
    for name in preferred:
        if name in found:
            src = found[name]
            dest = os.path.join(SCRUBBER_DIR, name)
            if src != dest:
                shutil.move(src, dest)
            return dest
    return None


def download_scrubber(
    progress_cb: Callable[[int], None],
    log_cb: Callable[[str], None],
    cancel_event: threading.Event,
) -> bool:
    ensure_dir(SCRUBBER_DIR)
    existing = find_installed_binary()
    if existing:
        return True

    url = get_latest_scrubber_url(log_cb)
    log_cb(f"Downloading NLM Scrubber from {url}...")
    try:
        with request.urlopen(url) as response:
            total_length = response.getheader("content-length")
            total_length = int(total_length) if total_length else None
            downloaded = 0
            chunk_size = 1024 * 64
            with open(SCRUBBER_ZIP, "wb") as f:
                while True:
                    if cancel_event.is_set():
                        log_cb("Download cancelled.")
                        return False
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_length:
                        progress_cb(min(30, int((downloaded / total_length) * 30)))
        log_cb("Download complete.")
    except (URLError, HTTPError) as err:
        log_cb(f"Download failed: {err}")
        # Remove the partial download so a retry starts clean.
        if os.path.exists(SCRUBBER_ZIP):
            os.remove(SCRUBBER_ZIP)
        raise

    if SCRUBBER_SHA256:
        log_cb("Verifying checksum...")
        if not verify_checksum(SCRUBBER_ZIP, SCRUBBER_SHA256):
            os.remove(SCRUBBER_ZIP)
            raise ValueError(
                "Scrubber zip checksum mismatch — the download may be corrupt or tampered with."
            )
        log_cb("Checksum verified.")

    log_cb("Extracting scrubber...")
    try:
        with zipfile.ZipFile(SCRUBBER_ZIP, "r") as zf:
            zf.extractall(SCRUBBER_DIR)
        if os.path.exists(SCRUBBER_ZIP):
            os.remove(SCRUBBER_ZIP)
    except zipfile.BadZipFile as err:
        log_cb(f"Extraction failed: {err}")
        if os.path.exists(SCRUBBER_ZIP):
            os.remove(SCRUBBER_ZIP)
        raise

    binary = _locate_extracted_binary()
    if binary:
        st = os.stat(binary)
        os.chmod(binary, st.st_mode | stat.S_IEXEC)
        # If this isn't the OS-preferred binary, warn — the binary may not run.
        preferred = scrubber_binary_candidates()[0]
        if os.path.basename(binary) != preferred:
            log_cb(
                f"Warning: the downloaded package does not contain {preferred} "
                f"(only {os.path.basename(binary)} was found). It may not run on "
                f"this platform ({platform.system()})."
            )
        log_cb(f"Scrubber ready: {os.path.basename(binary)}")
        progress_cb(30)
        return True

    log_cb(
        "Scrubber binary not found after extraction. "
        f"Expected one of: {', '.join(scrubber_binary_candidates())}."
    )
    return False


# PHI detectors exposed as checkboxes in the UI.
# (config_key, display_label, default_enabled)
PHI_DETECTORS: list[tuple[str, str, bool]] = [
    ("find_date", "Dates", True),
    ("find_patient", "Patient names", True),
    ("find_doctor", "Doctor names", True),
    ("find_hospital", "Hospitals", True),
    ("find_unique_id", "Unique IDs (MRN, SSN, ...)", True),
    ("find_phone", "Phone numbers", True),
    ("find_email", "Email addresses", True),
    ("find_url", "URLs", True),
    ("find_age", "Ages over 89", True),
    ("find_state", "US states", True),
    ("find_city", "Cities", True),
    ("find_rated_number", "Rated numbers (experimental)", False),
]

# Fixed (non-toggleable) defaults; kept here so existing imports/tests still work.
_CONFIG_DEFAULTS = [
    "input_type=txt",
    "output_type=txt",
    *[f"{key}={'yes' if default else 'no'}" for key, _, default in PHI_DETECTORS],
]


def build_config(
    input_dir: str,
    output_dir: str,
    use_surrogates: bool,
    detector_overrides: Optional[dict[str, bool]] = None,
    user_dict_path: Optional[str] = None,
) -> str:
    """Write the scrubber config file.

    *detector_overrides* lets callers (the UI) flip individual PHI detectors
    on/off. Keys must match the first column of PHI_DETECTORS; unknown keys
    are ignored. If None, the PHI_DETECTORS defaults are used.
    """
    ensure_dir(SCRUBBER_DIR)
    overrides = detector_overrides or {}
    detector_lines = [
        f"{key}={'yes' if overrides.get(key, default) else 'no'}"
        for key, _, default in PHI_DETECTORS
    ]
    surrogate_line = "use_surrogates=yes" if use_surrogates else "use_surrogates=no"
    lines = [
        f"input_dir={input_dir}",
        f"output_dir={output_dir}",
        "input_type=txt",
        "output_type=txt",
        *detector_lines,
        surrogate_line,
    ]
    if user_dict_path and os.path.exists(user_dict_path):
        lines.append(f"user_dictionary_file={user_dict_path}")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return CONFIG_FILE


# ---------------------------------------------------------------------------
# Text extraction from PDF and DOCX (stdlib only for DOCX; pdftotext for PDF).
# ---------------------------------------------------------------------------

_DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_text_from_docx(path: str) -> str:
    """Plain text from a .docx file using only stdlib (zipfile + ElementTree)."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path, "r") as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)
    paragraphs: list[str] = []
    for para in tree.iter(f"{_DOCX_NS}p"):
        runs = [t.text or "" for t in para.iter(f"{_DOCX_NS}t")]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def extract_text_from_pdf_ocr(path: str, log_cb: Callable[[str], None]) -> Optional[str]:
    """OCR fallback for scanned PDFs: rasterise with pdftoppm, then run tesseract.

    Returns None if pdftoppm or tesseract isn't installed, or extraction fails.
    Install on macOS with: brew install poppler tesseract.
    """
    for tool in ("pdftoppm", "tesseract"):
        if shutil.which(tool) is None:
            log_cb(
                f"OCR fallback unavailable: {tool} not found. "
                "Install with: brew install poppler tesseract"
            )
            return None

    with tempfile.TemporaryDirectory(prefix="nlm_ocr_") as tmp:
        prefix = os.path.join(tmp, "page")
        try:
            subprocess.run(
                ["pdftoppm", "-r", "300", "-png", path, prefix],
                check=True, capture_output=True, timeout=300,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
            log_cb(f"pdftoppm failed during OCR for {os.path.basename(path)}: {err}")
            return None

        pages = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        if not pages:
            log_cb(f"OCR: no pages rasterised from {os.path.basename(path)}.")
            return None

        texts: list[str] = []
        for page in pages:
            try:
                result = subprocess.run(
                    ["tesseract", os.path.join(tmp, page), "-", "-l", "eng"],
                    check=True, capture_output=True, text=True, timeout=120,
                )
                texts.append(result.stdout)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
                log_cb(f"tesseract failed on {page}: {err}")
                continue

        return "\n".join(texts) if texts else None


def extract_text_from_pdf(path: str, log_cb: Callable[[str], None]) -> Optional[str]:
    """Plain text from a PDF using `pdftotext` (poppler).

    Falls back to OCR (pdftoppm + tesseract) if the PDF has no text layer.
    Returns None if all extraction methods fail. macOS users can install
    both toolchains with: brew install poppler tesseract.
    """
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        log_cb(
            "pdftotext not found — cannot extract PDF text. "
            "Install with: brew install poppler"
        )
        return None
    if result.returncode != 0:
        log_cb(f"pdftotext failed for {os.path.basename(path)}: {result.stderr.strip()}")
        return None
    text = result.stdout
    # Scanned PDFs have no text layer; pdftotext returns empty output. Fall back
    # to OCR so they don't slip through silently.
    if not text.strip():
        log_cb(
            f"PDF {os.path.basename(path)} has no text layer; attempting OCR "
            "(this may take a minute per page)..."
        )
        ocr_text = extract_text_from_pdf_ocr(path, log_cb)
        if ocr_text and ocr_text.strip():
            log_cb(f"OCR extracted {len(ocr_text):,} characters from {os.path.basename(path)}.")
            return ocr_text
        return None
    return text


def extract_text(path: str, log_cb: Callable[[str], None]) -> Optional[str]:
    """Dispatch to the right extractor based on extension. None on failure."""
    ext = os.path.splitext(path.lower())[1]
    if ext in TEXT_EXTS:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    if ext == ".docx":
        try:
            return extract_text_from_docx(path)
        except (zipfile.BadZipFile, KeyError) as err:
            log_cb(f"Could not read DOCX {os.path.basename(path)}: {err}")
            return None
    if ext == ".pdf":
        return extract_text_from_pdf(path, log_cb)
    return None


def gather_files(input_path: str) -> list[str]:
    if os.path.isfile(input_path):
        return [input_path] if is_supported_file(input_path) else []
    files = []
    for root, _, filenames in os.walk(input_path):
        for name in filenames:
            full = os.path.join(root, name)
            if is_supported_file(full):
                files.append(full)
    return files


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    ensure_dir(SCRUBBER_DIR)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


class ScrubberApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x720")
        self.root.minsize(820, 640)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.use_surrogates = tk.BooleanVar(value=False)
        self.log_to_file = tk.BooleanVar(value=False)
        self.use_docker = tk.BooleanVar(value=False)
        self.progress_value = tk.IntVar(value=0)

        # One BooleanVar per detector for the UI checkboxes.
        self.phi_vars: dict[str, tk.BooleanVar] = {
            key: tk.BooleanVar(value=default)
            for key, _, default in PHI_DETECTORS
        }

        # One BooleanVar per EU/Spain identifier validator.
        self.eu_vars: dict[str, tk.BooleanVar] = {
            key: tk.BooleanVar(value=default)
            for key, _, default, _ in EU_VALIDATORS
        }

        self.cancel_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self._dnd_status = ""

        # Most-recent run results, for the Preview tab and clipboard copy.
        self._diff_pairs: list[tuple[str, str, str]] = []  # (label, original, anonymized)
        self._redaction_counts: dict[str, int] = {}
        self._custom_terms: str = ""
        self._enabled_eu: set[str] = set()
        self._log_file_handle: Optional[object] = None
        self._log_output_dir: str = ""

        self._configure_style()
        self._build_ui()
        self._load_settings()
        self._setup_dnd()
        if self._dnd_status and hasattr(self, "dnd_label"):
            self.dnd_label.configure(text=self._dnd_status)

    def _load_settings(self) -> None:
        s = load_settings()
        if s.get("output_path"):
            self.output_path.set(s["output_path"])
        if s.get("use_surrogates") is not None:
            self.use_surrogates.set(bool(s["use_surrogates"]))
        if s.get("log_to_file") is not None:
            self.log_to_file.set(bool(s["log_to_file"]))
        if s.get("use_docker") is not None:
            self.use_docker.set(bool(s["use_docker"]))
        detectors = s.get("detectors", {})
        for key, var in self.phi_vars.items():
            if key in detectors:
                var.set(bool(detectors[key]))
        eu = s.get("eu_validators", {})
        for key, var in self.eu_vars.items():
            if key in eu:
                var.set(bool(eu[key]))
        terms = s.get("custom_terms", "")
        if terms and hasattr(self, "custom_terms_text"):
            self.custom_terms_text.delete("1.0", "end")
            self.custom_terms_text.insert("1.0", terms)

    def _save_settings(self) -> None:
        terms = ""
        if hasattr(self, "custom_terms_text"):
            terms = self.custom_terms_text.get("1.0", "end").strip()
        save_settings({
            "output_path": self.output_path.get(),
            "use_surrogates": self.use_surrogates.get(),
            "log_to_file": self.log_to_file.get(),
            "use_docker": self.use_docker.get(),
            "detectors": {key: var.get() for key, var in self.phi_vars.items()},
            "eu_validators": {key: var.get() for key, var in self.eu_vars.items()},
            "custom_terms": terms,
        })

    def _configure_style(self) -> None:
        style = ttk.Style()
        theme = "aqua" if "aqua" in style.theme_names() else "clam"
        style.theme_use(theme)

        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=4)
        style.configure("TFrame", padding=6)
        style.configure("TLabelframe", padding=8)
        style.configure("TCheckbutton", padding=4)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        path_frame = ttk.LabelFrame(main, text="Input / Output")
        path_frame.pack(fill="x", padx=10, pady=10)

        input_row = ttk.Frame(path_frame)
        input_row.pack(fill="x", pady=4)
        ttk.Label(input_row, text="Input Folder/File:").pack(side="left")
        self.input_entry = ttk.Entry(input_row, textvariable=self.input_path)
        self.input_entry.pack(side="left", fill="x", expand=True, padx=6)
        # Two separate buttons avoid the confusing cascade where cancelling the
        # file picker would silently open the folder picker.
        ttk.Button(input_row, text="Select File", command=self.select_input_file).pack(side="left")
        ttk.Button(input_row, text="Select Folder", command=self.select_input_folder).pack(side="left", padx=(4, 0))

        # Surface drag-and-drop availability so users aren't left guessing
        # whether the headline feature actually works on their system.
        self.dnd_label = ttk.Label(path_frame, text="", foreground="#666")
        self.dnd_label.pack(anchor="w", pady=(2, 0))

        output_row = ttk.Frame(path_frame)
        output_row.pack(fill="x", pady=4)
        ttk.Label(output_row, text="Output Folder:").pack(side="left")
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_path)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(output_row, text="Select Output Folder", command=self.select_output).pack(side="left")

        options_frame = ttk.LabelFrame(main, text="Options")
        options_frame.pack(fill="x", padx=10)
        ttk.Checkbutton(
            options_frame,
            text="Enable surrogate replacements (replace PHI with plausible fakes instead of [PHI] tags)",
            variable=self.use_surrogates,
        ).pack(anchor="w")
        ttk.Checkbutton(options_frame, text="Save log to file (in output folder)", variable=self.log_to_file).pack(anchor="w")
        docker_row = ttk.Frame(options_frame)
        docker_row.pack(anchor="w", fill="x")
        ttk.Checkbutton(docker_row, text="Run scrubber via Docker (required on macOS if no native binary)", variable=self.use_docker).pack(side="left", anchor="w")

        detectors_frame = ttk.LabelFrame(main, text="PHI Detectors")
        detectors_frame.pack(fill="x", padx=10, pady=(8, 0))
        # Lay out checkboxes in a 3-column grid for compactness.
        for i, (key, label, _) in enumerate(PHI_DETECTORS):
            row, col = divmod(i, 3)
            ttk.Checkbutton(detectors_frame, text=label, variable=self.phi_vars[key]).grid(
                row=row, column=col, sticky="w", padx=4, pady=2
            )
        for c in range(3):
            detectors_frame.columnconfigure(c, weight=1)

        # EU / Spain identifiers: a second pass of deterministic, checksum-validated
        # recognizers that NLM Scrubber (US-centric) does not cover.
        eu_frame = ttk.LabelFrame(main, text="EU / Spain identifiers (checksum-validated second pass)")
        eu_frame.pack(fill="x", padx=10, pady=(8, 0))
        for i, (key, label, _, _) in enumerate(EU_VALIDATORS):
            row, col = divmod(i, 3)
            ttk.Checkbutton(eu_frame, text=label, variable=self.eu_vars[key]).grid(
                row=row, column=col, sticky="w", padx=4, pady=2
            )
        for c in range(3):
            eu_frame.columnconfigure(c, weight=1)

        custom_frame = ttk.LabelFrame(main, text="Custom PHI terms (one per line — names/IDs the scrubber might miss)")
        custom_frame.pack(fill="x", padx=10, pady=(8, 0))
        self.custom_terms_text = tk.Text(custom_frame, height=3, wrap="word")
        self.custom_terms_text.pack(fill="x", padx=4, pady=4)

        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill="x", padx=10, pady=8)
        self.progress_bar = ttk.Progressbar(progress_frame, maximum=100, variable=self.progress_value)
        self.progress_bar.pack(fill="x")
        self.status_label = ttk.Label(progress_frame, text="")
        self.status_label.pack(anchor="w", pady=(2, 0))

        # Tabbed view: log on one tab, before/after preview on another, summary on a third.
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=8)

        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text="Log")
        self.log_text = tk.Text(log_tab, height=12, wrap="word")
        self.log_text.configure(state="disabled")
        log_scroll = ttk.Scrollbar(log_tab, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        preview_tab = ttk.Frame(self.notebook)
        self.notebook.add(preview_tab, text="Preview")
        picker_row = ttk.Frame(preview_tab)
        picker_row.pack(fill="x")
        ttk.Label(picker_row, text="File:").pack(side="left", padx=(4, 4))
        self.preview_picker = ttk.Combobox(picker_row, state="readonly")
        self.preview_picker.pack(side="left", fill="x", expand=True, padx=4)
        self.preview_picker.bind("<<ComboboxSelected>>", self._on_preview_selected)
        self.copy_button = ttk.Button(
            picker_row, text="Copy anonymized to clipboard",
            command=self._copy_to_clipboard, state="disabled",
        )
        self.copy_button.pack(side="left", padx=4)

        diff_row = ttk.Frame(preview_tab)
        diff_row.pack(fill="both", expand=True, pady=(4, 0))
        original_frame = ttk.LabelFrame(diff_row, text="Original")
        original_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.original_text = tk.Text(original_frame, wrap="word")
        self.original_text.configure(state="disabled")
        self.original_text.pack(fill="both", expand=True)
        anonymized_frame = ttk.LabelFrame(diff_row, text="Anonymized")
        anonymized_frame.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.anonymized_text = tk.Text(anonymized_frame, wrap="word")
        self.anonymized_text.configure(state="disabled")
        self.anonymized_text.pack(fill="both", expand=True)
        # Tag config: red for removed PHI, green for inserted surrogate/placeholder.
        self.original_text.tag_configure("removed", background="#ffe2e2")
        self.anonymized_text.tag_configure("added", background="#dcffd8")

        report_tab = ttk.Frame(self.notebook)
        self.notebook.add(report_tab, text="Report")
        self.report_text = tk.Text(report_tab, wrap="word")
        self.report_text.configure(state="disabled")
        self.report_text.pack(fill="both", expand=True)

        button_frame = ttk.Frame(main)
        button_frame.pack(fill="x", padx=10, pady=10)
        self.start_button = ttk.Button(button_frame, text="Start Anonymization", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(button_frame, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)

    def _setup_dnd(self) -> None:
        """Wire up file drop support.

        Two independent mechanisms:
          1. macOS OpenDocument Apple Event — stdlib only. Fires when files are
             dropped on the app's Dock icon or "Open With" is used. Works on
             every stock macOS Python (no tkdnd needed).
          2. tkdnd drop_target — handles in-window drops, but requires the
             tkdnd Tcl package which is NOT bundled with macOS Tk. Used only
             when available.
        """
        dnd_mechanisms: list[str] = []

        if platform.system() == "Darwin":
            try:
                self.root.createcommand(
                    "::tk::mac::OpenDocument", self._on_macos_open_document
                )
                dnd_mechanisms.append("Dock drop")
            except tk.TclError as err:
                self.log(f"macOS OpenDocument hook unavailable: {err}")

        try:
            self.root.tk.call("package", "require", "tkdnd")
            self.root.tk.call("tkdnd::drop_target", "register", self.root, "*")
            self.root.bind("<<Drop>>", self._on_drop)
            dnd_mechanisms.append("in-window drop")
        except tk.TclError:
            pass  # tkdnd not installed — no in-window drop

        if dnd_mechanisms:
            self._dnd_status = "Drop files: " + ", ".join(dnd_mechanisms)
        else:
            self._dnd_status = "Drag-and-drop unavailable — use Select File/Folder"

    def _on_macos_open_document(self, *paths: str) -> None:
        self._accept_dropped_paths(list(paths))

    def _on_drop(self, event: tk.Event) -> None:
        if not event.data:
            return
        self._accept_dropped_paths(self._parse_dnd_paths(event.data))

    def _accept_dropped_paths(self, paths: list[str]) -> None:
        valid = [p for p in paths if os.path.isdir(p) or os.path.isfile(p)]
        if not valid:
            return
        if len(valid) > 1:
            self.log(
                f"Received {len(valid)} dropped items; using the first "
                f"({valid[0]}). Drop a folder to process multiple files."
            )
        self.input_path.set(valid[0])

    def _parse_dnd_paths(self, data: str) -> list[str]:
        if data.startswith("{") and data.endswith("}"):
            data = data[1:-1]
        parts: list[str] = []
        current = ""
        in_brace = False
        for char in data:
            if char == "{":
                in_brace = True
                current = ""
                continue
            if char == "}":
                in_brace = False
                parts.append(current)
                current = ""
                continue
            if char == " " and not in_brace:
                if current:
                    parts.append(current)
                    current = ""
                continue
            current += char
        if current:
            parts.append(current)
        return [p for p in parts if p]

    def select_input_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select input file",
            filetypes=[
                ("Supported", "*.txt *.md *.pdf *.docx"),
                ("Text/Markdown", "*.txt *.md"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_path.set(path)

    def select_input_folder(self) -> None:
        path = filedialog.askdirectory(title="Select input folder")
        if path:
            self.input_path.set(path)

    def select_output(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_path.set(path)

    def log(self, message: str) -> None:
        def append() -> None:
            timestamp = time.strftime("%H:%M:%S")
            line = f"[{timestamp}] {message}\n"
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            self.log_text.configure(state="disabled")
            self.log_text.see("end")
            if self._log_file_handle is not None:
                try:
                    self._log_file_handle.write(line)
                    self._log_file_handle.flush()
                except OSError:
                    pass

        if threading.current_thread() is threading.main_thread():
            append()
        else:
            self.root.after(0, append)

    def set_progress(self, value: int) -> None:
        def update() -> None:
            self.progress_value.set(value)
            self.root.update_idletasks()

        if threading.current_thread() is threading.main_thread():
            update()
        else:
            self.root.after(0, update)

    def _set_status(self, text: str) -> None:
        def update() -> None:
            self.status_label.configure(text=text)

        if threading.current_thread() is threading.main_thread():
            update()
        else:
            self.root.after(0, update)

    def start(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        input_path = self.input_path.get().strip()
        output_path = self.output_path.get().strip()
        if not validate_path(input_path):
            messagebox.showerror(APP_TITLE, "Please select a valid input file or folder.")
            return
        if not output_path:
            messagebox.showerror(APP_TITLE, "Please select an output folder.")
            return
        ensure_dir(output_path)
        self._save_settings()

        if self.log_to_file.get() and output_path:
            ts = time.strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(output_path, f"scrubber_log_{ts}.txt")
            try:
                self._log_file_handle = open(log_path, "w", encoding="utf-8")
            except OSError:
                self._log_file_handle = None
        else:
            self._log_file_handle = None

        files = gather_files(input_path)
        if not files:
            messagebox.showerror(
                APP_TITLE,
                "No supported files found. Accepted: .txt, .md, .pdf, .docx",
            )
            return

        detector_overrides = {key: var.get() for key, var in self.phi_vars.items()}
        # Tk variables must be read on the main thread; snapshot the enabled
        # EU validators here and hand the set to the worker thread.
        self._enabled_eu = {key for key, var in self.eu_vars.items() if var.get()}
        self._custom_terms = ""
        if hasattr(self, "custom_terms_text"):
            self._custom_terms = self.custom_terms_text.get("1.0", "end").strip()

        self.cancel_event.clear()
        self.progress_value.set(0)
        self._set_status("Starting...")
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.copy_button.configure(state="disabled")

        self.worker_thread = threading.Thread(
            target=self._run_scrubber,
            args=(
                input_path,
                output_path,
                self.use_surrogates.get(),
                files,
                detector_overrides,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.log("Cancellation requested.")
        self._set_status("Cancelling...")

    def _prepare_input_files(
        self, files: list[str], input_root: Optional[str] = None
    ) -> tuple[str, list[tuple[str, str]]]:
        """Build a temp dir of .txt copies for the scrubber, preserving folder structure.

        If *input_root* is provided (the original top-level input folder), output
        files are placed at the same relative path inside the temp dir so the
        scrubber (and later _populate_results) can mirror that structure.

        Returns (temp_dir, prepared) where prepared is a list of
        (original_path, relative_txt_path).
        """
        temp_dir = tempfile.mkdtemp(prefix="nlm_scrubber_input_", dir=SCRUBBER_DIR)
        prepared: list[tuple[str, str]] = []
        used_relpaths: set[str] = set()

        def _unique_relpath(relpath: str) -> str:
            candidate = relpath
            i = 1
            while candidate in used_relpaths:
                stem, ext = os.path.splitext(relpath)
                candidate = f"{stem}_{i}{ext}"
                i += 1
            used_relpaths.add(candidate)
            return candidate

        for src in files:
            ext = os.path.splitext(src.lower())[1]
            stem = os.path.splitext(os.path.basename(src))[0]
            # Compute the relative path from input_root for structure preservation.
            if input_root and os.path.isdir(input_root):
                try:
                    rel_dir = os.path.relpath(os.path.dirname(src), input_root)
                except ValueError:
                    rel_dir = ""
            else:
                rel_dir = ""
            # Normalise: "." means same level as root
            if rel_dir == ".":
                rel_dir = ""
            rel_txt = _unique_relpath(
                os.path.join(rel_dir, stem + ".txt") if rel_dir else stem + ".txt"
            )
            dest = os.path.join(temp_dir, rel_txt)
            ensure_dir(os.path.dirname(dest))

            if ext in TEXT_EXTS:
                try:
                    shutil.copyfile(src, dest)
                except OSError as err:
                    self.log(f"Skipping {os.path.basename(src)}: {err}")
                    continue
            else:
                text = extract_text(src, self.log)
                if text is None:
                    self.log(f"Skipping {os.path.basename(src)}: extraction failed.")
                    continue
                try:
                    with open(dest, "w", encoding="utf-8") as f:
                        f.write(text)
                except OSError as err:
                    self.log(f"Skipping {os.path.basename(src)}: {err}")
                    continue
            prepared.append((src, rel_txt))

        if not prepared:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError("No input files could be prepared (extraction failures only).")

        self.log(f"Prepared {len(prepared)} file(s) in {temp_dir}")
        return temp_dir, prepared

    def _watch_output_progress(
        self,
        output_dir: str,
        total_files: int,
        stop_event: threading.Event,
    ) -> None:
        """Poll output_dir and update the progress bar as output files appear."""
        seen: set[str] = set()
        while not stop_event.is_set():
            try:
                current = set(os.listdir(output_dir)) - seen
                if current:
                    seen |= current
                    n = len(seen)
                    pct = 35 + int(n / total_files * 55)
                    self.set_progress(min(pct, 90))
                    self._set_status(f"Scrubbing... {n}/{total_files} file(s) done")
            except OSError:
                pass
            time.sleep(0.25)

    @staticmethod
    def _snapshot_dir(path: str) -> set[str]:
        """Return the set of relative file paths currently inside *path*."""
        snapshot: set[str] = set()
        if not os.path.isdir(path):
            return snapshot
        for root, _, files in os.walk(path):
            for name in files:
                snapshot.add(os.path.relpath(os.path.join(root, name), path))
        return snapshot

    @staticmethod
    def _cleanup_partial_output(path: str, pre_existing: set[str]) -> int:
        """Delete files in *path* that did not exist in the *pre_existing* snapshot.

        Returns the number of files removed. Empty directories left behind are
        also cleaned up. Pre-existing files are never touched.
        """
        if not os.path.isdir(path):
            return 0
        removed = 0
        for root, _, files in os.walk(path):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path)
                if rel in pre_existing:
                    continue
                try:
                    os.remove(full)
                    removed += 1
                except OSError:
                    pass
        # Tidy up subdirs that the scrubber created and are now empty.
        for root, dirs, _ in os.walk(path, topdown=False):
            for name in dirs:
                full = os.path.join(root, name)
                try:
                    os.rmdir(full)
                except OSError:
                    pass  # not empty or in-use — leave it alone
        return removed

    def _stream_subprocess(self, process: subprocess.Popen) -> int:
        """Forward stdout of *process* to the log; terminate cleanly on cancel.

        Returns the process exit code, or -1 if cancelled.
        """
        while True:
            if self.cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                self.log("Process terminated.")
                return -1
            line = process.stdout.readline()
            if line:
                self.log(line.rstrip())
            if line == "" and process.poll() is not None:
                break
        return process.wait()

    def _run_scrubber(
        self,
        input_path: str,
        output_path: str,
        use_surrogates: bool,
        files: list[str],
        detector_overrides: dict[str, bool],
    ) -> None:
        temp_input_dir: Optional[str] = None
        prepared: list[tuple[str, str]] = []
        try:
            self._set_status("Downloading scrubber...")
            try:
                if not download_scrubber(self.set_progress, self.log, self.cancel_event):
                    self._finish(False, "Scrubber download was cancelled or failed.")
                    return
            except Exception as err:
                self._finish(False, f"Failed to prepare scrubber: {err}")
                return

            if self.cancel_event.is_set():
                self._finish(False, "Operation cancelled before start.")
                return

            try:
                input_root = input_path if os.path.isdir(input_path) else None
                temp_input_dir, prepared = self._prepare_input_files(files, input_root=input_root)
            except RuntimeError as err:
                self._finish(False, str(err))
                return

            self.log(f"Preparing to scrub {len(prepared)} file(s).")
            self._set_status(f"Scrubbing {len(prepared)} file(s)...")

            # Write custom user dictionary if user provided any terms.
            user_dict_path: Optional[str] = None
            if self._custom_terms.strip():
                ensure_dir(SCRUBBER_DIR)
                with open(USER_DICT_FILE, "w", encoding="utf-8") as _f:
                    _f.write(self._custom_terms)
                user_dict_path = USER_DICT_FILE
                self.log(f"Custom dictionary: {len([t for t in self._custom_terms.splitlines() if t.strip()])} term(s).")

            build_config(temp_input_dir, output_path, use_surrogates, detector_overrides, user_dict_path)
            self.log("Configuration generated.")
            self.set_progress(35)

            binary = find_installed_binary()
            if not binary:
                self._finish(False, "Scrubber binary not found after install.")
                return
            cmd = [binary, CONFIG_FILE]
            self.log(f"Running: {' '.join(cmd)}")

            # Snapshot output dir so we can clean up files we wrote if cancelled,
            # without touching files the user already had there.
            pre_existing_output = self._snapshot_dir(output_path)

            process: Optional[subprocess.Popen] = None
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=SCRUBBER_DIR,
                )
            except FileNotFoundError:
                self._finish(False, "Scrubber binary not found.")
                return
            except OSError as err:
                if "Exec format" in str(err) or getattr(err, "errno", None) == 8:
                    self.log("Native binary cannot run on this OS — trying Docker fallback...")
                    process = run_with_docker(
                        binary, CONFIG_FILE, temp_input_dir, output_path,
                        self.log, self.cancel_event,
                    )
                    if process is None:
                        self._finish(
                            False,
                            f"Scrubber binary is not executable on this OS "
                            f"({platform.system()}) and Docker fallback failed. "
                            "Install Docker Desktop or run on Linux.",
                        )
                        return
                else:
                    self._finish(False, f"Error running scrubber: {err}")
                    return
            except Exception as err:
                self._finish(False, f"Error running scrubber: {err}")
                return

            stop_watcher = threading.Event()
            watcher = threading.Thread(
                target=self._watch_output_progress,
                args=(output_path, len(prepared), stop_watcher),
                daemon=True,
            )
            watcher.start()
            try:
                code = self._stream_subprocess(process)
            finally:
                stop_watcher.set()
                watcher.join(timeout=1)

            if code == -1:
                removed = self._cleanup_partial_output(output_path, pre_existing_output)
                if removed:
                    self.log(f"Removed {removed} partial output file(s) created during the cancelled run.")
                self._finish(False, "Operation cancelled.")
                return

            if code != 0:
                self._finish(False, f"Scrubber exited with code {code}.")
                return

            if self._enabled_eu:
                self._set_status("Applying EU/Spain validators...")
                self._apply_eu_validators(output_path, prepared)

            self.set_progress(95)
            self._set_status("Computing diff and report...")
            self._populate_results(temp_input_dir, output_path, prepared)
            self.set_progress(100)
            self._set_status("Complete")
            self._finish(True, "Anonymization complete.", output_path)
        finally:
            if temp_input_dir:
                shutil.rmtree(temp_input_dir, ignore_errors=True)

    @staticmethod
    def _resolve_output_file(output_path: str, rel_txt: str) -> Optional[str]:
        """Locate the scrubber's output file for a given prepared input.

        The scrubber may write output flat or with the input's subdirectory
        structure, and may vary the filename slightly. Checks the structured
        location, then the flat location (moving it into place to preserve
        structure), then falls back to a stem-name search.
        """
        stem = os.path.splitext(os.path.basename(rel_txt))[0]
        rel_dir = os.path.dirname(rel_txt)
        flat_output = os.path.join(output_path, os.path.basename(rel_txt))
        structured_output = os.path.join(output_path, rel_txt)
        if os.path.exists(structured_output):
            return structured_output
        if os.path.exists(flat_output):
            if rel_dir:
                ensure_dir(os.path.join(output_path, rel_dir))
                shutil.move(flat_output, structured_output)
                return structured_output
            return flat_output
        try:
            return next(
                (os.path.join(output_path, n)
                 for n in os.listdir(output_path)
                 if stem in n),
                None,
            )
        except OSError:
            return None

    def _apply_eu_validators(
        self,
        output_path: str,
        prepared: list[tuple[str, str]],
    ) -> None:
        """Second pass: rewrite each scrubber output file in place, replacing
        checksum-validated EU/Spain identifiers with ``**TOKEN**`` placeholders.

        Runs before _populate_results so the new tokens flow into the diff and
        report automatically. Uses self._enabled_eu (snapshotted on the main
        thread in start()).
        """
        total = 0
        for _original_path, rel_txt in prepared:
            output_file = self._resolve_output_file(output_path, rel_txt)
            if not output_file:
                continue
            try:
                with open(output_file, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            new_text, counts = apply_validators(text, self._enabled_eu)
            hits = sum(counts.values())
            if hits:
                try:
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write(new_text)
                    total += hits
                except OSError as err:
                    self.log(f"Could not write validator output for {os.path.basename(output_file)}: {err}")
        if total:
            self.log(f"EU/Spain validators replaced {total} additional identifier(s).")

    def _populate_results(
        self,
        temp_input_dir: str,
        output_path: str,
        prepared: list[tuple[str, str]],
    ) -> None:
        """Read input/output text pairs, store them for the Preview tab, and
        compute redaction counts for the Report tab.

        The scrubber writes output files alongside the temp .txt name, often
        with a suffix/prefix variation. We find the matching output file by
        looking for files whose name contains the input stem.
        """
        diff_pairs: list[tuple[str, str, str]] = []
        counts: dict[str, int] = {
            "Total PHI tokens replaced": 0,
            "Dates": 0,
            "Names": 0,
            "Numbers/IDs": 0,
            "Locations": 0,
            "EU/Spain IDs": 0,
            "Other": 0,
        }

        for original_path, rel_txt in prepared:
            input_full = os.path.join(temp_input_dir, rel_txt)
            try:
                with open(input_full, encoding="utf-8", errors="replace") as f:
                    original_text = f.read()
            except OSError:
                continue

            output_file = self._resolve_output_file(output_path, rel_txt)
            if not output_file:
                continue
            try:
                with open(output_file, encoding="utf-8", errors="replace") as f:
                    anonymized_text = f.read()
            except OSError:
                continue

            label = os.path.basename(original_path)
            diff_pairs.append((label, original_text, anonymized_text))
            self._tally_redactions(anonymized_text, counts)

        self._diff_pairs = diff_pairs
        self._redaction_counts = counts
        self.root.after(0, self._refresh_results_ui)

    @staticmethod
    def _tally_redactions(anonymized: str, counts: dict[str, int]) -> None:
        """NLM Scrubber emits tokens like **DATE**, **NAME[xxx]**, etc.
        Count them by category. Surrogate-replacement output won't have these
        tokens, so the report will be empty in that mode — that's expected.
        """
        # Token charset includes "_" to match EU validator tokens like ES_DNI.
        for token in re.findall(r"\*\*([A-Z_\-]+)(?:\[[^\]]*\])?\*\*", anonymized):
            counts["Total PHI tokens replaced"] += 1
            t = token.upper()
            # EU/Spain validator tokens are routed first so the generic ID/SSN
            # checks below don't claim them.
            if t in {"ES_DNI", "ES_NIE", "ES_NIF", "IBAN", "ES_PHONE", "ES_SSN"}:
                counts["EU/Spain IDs"] = counts.get("EU/Spain IDs", 0) + 1
            elif "DATE" in t or "TIME" in t:
                counts["Dates"] += 1
            elif "NAME" in t or "PATIENT" in t or "DOCTOR" in t:
                counts["Names"] += 1
            elif "ID" in t or "NUM" in t or "PHONE" in t or "MRN" in t or "SSN" in t:
                counts["Numbers/IDs"] += 1
            elif (
                "CITY" in t or "STATE" in t or "ADDRESS" in t
                or "HOSPITAL" in t or "LOC" in t
            ):
                counts["Locations"] += 1
            else:
                counts["Other"] += 1

    def _refresh_results_ui(self) -> None:
        labels = [pair[0] for pair in self._diff_pairs]
        self.preview_picker["values"] = labels
        if labels:
            self.preview_picker.current(0)
            self._render_preview(0)
            self.copy_button.configure(state="normal")
        else:
            self._render_empty_preview()
            self.copy_button.configure(state="disabled")
        self._render_report()

    def _on_preview_selected(self, _event: object) -> None:
        idx = self.preview_picker.current()
        if 0 <= idx < len(self._diff_pairs):
            self._render_preview(idx)

    def _render_preview(self, index: int) -> None:
        import difflib

        _, original, anonymized = self._diff_pairs[index]
        self.original_text.configure(state="normal")
        self.anonymized_text.configure(state="normal")
        self.original_text.delete("1.0", "end")
        self.anonymized_text.delete("1.0", "end")

        matcher = difflib.SequenceMatcher(a=original, b=anonymized, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            orig_chunk = original[i1:i2]
            anon_chunk = anonymized[j1:j2]
            if tag == "equal":
                self.original_text.insert("end", orig_chunk)
                self.anonymized_text.insert("end", anon_chunk)
            elif tag == "delete":
                self.original_text.insert("end", orig_chunk, ("removed",))
            elif tag == "insert":
                self.anonymized_text.insert("end", anon_chunk, ("added",))
            else:  # replace
                self.original_text.insert("end", orig_chunk, ("removed",))
                self.anonymized_text.insert("end", anon_chunk, ("added",))

        self.original_text.configure(state="disabled")
        self.anonymized_text.configure(state="disabled")

    def _render_empty_preview(self) -> None:
        for widget in (self.original_text, self.anonymized_text):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("end", "(no output to preview)")
            widget.configure(state="disabled")

    def _render_report(self) -> None:
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        if not self._diff_pairs:
            self.report_text.insert("end", "No results yet.")
        else:
            lines = [f"Files processed: {len(self._diff_pairs)}", ""]
            for key, val in self._redaction_counts.items():
                lines.append(f"  {key}: {val}")
            if self.use_surrogates.get():
                lines += [
                    "",
                    "Note: surrogate replacement is enabled. Counts above only",
                    "reflect ** PHI ** tokens; with surrogates, PHI is replaced",
                    "in-place with realistic-looking fakes and won't appear here.",
                    "Use the Preview tab to see the highlighted changes instead.",
                ]
            self.report_text.insert("end", "\n".join(lines))
        self.report_text.configure(state="disabled")

    def _copy_to_clipboard(self) -> None:
        idx = self.preview_picker.current()
        if not (0 <= idx < len(self._diff_pairs)):
            return
        _, _, anonymized = self._diff_pairs[idx]
        self.root.clipboard_clear()
        self.root.clipboard_append(anonymized)
        self.root.update()  # keep clipboard alive after window closes
        self.log("Anonymized text copied to clipboard.")

    def _finish(self, success: bool, message: str, output_path: Optional[str] = None) -> None:
        def finish_ui() -> None:
            self.start_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self._set_status("")
            if self._log_file_handle is not None:
                try:
                    self._log_file_handle.close()
                except OSError:
                    pass
                self._log_file_handle = None
            if success:
                self.log(message)
                if self._diff_pairs:
                    # Jump to the Preview tab so users immediately see the result.
                    self.notebook.select(1)
                if output_path:
                    if messagebox.askyesno(APP_TITLE, f"{message}\n\nReveal output folder?"):
                        open_in_finder(output_path)
                else:
                    messagebox.showinfo(APP_TITLE, message)
            else:
                self.log(message)
                messagebox.showerror(APP_TITLE, message)

        self.root.after(0, finish_ui)


def main() -> None:
    root = tk.Tk()
    app = ScrubberApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
