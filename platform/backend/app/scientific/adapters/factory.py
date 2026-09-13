"""Selects the scientific adapter from scientific configuration."""

from __future__ import annotations

from app.core.environment import Environment
from app.core.scientific_config import ScientificAdapterKind, ScientificSettings
from app.scientific.adapters.development import DevelopmentScientificAdapter
from app.scientific.adapters.http import HttpScientificAdapter
from app.scientific.contracts import ScientificEngineGateway


def build_scientific_gateway(
    settings: ScientificSettings, environment: Environment
) -> ScientificEngineGateway:
    if settings.adapter is ScientificAdapterKind.DEVELOPMENT:
        return DevelopmentScientificAdapter(environment)
    return HttpScientificAdapter(settings)
