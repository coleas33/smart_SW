"""The served ids each provider documents as aliases of a requested model."""

from __future__ import annotations

import re
from datetime import date

from swreview.agent.providers import ProviderName

_SUFFIXES = {
    ProviderName.OPENAI: r"-([0-9]{4}-[0-9]{2}-[0-9]{2})",
    ProviderName.GEMINI: r"-[0-9]{3}",
    ProviderName.FAKE: None,
}


def aliases(provider: ProviderName | str, requested: str, served: str) -> bool:
    """Accept an exact id or the provider's anchored snapshot/version form."""
    if provider not in _SUFFIXES:
        return False
    if requested == served:
        return True
    suffix = _SUFFIXES[provider]
    if suffix is None:
        return False
    match = re.fullmatch(re.escape(requested) + suffix, served)
    if match is None:
        return False
    if provider == ProviderName.OPENAI:
        try:
            date.fromisoformat(match.group(1))
        except ValueError:
            return False
    return True
