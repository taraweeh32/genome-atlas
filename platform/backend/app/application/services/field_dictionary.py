"""The annotation-aware filter field dictionary.

Package 7 filters and ranks whatever the field dictionary declares. Package 8 lets
an administrator register an annotation resource that declares its own fields, so
the dictionary is no longer a constant: it is the shipped definitions plus the
fields of every currently usable annotation resource version.

This service is the single place that composition happens. It caches the composed
registry because it is read on every filtering request and changes only when an
administrator registers or retires a resource version:

* an in-process change invalidates the cache immediately, so an administrator sees
  their own change on the next request;
* everything else is bounded by a short refresh interval, so another process's
  change appears without a restart.

The composed registry carries a derived version string, so an execution can never
record the shipped dictionary version while having been validated against a
different field set.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.domain.annotation.fields import extend_registry
from app.domain.query.fields import DEFAULT_FIELD_REGISTRY, FilterFieldRegistry


class AnnotationFieldDictionary:
    """Composes and caches the filterable field dictionary."""

    def __init__(
        self,
        clock: Any,
        *,
        base: FilterFieldRegistry = DEFAULT_FIELD_REGISTRY,
        refresh_seconds: int = 60,
    ) -> None:
        self._clock = clock
        self._base = base
        self._refresh = timedelta(seconds=max(1, refresh_seconds))
        self._registry: FilterFieldRegistry = base
        self._loaded_at: datetime | None = None

    @property
    def base(self) -> FilterFieldRegistry:
        return self._base

    def snapshot(self) -> FilterFieldRegistry:
        """The composed registry as last loaded.

        Falls back to the shipped definitions before the first load rather than
        blocking: filtering on platform fields must work even if the annotation
        registry is unreadable, and an annotation field that is not yet loaded is
        simply not offered.
        """
        return self._registry

    def invalidate(self) -> None:
        self._loaded_at = None

    def _is_stale(self) -> bool:
        if self._loaded_at is None:
            return True
        return self._clock.now() - self._loaded_at >= self._refresh

    async def refresh(self, unit_of_work: Any) -> FilterFieldRegistry:
        async with unit_of_work.begin() as repositories:
            resources = await repositories.annotation_resources.list_field_sources()
        self._registry = extend_registry(self._base, tuple(resources))
        self._loaded_at = self._clock.now()
        return self._registry

    async def refresh_if_stale(self, unit_of_work: Any) -> FilterFieldRegistry:
        if not self._is_stale():
            return self._registry
        return await self.refresh(unit_of_work)


__all__ = ["AnnotationFieldDictionary"]
