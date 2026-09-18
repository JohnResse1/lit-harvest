"""Provider registry for service-layer access."""

from __future__ import annotations

from lit_harvest.providers.base import Provider
from lit_harvest.providers.elsevier import ElsevierProvider


class ProviderRegistry:
    def __init__(self, providers: list[Provider] | None = None):
        self._providers: dict[str, Provider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: Provider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Provider not registered: {name}") from exc

    def list(self) -> list[Provider]:
        return list(self._providers.values())


def build_default_registry(elsevier: ElsevierProvider) -> ProviderRegistry:
    return ProviderRegistry([elsevier])
