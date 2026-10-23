"""Admin-only sign-in for Payslip Manager (no Google / no third-party login).

Design
- One admin account. Fails CLOSED: if no admin is configured nothing in the app is shown.
- Password is never stored; only a salted scrypt hash (stdlib, memory-hard).
- Optional TOTP (authenticator-app) second factor, RFC 6238, stdlib only, with replay protection.
- Global brute-force lockout that survives restarts and cannot be dodged by opening new sessions.
- Idle timeout + absolute session lifetime. Logout wipes the session and cached workbook data.
- Credentials come from (first found): environment variables, Streamlit secrets, config/admin.json.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import struct
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from .config import BASE_DIR, CONFIG_DIR, ENV_FILE, load_dotenv
from .logsetup import get_logger

ADMIN_FILE = CONFIG_DIR / "admin.json"
STATE_FILE = CONFIG_DIR / ".auth_state.json"

MIN_PASSWORD_LEN = 12
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
SCRYPT_MAXMEM = 128 * 1024 * 1024

IDLE_TIMEOUT_S = int(os.environ.get("PAYSLIP_IDLE_MINUTES", "20")) * 60
MAX_SESSION_S = int(os.environ.get("PAYSLIP_MAX_SESSION_HOURS", "8")) * 3600
FREE_ATTEMPTS = 5          # failures allowed before the lockout starts
BASE_LOCK_S = 30           # first lockout; doubles each further failure
MAX_LOCK_S = 3600

_lock = threading.Lock()


# ----------------------------------------------------------------------------- password hashing
def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                        maxmem=SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=_b64d(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=SCRYPT_MAXMEM, dklen=len(_b64d(dk)))
        return hmac.compare_digest(calc, _b64d(dk))
    except (ValueError, TypeError, binascii.Error):
        return False


def password_problem(password: str) -> Optional[str]:
    """Plain-language reason the password is too weak, or None."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Use at least {MIN_PASSWORD_LEN} characters."
    if len(set(password)) < 6:
        return "Use a wider mix of characters."
    classes = sum(any(f(c) for c in password) for f in (str.islower, str.isupper, str.isdigit,
                                                         lambda c: not c.isalnum()))
    if classes < 3:
        return "Mix at least three of: lowercase, UPPERCASE, numbers, symbols."
    if password.lower() in {"password1234", "123456789012", "qwertyuiop12", "admin1234567"}:
        return "That password is too common."
    return None


