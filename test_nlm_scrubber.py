"""
Unit tests for nlm_scrubber_mac_gui.py (pure-logic functions only).

Run with:  python3 -m pytest test_nlm_scrubber.py -v
or:        python3 -m unittest test_nlm_scrubber -v

tkinter is stubbed out at the sys.modules level so the tests work in headless
CI environments.  The ScrubberApp GUI class is never imported or instantiated.
"""

import hashlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


def _stub_tkinter() -> None:
    """Insert lightweight stubs for tkinter and its sub-modules.

    The main module uses ``tk.Tk``, ``tk.StringVar``, ``tk.BooleanVar``,
    ``tk.IntVar``, ``tk.Text``, ``tk.Event``, and ``tk.TclError`` at class
    *definition* time (type annotations are evaluated eagerly in Python 3.11).
    We must provide real-looking attributes so the class body parses cleanly.
    """
    tk_stub = types.ModuleType("tkinter")
    # Provide every name referenced at class/annotation scope
    for attr in ("Tk", "StringVar", "BooleanVar", "IntVar", "Text", "Event", "Frame"):
        setattr(tk_stub, attr, MagicMock)
    tk_stub.TclError = Exception  # type: ignore[attr-defined]
    sys.modules["tkinter"] = tk_stub

    for subname in ("filedialog", "messagebox", "ttk"):
        sub = types.ModuleType(f"tkinter.{subname}")
        sys.modules[f"tkinter.{subname}"] = sub
        setattr(tk_stub, subname, sub)


_stub_tkinter()

# Import only pure-logic symbols — no Tk initialisation occurs at import time.
from nlm_scrubber_mac_gui import (  # noqa: E402
    _ALL_BIN_NAMES,
    _CONFIG_DEFAULTS,
    PHI_DETECTORS,
    build_config,
    extract_text_from_docx,
    extract_text_from_pdf,
    extract_text_from_pdf_ocr,
    find_installed_binary,
    gather_files,
    get_latest_scrubber_url,
    is_supported_file,
    load_settings,
    save_settings,
    scrubber_binary_candidates,
    validate_path,
    verify_checksum,
)


class TestIsSupportedFile(unittest.TestCase):
    def test_txt_supported(self):
        self.assertTrue(is_supported_file("notes.txt"))

    def test_md_supported(self):
        self.assertTrue(is_supported_file("README.MD"))  # case-insensitive

    def test_pdf_supported(self):
        # PDF is now a supported input — extracted via pdftotext.
        self.assertTrue(is_supported_file("record.pdf"))

    def test_docx_supported(self):
        self.assertTrue(is_supported_file("note.docx"))

    def test_unrelated_unsupported(self):
        self.assertFalse(is_supported_file("scan.tiff"))

    def test_no_extension(self):
        self.assertFalse(is_supported_file("Makefile"))


class TestValidatePath(unittest.TestCase):
    def test_empty_string(self):
        self.assertFalse(validate_path(""))

    def test_none_like_empty(self):
        self.assertFalse(validate_path(""))

    def test_existing_path(self):
        with tempfile.NamedTemporaryFile() as f:
            self.assertTrue(validate_path(f.name))

    def test_nonexistent_path(self):
        self.assertFalse(validate_path("/tmp/__does_not_exist_nlm_test__"))


class TestVerifyChecksum(unittest.TestCase):
    def _write_file(self, content: bytes) -> str:
        fd, path = tempfile.mkstemp()
        os.write(fd, content)
        os.close(fd)
        return path

    def test_correct_checksum(self):
        data = b"hello scrubber"
        expected = hashlib.sha256(data).hexdigest()
        path = self._write_file(data)
        try:
            self.assertTrue(verify_checksum(path, expected))
        finally:
            os.unlink(path)

    def test_wrong_checksum(self):
        path = self._write_file(b"hello scrubber")
        try:
            self.assertFalse(verify_checksum(path, "0" * 64))
        finally:
            os.unlink(path)

    def test_case_insensitive(self):
        data = b"case test"
        expected = hashlib.sha256(data).hexdigest().upper()
        path = self._write_file(data)
        try:
            self.assertTrue(verify_checksum(path, expected))
        finally:
            os.unlink(path)


class TestGatherFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, name: str) -> str:
        path = os.path.join(self.tmp, name)
        open(path, "w").close()
        return path

    def test_single_supported_file(self):
        f = self._touch("doc.txt")
        self.assertEqual(gather_files(f), [f])

    def test_single_unsupported_file(self):
        f = self._touch("image.png")
        self.assertEqual(gather_files(f), [])

    def test_directory_returns_only_supported(self):
        self._touch("a.txt")
        self._touch("b.md")
        self._touch("c.pdf")
        self._touch("d.docx")
        self._touch("e.png")  # not supported
        result = gather_files(self.tmp)
        names = {os.path.basename(p) for p in result}
        self.assertEqual(names, {"a.txt", "b.md", "c.pdf", "d.docx"})

    def test_empty_directory(self):
        self.assertEqual(gather_files(self.tmp), [])

    def test_nested_files(self):
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub)
        f = os.path.join(sub, "nested.txt")
        open(f, "w").close()
        result = gather_files(self.tmp)
        self.assertIn(f, result)


class TestBuildConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read_config(self) -> dict[str, str]:
        from nlm_scrubber_mac_gui import CONFIG_FILE
        with open(CONFIG_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f if "=" in l]
        return dict(line.split("=", 1) for line in lines)

    @patch("nlm_scrubber_mac_gui.SCRUBBER_DIR")
    @patch("nlm_scrubber_mac_gui.CONFIG_FILE")
    def test_surrogate_yes(self, mock_cfg, mock_dir):
        cfg_path = os.path.join(self.tmp, "config.txt")
        mock_cfg.__str__ = lambda s: cfg_path
        # Call the real function with a real temp path
        import nlm_scrubber_mac_gui as m
        orig_dir, orig_cfg = m.SCRUBBER_DIR, m.CONFIG_FILE
        m.SCRUBBER_DIR = self.tmp
        m.CONFIG_FILE = cfg_path
        try:
            result = build_config("/in", "/out", use_surrogates=True)
            with open(result) as f:
                content = f.read()
            self.assertIn("use_surrogates=yes", content)
            self.assertIn("input_dir=/in", content)
            self.assertIn("output_dir=/out", content)
        finally:
            m.SCRUBBER_DIR = orig_dir
            m.CONFIG_FILE = orig_cfg

    @patch("nlm_scrubber_mac_gui.SCRUBBER_DIR")
    @patch("nlm_scrubber_mac_gui.CONFIG_FILE")
    def test_surrogate_no(self, mock_cfg, mock_dir):
        import nlm_scrubber_mac_gui as m
        orig_dir, orig_cfg = m.SCRUBBER_DIR, m.CONFIG_FILE
        cfg_path = os.path.join(self.tmp, "config.txt")
        m.SCRUBBER_DIR = self.tmp
        m.CONFIG_FILE = cfg_path
        try:
            result = build_config("/in", "/out", use_surrogates=False)
            with open(result) as f:
                content = f.read()
            self.assertIn("use_surrogates=no", content)
            self.assertNotIn("use_surrogates=yes", content)
        finally:
            m.SCRUBBER_DIR = orig_dir
            m.CONFIG_FILE = orig_cfg

    def test_all_default_fields_present(self):
        import nlm_scrubber_mac_gui as m
        orig_dir, orig_cfg = m.SCRUBBER_DIR, m.CONFIG_FILE
        cfg_path = os.path.join(self.tmp, "config.txt")
        m.SCRUBBER_DIR = self.tmp
        m.CONFIG_FILE = cfg_path
        try:
            build_config("/in", "/out", use_surrogates=False)
            with open(cfg_path) as f:
                content = f.read()
            for field in _CONFIG_DEFAULTS:
                self.assertIn(field, content, f"Missing field: {field}")
        finally:
            m.SCRUBBER_DIR = orig_dir
            m.CONFIG_FILE = orig_cfg

    def test_detector_overrides_disable(self):
        import nlm_scrubber_mac_gui as m
        orig_dir, orig_cfg = m.SCRUBBER_DIR, m.CONFIG_FILE
        cfg_path = os.path.join(self.tmp, "config.txt")
        m.SCRUBBER_DIR = self.tmp
        m.CONFIG_FILE = cfg_path
        try:
            build_config(
                "/in", "/out", use_surrogates=False,
                detector_overrides={"find_email": False, "find_phone": False},
            )
            with open(cfg_path) as f:
                content = f.read()
            self.assertIn("find_email=no", content)
            self.assertIn("find_phone=no", content)
            # An untouched default should remain enabled.
            self.assertIn("find_date=yes", content)
        finally:
            m.SCRUBBER_DIR = orig_dir
            m.CONFIG_FILE = orig_cfg

    def test_detector_overrides_enable_experimental(self):
        import nlm_scrubber_mac_gui as m
        orig_dir, orig_cfg = m.SCRUBBER_DIR, m.CONFIG_FILE
        cfg_path = os.path.join(self.tmp, "config.txt")
        m.SCRUBBER_DIR = self.tmp
        m.CONFIG_FILE = cfg_path
        try:
            # find_rated_number defaults to False; override flips it on.
            build_config(
                "/in", "/out", use_surrogates=False,
                detector_overrides={"find_rated_number": True},
            )
            with open(cfg_path) as f:
                content = f.read()
            self.assertIn("find_rated_number=yes", content)
        finally:
            m.SCRUBBER_DIR = orig_dir
            m.CONFIG_FILE = orig_cfg


