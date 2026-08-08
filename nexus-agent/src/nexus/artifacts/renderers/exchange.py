"""ExchangeRenderer — readable rendering of exchange-rate artifacts.

Reads the declared flat rate fields (``*_rate``); any number of currency
rates is supported — the field name's ``_rate`` suffix carries the code.
"""

from __future__ import annotations

from nexus.artifacts.renderers.base import ArtifactRenderer
from nexus.artifacts.renderers.registry import RendererRegistry


class ExchangeRenderer(ArtifactRenderer):
    """Render exchange-rate artifacts: base currency + per-currency rates."""

    def render(self, data: dict) -> str:
        if not data:
            return ""
        base = data.get("base_code")
        rates: list[str] = []
        for key, value in data.items():
            if not key.endswith("_rate") or value is None:
                continue
            code = key[: -len("_rate")].upper()
            rates.append(f"1 {base or 'base'} = {value} {code}")
        when = data.get("updated")
        if not rates:
            return ""
        text = "; ".join(rates)
        if when:
            text = f"{text} (updated {when})"
        return text


def _register() -> None:
    RendererRegistry.register("get_exchange_rates", ExchangeRenderer())


_register()
