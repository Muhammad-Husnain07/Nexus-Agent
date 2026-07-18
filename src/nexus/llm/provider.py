"""LLM provider registry — loads, resolves, and validates providers from settings."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import SecretStr

from nexus.config.secrets import EnvSecretResolver, SecretResolver
from nexus.config.settings import ProviderConfig, get_settings


@dataclass
class ProviderInstance:
    """A resolved provider ready for use by the LLM client.

    Attributes:
        config: The original provider configuration.
        api_key: The resolved API key secret.
    """

    config: ProviderConfig
    api_key: SecretStr = field(default_factory=lambda: SecretStr(""))


class ProviderRegistry:
    """Singleton registry of all configured LLM providers.

    Loads providers from settings on init, resolves API keys via
    SecretResolver, and provides lookup by model name.
    """

    _instance: ProviderRegistry | None = None

    def __init__(self, secret_resolver: SecretResolver | None = None) -> None:
        self._providers: dict[str, ProviderInstance] = {}
        self._model_to_provider: dict[str, str] = {}
        self._secret_resolver = secret_resolver or EnvSecretResolver()

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load()
        return cls._instance

    @classmethod
    def init(cls, secret_resolver: SecretResolver | None = None) -> ProviderRegistry:
        instance = cls(secret_resolver)
        instance._load()
        cls._instance = instance
        return instance

    def _load(self) -> None:
        settings = get_settings()
        for cfg in settings.llm.providers:
            api_key = (
                self._secret_resolver.resolve(cfg.api_key_ref) if cfg.api_key_ref else SecretStr("")
            )
            instance = ProviderInstance(config=cfg, api_key=api_key)
            self._providers[cfg.name] = instance
            for model in cfg.models:
                self._model_to_provider[model] = cfg.name
        # Register a default "litellm" provider that delegates routing to LiteLLM's
        # built-in model prefix routing (ollama/qwen2.5:7b, deepseek/deepseek-chat, etc.)
        if not self._providers:
            from nexus.config.settings import ProviderConfig  # noqa: PLC0415
            self._providers["litellm"] = ProviderInstance(
                config=ProviderConfig(
                    name="litellm",
                    base_url="",
                    api_key_ref="",
                    models=["*"],
                    supports_streaming=True,
                    supports_tools=True,
                    supports_structured_output=True,
                ),
            )

    def get_provider(self, name: str) -> ProviderInstance | None:
        return self._providers.get(name)

    def get_provider_for_model(self, model: str) -> ProviderInstance | None:
        provider_name = self._model_to_provider.get(model)
        if provider_name is None:
            return None
        return self._providers.get(provider_name)

    def resolve_provider(self, model: str) -> tuple[ProviderInstance, str]:
        provider = self.get_provider_for_model(model)
        if provider is not None:
            return provider, provider.config.name
        settings = get_settings()
        provider = self.get_provider(settings.llm.default_provider)
        if provider is not None:
            return provider, settings.llm.default_provider
        # Fallback: use the catch-all "litellm" provider (built-in routing)
        litellm_provider = self.get_provider("litellm")
        if litellm_provider is not None:
            return litellm_provider, "litellm"
        msg = f"No provider found for model '{model}' and no default provider configured"
        raise ValueError(msg)

    @property
    def providers(self) -> dict[str, ProviderInstance]:
        return dict(self._providers)

    @property
    def available_models(self) -> list[str]:
        return list(self._model_to_provider.keys())

    async def validate_connectivity(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, instance in self._providers.items():
            try:
                from litellm import acompletion  # noqa: PLC0415

                model = instance.config.models[0] if instance.config.models else "gpt-4o"
                await acompletion(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    api_key=instance.api_key.get_secret_value() if instance.api_key else None,
                )
                results[name] = True
            except Exception:
                results[name] = False
        return results