class TestPhiDetectorsRegistry(unittest.TestCase):
    def test_all_entries_have_three_columns(self):
        for entry in PHI_DETECTORS:
            self.assertEqual(len(entry), 3)
            key, label, default = entry
            self.assertTrue(key.startswith("find_"))
            self.assertIsInstance(label, str)
            self.assertIsInstance(default, bool)

    def test_keys_are_unique(self):
        keys = [k for k, _, _ in PHI_DETECTORS]
        self.assertEqual(len(keys), len(set(keys)))


class TestExtractTextFromDocx(unittest.TestCase):
    """Build a minimal valid .docx in-memory and verify extraction."""

    def _make_docx(self, paragraphs: list[str]) -> str:
        import zipfile as zf
        path = tempfile.mkstemp(suffix=".docx")[1]
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        body = "".join(
            f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
            for p in paragraphs
        )
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
        )
        with zf.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", document_xml)
        return path

    def test_extracts_paragraphs(self):
        path = self._make_docx(["Hello world", "Patient: John Doe"])
        try:
            text = extract_text_from_docx(path)
            self.assertIn("Hello world", text)
            self.assertIn("Patient: John Doe", text)
        finally:
            os.unlink(path)

    def test_preserves_paragraph_order(self):
        path = self._make_docx(["one", "two", "three"])
        try:
            text = extract_text_from_docx(path)
            self.assertEqual(text.splitlines(), ["one", "two", "three"])
        finally:
            os.unlink(path)


