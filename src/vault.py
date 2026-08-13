"""Encrypted credential vault.

Device credentials are never stored in plaintext: the GUI/CLI 'setup'
flows write them into the SQLite `devices` table encrypted with a
Fernet (AES-128-CBC + HMAC) key held in data/.secret. That key file is
gitignored and created with the most restrictive ACL Windows allows.
"""
import os

from cryptography.fernet import Fernet, InvalidToken

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.join(BASE, "data", ".secret")

_key = None


def _load_or_create_key():
    global _key
    if _key is not None:
        return _key
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as fh:
            _key = fh.read().strip()
    else:
        os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
        _key = Fernet.generate_key()
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(_key)
    return _key


def encrypt(plain):
    """Encrypt a secret -> opaque token string ('' in -> '' out)."""
    if not plain:
        return ""
    return Fernet(_load_or_create_key()).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token):
    """Decrypt a token; returns '' on missing/corrupt data."""
    if not token:
        return ""
    try:
        return Fernet(_load_or_create_key()).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask(value, visible=3):
    """'s3cretValue42' -> '•••••••••42' (never fully shown in UI)."""
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= visible:
        return "\u2022" * len(value)
    return "\u2022" * (len(value) - visible) + value[-visible:]


def has_key():
    return os.path.exists(KEY_FILE)


def drop_key():
    """Delete the encryption key (used by 'wipe database')."""
    global _key
    _key = None
    try:
        if os.path.exists(KEY_FILE):
            os.remove(KEY_FILE)
    except OSError:
        pass
