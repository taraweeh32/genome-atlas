"""Migration revisions.

Revision modules are normally loaded by Alembic, not imported directly. The
loader below lets tests import the domain-schema revision by path so they can
assert that the migration's table set has not drifted from the models.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_REVISION_DIRECTORY = Path(__file__).parent


def _load_revision(module_name: str) -> ModuleType:
    path = _REVISION_DIRECTORY / f"{module_name}.py"
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load migration revision {module_name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_domain_schema_revision() -> ModuleType:
    return _load_revision("0002_domain_schema")