# ----------------------------------------------------------------------------- TOTP (RFC 6238)
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_counter(now: Optional[float] = None) -> int:
    return int((time.time() if now is None else now) // 30)


def verify_totp(secret_b32: str, code: str, last_counter: int = 0,
                now: Optional[float] = None) -> Optional[int]:
    """Return the matched time-step counter (to store against replay), or None."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != 6:
        return None
    base = totp_counter(now)
    for c in (base - 1, base, base + 1):
        if c > last_counter and hmac.compare_digest(_hotp(secret_b32, c), code):
            return c
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str = "Payslip Manager") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30")


# ----------------------------------------------------------------------------- credentials
@dataclass
class Credentials:
    username: str
    password_hash: str
    totp_secret: str = ""


def _secret_from_streamlit(name: str) -> str:
    try:
        import streamlit as st
        return str(st.secrets.get(name, "") or "")
    except Exception:
        return ""


def load_credentials() -> Optional[Credentials]:
    """Environment (.env / os.environ) -> Streamlit secrets -> config/admin.json. None = not configured."""
    try:
        load_dotenv(ENV_FILE)
    except Exception:
        pass

    def pick(*names: str) -> str:
        for name in names:
            v = os.environ.get(name, "").strip() or _secret_from_streamlit(name).strip()
            if v:
                return v
        lower_names = {n.lower(): n for n in names}
        for k, v in os.environ.items():
            if k.lower() in lower_names and v.strip():
                return v.strip()
        return ""

    user = pick("PAYSLIP_ADMIN_USER", "ENV_USERNAME", "ADMIN_USERNAME", "ADMIN_USER")
    phash = pick("PAYSLIP_ADMIN_HASH", "ENV_PASSWORD_HASH", "ADMIN_PASSWORD_HASH", "ADMIN_HASH", "PASSWORD_HASH")
    totp = pick("PAYSLIP_ADMIN_TOTP", "ENV_TOTP_SECRET", "ADMIN_TOTP", "ADMIN_TOTP_SECRET", "TOTP_SECRET")

    if user and phash:
        return Credentials(user, phash, totp)
    try:
        if ADMIN_FILE.exists():
            d = json.loads(ADMIN_FILE.read_text(encoding="utf-8"))
            if d.get("username") and d.get("password_hash"):
                return Credentials(str(d["username"]), str(d["password_hash"]), str(d.get("totp_secret", "")))
    except (OSError, ValueError):
        pass
    return None


def save_credentials_env(c: Credentials, path: Optional[Path] = None) -> Path:
    """Save admin credentials directly into a protected .env file."""
    target = path or ENV_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("# Payslip Manager Admin Credentials\n")
            fh.write(f"PAYSLIP_ADMIN_USER={c.username}\n")
            fh.write(f"PAYSLIP_ADMIN_HASH={c.password_hash}\n")
            if c.totp_secret:
                fh.write(f"PAYSLIP_ADMIN_TOTP={c.totp_secret}\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass

    os.environ["PAYSLIP_ADMIN_USER"] = c.username
    os.environ["PAYSLIP_ADMIN_HASH"] = c.password_hash
    if c.totp_secret:
        os.environ["PAYSLIP_ADMIN_TOTP"] = c.totp_secret
    return target


def save_credentials_file(c: Credentials) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"username": c.username, "password_hash": c.password_hash,
                       "totp_secret": c.totp_secret}, fh, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, ADMIN_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return ADMIN_FILE


# ----------------------------------------------------------------------------- lockout state
def _read_state() -> Dict[str, Any]:
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(d: Dict[str, Any]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(CONFIG_DIR), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass  # best effort; the in-session delay still applies


def lock_remaining(now: Optional[float] = None) -> int:
    """Seconds until sign-in is allowed again (0 = allowed)."""
    now = time.time() if now is None else now
    with _lock:
        return max(0, int(_read_state().get("locked_until", 0) - now + 0.999))


def _register_failure(now: float) -> None:
    with _lock:
        st = _read_state()
        fails = int(st.get("failures", 0)) + 1
        st["failures"] = fails
        if fails >= FREE_ATTEMPTS:
            st["locked_until"] = now + min(MAX_LOCK_S, BASE_LOCK_S * 2 ** (fails - FREE_ATTEMPTS))
        _write_state(st)


def _register_success(totp_counter_used: Optional[int]) -> None:
    with _lock:
        st = _read_state()
        st.update(failures=0, locked_until=0)
        if totp_counter_used:
            st["last_totp"] = totp_counter_used
        _write_state(st)


def _last_totp() -> int:
    with _lock:
        return int(_read_state().get("last_totp", 0))


# ----------------------------------------------------------------------------- login check
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))  # equalises timing for unknown usernames


def check_login(username: str, password: str, totp_code: str, creds: Credentials,
                now: Optional[float] = None) -> Tuple[bool, str]:
    """Returns (ok, message). Message is deliberately generic on failure."""
    now = time.time() if now is None else now
    wait = lock_remaining(now)
    if wait:
        return False, f"Too many failed attempts. Try again in {_fmt_wait(wait)}."

    user_ok = hmac.compare_digest(username.strip().encode(), creds.username.encode())
    pw_ok = verify_password(password, creds.password_hash if user_ok else _DUMMY_HASH)
    totp_used: Optional[int] = None
    totp_ok = True
    if creds.totp_secret:
        totp_used = verify_totp(creds.totp_secret, totp_code, _last_totp(), now)
        totp_ok = totp_used is not None

    if user_ok and pw_ok and totp_ok:
        _register_success(totp_used)
        get_logger().info("SECURITY admin sign-in succeeded")
        return True, ""
    _register_failure(now)
    get_logger().warning("SECURITY failed sign-in attempt")
    time.sleep(0.8)
    return False, "Sign-in details are incorrect."


def _fmt_wait(s: int) -> str:
    return f"{s} seconds" if s < 90 else f"{(s + 59) // 60} minutes"


# ----------------------------------------------------------------------------- session helpers
SESSION_KEY = "_ps_auth"


def session_state_valid(state: Optional[Dict[str, Any]], now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    if not state or not state.get("ok"):
        return False
    if now - state.get("t0", 0) > MAX_SESSION_S:
        return False
    if now - state.get("last", 0) > IDLE_TIMEOUT_S:
        return False
    return True


def new_session(now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    return {"ok": True, "t0": now, "last": now}
