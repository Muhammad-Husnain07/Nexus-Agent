"""ToolCredentialVault — encrypt/decrypt tool auth secrets using AES-256-GCM.

Master key is resolved from ``SecretResolver`` (env var / Vault).
Decrypted credentials are never logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from typing import Any

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from nexus.config.secrets import SecretResolver
from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.credential import ToolCredential

logger = structlog.get_logger("nexus.security.credentials")

_KEY_CACHE: bytes | None = None
_KEY_REF: str = ""


def _get_master_key() -> bytes:
    """Resolve the AES-256-GCM master key (32 bytes).

    The key is fetched once and cached.  The setting ``credential_master_key_ref``
    specifies which env var or Vault path to use.
    """
    global _KEY_CACHE, _KEY_REF  # noqa: PLW0603

    settings = get_settings()
    ref = settings.auth.credential_master_key_ref
    if _KEY_CACHE is not None and ref == _KEY_REF:
        return _KEY_CACHE

    resolver: SecretResolver
    if ref.startswith("env:"):
        from nexus.config.secrets import EnvSecretResolver

        resolver = EnvSecretResolver()
        secret = resolver.resolve(ref[4:])
    else:
        from nexus.config.secrets import VaultSecretResolver

        resolver = VaultSecretResolver()
        secret = resolver.resolve(ref)

    raw = secret.get_secret_value().encode("utf-8")
    key = hashlib.sha256(raw).digest()
    _KEY_CACHE = key
    _KEY_REF = ref
    return key


def encrypt_credential(auth_type: str, payload: dict[str, Any]) -> str:
    """Encrypt a credential payload using AES-256-GCM.

    Args:
        auth_type: ``bearer``, ``basic``, ``oauth``, etc.
        payload: The credential data dict (never logged).

    Returns:
        Base64-encoded encrypted blob string.
    """
    key = _get_master_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = json.dumps({"type": auth_type, **payload}).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_credential(encrypted_blob: str) -> dict[str, Any]:
    """Decrypt an encrypted credential blob.

    Args:
        encrypted_blob: Base64-encoded blob from ``encrypt_credential``.

    Returns:
        The original credential payload dict.
    """
    key = _get_master_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(encrypted_blob.encode("ascii"))
    nonce = raw[:12]
    ciphertext = raw[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return dict(json.loads(plaintext.decode("utf-8")))


async def store_credential(
    tenant_id: uuid.UUID,
    tool_id: uuid.UUID,
    auth_type: str,
    payload: dict[str, Any],
) -> ToolCredential:
    """Encrypt and persist a credential for a tool.

    Args:
        tenant_id: The tenant UUID.
        tool_id: The tool UUID.
        auth_type: Authentication type (bearer, basic, oauth2, api_key).
        payload: The credential data dict.

    Returns:
        The created ToolCredential record.
    """
    encrypted = encrypt_credential(auth_type, payload)
    async with async_session() as session:
        credential = ToolCredential(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            tool_id=tool_id,
            auth_type=auth_type,
            encrypted_blob=encrypted,
        )
        session.add(credential)
        await session.commit()
    logger.info("credential.stored", tool_id=str(tool_id), auth_type=auth_type)
    return credential


async def resolve_credential(
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    """Resolve and decrypt the credential for a tool.

    Fetches the ToolCredential row from the DB, decrypts the blob,
    and returns the plaintext credential dict.

    The decrypted credential is **never logged**.

    Args:
        tool_id: The tool's UUID.
        tenant_id: The tenant UUID for access control.

    Returns:
        Decrypted credential dict with keys like ``token``, ``username``,
        ``password``, etc.

    Raises:
        LookupError: If the tool has no stored credential.
    """
    async with async_session() as session:
        stmt = (
            select(ToolCredential)
            .where(
                ToolCredential.tool_id == tool_id,
                ToolCredential.tenant_id == tenant_id,
            )
            .order_by(ToolCredential.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        credential = result.scalar_one_or_none()

    if credential is None:
        raise LookupError(f"No credential stored for tool {tool_id}")

    decrypted = decrypt_credential(credential.encrypted_blob)
    logger.info("credential.resolved", tool_id=str(tool_id))
    return decrypted
