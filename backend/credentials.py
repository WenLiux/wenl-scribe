"""Small Windows-user-scoped credential store for the desktop app.

The portable app should not need a third-party keyring dependency.  Windows
Data Protection API (DPAPI) encrypts the value for the current Windows user;
the encrypted file can be copied as application data without exposing the
secret in readable JSON.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class CredentialStorageUnavailable(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _crypt32():
    if os.name != "nt":
        raise CredentialStorageUnavailable("Windows DPAPI 仅在 Windows 上可用")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return crypt32, kernel32


def _protect(value: str) -> str:
    crypt32, kernel32 = _crypt32()
    raw = value.encode("utf-8")
    source = ctypes.create_string_buffer(raw)
    source_blob = _DataBlob(len(raw), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    result_blob = _DataBlob()
    if not crypt32.CryptProtectData(ctypes.byref(source_blob), "WENL Scribe", None, None, None, 0, ctypes.byref(result_blob)):
        raise CredentialStorageUnavailable("Windows DPAPI 加密失败")
    try:
        encrypted = ctypes.string_at(result_blob.pbData, result_blob.cbData)
    finally:
        kernel32.LocalFree(result_blob.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect(value: str) -> str:
    crypt32, kernel32 = _crypt32()
    raw = base64.b64decode(value.encode("ascii"), validate=True)
    source = ctypes.create_string_buffer(raw)
    source_blob = _DataBlob(len(raw), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    result_blob = _DataBlob()
    description = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(ctypes.byref(source_blob), ctypes.byref(description), None, None, None, 0, ctypes.byref(result_blob)):
        raise CredentialStorageUnavailable("Windows DPAPI 解密失败")
    try:
        plain = ctypes.string_at(result_blob.pbData, result_blob.cbData)
    finally:
        if description:
            kernel32.LocalFree(description)
        kernel32.LocalFree(result_blob.pbData)
    return plain.decode("utf-8")


def _read_store(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_store(path: Path, value: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_secret(path: Path, reference: str) -> str:
    if not reference or not path.exists():
        return ""
    encoded = _read_store(path).get(reference, "")
    if not encoded:
        return ""
    try:
        return _unprotect(encoded)
    except (CredentialStorageUnavailable, ValueError, UnicodeError):
        return ""


def write_secret(path: Path, reference: str, value: str) -> None:
    if not reference:
        raise ValueError("credential reference 不能为空")
    store = _read_store(path)
    if value:
        store[reference] = _protect(value)
    else:
        store.pop(reference, None)
    _write_store(path, store)


def delete_secret(path: Path, reference: str) -> None:
    if not reference or not path.exists():
        return
    store = _read_store(path)
    if reference in store:
        store.pop(reference, None)
        _write_store(path, store)
