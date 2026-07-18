"""Tests for credential encryption/decryption."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from nexus.security.credentials import (
    decrypt_credential,
    encrypt_credential,
    _get_master_key,
)


class TestCredentialEncryption:
    """Test AES-256-GCM encryption roundtrip."""

    @pytest.fixture(autouse=True)
    def _set_master_key(self) -> None:
        os.environ["NEXUS_CREDENTIAL_MASTER_KEY"] = "test-master-key-32-bytes-!"
        from nexus.security.credentials import _KEY_CACHE, _KEY_REF
        _KEY_CACHE = None
        _KEY_REF = ""
        yield
        os.environ.pop("NEXUS_CREDENTIAL_MASTER_KEY", None)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        payload = {"token": "secret-token", "username": "admin", "password": "p@ss"}
        blob = encrypt_credential("basic", payload)
        assert isinstance(blob, str)
        assert len(blob) > 0

        decrypted = decrypt_credential(blob)
        assert decrypted["type"] == "basic"
        assert decrypted["token"] == "secret-token"
        assert decrypted["username"] == "admin"
        assert decrypted["password"] == "p@ss"

    def test_master_key_derived(self) -> None:
        key = _get_master_key()
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_different_payloads_different_encrypted(self) -> None:
        blob1 = encrypt_credential("bearer", {"token": "abc"})
        blob2 = encrypt_credential("bearer", {"token": "def"})
        assert blob1 != blob2

    def test_same_payload_different_encrypted(self) -> None:
        """Each encryption uses a random nonce, producing different blobs."""
        blob1 = encrypt_credential("api_key", {"key": "value"})
        blob2 = encrypt_credential("api_key", {"key": "value"})
        assert blob1 != blob2
        assert decrypt_credential(blob1) == decrypt_credential(blob2)
