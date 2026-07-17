"""Tests for configuration validation — edge cases and error states."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from nexus.config.settings import (
    AuthSettings,
    DatabaseSettings,
    LLMSettings,
    RedisSettings,
    ServerSettings,
    ToolSettings,
)


class TestDatabaseSettings:
    def test_defaults(self) -> None:
        settings = DatabaseSettings()
        assert settings.pool_size == 10
        assert settings.max_overflow == 20
        assert settings.echo_sql is False
        assert settings.statement_timeout_ms == 30000

    def test_invalid_pool_size(self) -> None:
        with pytest.raises(ValidationError):
            DatabaseSettings(pool_size=0)

    def test_invalid_max_overflow(self) -> None:
        with pytest.raises(ValidationError):
            DatabaseSettings(max_overflow=-1)

    def test_invalid_timeout(self) -> None:
        with pytest.raises(ValidationError):
            DatabaseSettings(statement_timeout_ms=-1)


class TestRedisSettings:
    def test_defaults(self) -> None:
        settings = RedisSettings()
        assert settings.db == 0
        assert settings.max_connections == 20
        assert settings.ssl is False

    def test_invalid_db(self) -> None:
        with pytest.raises(ValidationError):
            RedisSettings(db=-1)

    def test_invalid_max_connections(self) -> None:
        with pytest.raises(ValidationError):
            RedisSettings(max_connections=0)


class TestLLMSettings:
    def test_defaults(self) -> None:
        settings = LLMSettings()
        assert settings.temperature == 0.7
        assert settings.max_tokens == 4096
        assert settings.timeout_s == 60

    def test_temperature_too_high(self) -> None:
        with pytest.raises(ValidationError):
            LLMSettings(temperature=3.0)

    def test_temperature_too_low(self) -> None:
        with pytest.raises(ValidationError):
            LLMSettings(temperature=-1.0)

    def test_invalid_max_tokens(self) -> None:
        with pytest.raises(ValidationError):
            LLMSettings(max_tokens=0)


class TestServerSettings:
    def test_defaults(self) -> None:
        settings = ServerSettings()
        assert settings.port == 8000
        assert settings.workers == 1

    def test_port_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ServerSettings(port=70000)

    def test_port_zero(self) -> None:
        with pytest.raises(ValidationError):
            ServerSettings(port=0)

    def test_invalid_workers(self) -> None:
        with pytest.raises(ValidationError):
            ServerSettings(workers=0)


class TestAuthSettings:
    def test_defaults(self) -> None:
        settings = AuthSettings()
        assert settings.jwt_algorithm == "HS256"
        assert settings.access_token_ttl_minutes == 30

    def test_jwt_secret_is_secret_str(self) -> None:
        settings = AuthSettings()
        assert isinstance(settings.jwt_secret, SecretStr)

    def test_invalid_access_token_ttl(self) -> None:
        with pytest.raises(ValidationError):
            AuthSettings(access_token_ttl_minutes=0)


class TestToolSettings:
    def test_defaults(self) -> None:
        settings = ToolSettings()
        assert settings.execution_timeout_s == 30
        assert settings.max_retries == 3
        assert settings.sandbox_enabled is False

    def test_invalid_timeout(self) -> None:
        with pytest.raises(ValidationError):
            ToolSettings(execution_timeout_s=0)

    def test_invalid_retries(self) -> None:
        with pytest.raises(ValidationError):
            ToolSettings(max_retries=-1)


class TestJWTSecretValidation:
    @pytest.mark.parametrize("env", ["development", "dev", "test"])
    def test_development_envs_allow_default_secret(self, env: str) -> None:
        """Default JWT secret is allowed in dev/test environments."""
        with patch.dict(os.environ, {"NEXUS_ENV": env}, clear=False):
            settings = AuthSettings(
                jwt_secret=SecretStr("dev-secret-change-in-production")
            )
            assert settings.jwt_secret.get_secret_value() == "dev-secret-change-in-production"

    def test_production_env_rejects_default_secret(self) -> None:
        """Default JWT secret raises in production."""
        with patch.dict(os.environ, {"NEXUS_ENV": "production"}, clear=False):
            with pytest.raises(ValueError, match="JWT secret is using the default value"):
                AuthSettings(jwt_secret=SecretStr("dev-secret-change-in-production"))

    def test_production_env_allows_custom_secret(self) -> None:
        """Custom JWT secret is accepted in production."""
        with patch.dict(os.environ, {"NEXUS_ENV": "production"}, clear=False):
            settings = AuthSettings(jwt_secret=SecretStr("my-custom-secret-value"))
            assert settings.jwt_secret.get_secret_value() == "my-custom-secret-value"
