"""Retry, timeout, lease and error-classification policy.

Pure functions over explicit inputs so every decision is testable without a
database, a clock or a worker. Retryability is derived from a *classified*
error, never from a string match on an exception message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.errors import (
    AuthorizationError,
    ConcurrencyConflictError,
    DependencyFailureError,
    InfrastructureError,
    InvalidStateTransitionError,
    NotFoundError,
    ScientificIntegrationError,
    ValidationError,
)
from app.domain.value_objects.enums import JobErrorClass, JobKind, JobQueue, NodeClass

#: Error classes that may be attempted again. Everything absent from this set is
#: permanent: retrying it would burn credits/compute and fail identically.
RETRYABLE_ERROR_CLASSES: frozenset[JobErrorClass] = frozenset(
    {
        JobErrorClass.TRANSIENT_INFRASTRUCTURE_ERROR,
        JobErrorClass.RESOURCE_UNAVAILABLE,
        JobErrorClass.TIMEOUT,
    }
)

#: Which fleet each job kind runs on. A scientific execution is never handed to
#: an application worker, and vice versa.
JOB_KIND_NODE_CLASS: dict[JobKind, NodeClass] = {
    JobKind.ANALYSIS_EXECUTION: NodeClass.APPLICATION_WORKER,
    JobKind.SCIENTIFIC_EXECUTION: NodeClass.SCIENTIFIC_WORKER,
    JobKind.DATASET_IMPORT: NodeClass.APPLICATION_WORKER,
    JobKind.DATASET_VALIDATION: NodeClass.APPLICATION_WORKER,
    JobKind.EXPORT: NodeClass.APPLICATION_WORKER,
    JobKind.REPORT_GENERATION: NodeClass.APPLICATION_WORKER,
    JobKind.NOTIFICATION_DELIVERY: NodeClass.APPLICATION_WORKER,
    JobKind.RETENTION: NodeClass.APPLICATION_WORKER,
    JobKind.MAINTENANCE: NodeClass.APPLICATION_WORKER,
    JobKind.SCHEDULE_TRIGGER: NodeClass.APPLICATION_WORKER,
    JobKind.STALE_RECOVERY: NodeClass.APPLICATION_WORKER,
    # Ingesting a result surface is application work — verifying bytes, reading a
    # file's declared shape, writing rows. It never runs on a scientific node.
    JobKind.RESULT_INGESTION: NodeClass.APPLICATION_WORKER,
    # A deferred variant query reads analytical files and writes an artifact. It
    # is application work: no scientific computation happens in it.
    JobKind.VARIANT_QUERY: NodeClass.APPLICATION_WORKER,
    # Submitting an annotation run and ingesting its output are application work.
    # The annotation itself runs on a scientific node, behind the adapter.
    JobKind.ANNOTATION_EXECUTION: NodeClass.APPLICATION_WORKER,
    JobKind.ANNOTATION_INGESTION: NodeClass.APPLICATION_WORKER,
    # Submitting an interpretation request and ingesting the engine's payload are
    # application work. The interpretation rules engine runs behind the adapter.
    JobKind.CLASSIFICATION_EVALUATION: NodeClass.APPLICATION_WORKER,
    JobKind.CLASSIFICATION_INGESTION: NodeClass.APPLICATION_WORKER,
}

DEFAULT_QUEUE_FOR_KIND: dict[JobKind, JobQueue] = {
    JobKind.ANALYSIS_EXECUTION: JobQueue.DEFAULT,
    JobKind.SCIENTIFIC_EXECUTION: JobQueue.SCIENTIFIC,
    JobKind.DATASET_IMPORT: JobQueue.IMPORT,
    JobKind.DATASET_VALIDATION: JobQueue.VALIDATION,
    JobKind.EXPORT: JobQueue.EXPORT,
    JobKind.MAINTENANCE: JobQueue.MAINTENANCE,
    JobKind.SCHEDULE_TRIGGER: JobQueue.MAINTENANCE,
    JobKind.STALE_RECOVERY: JobQueue.MAINTENANCE,
    JobKind.RESULT_INGESTION: JobQueue.IMPORT,
    JobKind.VARIANT_QUERY: JobQueue.EXPORT,
    JobKind.ANNOTATION_EXECUTION: JobQueue.SCIENTIFIC,
    JobKind.ANNOTATION_INGESTION: JobQueue.IMPORT,
    JobKind.CLASSIFICATION_EVALUATION: JobQueue.SCIENTIFIC,
    JobKind.CLASSIFICATION_INGESTION: JobQueue.IMPORT,
}


def classify_exception(error: BaseException) -> JobErrorClass:
    """Map a raised error onto the job error taxonomy.

    Unknown errors are ``internal_error`` — permanent — because retrying an
    unclassified failure is how a single bug becomes a request storm.
    """
    if isinstance(error, TimeoutError):
        return JobErrorClass.TIMEOUT
    if isinstance(error, ValidationError):
        return JobErrorClass.VALIDATION_ERROR
    if isinstance(error, AuthorizationError):
        return JobErrorClass.AUTHORIZATION_ERROR
    if isinstance(error, (InvalidStateTransitionError, NotFoundError)):
        return JobErrorClass.CONFIGURATION_ERROR
    if isinstance(error, ScientificIntegrationError):
        # The adapter reports whether the subsystem considers the failure
        # retryable; an unreachable subsystem is transient, a rejected request
        # is not. Callers that know better pass an explicit class instead.
        return JobErrorClass.SCIENTIFIC_EXECUTION_ERROR
    if isinstance(error, DependencyFailureError):
        return JobErrorClass.RESOURCE_UNAVAILABLE
    if isinstance(error, ConcurrencyConflictError):
        return JobErrorClass.TRANSIENT_INFRASTRUCTURE_ERROR
    if isinstance(error, InfrastructureError):
        return JobErrorClass.TRANSIENT_INFRASTRUCTURE_ERROR
    return JobErrorClass.INTERNAL_ERROR


def is_retryable(error_class: JobErrorClass) -> bool:
    return error_class in RETRYABLE_ERROR_CLASSES


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff with a cap.

    ``max_attempts`` is a hard ceiling on *total* attempts, so a permanently
    broken job dead-letters instead of cycling forever.
    """

    max_attempts: int = 3
    initial_backoff_seconds: int = 30
    backoff_multiplier: int = 4
    max_backoff_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValidationError(
                "max_attempts must be at least 1", details={"field": "max_attempts"}
            )

    def backoff_for(self, attempt_number: int) -> timedelta:
        exponent = max(0, attempt_number - 1)
        seconds = self.initial_backoff_seconds * (self.backoff_multiplier**exponent)
        return timedelta(seconds=min(seconds, self.max_backoff_seconds))

    def next_attempt_at(self, *, attempt_number: int, now: datetime) -> datetime:
        return now + self.backoff_for(attempt_number)

    def should_retry(
        self, *, attempt_number: int, error_class: JobErrorClass, cancelled: bool = False
    ) -> bool:
        if cancelled or error_class is JobErrorClass.CANCELLATION:
            return False
        if not is_retryable(error_class):
            return False
        return attempt_number < self.max_attempts


