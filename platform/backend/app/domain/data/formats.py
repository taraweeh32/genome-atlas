"""File-name safety, format recognition and declared-metadata rules.

Everything here is a *file* concern, not a scientific one. Recognising that an
object is a bgzip-compressed VCF says nothing about whether its records describe
valid variants; that judgement belongs to the scientific compute subsystem.

Two rules are enforced strictly:

* A client-supplied filename is never used as a storage key, and never trusted
  for path structure. It is sanitised for display and preserved verbatim as
  source metadata.
* A declared format is a claim. When detection contradicts the claim, the
  contradiction is recorded as a validation issue rather than resolved silently.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import (
    CompressionKind,
    DatasetKind,
    InputFormat,
)

#: Characters allowed in a sanitised display filename.
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILENAME_LENGTH = 255

#: Extension → (format, compression). Compound extensions are matched first so
#: ``.vcf.gz`` is never read as a bare ``.gz``.
_EXTENSION_TABLE: tuple[tuple[str, InputFormat, CompressionKind], ...] = (
    (".vcf.gz", InputFormat.VCF, CompressionKind.BGZF),
    (".vcf.bgz", InputFormat.VCF, CompressionKind.BGZF),
    (".tsv.gz", InputFormat.TSV, CompressionKind.GZIP),
    (".csv.gz", InputFormat.CSV, CompressionKind.GZIP),
    (".txt.gz", InputFormat.TEXT, CompressionKind.GZIP),
    (".json.gz", InputFormat.JSON, CompressionKind.GZIP),
    (".vcf", InputFormat.VCF, CompressionKind.NONE),
    (".bcf", InputFormat.BCF, CompressionKind.NONE),
    (".tsv", InputFormat.TSV, CompressionKind.NONE),
    (".tab", InputFormat.TSV, CompressionKind.NONE),
    (".csv", InputFormat.CSV, CompressionKind.NONE),
    (".json", InputFormat.JSON, CompressionKind.NONE),
    (".txt", InputFormat.TEXT, CompressionKind.NONE),
)

#: Formats this platform accepts as a scientific input, by dataset kind. An
#: unaccepted format is refused at the boundary rather than half-imported.
ACCEPTED_FORMATS: dict[DatasetKind, frozenset[InputFormat]] = {
    DatasetKind.VARIANT_CALLS: frozenset(
        {InputFormat.VCF, InputFormat.BCF, InputFormat.TSV, InputFormat.CSV}
    ),
    DatasetKind.SAMPLE_MANIFEST: frozenset({InputFormat.CSV, InputFormat.TSV}),
    DatasetKind.PHENOTYPE: frozenset({InputFormat.CSV, InputFormat.TSV}),
    DatasetKind.ANNOTATION_INPUT: frozenset(
        {InputFormat.CSV, InputFormat.TSV, InputFormat.JSON}
    ),
    DatasetKind.ALIGNMENT: frozenset(),
    DatasetKind.DERIVED_RESULT: frozenset(
        {InputFormat.CSV, InputFormat.TSV, InputFormat.JSON}
    ),
    DatasetKind.OTHER: frozenset(
        {InputFormat.CSV, InputFormat.TSV, InputFormat.TEXT, InputFormat.JSON}
    ),
}

#: Tabular formats have a column structure the platform may inspect.
TABULAR_FORMATS: frozenset[InputFormat] = frozenset({InputFormat.CSV, InputFormat.TSV})

_DELIMITERS: dict[InputFormat, str] = {InputFormat.CSV: ",", InputFormat.TSV: "\t"}

#: Leading byte signatures used to detect the container, independent of the name.
_GZIP_MAGIC = b"\x1f\x8b"
_BCF_MAGIC = b"BCF\x02"
_VCF_MAGIC = b"##fileformat=VCF"


@dataclass(frozen=True, slots=True)
class FormatDetection:
    """What the bytes and the name each say, kept separate on purpose."""

    format: InputFormat
    compression: CompressionKind
    #: True when detection could not identify the container at all.
    inconclusive: bool = False


def sanitize_filename(raw: str) -> str:
    """Return a safe display filename, or refuse the input.

    Path traversal, absolute paths, control characters and empty names are
    refused rather than repaired, because a name that needs repairing to be safe
    is a name the submitter should correct.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise ValidationError("a filename is required", details={"field": "filename"})
    if len(candidate) > MAX_FILENAME_LENGTH:
        raise ValidationError(
            "filename is too long",
            details={"field": "filename", "max_length": MAX_FILENAME_LENGTH},
        )
    if "\x00" in candidate or any(ord(c) < 32 for c in candidate):
        raise ValidationError(
            "filename contains control characters", details={"field": "filename"}
        )
    if candidate.startswith("/") or "\\" in candidate:
        raise ValidationError(
            "filename must not contain a path", details={"field": "filename"}
        )
    if posixpath.basename(candidate) != candidate or candidate in {".", ".."}:
        raise ValidationError(
            "filename must not contain a path", details={"field": "filename"}
        )
    safe = _SAFE_FILENAME.sub("_", candidate).lstrip(".")
    if not safe:
        raise ValidationError("filename is not usable", details={"field": "filename"})
    return safe


