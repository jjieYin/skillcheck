"""Stable registry for local Agent review adapters."""

from __future__ import annotations

from collections.abc import Iterable

from skillcheck.reviewers.base import ReviewAdapter, ReviewCapability


class ReviewRegistry:
    def __init__(self, adapters: Iterable[ReviewAdapter] = ()) -> None:
        self._adapters = {adapter.detect().agent: adapter for adapter in adapters}

    def capabilities(self) -> list[ReviewCapability]:
        return [adapter.detect() for adapter in self._adapters.values()]

    def get(self, agent: str) -> ReviewAdapter:
        return self._adapters[agent]

