"""ToolCredentialVault — encrypt/decrypt tool auth secrets using AES-256-GCM.

Master key is resolved from ``SecretResolver`` (env var / Vault).
Decrypted credentials are never logged.
"""

from __future__ import annotations

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
from nexus.db.models.tool import Tool

logger = structlog.get_logger("nexus.security.credentials")

_KEY_CACHE: bytes | None = None
_KEY_REF: str = ""

# Model name for the credential — we store encrypted blobs in tool.metadata_
# since the Tool model already has a metadata_ JSONB column.
# In production, a dedicated Credential table should be created via migration.


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
    # Derive a 32-byte key using SHA-256
    import hashlib

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
    import base64

    key = _get_master_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = json.dumps({"type": auth_type, **payload}).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    blob = base64.b64encode(nonce + ciphertext).decode("ascii")
    return blob


def decrypt_credential(encrypted_blob: str) -> dict[str, Any]:
    """Decrypt an encrypted credential blob.

    Args:
        encrypted_blob: Base64-encoded blob from ``encrypt_credential``.

    Returns:
        The original credential payload dict.
    """
    import base64

    key = _get_master_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(encrypted_blob.encode("ascii"))
    nonce = raw[:12]
    ciphertext = raw[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return dict(json.loads(plaintext.decode("utf-8")))


async def resolve_credential(
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    """Resolve and decrypt the credential for a tool.

    Fetches the tool from the DB, extracts the encrypted credential
    from ``tool.metadata_.get("encrypted_credential")``, decrypts it,
    and returns the plaintext credential dict.

    The decrypted credential is **never logged**.

    Args:
        tool_id: The tool's UUID.
        tenant_id: The tenant UUID for access control.

    Returns:
        Decrypted credential dict with keys like ``token``, ``username``,
        ``password``, etc.

    Raises:
        LookupError: If the tool is not found or has no credential.
    """
    async with async_session() as session:
        stmt = select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id)
        result = await session.execute(stmt)
        tool = result.scalar_one_or_none()

    if tool is None:
        raise LookupError(f"Tool {tool_id} not found for tenant {tenant_id}")

    metadata = tool.metadata_ or {}
    encrypted = metadata.get("encrypted_credential")
    if not encrypted:
        raise LookupError(f"Tool {tool_id} has no stored credential")

    credential = decrypt_credential(encrypted)
    # Sanitise: never log the decrypted content
    logger.info("credential.resolved", tool_id=str(tool_id))
    return credential
