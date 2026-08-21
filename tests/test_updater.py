"""
tests/test_updater.py

Тесты проверки обновлений: парсинг и сравнение версий, парсинг ответа
GitHub API, логика «не спрашивать до следующей версии».
"""

import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import updater


class TestParseVersion(unittest.TestCase):

    def test_plain(self):
        self.assertEqual(updater.parse_version("4.24.7"), (4, 24, 7))

    def test_v_prefix(self):
        self.assertEqual(updater.parse_version("v4.24.7"), (4, 24, 7))

    def test_with_spaces(self):
        self.assertEqual(updater.parse_version("  4.1.0  "), (4, 1, 0))

    def test_suffix_ignored(self):
        self.assertEqual(updater.parse_version("4.24.7-rc1"), (4, 24, 7))

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            updater.parse_version("abc")
        with self.assertRaises(ValueError):
            updater.parse_version("4.24")
        with self.assertRaises(ValueError):
            updater.parse_version("")


class TestVersionNewer(unittest.TestCase):

    def test_newer(self):
        self.assertTrue(updater.version_newer("4.24.7", "4.24.6"))
        self.assertTrue(updater.version_newer("5.0.0", "4.99.99"))
        self.assertTrue(updater.version_newer("4.24.6", "4.24.5"))

    def test_not_newer(self):
        self.assertFalse(updater.version_newer("4.24.6", "4.24.6"))
        self.assertFalse(updater.version_newer("4.24.5", "4.24.6"))
        self.assertFalse(updater.version_newer("v4.24.5", "4.24.6"))

    def test_garbage_is_not_newer(self):
        self.assertFalse(updater.version_newer("latest", "4.24.6"))
        self.assertFalse(updater.version_newer("", "4.24.6"))


class TestFetchLatest(unittest.TestCase):

    def _payload(self, tag="v4.24.7"):
        return {
            "tag_name": tag,
            "html_url": "https://github.com/alekosExclusiveVersion/"
                        "parallels-sql-admins/releases/tag/v4.24.7",
            "assets": [
                {"name": "ParallelsSQLAdmin-linux.tar.gz",
                 "browser_download_url": "https://ex/l.tar.gz"},
                {"name": f"ParallelsSQLAdmin-Setup-{tag.lstrip('v')}.exe",
                 "browser_download_url": "https://ex/Setup.exe"},
            ],
        }

    def test_parses_release_and_finds_setup(self):
        with mock.patch.object(updater, "_request_json",
                               return_value=self._payload()):
            info = updater.fetch_latest()
        self.assertEqual(info.version, "4.24.7")
        self.assertEqual(info.url, "https://ex/Setup.exe")
        self.assertIn("releases/tag", info.html_url)

    def test_no_setup_asset_uses_deterministic_url(self):
        payload = self._payload()
        payload["assets"] = [{"name": "other.zip",
                              "browser_download_url": "https://ex/o.zip"}]
        with mock.patch.object(updater, "_request_json", return_value=payload):
            info = updater.fetch_latest()
        self.assertEqual(info.version, "4.24.7")
        self.assertEqual(info.url, updater.setup_download_url("4.24.7"))

    def test_setup_download_url_format(self):
        self.assertEqual(
            updater.setup_download_url("4.24.8"),
            "https://github.com/alekosExclusiveVersion/parallels-sql-admins/"
            "releases/download/v4.24.8/ParallelsSQLAdmin-Setup-4.24.8.exe",
        )
        self.assertEqual(
            updater.setup_download_url("v4.24.8"),
            updater.setup_download_url("4.24.8"),
        )

    def test_missing_tag_raises(self):
        with mock.patch.object(updater, "_request_json", return_value={}):
            with self.assertRaises(ValueError):
                updater.fetch_latest()

    def test_invalid_json_raises(self):
        with mock.patch.object(updater, "_request_json", side_effect=ValueError):
            with self.assertRaises(ValueError):
                updater.fetch_latest()


class TestShouldNotify(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._state = Path(self._tmp.name) / "updates.json"
        self._patcher = mock.patch.object(updater, "_state_path",
                                          return_value=self._state)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def _info(self, version="4.24.7"):
        return updater.UpdateInfo(version=version, url=None,
                                  html_url=updater.RELEASES_URL)

    def test_notify_by_default(self):
        self.assertTrue(updater.should_notify(self._info()))

    def test_dont_ask_blocks_same_version(self):
        updater.set_dont_ask_until("4.24.7")
        self.assertFalse(updater.should_notify(self._info("4.24.7")))
        self.assertFalse(updater.should_notify(self._info("4.24.6")))

    def test_dont_ask_newer_version_notifies(self):
        updater.set_dont_ask_until("4.24.7")
        self.assertTrue(updater.should_notify(self._info("4.24.8")))

    def test_broken_state_notifies(self):
        self._state.write_text("{{{ не json", encoding="utf-8")
        self.assertTrue(updater.should_notify(self._info()))

    def test_dont_ask_persisted(self):
        updater.set_dont_ask_until("4.24.7")
        self.assertEqual(json.loads(self._state.read_text()),
                         {"dont_ask_until": "4.24.7"})


class TestDownload(unittest.TestCase):

    def test_download_writes_file(self):
        class FakeResp:
            headers = {"Content-Length": "5"}

            def read(self, size):
                if not hasattr(self, "_done"):
                    self._done = False
                if self._done:
                    return b""
                self._done = True
                return b"hello"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "setup.exe"
            with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
                updater.download("https://ex/Setup.exe", dest)
            self.assertEqual(dest.read_bytes(), b"hello")


class TestSSLContext(unittest.TestCase):

    def test_ssl_ctx_is_ssl_context(self):
        self.assertIsInstance(updater._SSL_CTX, ssl.SSLContext)

    def test_request_json_uses_ssl_context(self):
        class FakeResp:
            headers = {}

            def read(self, sz=0):
                return b'{"ok":true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = FakeResp()
            updater._request_json("https://example.com/api", timeout=5)
            _, kwargs = mock_open.call_args
            self.assertIs(kwargs.get("context"), updater._SSL_CTX)

    def test_download_uses_ssl_context(self):
        class FakeResp:
            headers = {"Content-Length": "5"}

            def read(self, sz=0):
                if not hasattr(self, "_done"):
                    self._done = False
                if self._done:
                    return b""
                self._done = True
                return b"hello"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "setup.exe"
            with mock.patch("urllib.request.urlopen") as mock_open:
                mock_open.return_value = FakeResp()
                updater.download("https://ex/Setup.exe", dest)
                _, kwargs = mock_open.call_args
                self.assertIs(kwargs.get("context"), updater._SSL_CTX)


if __name__ == "__main__":
    unittest.main()
