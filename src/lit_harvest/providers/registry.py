"""Provider registry for service-layer access."""

from __future__ import annotations

from collections.abc import Sequence

from lit_harvest.providers.base import Provider

# `ProviderRegistry.list()` shadows the builtin inside the class body, so keep a
# module-level alias for annotations.
NameList = list[str]


class ProviderRegistry:
    """Holds the providers active for this instance.

    Providers advertise capabilities (search / fulltext / pdf / metadata) so the
    workflow can pick a suitable one instead of assuming Elsevier.
    """

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

    def all(self) -> Sequence[Provider]:
        return list(self._providers.values())

    # Backwards-compatible alias for the original method name.
    def list(self) -> Sequence[Provider]:
        return self.all()

    def names(self) -> NameList:
        return sorted(self._providers)

    def with_capability(self, capability: str) -> Sequence[Provider]:
        """All registered providers advertising the given capability flag."""
        return [item for item in self._providers.values() if getattr(item, capability, False)]

    def search_providers(self) -> Sequence[Provider]:
        return self.with_capability("supports_search")

    def fulltext_providers(self) -> Sequence[Provider]:
        return self.with_capability("supports_fulltext")

    def pdf_providers(self) -> Sequence[Provider]:
        return self.with_capability("supports_pdf")

    def first_with_capability(self, capability: str) -> Provider | None:
        matches = self.with_capability(capability)
        return matches[0] if matches else None


def build_registry(providers: list[Provider]) -> ProviderRegistry:
    return ProviderRegistry(providers)


def build_default_registry(elsevier: Provider) -> ProviderRegistry:
    """Kept for backwards compatibility with older call sites."""
    return ProviderRegistry([elsevier])
