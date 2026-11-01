import ctypes
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from muse_cli import browsers

KEY = b"k" * 16


def fake_decrypt(key, iv, data):
    return data


def blob(host, value, prefix=True):
    digest = hashlib.sha256(host.encode()).digest() if prefix else b""
    return b"v10" + digest + value.encode()


def make_db(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, path TEXT, is_secure INTEGER, "
               "expires_utc INTEGER, value TEXT, encrypted_value BLOB)")
    db.executemany("INSERT INTO cookies VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


def row(host, name, value, expires=13400000000000000, plain=None):
    return (host, name, "/", 1, expires, plain or "", b"" if plain else blob(host, value))


class ReadCookiesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(browsers, "SUPPORT", self.tmp.name)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(browsers, "supported", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        p = patch("time.time", return_value=1700000000)
        p.start()
        self.addCleanup(p.stop)
        self.asked = []

    def key_for(self, service, account):
        self.asked.append(service)
        return KEY

    def read(self, browser="auto"):
        return browsers.read_cookies(browser, key_for=self.key_for, decrypt=fake_decrypt)

    def chrome(self, profile, rows, network=True):
        sub = "Network/Cookies" if network else "Cookies"
        make_db(os.path.join(self.tmp.name, "Google/Chrome", profile, sub), rows)

    def test_decrypts_muse_cookies_and_strips_host_hash(self):
        self.chrome("Default", [
            row(".muse.ai", "hatch_sess", "SESS"),
            row("muse.ai", "hatch_native_auth_device", "DEV"),
            row(".example.com", "other", "NOPE"),
            row(".notmuse.ai", "other", "NOPE"),
            row("other.muse.ai", "hatch_sess", "SUBDOMAIN"),
            row(".other.muse.ai", "subdomain_only", "NOPE"),
        ])
        jar, source = self.read()
        self.assertEqual(source, "chrome (Default)")
        self.assertEqual({c["name"]: c["value"] for c in jar},
                         {"hatch_sess": "SESS", "hatch_native_auth_device": "DEV"})
        sess = next(c for c in jar if c["name"] == "hatch_sess")
        self.assertEqual((sess["domain"], sess["path"], sess["secure"]), (".muse.ai", "/", True))
        self.assertEqual(sess["expires"], 13400000000 - 11644473600)

    def test_value_without_host_hash_prefix_and_plaintext_rows(self):
        self.chrome("Default", [
            ("muse.ai", "hatch_sess", "/", 0, 0, "", blob("muse.ai", "OLD", prefix=False)),
            ("muse.ai", "theme", "/", 0, 0, "dark", b""),
        ], network=False)
        jar, _ = self.read()
        self.assertEqual({c["name"]: c["value"] for c in jar}, {"hatch_sess": "OLD", "theme": "dark"})
        self.assertEqual(jar[0]["expires"], 0)

    def test_picks_the_logged_in_profile_and_asks_keychain_once(self):
        self.chrome("Profile 1", [row(".muse.ai", "theme", "x")])
        self.chrome("Profile 2", [row(".muse.ai", "hatch_sess", "P2", expires=13360000000000000)])
        self.chrome("Profile 3", [row(".muse.ai", "hatch_sess", "P3", expires=13400000000000000)])
        jar, source = self.read()
        self.assertEqual(source, "chrome (Profile 3)")
        self.assertEqual(next(c["value"] for c in jar if c["name"] == "hatch_sess"), "P3")
        self.assertEqual(self.asked, ["Chrome Safe Storage"])

    def test_no_login_never_touches_the_keychain(self):
        self.chrome("Default", [row(".muse.ai", "theme", "x")])
        with self.assertRaisesRegex(browsers.BrowserCookieError, "no muse.ai login"):
            self.read()
        self.assertEqual(self.asked, [])

    def test_subdomain_login_does_not_authenticate_muse_ai(self):
        self.chrome("Default", [row("other.muse.ai", "hatch_sess", "SUBDOMAIN")])
        with self.assertRaisesRegex(browsers.BrowserCookieError, "no muse.ai login"):
            self.read()
        self.assertEqual(self.asked, [])

    def test_subdomain_login_does_not_hide_a_usable_profile(self):
        self.chrome("Default", [row(".other.muse.ai", "hatch_sess", "SUBDOMAIN")])
        self.chrome("Profile 1", [row("muse.ai", "hatch_sess", "LIVE", expires=0)])
        jar, source = self.read()
        self.assertEqual(source, "chrome (Profile 1)")
        self.assertEqual(jar[0]["value"], "LIVE")
        self.assertEqual(self.asked, ["Chrome Safe Storage"])

    def test_expired_login_never_touches_the_keychain(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "OLD",
                                    expires=13300000000000000)])
        with self.assertRaisesRegex(browsers.BrowserCookieError, "no muse.ai login"):
            self.read()
        self.assertEqual(self.asked, [])

    def test_expired_cookies_are_not_exported_or_decrypted(self):
        self.chrome("Default", [
            row(".muse.ai", "hatch_sess", "LIVE", expires=0),
            (".muse.ai", "old", "/", 1, 13300000000000000, "", b"v99bad"),
        ])
        jar, _ = self.read()
        self.assertEqual([c["name"] for c in jar], ["hatch_sess"])

    def test_empty_session_does_not_hide_a_usable_profile(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "")])
        self.chrome("Profile 1", [row(".muse.ai", "hatch_sess", "LIVE", expires=0)])
        jar, source = self.read()
        self.assertEqual(source, "chrome (Profile 1)")
        self.assertEqual(jar[0]["value"], "LIVE")
        self.assertEqual(self.asked, ["Chrome Safe Storage"])

    def test_empty_session_is_not_a_login(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "")])
        with self.assertRaisesRegex(browsers.BrowserCookieError, "no muse.ai login"):
            self.read()

    def test_broken_database_does_not_hide_a_usable_profile(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "BROKEN")])
        path = os.path.join(self.tmp.name, "Google/Chrome/Default/Network/Cookies")
        with open(path, "wb") as fh:
            fh.write(b"not sqlite")
        self.chrome("Profile 1", [row(".muse.ai", "hatch_sess", "LIVE")])
        jar, source = self.read()
        self.assertEqual(source, "chrome (Profile 1)")
        self.assertEqual(jar[0]["value"], "LIVE")

    def test_bad_ciphertext_does_not_hide_a_usable_profile(self):
        self.chrome("Default", [(".muse.ai", "hatch_sess", "/", 1,
                                 13500000000000000, "", b"v99bad")])
        self.chrome("Profile 1", [row(".muse.ai", "hatch_sess", "LIVE")])
        jar, source = self.read()
        self.assertEqual(source, "chrome (Profile 1)")
        self.assertEqual(jar[0]["value"], "LIVE")
        self.assertEqual(self.asked, ["Chrome Safe Storage"])

    def test_keychain_denial_is_not_repeated_for_each_profile(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "A")])
        self.chrome("Profile 1", [row(".muse.ai", "hatch_sess", "B")])
        with patch.object(browsers, "_safe_storage_key",
                          side_effect=browsers.BrowserCookieError("denied")) as key:
            with self.assertRaisesRegex(browsers.BrowserCookieError, "denied"):
                browsers.read_cookies(key_for=key, decrypt=fake_decrypt)
        key.assert_called_once()

    def test_copy_permission_error_is_a_browser_error(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "X")])
        with patch.object(browsers.shutil, "copy", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(browsers.BrowserCookieError, "denied"):
                self.read()
        self.assertEqual(self.asked, [])

    def test_unreadable_profile_does_not_hide_another_browser(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "CHROME")])
        make_db(os.path.join(self.tmp.name, "BraveSoftware/Brave-Browser/Default/Cookies"),
                [row(".muse.ai", "hatch_sess", "BRAVE")])
        copy = shutil.copy

        def deny_chrome(src, dst):
            if "Google/Chrome" in src:
                raise PermissionError("denied")
            return copy(src, dst)

        with patch.object(browsers.shutil, "copy", side_effect=deny_chrome):
            jar, source = self.read()
        self.assertEqual(source, "brave (Default)")
        self.assertEqual(jar[0]["value"], "BRAVE")
        self.assertEqual(self.asked, ["Brave Safe Storage"])

    def test_keeps_changing_database_has_bounded_retries_and_cleans_up(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "X")])
        stamp = browsers._file_stamp
        copies = []
        copy = shutil.copy

        def changing_stamp(path):
            original = stamp(path)
            return (*original, len(copies)) if original else None

        def record_copy(src, dst):
            copies.append(dst)
            return copy(src, dst)

        with patch.object(browsers, "_file_stamp", side_effect=changing_stamp), \
                patch.object(browsers.shutil, "copy", side_effect=record_copy):
            with self.assertRaisesRegex(browsers.BrowserCookieError, "close the browser"):
                self.read()
        self.assertEqual(len(copies), 3)
        self.assertTrue(all(not os.path.exists(os.path.dirname(p)) for p in copies))
        self.assertEqual(self.asked, [])

    def test_retries_a_database_changed_during_copy(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "OLD")])
        path = os.path.join(self.tmp.name, "Google/Chrome/Default/Network/Cookies")
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        db.execute("PRAGMA journal_mode=WAL")
        copy = shutil.copy
        changed = []

        def copy_then_checkpoint(src, dst):
            result = copy(src, dst)
            if src == path and not changed:
                changed.append(True)
                db.execute("UPDATE cookies SET encrypted_value=?", (blob(".muse.ai", "NEW"),))
                db.commit()
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return result

        with patch.object(browsers.shutil, "copy", side_effect=copy_then_checkpoint):
            jar, _ = self.read()
        self.assertEqual(jar[0]["value"], "NEW")

    def test_reads_committed_wal_rows_but_not_uncommitted_changes(self):
        self.chrome("Default", [row(".muse.ai", "hatch_sess", "OLD")])
        path = os.path.join(self.tmp.name, "Google/Chrome/Default/Network/Cookies")
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE cookies SET encrypted_value=?", (blob(".muse.ai", "LIVE"),))
        db.commit()
        db.execute("UPDATE cookies SET encrypted_value=?", (blob(".muse.ai", "UNCOMMITTED"),))
        jar, _ = self.read()
        self.assertEqual(jar[0]["value"], "LIVE")

    def test_missing_browser_and_unknown_profiles(self):
        with self.assertRaisesRegex(browsers.BrowserCookieError, "no Chromium-based browser"):
            self.read()
        with self.assertRaisesRegex(browsers.BrowserCookieError, "no brave profile"):
            self.read("brave")
        self.chrome("Guest Profile", [row(".muse.ai", "hatch_sess", "X")])
        with self.assertRaisesRegex(browsers.BrowserCookieError, "no Chromium-based browser"):
            self.read()

    def test_other_browsers_use_their_own_keychain_entry(self):
        make_db(os.path.join(self.tmp.name, "BraveSoftware/Brave-Browser/Default/Cookies"),
                [row(".muse.ai", "hatch_sess", "B")])
        jar, source = self.read()
        self.assertEqual(source, "brave (Default)")
        self.assertEqual(self.asked, ["Brave Safe Storage"])

    def test_bad_encryption_format_and_garbage_are_errors(self):
        self.chrome("Default", [("muse.ai", "hatch_sess", "/", 1, 0, "", b"v99abc")])
        with self.assertRaisesRegex(browsers.BrowserCookieError, "unknown cookie encryption"):
            self.read()
        os.remove(os.path.join(self.tmp.name, "Google/Chrome/Default/Network/Cookies"))
        self.chrome("Default", [("muse.ai", "hatch_sess", "/", 1, 0, "", b"v10\xff\xfe\xfd")])
        with self.assertRaisesRegex(browsers.BrowserCookieError, "garbage"):
            self.read()

    def test_refuses_off_macos(self):
        with patch.object(browsers, "supported", return_value=False):
            with self.assertRaisesRegex(browsers.BrowserCookieError, "macOS-only"):
                self.read()