class TestGetLatestScrubberUrl(unittest.TestCase):
    def _urlopen_ctx(self, body: bytes):
        """Build a mock for request.urlopen whose context manager yields a
        response with ``read()`` returning *body* (bytes).

        MagicMock resolves magic methods (``__enter__``) on the *class*, not
        the instance, so we must use ``return_value`` rather than assigning
        instance attributes.
        """
        mock_open = MagicMock()
        mock_response = MagicMock()
        mock_response.read.return_value = body
        mock_open.return_value.__enter__.return_value = mock_response
        mock_open.return_value.__exit__.return_value = False
        return mock_open

    def test_returns_default_when_no_urls_found(self):
        from nlm_scrubber_mac_gui import DEFAULT_SCRUBBER_URL
        log_cb = MagicMock()
        with patch("nlm_scrubber_mac_gui.request.urlopen", self._urlopen_ctx(b"<html>no links</html>")):
            result = get_latest_scrubber_url(log_cb)
        self.assertEqual(result, DEFAULT_SCRUBBER_URL)

    def test_picks_highest_version(self):
        # URLs use the real two-part format: scrubber.MAJOR.BUILDL.zip
        html = (
            b'<a href="https://example.com/scrubber.18.0101L.zip">old</a>'
            b'<a href="https://example.com/scrubber.20.0101L.zip">new</a>'
        )
        log_cb = MagicMock()
        with patch("nlm_scrubber_mac_gui.request.urlopen", self._urlopen_ctx(html)):
            result = get_latest_scrubber_url(log_cb)
        # version_key parses (major, build) tuples: (20,101) beats (18,101)
        self.assertIn("scrubber.20.0101L.zip", result)

    def test_falls_back_on_network_error(self):
        from nlm_scrubber_mac_gui import DEFAULT_SCRUBBER_URL
        log_cb = MagicMock()
        with patch("nlm_scrubber_mac_gui.request.urlopen", side_effect=OSError("timeout")):
            result = get_latest_scrubber_url(log_cb)
        self.assertEqual(result, DEFAULT_SCRUBBER_URL)
        log_cb.assert_called_once()
        self.assertIn("Could not check", log_cb.call_args[0][0])


class TestScrubberBinaryCandidates(unittest.TestCase):
    def test_preferred_first_on_darwin(self):
        with patch("nlm_scrubber_mac_gui.platform.system", return_value="Darwin"):
            candidates = scrubber_binary_candidates()
        self.assertEqual(candidates[0], "scrubber.osx")

    def test_preferred_first_on_linux(self):
        with patch("nlm_scrubber_mac_gui.platform.system", return_value="Linux"):
            candidates = scrubber_binary_candidates()
        self.assertEqual(candidates[0], "scrubber.lnx")

    def test_unknown_os_falls_back_to_all(self):
        with patch("nlm_scrubber_mac_gui.platform.system", return_value="Plan9"):
            candidates = scrubber_binary_candidates()
        # No preferred, but every known binary still appears as fallback.
        for name in _ALL_BIN_NAMES:
            self.assertIn(name, candidates)

    def test_no_duplicates(self):
        with patch("nlm_scrubber_mac_gui.platform.system", return_value="Darwin"):
            candidates = scrubber_binary_candidates()
        self.assertEqual(len(candidates), len(set(candidates)))


class TestFindInstalledBinary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_none_when_missing(self):
        with patch("nlm_scrubber_mac_gui.SCRUBBER_DIR", self.tmp):
            self.assertIsNone(find_installed_binary())

    def test_finds_preferred_binary_first(self):
        # Put both Linux and macOS binaries on disk; on Darwin macOS wins.
        open(os.path.join(self.tmp, "scrubber.lnx"), "w").close()
        open(os.path.join(self.tmp, "scrubber.osx"), "w").close()
        with patch("nlm_scrubber_mac_gui.SCRUBBER_DIR", self.tmp), \
             patch("nlm_scrubber_mac_gui.platform.system", return_value="Darwin"):
            result = find_installed_binary()
        self.assertTrue(result.endswith("scrubber.osx"))

    def test_falls_back_to_any_known_binary(self):
        # Only Linux binary present, but running on macOS — still discoverable.
        open(os.path.join(self.tmp, "scrubber.lnx"), "w").close()
        with patch("nlm_scrubber_mac_gui.SCRUBBER_DIR", self.tmp), \
             patch("nlm_scrubber_mac_gui.platform.system", return_value="Darwin"):
            result = find_installed_binary()
        self.assertTrue(result.endswith("scrubber.lnx"))


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_returns_empty_dict_when_missing(self):
        import nlm_scrubber_mac_gui as m
        orig = m.SETTINGS_FILE
        m.SETTINGS_FILE = os.path.join(self.tmp, "nonexistent_settings.json")
        try:
            result = load_settings()
            self.assertEqual(result, {})
        finally:
            m.SETTINGS_FILE = orig

    def test_save_and_load_roundtrip(self):
        import nlm_scrubber_mac_gui as m
        orig_settings = m.SETTINGS_FILE
        orig_dir = m.SCRUBBER_DIR
        m.SCRUBBER_DIR = self.tmp
        m.SETTINGS_FILE = os.path.join(self.tmp, "settings.json")
        try:
            data = {
                "output_path": "/tmp/out",
                "use_surrogates": True,
                "log_to_file": False,
                "use_docker": False,
                "detectors": {"find_date": True, "find_phone": False},
                "custom_terms": "John Doe\nMRN-12345",
            }
            save_settings(data)
            loaded = load_settings()
            self.assertEqual(loaded, data)
        finally:
            m.SCRUBBER_DIR = orig_dir
            m.SETTINGS_FILE = orig_settings

    def test_save_handles_oserror_gracefully(self):
        import nlm_scrubber_mac_gui as m
        orig_settings = m.SETTINGS_FILE
        orig_dir = m.SCRUBBER_DIR
        m.SCRUBBER_DIR = self.tmp
        m.SETTINGS_FILE = os.path.join(self.tmp, "settings.json")
        try:
            # Patch open so writing raises OSError — should be swallowed silently.
            with patch("builtins.open", side_effect=OSError("disk full")):
                save_settings({"key": "value"})  # must not raise
        finally:
            m.SCRUBBER_DIR = orig_dir
            m.SETTINGS_FILE = orig_settings

    def test_load_handles_corrupt_json_gracefully(self):
        import nlm_scrubber_mac_gui as m
        orig = m.SETTINGS_FILE
        bad_json = os.path.join(self.tmp, "bad.json")
        with open(bad_json, "w") as f:
            f.write("{not valid json")
        m.SETTINGS_FILE = bad_json
        try:
            result = load_settings()
            self.assertEqual(result, {})
        finally:
            m.SETTINGS_FILE = orig


