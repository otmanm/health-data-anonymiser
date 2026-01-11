# Run with: python3 nlm_scrubber_mac_gui.py
# Requires Python 3.9+ (macOS default), no extra installs needed.
"""
Native-feeling macOS GUI wrapper for NLM Scrubber (Linux CLI version).
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import zipfile
from urllib import request
from urllib.error import URLError, HTTPError

APP_TITLE = "NLM Scrubber (macOS GUI Wrapper)"
DEFAULT_SCRUBBER_URL = "https://lhncbc.nlm.nih.gov/scrubber/files/scrubber.19.0403L.zip"
SCRUBBER_DIR = os.path.expanduser("~/.nlm_scrubber")
SCRUBBER_ZIP = os.path.join(SCRUBBER_DIR, "scrubber.zip")
SCRUBBER_BIN = os.path.join(SCRUBBER_DIR, "scrubber.lnx")
CONFIG_FILE = os.path.join(SCRUBBER_DIR, "config.txt")

SUPPORTED_EXTS = {".txt", ".md"}


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def is_supported_file(path):
    _, ext = os.path.splitext(path.lower())
    return ext in SUPPORTED_EXTS


def validate_path(path):
    if not path:
        return False
    return os.path.exists(path)


def open_in_finder(path):
    try:
        subprocess.run(["open", path], check=False)
    except Exception:
        return


def get_latest_scrubber_url(log_cb):
    try:
        with request.urlopen("https://lhncbc.nlm.nih.gov/scrubber/") as response:
            html = response.read().decode("utf-8", errors="ignore")
        urls = re.findall(r"https?://[^\"\\s]*scrubber\\.\\d+L\\.zip", html)
        if not urls:
            return DEFAULT_SCRUBBER_URL

        def version_key(url):
            match = re.search(r"scrubber\\.(\\d+)L\\.zip", url)
            return int(match.group(1)) if match else 0

        latest = max(urls, key=version_key)
        if latest != DEFAULT_SCRUBBER_URL:
            log_cb(f"Found newer scrubber package: {latest}")
        return latest
    except Exception as err:
        log_cb(f"Could not check for newer scrubber packages: {err}")
        return DEFAULT_SCRUBBER_URL


def download_scrubber(progress_cb, log_cb, cancel_event):
    ensure_dir(SCRUBBER_DIR)
    if os.path.exists(SCRUBBER_BIN):
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
        raise

    log_cb("Extracting scrubber...")
    try:
        with zipfile.ZipFile(SCRUBBER_ZIP, "r") as zf:
            zf.extractall(SCRUBBER_DIR)
        if os.path.exists(SCRUBBER_ZIP):
            os.remove(SCRUBBER_ZIP)
    except zipfile.BadZipFile as err:
        log_cb(f"Extraction failed: {err}")
        raise

    if not os.path.exists(SCRUBBER_BIN):
        for root, _, files in os.walk(SCRUBBER_DIR):
            if "scrubber.lnx" in files:
                shutil.move(os.path.join(root, "scrubber.lnx"), SCRUBBER_BIN)
                break

    if os.path.exists(SCRUBBER_BIN):
        st = os.stat(SCRUBBER_BIN)
        os.chmod(SCRUBBER_BIN, st.st_mode | stat.S_IEXEC)
        log_cb("Scrubber ready.")
        progress_cb(30)
        return True

    log_cb("Scrubber binary not found after extraction.")
    return False


def build_config(input_dir, output_dir, use_surrogates):
    ensure_dir(SCRUBBER_DIR)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(f"input_dir={input_dir}\n")
        f.write(f"output_dir={output_dir}\n")
        f.write("input_type=txt\n")
        f.write("output_type=txt\n")
        f.write("find_rated_number=no\n")
        f.write("find_date=yes\n")
        f.write("find_patient=yes\n")
        f.write("find_doctor=yes\n")
        f.write("find_hospital=yes\n")
        f.write("find_unique_id=yes\n")
        f.write("find_url=yes\n")
        f.write("find_phone=yes\n")
        f.write("find_email=yes\n")
        f.write("find_age=yes\n")
        f.write("find_state=yes\n")
        f.write("find_city=yes\n")
        f.write("use_surrogates=yes\n" if use_surrogates else "use_surrogates=no\n")
    return CONFIG_FILE


def gather_files(input_path):
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
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("760x520")
        self.root.minsize(720, 500)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.use_surrogates = tk.BooleanVar(value=False)
        self.progress_value = tk.IntVar(value=0)

        self.cancel_event = threading.Event()
        self.worker_thread = None

        self._configure_style()
        self._build_ui()
        self._setup_dnd()

    def _configure_style(self):
        style = ttk.Style()
        theme = "aqua" if "aqua" in style.theme_names() else "clam"
        style.theme_use(theme)

        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=4)
        style.configure("TFrame", padding=6)
        style.configure("TLabelframe", padding=8)
        style.configure("TCheckbutton", padding=4)

    def _build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        path_frame = ttk.LabelFrame(main, text="Input / Output")
        path_frame.pack(fill="x", padx=10, pady=10)

        input_row = ttk.Frame(path_frame)
        input_row.pack(fill="x", pady=4)
        ttk.Label(input_row, text="Input Folder/File:").pack(side="left")
        self.input_entry = ttk.Entry(input_row, textvariable=self.input_path)
        self.input_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(input_row, text="Select Input Folder/File", command=self.select_input).pack(side="left")

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

    def _setup_dnd(self):
        try:
            self.root.tk.call("package", "require", "tkdnd")
        except tk.TclError:
            self.log("Drag-and-drop not available in this Tk build.")
            return
        try:
            self.root.tk.call("tkdnd::drop_target", "register", self.root, "*")
            self.root.bind("<<Drop>>", self._on_drop)
        except tk.TclError as err:
            self.log(f"Drag-and-drop setup failed: {err}")

    def _on_drop(self, event):
        data = event.data
        if not data:
            return
        paths = self._parse_dnd_paths(data)
        if not paths:
            return
        selected = paths[0]
        if os.path.isdir(selected) or os.path.isfile(selected):
            self.input_path.set(selected)

    def _parse_dnd_paths(self, data):
        if data.startswith("{") and data.endswith("}"):
            data = data[1:-1]
        parts = []
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

    def select_input(self):
        path = filedialog.askopenfilename(title="Select file", filetypes=[("Text/Markdown", "*.txt *.md"), ("All files", "*.*")])
        if not path:
            path = filedialog.askdirectory(title="Select folder")
        if path:
            self.input_path.set(path)

    def select_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_path.set(path)

    def log(self, message):
        def append():
            timestamp = time.strftime("%H:%M:%S")
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{timestamp}] {message}\n")
            self.log_text.configure(state="disabled")
            self.log_text.see("end")

        if threading.current_thread() is threading.main_thread():
            append()
        else:
            self.root.after(0, append)

    def set_progress(self, value):
        def update():
            self.progress_value.set(value)
            self.root.update_idletasks()

        if threading.current_thread() is threading.main_thread():
            update()
        else:
            self.root.after(0, update)

    def start(self):
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
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        self.worker_thread = threading.Thread(
            target=self._run_scrubber,
            args=(input_path, output_path, self.use_surrogates.get(), files),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel(self):
        self.cancel_event.set()
        self.log("Cancellation requested.")

    def _run_scrubber(self, input_path, output_path, use_surrogates, files):
        temp_input_dir = None
        try:
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
                temp_input_dir = tempfile.mkdtemp(prefix="nlm_scrubber_input_", dir=SCRUBBER_DIR)
                try:
                    shutil.copy2(input_path, temp_input_dir)
                    self.log(f"Copied file into temporary input folder: {temp_input_dir}")
                except OSError as err:
                    self._finish(False, f"Failed to prepare input file: {err}")
                    return
                effective_input = temp_input_dir
            else:
                effective_input = input_path

            self.log(f"Preparing to scrub {len(files)} file(s).")
            build_config(effective_input, output_path, use_surrogates)
            self.log("Configuration generated.")
            self.set_progress(35)

            cmd = [SCRUBBER_BIN, CONFIG_FILE]
            self.log(f"Running: {' '.join(cmd)}")

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=SCRUBBER_DIR,
                )
                while True:
                    if self.cancel_event.is_set():
                        process.terminate()
                        self.log("Process terminated.")
                        self._finish(False, "Operation cancelled.")
                        return
                    line = process.stdout.readline()
                    if line:
                        self.log(line.rstrip())
                    if line == "" and process.poll() is not None:
                        break
                code = process.wait()
            except FileNotFoundError:
                self._finish(False, "Scrubber binary not found.")
                return
            except Exception as err:
                self._finish(False, f"Error running scrubber: {err}")
                return

            if code != 0:
                self._finish(False, f"Scrubber exited with code {code}.")
                return

            self.set_progress(100)
            self._finish(True, "Anonymization complete.", output_path)
        finally:
            if temp_input_dir:
                shutil.rmtree(temp_input_dir, ignore_errors=True)

    def _finish(self, success, message, output_path=None):
        def finish_ui():
            self.start_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
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


def main():
    root = tk.Tk()
    app = ScrubberApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
