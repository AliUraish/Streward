"""Ed25519 attestation signing over canonical JSON.

Key file: <data dir>/signing.key (PKCS8 PEM, mode 0600, created on first use). The payload that is
signed is the canonical JSON (sorted keys, no spaces, ASCII) of the attestation without `signature`.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

VERIFIER_VERSION = "steward-verify/1"
_lock = threading.Lock()
_cache: dict[str, Ed25519PrivateKey] = {}


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _load_or_create(key_path: Path) -> Ed25519PrivateKey:
    key = str(key_path.resolve())
    with _lock:
        if key in _cache:
            return _cache[key]
        if key_path.exists():
            private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if not isinstance(private, Ed25519PrivateKey):
                raise ValueError("signing.key is not an Ed25519 private key.")
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            private = Ed25519PrivateKey.generate()
            pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())
            descriptor = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(pem)
            os.chmod(key_path, 0o600)
        _cache[key] = private
        return private


class Signer:
    def __init__(self, directory: Path):
        self.key_path = Path(directory) / "signing.key"
        self._private = _load_or_create(self.key_path)

    @property
    def public_key_b64(self) -> str:
        raw = self._private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return base64.b64encode(raw).decode("ascii")

    def sign(self, payload: dict) -> tuple[str, str]:
        signature = self._private.sign(canonical_json(payload))
        return base64.b64encode(signature).decode("ascii"), self.public_key_b64


def sign(payload: dict, directory: Path) -> tuple[str, str]:
    """Sign a payload dict with the key stored under `directory`; returns (signature_b64, public_key_b64)."""
    return Signer(directory).sign(payload)


def verify(payload: dict, signature_b64: str, public_key_b64: str) -> bool:
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        public.verify(base64.b64decode(signature_b64), canonical_json(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