@dataclass(frozen=True, slots=True)
class LeasePolicy:
    """How long a claim is honoured and when it is considered abandoned."""

    lease_seconds: int = 60
    heartbeat_interval_seconds: int = 15
    #: Grace beyond lease expiry before recovery treats a job as abandoned, so a
    #: momentarily slow worker is not stolen from mid-write.
    stale_grace_seconds: int = 30

    def expires_at(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self.lease_seconds)

    def stale_before(self, now: datetime) -> datetime:
        return now - timedelta(seconds=self.stale_grace_seconds)


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Wall-clock ceiling for one attempt of a job kind."""

    default_seconds: int = 3600
    per_kind_seconds: dict[str, int] | None = None

    def for_kind(self, kind: JobKind) -> int:
        if self.per_kind_seconds and kind.value in self.per_kind_seconds:
            return int(self.per_kind_seconds[kind.value])
        return self.default_seconds

    def deadline(self, *, kind: JobKind, started_at: datetime) -> datetime:
        return started_at + timedelta(seconds=self.for_kind(kind))


@dataclass(frozen=True, slots=True)
class ResourceRequirements:
    """What an execution needs from a node, expressed declaratively.

    The scheduler matches these against a node's advertised resource profile; it
    never inspects the scientific meaning of the work.
    """

    cpu_cores: int = 1
    memory_mib: int = 1024
    disk_mib: int = 1024
    gpu_count: int = 0
    requires_capabilities: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: dict | None) -> ResourceRequirements:
        raw = raw or {}
        capabilities = raw.get("requires_capabilities") or ()
        return cls(
            cpu_cores=int(raw.get("cpu_cores", 1)),
            memory_mib=int(raw.get("memory_mib", 1024)),
            disk_mib=int(raw.get("disk_mib", 1024)),
            gpu_count=int(raw.get("gpu_count", 0)),
            requires_capabilities=tuple(str(item) for item in capabilities),
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "cpu_cores": self.cpu_cores,
            "memory_mib": self.memory_mib,
            "disk_mib": self.disk_mib,
            "gpu_count": self.gpu_count,
            "requires_capabilities": list(self.requires_capabilities),
        }


def node_class_for(kind: JobKind) -> NodeClass:
    return JOB_KIND_NODE_CLASS.get(kind, NodeClass.APPLICATION_WORKER)


def default_queue_for(kind: JobKind) -> JobQueue:
    return DEFAULT_QUEUE_FOR_KIND.get(kind, JobQueue.DEFAULT)


__all__ = [
    "DEFAULT_QUEUE_FOR_KIND",
    "JOB_KIND_NODE_CLASS",
    "RETRYABLE_ERROR_CLASSES",
    "LeasePolicy",
    "ResourceRequirements",
    "RetryPolicy",
    "TimeoutPolicy",
    "classify_exception",
    "default_queue_for",
    "is_retryable",
    "node_class_for",
]
