"""Read the muse.ai login straight from a browser's cookie store.

Firefox, on every system: cookies.sqlite holds plain values, so nothing needs
decrypting.

Chromium browsers, macOS only: values are AES-128-CBC encrypted with a key
derived from the browser's "Safe Storage" password in the login keychain, so
macOS asks the user once before `security` may read it. (Windows Chromium uses
app-bound encryption that only the browser itself can undo.)

Nothing here needs Node.js or a debugging port, and the browser can stay closed.
"""
import ctypes
import glob
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

SUPPORT = os.path.expanduser("~/Library/Application Support")

# name -> (data dir under Application Support, keychain service, keychain account)
BROWSERS = {
    "chrome": ("Google/Chrome", "Chrome Safe Storage", "Chrome"),
    "brave": ("BraveSoftware/Brave-Browser", "Brave Safe Storage", "Brave"),
    "arc": ("Arc/User Data", "Arc Safe Storage", "Arc"),
    "edge": ("Microsoft Edge", "Microsoft Edge Safe Storage", "Microsoft Edge"),
    "chromium": ("Chromium", "Chromium Safe Storage", "Chromium"),
}

KEYCHAIN_WAIT = 120   # seconds; macOS shows an Allow dialog the first time

CHROMIUM_SQL = ("SELECT host_key, name, path, is_secure, expires_utc, value, encrypted_value "
                "FROM cookies WHERE host_key IN ('muse.ai', '.muse.ai')")
# Default container only: container tabs keep a second copy of each cookie.
FIREFOX_SQL = ("SELECT host, name, path, isSecure, expiry, value FROM moz_cookies "
               "WHERE host IN ('muse.ai', '.muse.ai') AND originAttributes = ''")


class BrowserCookieError(RuntimeError):
    pass


def supported():
    return sys.platform == "darwin"


def cookie_stores(names=None):
    """(browser, profile, path) for every cookie database that exists."""
    found = []
    for name in names or BROWSERS:
        try:
            data_dir = BROWSERS[name][0]
        except KeyError:
            raise BrowserCookieError(
                f"unknown browser '{name}'; choose from: "
                + ", ".join(["auto", *BROWSERS])
            ) from None
        base = os.path.join(SUPPORT, data_dir)
        try:
            profiles = sorted(os.listdir(base))
        except OSError:
            continue
        for profile in profiles:
            if profile != "Default" and not profile.startswith("Profile "):
                continue
            for rel in ("Network/Cookies", "Cookies"):
                path = os.path.join(base, profile, rel)
                if os.path.isfile(path):
                    found.append((name, profile, path))
                    break
    return found


