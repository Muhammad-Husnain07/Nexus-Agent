"""Secret resolution abstraction for local and production environments."""

import os
from abc import ABC, abstractmethod

from pydantic import SecretStr


class SecretResolver(ABC):
    """Abstract base for resolving secret references to secret values.

    In local/dev environments use EnvSecretResolver; in production use
    VaultSecretResolver (or replace with AWS Secrets Manager, etc.).
    """

    @abstractmethod
    def resolve(self, secret_ref: str) -> SecretStr:
        """Resolve a secret reference to its value.

        Args:
            secret_ref: Reference identifier (env var name, Vault path, etc.).

        Returns:
            SecretStr wrapping the resolved secret value.
        """
        ...


class EnvSecretResolver(SecretResolver):
    """Resolves secrets by reading environment variables.

    The secret_ref is interpreted as an environment variable name.
    """

    def resolve(self, secret_ref: str) -> SecretStr:
        """Read the secret from an environment variable.

        Args:
            secret_ref: Name of the environment variable.

        Returns:
            SecretStr with the value, or empty if not found.
        """
        return SecretStr(os.environ.get(secret_ref, ""))


class VaultSecretResolver(SecretResolver):
    """Resolves secrets via HashiCorp Vault or AWS Secrets Manager.

    This is a stub implementation for production use. Replace with
    hvac client or boto3 secretsmanager calls as needed.
    """

    def __init__(self, endpoint: str = "", token: SecretStr | None = None) -> None:
        """Initialize the Vault resolver.

        Args:
            endpoint: Vault server URL or AWS region.
            token: Authentication token for the secret store.
        """
        self._endpoint = endpoint
        self._token = token or SecretStr("")

    def resolve(self, secret_ref: str) -> SecretStr:
        """Resolve a secret from Vault/AWS Secrets Manager.

        Args:
            secret_ref: Path or ARN identifying the secret.

        Raises:
            NotImplementedError: This stub has no backend implementation.
        """
        msg = (
            f"VaultSecretResolver is a stub. "
            f"Implement a backend for endpoint={self._endpoint!r} "
            f"secret_ref={secret_ref!r}"
        )
        raise NotImplementedError(msg)
