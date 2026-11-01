"""Read the muse.ai login straight from a Chromium browser's cookie store on macOS.

Chromium keeps cookies in a SQLite file. Values are AES-128-CBC encrypted with
a key derived from the browser's "Safe Storage" password in the login
keychain, so macOS asks the user once before `security` may read it. Nothing
here needs Node.js or a debugging port, and the browser can stay closed.
"""
import ctypes
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

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


class BrowserCookieError(RuntimeError):
    pass


def supported():
    return sys.platform == "darwin"


def cookie_stores(names=None):
    """(browser, profile, path) for every cookie database that exists."""
    found = []
    for name in names or BROWSERS:
        base = os.path.join(SUPPORT, BROWSERS[name][0])
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


def _muse_rows(path):
    """Encrypted muse.ai rows from a copy of the database (the browser locks the original)."""
    tmp = tempfile.mkdtemp(prefix="muse-cli-")   # mode 0700
    try:
        copy = os.path.join(tmp, "Cookies")
        shutil.copy(path, copy)
        if os.path.exists(path + "-wal"):
            shutil.copy(path + "-wal", copy + "-wal")
        db = sqlite3.connect(copy)
        try:
            return db.execute(
                "SELECT host_key, name, path, is_secure, expires_utc, value, encrypted_value "
                "FROM cookies WHERE host_key = 'muse.ai' OR host_key LIKE '%.muse.ai'").fetchall()
        finally:
            db.close()
    except sqlite3.Error as e:
        raise BrowserCookieError(f"cannot read {path}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_storage_key(service, account):
    try:
        r = subprocess.run(["security", "find-generic-password", "-w", "-s", service, "-a", account],
                           capture_output=True, text=True, timeout=KEYCHAIN_WAIT)
    except subprocess.TimeoutExpired:
        raise BrowserCookieError("timed out waiting for the macOS keychain prompt")
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
    secure, expires. The keychain is asked only once a profile with a
    `hatch_sess` row is found, so a browser without a muse.ai login never
    triggers a prompt. Raises BrowserCookieError with a reason otherwise.
    """
    if not supported():
        raise BrowserCookieError("reading browser cookies directly is macOS-only")
    names = None if browser == "auto" else [browser]
    stores = cookie_stores(names)
    if not stores:
        raise BrowserCookieError("no Chromium-based browser profile found"
                                 if names is None else f"no {browser} profile found")
    logged_in = []
    for name, profile, path in stores:
        rows = _muse_rows(path)
        sess = [r for r in rows if r[1] == "hatch_sess"]
        if sess:
            logged_in.append((max(r[4] for r in sess), name, profile, rows))
    if not logged_in:
        raise BrowserCookieError("no muse.ai login (hatch_sess) in " +
                                 ", ".join(sorted({f"{n} {p}" for n, p, _ in stores})))
    _, name, profile, rows = max(logged_in, key=lambda t: t[0])
    _, service, account = BROWSERS[name]
    key = key_for(service, account)
    jar = []
    for host, cname, cpath, secure, expires, value, blob in rows:
        jar.append({"name": cname, "domain": host, "path": cpath or "/",
                    "secure": bool(secure), "expires": _expires(expires),
                    "value": _decrypt(blob, key, host, decrypt) if blob else value})
    return jar, f"{name} ({profile})"