def _file_stamp(path):
    try:
        s = os.stat(path)
    except FileNotFoundError:
        return None
    return s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def firefox_roots():
    """Directories that hold Firefox profile folders on this system."""
    if sys.platform == "win32":
        return [os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")]
    if sys.platform == "darwin":
        return [os.path.join(SUPPORT, "Firefox", "Profiles")]
    home = os.path.expanduser("~")
    return [os.path.join(home, rel) for rel in (
        ".mozilla/firefox", "snap/firefox/common/.mozilla/firefox",
        ".var/app/org.mozilla.firefox/.mozilla/firefox")]


def _firefox_expires(expiry):
    # Newer Firefox stores milliseconds, older seconds; 0 marks a session cookie.
    return int(expiry / 1000 if expiry > 1e11 else expiry or 0)


def read_firefox_cookies():
    """(jar, source) from the Firefox profile with the newest muse.ai login."""
    paths = sorted(p for root in firefox_roots()
                   for p in glob.glob(os.path.join(glob.escape(root), "*", "cookies.sqlite")))
    if not paths:
        raise BrowserCookieError("no Firefox profile found")
    now = time.time()
    best, errors = None, []
    for path in paths:
        try:
            rows = _muse_rows(path, FIREFOX_SQL)
        except BrowserCookieError as e:
            errors.append(str(e))
            continue
        jar = [{"name": name, "domain": host, "path": cpath or "/", "secure": bool(secure),
                "expires": _firefox_expires(expiry), "value": value or ""}
               for host, name, cpath, secure, expiry, value in rows]
        jar = [c for c in jar if not c["expires"] or c["expires"] > now]
        sess = [c["expires"] or float("inf") for c in jar if c["name"] == "hatch_sess" and c["value"]]
        if sess and (best is None or max(sess) > best[0]):
            best = (max(sess), jar, path)
    if best:
        return best[1], f"firefox ({os.path.basename(os.path.dirname(best[2]))})"
    if errors:
        raise BrowserCookieError("; ".join(errors))
    raise BrowserCookieError("no muse.ai login (hatch_sess) in Firefox")


def _muse_rows(path, sql=CHROMIUM_SQL):
    """muse.ai rows from a copy of the database (the browser locks the original)."""
    paths = [path, path + "-wal", path + "-journal"]
    try:
        for _ in range(3):
            before = [_file_stamp(p) for p in paths]
            with tempfile.TemporaryDirectory(prefix="muse-cli-") as tmp:  # mode 0700
                copy = os.path.join(tmp, "Cookies")
                try:
                    shutil.copy(path, copy)
                    for src, stamp in zip(paths[1:], before[1:]):
                        if stamp is not None:
                            shutil.copy(src, copy + src[len(path):])
                except FileNotFoundError:
                    continue
                # A checkpoint between copying the DB and WAL can silently lose cookies.
                if before != [_file_stamp(p) for p in paths]:
                    continue
                db = sqlite3.connect(copy)
                try:
                    return db.execute(sql).fetchall()
                finally:
                    db.close()
    except (OSError, sqlite3.Error) as e:
        raise BrowserCookieError(f"cannot read {path}: {e}")
    raise BrowserCookieError(f"cookie database changed while reading {path}; close the browser and retry")


def _safe_storage_key(service, account):
    try:
        r = subprocess.run(["security", "find-generic-password", "-w", "-s", service, "-a", account],
                           capture_output=True, text=True, timeout=KEYCHAIN_WAIT)
    except subprocess.TimeoutExpired:
        raise BrowserCookieError("timed out waiting for the macOS keychain prompt")
    except OSError as e:
        raise BrowserCookieError(f"could not read '{service}' from the keychain ({e})")
    if r.returncode != 0:
        why = (r.stderr or "").strip().splitlines()[-1:] or [f"exit {r.returncode}"]
        raise BrowserCookieError(f"could not read '{service}' from the keychain ({why[0]})")
    # 1003 rounds, fixed salt: Chromium's own derivation on macOS.
    return hashlib.pbkdf2_hmac("sha1", r.stdout.strip().encode(), b"saltysalt", 1003, 16)


def _aes_cbc_decrypt(key, iv, data):
    lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    lib.CCCrypt.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                            ctypes.c_char_p, ctypes.c_size_t,
                            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    out = ctypes.create_string_buffer(len(data) + 16)
    moved = ctypes.c_size_t()
    # op 1 = decrypt, algorithm 0 = AES, options 1 = PKCS7 padding
    rc = lib.CCCrypt(1, 0, 1, key, len(key), iv, data, len(data), out, len(out), ctypes.byref(moved))
    if rc != 0:
        raise BrowserCookieError(f"cookie decryption failed (CCCrypt {rc}); wrong keychain key?")
    return out.raw[:moved.value]


def _decrypt(blob, key, host, decrypt=_aes_cbc_decrypt):
    if blob[:3] not in (b"v10", b"v11"):
        raise BrowserCookieError("unknown cookie encryption format")
    plain = decrypt(key, b" " * 16, bytes(blob[3:]))
    # Chromium 130+ (cookie DB version 24) prefixes the value with SHA-256 of the host.
    if plain[:32] == hashlib.sha256(host.encode()).digest():
        plain = plain[32:]
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        raise BrowserCookieError("cookie decrypted to garbage; wrong keychain key?")


def _expires(chrome_us):
    # Chromium counts microseconds from 1601-01-01; 0 marks a session cookie.
    return int(chrome_us / 1e6 - 11644473600) if chrome_us else 0


def read_cookies(browser="auto", key_for=_safe_storage_key, decrypt=_aes_cbc_decrypt):
    """Return (jar, source) with the muse.ai cookies of the profile that is logged in.

    jar entries match what `auth export` writes: name, value, domain, path,
    secure, expires. The keychain is asked only once a profile with an
    unexpired `hatch_sess` row is found, so a browser without a muse.ai login never
    triggers a prompt. `auto` tries Chromium browsers first on macOS, then
    Firefox. Raises BrowserCookieError with a reason otherwise.
    """
    if browser == "firefox" or (browser == "auto" and not supported()):
        return read_firefox_cookies()
    if not supported():
        raise BrowserCookieError("reading Chromium browsers directly is macOS-only; "
                                 "use --browser firefox or agent-browser")
    try:
        return _read_chromium(browser, key_for, decrypt)
    except BrowserCookieError as e:
        if browser != "auto":
            raise
        try:
            return read_firefox_cookies()
        except BrowserCookieError as ff:
            raise BrowserCookieError(f"{e}; {ff}") from None


def _read_chromium(browser, key_for, decrypt):
    names = None if browser == "auto" else [browser]
    stores = cookie_stores(names)
    if not stores:
        raise BrowserCookieError("no Chromium-based browser profile found"
                                 if names is None else f"no {browser} profile found")
    logged_in, errors = [], []
    now = time.time()
    for name, profile, path in stores:
        try:
            rows = [r for r in _muse_rows(path) if not r[4] or _expires(r[4]) > now]
        except BrowserCookieError as e:
            errors.append(str(e))
            continue
        sess = [r for r in rows if r[1] == "hatch_sess"]
        if sess:
            logged_in.append((max(r[4] for r in sess), name, profile, rows))
    keys = {}
    for _, name, profile, rows in sorted(logged_in, key=lambda t: t[0], reverse=True):
        try:
            if name not in keys:
                _, service, account = BROWSERS[name]
                try:
                    keys[name] = key_for(service, account)
                except BrowserCookieError as e:
                    keys[name] = e
            key = keys[name]
            if isinstance(key, BrowserCookieError):
                raise key
            jar = []
            for host, cname, cpath, secure, expires, value, blob in rows:
                jar.append({"name": cname, "domain": host, "path": cpath or "/",
                            "secure": bool(secure), "expires": _expires(expires),
                            "value": _decrypt(blob, key, host, decrypt) if blob else value})
            if any(c["name"] == "hatch_sess" and c["value"] for c in jar):
                return jar, f"{name} ({profile})"
        except (BrowserCookieError, OSError) as e:
            errors.append(f"{name} ({profile}): {e}")
    if errors:
        raise BrowserCookieError("; ".join(errors))
    raise BrowserCookieError("no muse.ai login (hatch_sess) in " +
                             ", ".join(sorted({f"{n} {p}" for n, p, _ in stores})))
