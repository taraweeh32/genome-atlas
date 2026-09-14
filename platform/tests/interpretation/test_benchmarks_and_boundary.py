"""Benchmark honesty and the scientific boundary of the rules engine.

Two things are pinned down here. First, that the platform never turns contract
tests into a clinical accuracy claim: a run is only labelled scientific accuracy
when every executed case is an accuracy case with a declared reference corpus.
Second, that submission reaches the rules engine only through the existing
scientific gateway, as structured data, with no command, script or free parameter.
"""

from __future__ import annotations

import contextlib

import pytest

from app.application.use_cases.interpretation.benchmarks import (
    ObservedCaseOutcome,
    RecordBenchmarkRun,
    RecordBenchmarkRunCommand,
    RegisterBenchmarkCase,
    RegisterBenchmarkCaseCommand,
)
from app.domain.errors import AuthorizationError, ScientificIntegrationError
from app.domain.value_objects.enums import (
    BenchmarkCaseOutcome,
    BenchmarkValidationKind,
    Classification,
    ClassificationEvaluationState,
    JobKind,
)
from app.scientific.interpretation import (
    DEFAULT_INTERPRETATION_CAPABILITY,
    INTERPRETATION_CONTRACT_VERSION,
)
from tests.interpretation.support import (
    PAGE,
    platform_admin,
    registered_ruleset,
    request_evaluation,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness


async def register_case(harness, admin_id, ruleset_id, **kwargs):
    return await RegisterBenchmarkCase(harness.interpretation).execute(
        RegisterBenchmarkCaseCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            ruleset_id=ruleset_id,
            case_key=kwargs.pop("case_key", "fixture-case-1"),
            validation_kind=kwargs.pop(
                "validation_kind", BenchmarkValidationKind.CONTRACT
            ),
            input_snapshot=kwargs.pop(
                "input_snapshot", {"note": "fixture input, not a real variant"}
            ),
            **kwargs,
        )
    )


async def record_run(harness, admin_id, ruleset_id, observations):
    return await RecordBenchmarkRun(harness.interpretation).execute(
        RecordBenchmarkRunCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            ruleset_id=ruleset_id,
            observations=observations,
        )
    )


# --------------------------------------------------------------------------- #
# Benchmarking claims only what it can support                                #
# --------------------------------------------------------------------------- #


async def test_a_contract_case_run_is_never_labelled_a_scientific_accuracy_run():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id)
    await register_case(
        harness,
        admin_id,
        ruleset.id,
        expected_classification=Classification.UNCERTAIN_SIGNIFICANCE,
    )

    run = await record_run(
        harness,
        admin_id,
        ruleset.id,
        (
            ObservedCaseOutcome(
                case_key="fixture-case-1",
                observed_classification=Classification.UNCERTAIN_SIGNIFICANCE.value,
            ),
        ),
    )

    assert run.is_accuracy_run is False
    assert run.validation_kind is BenchmarkValidationKind.CONTRACT
    assert run.matched_count == 1
    assert run.comparisons[0].outcome is BenchmarkCaseOutcome.MATCHED


async def test_a_mismatch_is_recorded_rather_than_smoothed_over():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id)
    await register_case(
        harness,
        admin_id,
        ruleset.id,
        expected_classification=Classification.UNCERTAIN_SIGNIFICANCE,
    )

    run = await record_run(
        harness,
        admin_id,
        ruleset.id,
        (
            ObservedCaseOutcome(
                case_key="fixture-case-1",
                observed_classification=Classification.PATHOGENIC.value,
            ),
        ),
    )

    assert run.mismatched_count == 1
    assert run.comparisons[0].outcome is BenchmarkCaseOutcome.MISMATCHED
    assert run.is_accuracy_run is False


async def test_an_unexecuted_case_is_reported_as_not_evaluated():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id)
    await register_case(harness, admin_id, ruleset.id)

    run = await record_run(harness, admin_id, ruleset.id, ())

    assert run.not_evaluated_count == 1
    assert run.is_accuracy_run is False


async def test_only_a_platform_administrator_may_register_a_benchmark_case():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    ruleset = await registered_ruleset(harness, admin_id)
    ordinary_id = await create_account(harness, "curator2@example.org")

    with pytest.raises(AuthorizationError):
        await register_case(harness, ordinary_id, ruleset.id)


# --------------------------------------------------------------------------- #
# The scientific boundary                                                     #
# --------------------------------------------------------------------------- #


class RecordingGateway:
    """Records what crossed the boundary; the real adapter still answers."""

    def __init__(self, inner):
        self._inner = inner
        self.requests = []

    async def submit_execution(self, request):
        self.requests.append(request)
        return await self._inner.submit_execution(request)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def test_submission_reaches_the_engine_only_as_structured_data():
    from dataclasses import replace

    from app.workers.interpretation_handlers import InterpretationJobHandlers
    from tests.interpretation.test_rulesets_and_evaluation import arrange

    harness, admin_id, ruleset, variant, workspace_id, record, *_ = await arrange()
    view = await request_evaluation(
        harness,
        admin_id,
        workspace_id=workspace_id,
        variant_id=variant.id,
        ruleset_id=ruleset.id,
    )
    assert await harness.repositories.jobs.get(view.evaluation.job_id) is not None

    gateway = RecordingGateway(harness.scientific)
    services = replace(harness.interpretation, scientific=gateway)
    handlers = InterpretationJobHandlers(services)
    with contextlib.suppress(ScientificIntegrationError):
        # The development adapter implements no interpretation capability. What
        # matters here is *what* crossed the boundary, and that the evaluation
        # never silently stayed in a requested state.
        await handlers.handle(
            JobKind.CLASSIFICATION_EVALUATION,
            {"classification_evaluation_id": view.evaluation.id},
            correlation_id="corr-interpretation-boundary",
        )

    stored = await harness.repositories.classification_evaluations.get(
        view.evaluation.id
    )
    assert stored.state in {
        ClassificationEvaluationState.SUBMITTED,
        ClassificationEvaluationState.FAILED,
    }
    sent = gateway.requests[-1]
    assert sent.capability_id == DEFAULT_INTERPRETATION_CAPABILITY
    parameters = sent.parameters
    assert parameters["contract_version"] == INTERPRETATION_CONTRACT_VERSION
    assert parameters["ruleset"]["ruleset_version"] == ruleset.version
    assert parameters["ruleset"]["configuration_digest"] == ruleset.configuration_digest
    assert [item["evidence_id"] for item in parameters["evidence"]] == [record.id]
    # Nothing that could become code or an unbounded instruction crosses over.
    for forbidden in ("command", "script", "shell", "argv", "sql"):
        assert forbidden not in parameters


async def test_the_registry_lists_only_usable_versions_to_a_tenant_reader():
    from app.application.use_cases.interpretation.rulesets import RulesetReader

    harness = build_harness()
    admin_id = await platform_admin(harness)
    await registered_ruleset(harness, admin_id, activate=False)
    active = await registered_ruleset(
        harness, admin_id, version="0.0.2-development-only"
    )
    reader_id = await create_account(harness, "reader@example.org")

    listed = await RulesetReader(harness.interpretation).list_rulesets(
        await actor_for(harness, reader_id), harness.request, page=PAGE
    )

    assert [item.id for item in listed.items] == [active.id]
