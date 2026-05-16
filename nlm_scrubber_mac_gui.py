# Run with: python3 nlm_scrubber_mac_gui.py
# Requires Python 3.9+ (macOS default), no extra installs needed.
"""
Native-feeling macOS GUI wrapper for NLM Scrubber (Linux CLI version).
"""

import hashlib
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

APP_TITLE = "NLM Scrubber (macOS GUI Wrapper)"
DEFAULT_SCRUBBER_URL = "https://lhncbc.nlm.nih.gov/scrubber/files/scrubber.19.0403L.zip"
# SHA-256 digest of the expected zip. Set to None to skip verification.
# Update this whenever DEFAULT_SCRUBBER_URL changes.
SCRUBBER_SHA256: Optional[str] = None
SCRUBBER_DIR = os.path.expanduser("~/.nlm_scrubber")
SCRUBBER_ZIP = os.path.join(SCRUBBER_DIR, "scrubber.zip")
CONFIG_FILE = os.path.join(SCRUBBER_DIR, "config.txt")

SUPPORTED_EXTS = {".txt", ".md"}

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


_CONFIG_DEFAULTS = [
    "input_type=txt",
    "output_type=txt",
    "find_rated_number=no",
    "find_date=yes",
    "find_patient=yes",
    "find_doctor=yes",
    "find_hospital=yes",
    "find_unique_id=yes",
    "find_url=yes",
    "find_phone=yes",
    "find_email=yes",
    "find_age=yes",
    "find_state=yes",
    "find_city=yes",
]


def build_config(input_dir: str, output_dir: str, use_surrogates: bool) -> str:
    ensure_dir(SCRUBBER_DIR)
    surrogate_line = "use_surrogates=yes" if use_surrogates else "use_surrogates=no"
    lines = [
        f"input_dir={input_dir}",
        f"output_dir={output_dir}",
        *_CONFIG_DEFAULTS,
        surrogate_line,
    ]
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return CONFIG_FILE


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


class ScrubberApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("760x520")
        self.root.minsize(720, 500)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.use_surrogates = tk.BooleanVar(value=False)
        self.progress_value = tk.IntVar(value=0)

        self.cancel_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self._dnd_status = ""

        self._configure_style()
        self._build_ui()
        self._setup_dnd()
        if self._dnd_status and hasattr(self, "dnd_label"):
            self.dnd_label.configure(text=self._dnd_status)

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
        ttk.Checkbutton(options_frame, text="Enable surrogate replacements", variable=self.use_surrogates).pack(anchor="w")

        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill="x", padx=10, pady=8)
        self.progress_bar = ttk.Progressbar(progress_frame, maximum=100, variable=self.progress_value)
        self.progress_bar.pack(fill="x")
        self.status_label = ttk.Label(progress_frame, text="")
        self.status_label.pack(anchor="w", pady=(2, 0))

        log_frame = ttk.LabelFrame(main, text="Log")
        log_frame.pack(fill="both", expand=True, padx=10, pady=8)

        self.log_text = tk.Text(log_frame, height=12, wrap="word")
        self.log_text.configure(state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

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
            filetypes=[("Text/Markdown", "*.txt *.md"), ("All files", "*.*")],
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
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{timestamp}] {message}\n")
            self.log_text.configure(state="disabled")
            self.log_text.see("end")

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

        files = gather_files(input_path)
        if not files:
            messagebox.showerror(APP_TITLE, "No .txt or .md files found in the selected input.")
            return

        self.cancel_event.clear()
        self.progress_value.set(0)
        self._set_status("Starting...")
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        self.worker_thread = threading.Thread(
            target=self._run_scrubber,
            args=(input_path, output_path, self.use_surrogates.get(), files),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.log("Cancellation requested.")
        self._set_status("Cancelling...")

    def _prepare_input_dir(self, input_path: str) -> str:
        """Copy a single file into a temp dir so the scrubber receives a directory.

        Returns the temp dir path; the caller is responsible for cleanup.
        Raises RuntimeError on failure.
        """
        temp_dir = tempfile.mkdtemp(prefix="nlm_scrubber_input_", dir=SCRUBBER_DIR)
        try:
            shutil.copy2(input_path, temp_dir)
            self.log(f"Copied file into temporary input folder: {temp_dir}")
        except OSError as err:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to prepare input file: {err}") from err
        return temp_dir

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
    ) -> None:
        temp_input_dir: Optional[str] = None
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

            if os.path.isfile(input_path):
                try:
                    temp_input_dir = self._prepare_input_dir(input_path)
                except RuntimeError as err:
                    self._finish(False, str(err))
                    return
                effective_input = temp_input_dir
            else:
                effective_input = input_path

            self.log(f"Preparing to scrub {len(files)} file(s).")
            self._set_status(f"Scrubbing {len(files)} file(s)...")
            build_config(effective_input, output_path, use_surrogates)
            self.log("Configuration generated.")
            self.set_progress(35)

            binary = find_installed_binary()
            if not binary:
                self._finish(False, "Scrubber binary not found after install.")
                return
            cmd = [binary, CONFIG_FILE]
            self.log(f"Running: {' '.join(cmd)}")

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=SCRUBBER_DIR,
                )
                code = self._stream_subprocess(process)
            except FileNotFoundError:
                self._finish(False, "Scrubber binary not found.")
                return
            except OSError as err:
                # Exec format errors on macOS show up here (e.g. running a Linux
                # ELF binary on Darwin). Translate to something actionable.
                if "Exec format" in str(err) or getattr(err, "errno", None) == 8:
                    self._finish(
                        False,
                        f"The scrubber binary ({os.path.basename(binary)}) is not "
                        f"executable on this OS ({platform.system()}). NLM may not "
                        "ship a native build for your platform — try running through "
                        "Docker or a Linux VM.",
                    )
                    return
                self._finish(False, f"Error running scrubber: {err}")
                return
            except Exception as err:
                self._finish(False, f"Error running scrubber: {err}")
                return

            if code == -1:
                self._finish(False, "Operation cancelled.")
                return

            if code != 0:
                self._finish(False, f"Scrubber exited with code {code}.")
                return

            self.set_progress(100)
            self._set_status("Complete")
            self._finish(True, "Anonymization complete.", output_path)
        finally:
            if temp_input_dir:
                shutil.rmtree(temp_input_dir, ignore_errors=True)

    def _finish(self, success: bool, message: str, output_path: Optional[str] = None) -> None:
        def finish_ui() -> None:
            self.start_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self._set_status("")
            if success:
                self.log(message)
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
