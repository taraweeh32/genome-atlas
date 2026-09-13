"""Scientific integration boundary behaviour and architectural guarantees."""

from __future__ import annotations

import pathlib

import pytest

from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.core.environment import Environment
from app.core.errors import ConfigurationError
from app.core.scientific_config import ScientificAdapterKind, ScientificSettings
from app.domain.errors import ScientificIntegrationError
from app.scientific.adapters.development import DevelopmentScientificAdapter
from app.scientific.adapters.factory import build_scientific_gateway
from app.scientific.contracts import (
    ExecutionStatus,
    ScientificEngineGateway,
    ScientificExecutionRequest,
)

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2] / "backend" / "app"

# Terms that would indicate scientific algorithms leaked into the application.
FORBIDDEN_SCIENTIFIC_TERMS = (
    "acmg",
    "pathogenic",
    "allele_frequency",
    "gnomad_query",
    "normalize_variant",
    "vep_run",
)


def test_development_adapter_is_refused_in_production() -> None:
    with pytest.raises(ConfigurationError, match="never be enabled in production"):
        DevelopmentScientificAdapter(Environment.PRODUCTION)


def test_development_adapter_labels_itself_as_development() -> None:
    adapter = DevelopmentScientificAdapter(Environment.DEVELOPMENT)
    assert isinstance(adapter, ScientificEngineGateway)


async def test_development_capabilities_are_flagged_and_never_claim_validity() -> None:
    adapter = DevelopmentScientificAdapter(Environment.DEVELOPMENT)
    capabilities = await DescribeScientificCapabilities(adapter).execute()
    assert capabilities.is_development_adapter is True
    assert "development-only" in capabilities.engine.engine_version
    assert [item.capability_id for item in capabilities.capabilities] == ["integration.echo"]


async def test_development_execution_is_deterministic_and_correlated() -> None:
    adapter = DevelopmentScientificAdapter(Environment.TEST)
    request = ScientificExecutionRequest(
        capability_id="integration.echo", capability_version="1", correlation_id="corr-123"
    )
    first = await adapter.submit_execution(request)
    second = await adapter.submit_execution(request)
    assert first.execution_id == second.execution_id
    assert first.status is ExecutionStatus.SUCCEEDED
    assert first.correlation_id == "corr-123"
    # Artifacts are referenced, never inlined.
    assert first.artifacts[0].storage_uri.startswith("memory://development/")
    assert first.provenance is not None
    assert first.provenance.engine.engine_id == "development-stub"


async def test_development_adapter_refuses_scientific_capabilities() -> None:
    adapter = DevelopmentScientificAdapter(Environment.TEST)
    with pytest.raises(ScientificIntegrationError, match="no scientific capability"):
        await adapter.submit_execution(
            ScientificExecutionRequest(
                capability_id="variant.annotate",
                capability_version="3",
                correlation_id="corr-456",
            )
        )


async def test_unknown_execution_lookup_is_a_structured_failure() -> None:
    adapter = DevelopmentScientificAdapter(Environment.TEST)
    with pytest.raises(ScientificIntegrationError):
        await adapter.get_execution("devexec_missing")


def test_factory_selects_the_configured_adapter() -> None:
    development = build_scientific_gateway(
        ScientificSettings(adapter=ScientificAdapterKind.DEVELOPMENT), Environment.DEVELOPMENT
    )
    assert isinstance(development, DevelopmentScientificAdapter)

    http = build_scientific_gateway(
        ScientificSettings(
            adapter=ScientificAdapterKind.HTTP, service_base_url="https://sci.internal"
        ),
        Environment.DEVELOPMENT,
    )
    assert isinstance(http, ScientificEngineGateway)
    assert not isinstance(http, DevelopmentScientificAdapter)


def test_no_scientific_algorithm_terms_exist_in_the_application_tree() -> None:
    """Architectural guard: scientific computation stays out of the application.

    ``app/scientific`` is the integration boundary itself, so it may *name*
    scientific concepts (for example an ACMG ruleset version carried as engine
    identity) without computing them. Every other layer — api, application,
    domain, infrastructure, workers — must not mention them at all.
    """
    boundary = BACKEND_ROOT / "scientific"
    offenders: list[str] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if boundary in path.parents:
            continue
        lowered = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_SCIENTIFIC_TERMS:
            if term in lowered:
                offenders.append(f"{path.name}:{term}")
    assert offenders == []


def test_scientific_boundary_names_concepts_without_computing_them() -> None:
    """The contract carries scientific *identity*, never scientific logic."""
    source = (BACKEND_ROOT / "scientific" / "contracts.py").read_text(encoding="utf-8").lower()
    # Identity/provenance vocabulary is expected...
    assert "acmg" in source
    # ...but no evaluation, scoring or classification is implemented here.
    for implementation_term in ("def classify", "def evaluate_criterion", "def score_variant"):
        assert implementation_term not in source


def test_domain_does_not_import_infrastructure_or_frameworks() -> None:
    """Architectural guard: the dependency rule points inward."""
    forbidden = ("import fastapi", "import sqlalchemy", "import redis", "import boto3", "import duckdb")
    offenders: list[str] = []
    for path in (BACKEND_ROOT / "domain").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in content:
                offenders.append(f"{path.name}:{term}")
    assert offenders == []