class TestGatherFilesNested(unittest.TestCase):
    """Test gather_files with deeper nesting to cover structure preservation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gather_files_deeply_nested_returns_all_supported(self):
        # Create a 3-level nested structure.
        deep = os.path.join(self.tmp, "a", "b", "c")
        os.makedirs(deep)
        paths = []
        for name in ("one.txt", "two.md", "three.pdf"):
            p = os.path.join(deep, name)
            open(p, "w").close()
            paths.append(p)
        unsupported = os.path.join(deep, "skip.tiff")
        open(unsupported, "w").close()

        result = gather_files(self.tmp)
        result_set = set(result)
        for p in paths:
            self.assertIn(p, result_set)
        self.assertNotIn(unsupported, result_set)

    def test_gather_files_mixed_levels(self):
        # Files at root level and in sub-dirs all collected.
        root_file = os.path.join(self.tmp, "root.txt")
        open(root_file, "w").close()
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub)
        sub_file = os.path.join(sub, "sub.docx")
        open(sub_file, "w").close()

        result = gather_files(self.tmp)
        self.assertIn(root_file, result)
        self.assertIn(sub_file, result)


class TestBuildConfigUserDict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _setup_module(self):
        import nlm_scrubber_mac_gui as m
        self._orig_dir = m.SCRUBBER_DIR
        self._orig_cfg = m.CONFIG_FILE
        m.SCRUBBER_DIR = self.tmp
        m.CONFIG_FILE = os.path.join(self.tmp, "config.txt")
        return m

    def _teardown_module(self, m):
        m.SCRUBBER_DIR = self._orig_dir
        m.CONFIG_FILE = self._orig_cfg

    def test_build_config_user_dict_included_when_file_exists(self):
        m = self._setup_module()
        try:
            dict_file = os.path.join(self.tmp, "user_dict.txt")
            with open(dict_file, "w") as f:
                f.write("John Doe\nMRN-99999\n")
            result = build_config("/in", "/out", use_surrogates=False, user_dict_path=dict_file)
            with open(result) as f:
                content = f.read()
            self.assertIn(f"user_dictionary_file={dict_file}", content)
        finally:
            self._teardown_module(m)

    def test_build_config_user_dict_omitted_when_file_missing(self):
        m = self._setup_module()
        try:
            nonexistent = os.path.join(self.tmp, "missing_dict.txt")
            result = build_config("/in", "/out", use_surrogates=False, user_dict_path=nonexistent)
            with open(result) as f:
                content = f.read()
            self.assertNotIn("user_dictionary_file", content)
        finally:
            self._teardown_module(m)

    def test_build_config_user_dict_omitted_when_not_provided(self):
        m = self._setup_module()
        try:
            result = build_config("/in", "/out", use_surrogates=False)
            with open(result) as f:
                content = f.read()
            self.assertNotIn("user_dictionary_file", content)
        finally:
            self._teardown_module(m)


class TestPdfOcrFallback(unittest.TestCase):
    """Verify that PDFs with no text layer trigger OCR, and that missing
    tools degrade gracefully without crashing the extractor.
    """

    def _completed(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        result = MagicMock()
        result.stdout = stdout
        result.returncode = returncode
        result.stderr = stderr
        return result

    def test_pdf_with_text_does_not_invoke_ocr(self):
        log_cb = MagicMock()
        # pdftotext returns real text — OCR path must not be touched.
        with patch(
            "nlm_scrubber_mac_gui.subprocess.run",
            return_value=self._completed(stdout="real PDF text"),
        ) as mock_run, patch(
            "nlm_scrubber_mac_gui.extract_text_from_pdf_ocr"
        ) as mock_ocr:
            result = extract_text_from_pdf("/fake.pdf", log_cb)
        self.assertEqual(result, "real PDF text")
        mock_ocr.assert_not_called()
        mock_run.assert_called_once()

    def test_pdf_with_empty_text_triggers_ocr(self):
        log_cb = MagicMock()
        with patch(
            "nlm_scrubber_mac_gui.subprocess.run",
            return_value=self._completed(stdout="   \n\n"),
        ), patch(
            "nlm_scrubber_mac_gui.extract_text_from_pdf_ocr",
            return_value="ocr extracted text",
        ) as mock_ocr:
            result = extract_text_from_pdf("/scanned.pdf", log_cb)
        self.assertEqual(result, "ocr extracted text")
        mock_ocr.assert_called_once()

    def test_pdftotext_missing_returns_none(self):
        log_cb = MagicMock()
        with patch(
            "nlm_scrubber_mac_gui.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            self.assertIsNone(extract_text_from_pdf("/x.pdf", log_cb))
        log_cb.assert_called_once()
        self.assertIn("pdftotext not found", log_cb.call_args[0][0])

    def test_ocr_requires_both_tools(self):
        log_cb = MagicMock()
        # pdftoppm exists, tesseract missing.
        def which(name):
            return "/usr/bin/pdftoppm" if name == "pdftoppm" else None
        with patch("nlm_scrubber_mac_gui.shutil.which", side_effect=which):
            result = extract_text_from_pdf_ocr("/x.pdf", log_cb)
        self.assertIsNone(result)
        log_cb.assert_called_once()
        self.assertIn("tesseract", log_cb.call_args[0][0])

    def test_ocr_concatenates_page_text(self):
        log_cb = MagicMock()
        # Pretend both tools exist.
        with patch("nlm_scrubber_mac_gui.shutil.which", return_value="/usr/bin/x"), \
             patch("nlm_scrubber_mac_gui.tempfile.TemporaryDirectory") as mock_td, \
             patch("nlm_scrubber_mac_gui.subprocess.run") as mock_run, \
             patch("nlm_scrubber_mac_gui.os.listdir", return_value=["page-1.png", "page-2.png"]):
            # tempfile context manager — yield a fake dir path.
            mock_td.return_value.__enter__.return_value = "/tmp/fake"
            mock_td.return_value.__exit__.return_value = False
            # subprocess.run is called once for pdftoppm, then once per page for tesseract.
            mock_run.side_effect = [
                self._completed(),  # pdftoppm
                self._completed(stdout="page 1 text"),
                self._completed(stdout="page 2 text"),
            ]
            result = extract_text_from_pdf_ocr("/scanned.pdf", log_cb)
        self.assertEqual(result, "page 1 text\npage 2 text")


class TestPartialOutputCleanup(unittest.TestCase):
    """The cleanup helpers are static methods on ScrubberApp but pure-logic;
    we instantiate via the class object without ever building a Tk root.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, relpath: str) -> None:
        full = os.path.join(self.tmp, relpath)
        os.makedirs(os.path.dirname(full) or self.tmp, exist_ok=True)
        open(full, "w").close()

    def _snapshot(self) -> set:
        from nlm_scrubber_mac_gui import ScrubberApp
        return ScrubberApp._snapshot_dir(self.tmp)

    def _cleanup(self, snapshot: set) -> int:
        from nlm_scrubber_mac_gui import ScrubberApp
        return ScrubberApp._cleanup_partial_output(self.tmp, snapshot)

    def test_snapshot_empty_dir(self):
        self.assertEqual(self._snapshot(), set())

    def test_snapshot_finds_nested_files(self):
        self._touch("a.txt")
        self._touch("sub/b.txt")
        snap = self._snapshot()
        self.assertIn("a.txt", snap)
        self.assertIn(os.path.join("sub", "b.txt"), snap)

    def test_cleanup_removes_only_new_files(self):
        self._touch("keep.txt")
        snap_before = self._snapshot()
        # Scrubber "writes" two new files.
        self._touch("new1.txt")
        self._touch("sub/new2.txt")
        removed = self._cleanup(snap_before)
        self.assertEqual(removed, 2)
        # Pre-existing file untouched; new files gone.
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "keep.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "new1.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "sub", "new2.txt")))
        # Empty subdir created by scrubber is also tidied.
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "sub")))

    def test_cleanup_handles_missing_dir(self):
        import nlm_scrubber_mac_gui as m
        self.assertEqual(m.ScrubberApp._cleanup_partial_output("/nonexistent/path", set()), 0)


