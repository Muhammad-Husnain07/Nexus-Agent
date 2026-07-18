"""Test that the JWT secret startup guard rejects weak values."""

import pytest
from pydantic import SecretStr

from nexus.config.settings import AuthSettings


def test_rejects_empty_secret():
    with pytest.raises(RuntimeError, match="JWT secret is weak"):
        AuthSettings(jwt_secret=SecretStr(""))


def test_rejects_change_me():
    with pytest.raises(RuntimeError, match="JWT secret is weak"):
        AuthSettings(jwt_secret=SecretStr("change-me"))


def test_rejects_short_secret():
    with pytest.raises(RuntimeError, match="JWT secret is weak"):
        AuthSettings(jwt_secret=SecretStr("short"))


def test_accepts_strong_secret():
    strong = "a" * 64
    settings = AuthSettings(jwt_secret=SecretStr(strong))
    assert settings.jwt_secret.get_secret_value() == strong


def test_accepts_32_char_secret():
    strong = "b" * 32
    settings = AuthSettings(jwt_secret=SecretStr(strong))
    assert settings.jwt_secret.get_secret_value() == strong
