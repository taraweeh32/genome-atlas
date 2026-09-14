"""Use cases for the ACMG/AMP rules-engine boundary.

Registry governance, automated evaluation, payload ingestion and controlled
benchmark validation. No module in this package evaluates a criterion, combines
criteria or decides a classification: those are the independently deployable rules
engine's job, reached only through the existing scientific gateway.
"""

from app.application.use_cases.interpretation.benchmarks import (
    BenchmarkReader,
    ObservedCaseOutcome,
    RecordBenchmarkRun,
    RecordBenchmarkRunCommand,
    RegisterBenchmarkCase,
    RegisterBenchmarkCaseCommand,
    compare_case,
)
from app.application.use_cases.interpretation.dependencies import InterpretationServices
from app.application.use_cases.interpretation.evaluations import (
    ClassificationReader,
    EvaluationView,
    RequestClassificationEvaluation,
    RequestEvaluationCommand,
    SubmitClassificationEvaluation,
)
from app.application.use_cases.interpretation.ingestion import (
    IngestInterpretationCommand,
    IngestInterpretationPayload,
    IngestionResult,
)
from app.application.use_cases.interpretation.rulesets import (
    RegisterRuleset,
    RegisterRulesetCommand,
    RulesetReader,
    TransitionRuleset,
    TransitionRulesetCommand,
)

__all__ = [
    "BenchmarkReader",
    "ClassificationReader",
    "EvaluationView",
    "IngestInterpretationCommand",
    "IngestInterpretationPayload",
    "IngestionResult",
    "InterpretationServices",
    "ObservedCaseOutcome",
    "RecordBenchmarkRun",
    "RecordBenchmarkRunCommand",
    "RegisterBenchmarkCase",
    "RegisterBenchmarkCaseCommand",
    "RegisterRuleset",
    "RegisterRulesetCommand",
    "RequestClassificationEvaluation",
    "RequestEvaluationCommand",
    "RulesetReader",
    "SubmitClassificationEvaluation",
    "TransitionRuleset",
    "TransitionRulesetCommand",
    "compare_case",
]