class TestTallyRedactions(unittest.TestCase):
    """_tally_redactions routes token categories, including EU/Spain validator
    tokens which must land in their own bucket, not Numbers/IDs.
    """

    def _counts(self) -> dict:
        return {
            "Total PHI tokens replaced": 0,
            "Dates": 0,
            "Names": 0,
            "Numbers/IDs": 0,
            "Locations": 0,
            "EU/Spain IDs": 0,
            "Other": 0,
        }

    def test_eu_tokens_routed_to_own_bucket(self):
        from nlm_scrubber_mac_gui import ScrubberApp
        counts = self._counts()
        text = "**NAME** has **ES_DNI**, **IBAN**, **ES_PHONE** on **DATE**"
        ScrubberApp._tally_redactions(text, counts)
        self.assertEqual(counts["EU/Spain IDs"], 3)
        self.assertEqual(counts["Names"], 1)
        self.assertEqual(counts["Dates"], 1)
        # EU tokens must NOT leak into the generic Numbers/IDs bucket.
        self.assertEqual(counts["Numbers/IDs"], 0)
        self.assertEqual(counts["Total PHI tokens replaced"], 5)

    def test_us_id_tokens_still_numbers(self):
        from nlm_scrubber_mac_gui import ScrubberApp
        counts = self._counts()
        ScrubberApp._tally_redactions("**SSN** and **PHONE**", counts)
        self.assertEqual(counts["Numbers/IDs"], 2)
        self.assertEqual(counts["EU/Spain IDs"], 0)

    def test_every_eu_token_routes_to_eu_bucket(self):
        # Drive the router from the same EU_TOKENS set the validators module emits,
        # so this fails if the router and the token set ever drift apart.
        from nlm_scrubber_mac_gui import ScrubberApp
        from validators import EU_TOKENS

        counts = self._counts()
        text = " ".join(f"**{token}**" for token in sorted(EU_TOKENS))
        ScrubberApp._tally_redactions(text, counts)
        self.assertEqual(counts["EU/Spain IDs"], len(EU_TOKENS))
        self.assertEqual(counts["Numbers/IDs"], 0)
        self.assertEqual(counts["Total PHI tokens replaced"], len(EU_TOKENS))


if __name__ == "__main__":
    unittest.main()
