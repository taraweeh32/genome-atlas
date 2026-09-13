"""The /api/v1 router.

Later packages attach their resource routers here (workspaces, organizations,
projects, datasets, files, analyses, jobs, variants, evidence, interpretations,
reports, notifications, search, administration) without touching transport
setup.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import scientific, system

api_v1_router = APIRouter()
api_v1_router.include_router(system.router)
api_v1_router.include_router(scientific.router)