class KeychainTest(unittest.TestCase):
    def test_denied_keychain_is_a_browser_error(self):
        result = subprocess.CompletedProcess([], 1, "", "access denied")
        with patch.object(browsers.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(browsers.BrowserCookieError, "access denied"):
                browsers._safe_storage_key("Chrome Safe Storage", "Chrome")

    def test_keychain_timeout_does_not_print_captured_password(self):
        error = subprocess.TimeoutExpired("security", 120, output="private-password")
        with patch.object(browsers.subprocess, "run", side_effect=error):
            with self.assertRaisesRegex(browsers.BrowserCookieError, "timed out") as cm:
                browsers._safe_storage_key("Chrome Safe Storage", "Chrome")
        self.assertNotIn("private-password", str(cm.exception))

    def test_keychain_launch_error_is_a_browser_error(self):
        with patch.object(browsers.subprocess, "run", side_effect=OSError("cannot launch")):
            with self.assertRaisesRegex(browsers.BrowserCookieError, "cannot launch"):
                browsers._safe_storage_key("Chrome Safe Storage", "Chrome")


@unittest.skipUnless(sys.platform == "darwin", "CommonCrypto is macOS-only")
class AesTest(unittest.TestCase):
    def encrypt(self, key, iv, data):
        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        lib.CCCrypt.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                                ctypes.c_char_p, ctypes.c_size_t,
                                ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        out = ctypes.create_string_buffer(len(data) + 16)
        moved = ctypes.c_size_t()
        self.assertEqual(lib.CCCrypt(0, 0, 1, key, len(key), iv, data, len(data), out, len(out),
                                     ctypes.byref(moved)), 0)
        return out.raw[:moved.value]

    def test_chromium_value_round_trip(self):
        key = hashlib.pbkdf2_hmac("sha1", b"password", b"saltysalt", 1003, 16)
        host = ".muse.ai"
        plain = hashlib.sha256(host.encode()).digest() + "sess-é".encode()
        stored = b"v10" + self.encrypt(key, b" " * 16, plain)
        self.assertEqual(browsers._decrypt(stored, key, host), "sess-é")

    def test_wrong_key_is_an_error_not_garbage(self):
        stored = b"v10" + self.encrypt(b"a" * 16, b" " * 16, b"secret value here")
        with self.assertRaises(browsers.BrowserCookieError):
            browsers._decrypt(stored, b"b" * 16, "muse.ai")


if __name__ == "__main__":
    unittest.main()
