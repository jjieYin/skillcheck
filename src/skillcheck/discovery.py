"""Compatibility exports for the v2 discovery core."""

from skillcheck.core.discovery import (
    DiscoveredInstall,
    Inventory,
    ProviderPath,
    default_provider_paths,
    discover_skills,
)

__all__ = [
    "DiscoveredInstall",
    "Inventory",
    "ProviderPath",
    "default_provider_paths",
    "discover_skills",
]
