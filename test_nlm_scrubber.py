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
    find_installed_binary,
    gather_files,
    get_latest_scrubber_url,
    is_supported_file,
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


if __name__ == "__main__":
    unittest.main()
