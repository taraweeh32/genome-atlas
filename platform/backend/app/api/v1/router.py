"""The /api/v1 router.

Later packages attach their resource routers here (datasets, files, analyses,
jobs, variants, evidence, interpretations, reports, notifications, search)
without touching transport setup.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    administration,
    authentication,
    datasets,
    identity,
    organizations,
    projects,
    scientific,
    system,
    workspaces,
)

api_v1_router = APIRouter()
api_v1_router.include_router(system.router)
api_v1_router.include_router(scientific.router)
api_v1_router.include_router(authentication.router)
api_v1_router.include_router(identity.router)
api_v1_router.include_router(workspaces.router)
api_v1_router.include_router(organizations.router)
api_v1_router.include_router(organizations.invitations_router)
api_v1_router.include_router(projects.router)
api_v1_router.include_router(datasets.router)
api_v1_router.include_router(datasets.versions_router)
api_v1_router.include_router(datasets.uploads_router)
api_v1_router.include_router(datasets.artifacts_router)
api_v1_router.include_router(datasets.imports_router)
api_v1_router.include_router(datasets.validation_router)
api_v1_router.include_router(administration.router)
