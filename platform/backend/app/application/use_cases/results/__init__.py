"""Use cases for the scientific data layer: variants and result surfaces.

Split by concern rather than by entity:

* ``dependencies`` — the shared service bundle and the one place scope and
  permission are resolved,
* ``ingestion`` — accepting an engine's result surface and making it available
  only after its bytes verify,
* ``variants`` — recording variant claims, and reading them back with their
  provenance intact,
* ``reads`` — result metadata, bounded content windows, artifact download grants,
  withdrawal and supersession.
"""

from __future__ import annotations

from app.application.use_cases.results.dependencies import ResultServices

__all__ = ["ResultServices"]