def format_from_filename(filename: str) -> FormatDetection:
    """Recognise the *claimed* container from the name only."""
    lowered = filename.lower()
    for extension, input_format, compression in _EXTENSION_TABLE:
        if lowered.endswith(extension):
            return FormatDetection(input_format, compression)
    if lowered.endswith(".gz"):
        return FormatDetection(InputFormat.UNKNOWN, CompressionKind.GZIP, True)
    if lowered.endswith(".zip"):
        return FormatDetection(InputFormat.UNKNOWN, CompressionKind.ZIP, True)
    return FormatDetection(InputFormat.UNKNOWN, CompressionKind.UNKNOWN, True)


def detect_format(head: bytes, *, filename: str | None = None) -> FormatDetection:
    """Recognise the container from the leading bytes, with the name as a hint.

    The bytes win over the name: a ``.csv`` that begins with a gzip signature is
    reported as compressed, so the mismatch surfaces instead of a parser being
    handed content it cannot read.
    """
    if head.startswith(_BCF_MAGIC):
        return FormatDetection(InputFormat.BCF, CompressionKind.NONE)
    if head.startswith(_GZIP_MAGIC):
        # Distinguishing bgzf from plain gzip needs the BGZF extra field; the
        # name is the only hint available from the first bytes alone.
        named = format_from_filename(filename or "")
        compression = (
            CompressionKind.BGZF
            if named.compression is CompressionKind.BGZF
            else CompressionKind.GZIP
        )
        return FormatDetection(named.format, compression, named.format is InputFormat.UNKNOWN)
    if head.startswith(_VCF_MAGIC):
        return FormatDetection(InputFormat.VCF, CompressionKind.NONE)
    text = head[:4096]
    try:
        decoded = text.decode("utf-8")
    except UnicodeDecodeError:
        return FormatDetection(InputFormat.UNKNOWN, CompressionKind.UNKNOWN, True)
    stripped = decoded.lstrip()
    if stripped.startswith(("{", "[")):
        return FormatDetection(InputFormat.JSON, CompressionKind.NONE)
    first_line = decoded.splitlines()[0] if decoded.splitlines() else ""
    if first_line.count("\t") >= 1:
        return FormatDetection(InputFormat.TSV, CompressionKind.NONE)
    if first_line.count(",") >= 1:
        return FormatDetection(InputFormat.CSV, CompressionKind.NONE)
    if first_line:
        return FormatDetection(InputFormat.TEXT, CompressionKind.NONE)
    return FormatDetection(InputFormat.UNKNOWN, CompressionKind.UNKNOWN, True)


def delimiter_for(input_format: InputFormat) -> str:
    delimiter = _DELIMITERS.get(input_format)
    if delimiter is None:
        raise ValidationError(
            "format is not tabular", details={"format": input_format.value}
        )
    return delimiter


def require_accepted_format(kind: DatasetKind, declared: InputFormat) -> InputFormat:
    accepted = ACCEPTED_FORMATS.get(kind, frozenset())
    if declared not in accepted:
        raise ValidationError(
            "the declared format is not accepted for this dataset kind",
            details={
                "field": "declared_format",
                "dataset_kind": kind.value,
                "declared_format": declared.value,
                "accepted_formats": sorted(f.value for f in accepted),
            },
        )
    return declared


def require_within_size_limit(size_bytes: int, *, limit_bytes: int) -> int:
    """Size is checked before a URL is issued, not after bytes have arrived."""
    if size_bytes <= 0:
        raise ValidationError(
            "declared size must be greater than zero",
            details={"field": "size_bytes"},
        )
    if size_bytes > limit_bytes:
        raise ValidationError(
            "declared size exceeds the configured upload limit",
            details={"field": "size_bytes", "limit_bytes": limit_bytes},
        )
    return size_bytes


__all__ = [
    "ACCEPTED_FORMATS",
    "MAX_FILENAME_LENGTH",
    "TABULAR_FORMATS",
    "FormatDetection",
    "delimiter_for",
    "detect_format",
    "format_from_filename",
    "require_accepted_format",
    "require_within_size_limit",
    "sanitize_filename",
]
