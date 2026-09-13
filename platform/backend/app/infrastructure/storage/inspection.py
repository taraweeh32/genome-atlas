"""Structural inspection of an uploaded artifact.

Reads a bounded prefix and reports *file* facts: which container the bytes
actually are, whether they are compressed, and — for tabular inputs — what the
header columns are and what the sampled values mean semantically.

Everything here stops short of interpretation:

* A column named ``CHROM`` is reported as a column named ``CHROM``. Deciding
  whether its values are valid contigs for a reference build is scientific work
  performed outside ordinary application code.
* A sampled value is classified into an explicit semantic (present, empty, NA,
  unknown, zero, false…) and never coerced. The sample itself is kept short and
  is only used to describe the shape of a column.
* Because only a prefix is read, the result is reported as ``truncated`` unless
  the whole object fitted in the sample. Nothing pretends the file was fully
  parsed.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from collections import Counter

from app.application.ports import FileInspection, InspectedColumn
from app.core.logging import get_logger
from app.domain.data.formats import TABULAR_FORMATS, delimiter_for, detect_format
from app.domain.data.semantics import classify
from app.domain.value_objects.enums import CompressionKind, InputFormat, ValueSemantics

logger = get_logger(__name__)

#: Bytes read from the front of an object. Large enough for a VCF header block,
#: small enough that inspection never becomes a data transfer.
INSPECTION_BYTES = 512 * 1024

#: Sampled data rows per inspection, and characters kept per sampled value.
SAMPLE_ROW_LIMIT = 50
SAMPLE_VALUE_LENGTH = 64
SAMPLE_VALUES_PER_COLUMN = 5

MAX_COLUMNS = 4096


class StreamingFileInspector:
    """Inspects the leading bytes of a stored object."""

    version = "1"

    def __init__(self, storage, *, max_bytes: int = INSPECTION_BYTES) -> None:
        self._storage = storage
        self._max_bytes = max_bytes

    async def inspect(self, key: str, *, declared_filename: str) -> FileInspection:
        raw = await self._storage.read_head(key, max_bytes=self._max_bytes)
        detection = detect_format(raw, filename=declared_filename)
        problems: list[str] = []

        payload = raw
        if detection.compression in (CompressionKind.GZIP, CompressionKind.BGZF):
            payload, decompression_problem = _decompress_prefix(raw)
            if decompression_problem:
                problems.append(decompression_problem)
        elif detection.compression is CompressionKind.ZIP:
            problems.append("zip_container_not_supported")
            payload = b""

        inner_format = detection.format
        if detection.compression in (CompressionKind.GZIP, CompressionKind.BGZF) and payload:
            # The name suggested the inner format; the decompressed bytes decide.
            inner = detect_format(payload, filename=_strip_compression(declared_filename))
            if inner.format is not InputFormat.UNKNOWN:
                inner_format = inner.format

        if detection.inconclusive and inner_format is InputFormat.UNKNOWN:
            problems.append("format_not_recognised")

        columns: tuple[InspectedColumn, ...] = ()
        header_lines = 0
        sampled_records = 0
        truncated = len(raw) >= self._max_bytes

        if inner_format is InputFormat.VCF:
            header_lines, columns, sampled_records = _inspect_vcf(payload)
        elif inner_format in TABULAR_FORMATS:
            header_lines, columns, sampled_records = _inspect_delimited(
                payload, delimiter_for(inner_format), truncated=truncated
            )
        elif (
            inner_format is InputFormat.JSON
            and not truncated
            and not _is_parseable_json(payload)
        ):
            # Only a complete object can be judged unparseable; a truncated prefix
            # of valid JSON is not evidence of a malformed document.
            problems.append("json_not_parseable")

        if len(columns) > MAX_COLUMNS:
            problems.append("too_many_columns")
            columns = columns[:MAX_COLUMNS]

        return FileInspection(
            detected_format=inner_format,
            compression=detection.compression,
            columns=columns,
            header_line_count=header_lines,
            sampled_record_count=sampled_records,
            truncated=truncated,
            problems=tuple(problems),
        )


def _strip_compression(filename: str) -> str:
    lowered = filename.lower()
    for suffix in (".gz", ".bgz"):
        if lowered.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def _decompress_prefix(raw: bytes) -> tuple[bytes, str | None]:
    """Decompress as much of a gzip/bgzf prefix as is available.

    A truncated member is expected — only a prefix was read — so an
    ``EOFError`` is not a problem with the file. A trailing-garbage or
    bad-header error is.
    """
    stream = gzip.GzipFile(fileobj=io.BytesIO(raw))
    out = bytearray()
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            out.extend(chunk)
    except EOFError:
        pass
    except (OSError, gzip.BadGzipFile) as exc:
        if out:
            return bytes(out), None
        return b"", f"compressed_stream_unreadable:{type(exc).__name__}"
    return bytes(out), None


def _decode(payload: bytes) -> tuple[str, bool]:
    """Decode text, dropping a trailing partial character or line."""
    try:
        return payload.decode("utf-8"), True
    except UnicodeDecodeError:
        return payload.decode("utf-8", errors="ignore"), False


def _sample_columns(
    headers: list[str], rows: list[list[str]]
) -> tuple[InspectedColumn, ...]:
    columns: list[InspectedColumn] = []
    for index, header in enumerate(headers):
        values = [row[index] if index < len(row) else None for row in rows]
        semantics = Counter(classify(value) for value in values)
        non_empty = sum(
            count
            for semantic, count in semantics.items()
            if semantic is not ValueSemantics.MISSING and semantic is not ValueSemantics.EMPTY
        )
        sampled = tuple(
            (value or "")[:SAMPLE_VALUE_LENGTH]
            for value in values[:SAMPLE_VALUES_PER_COLUMN]
        )
        columns.append(
            InspectedColumn(
                name=header,
                index=index,
                non_empty_sample_count=non_empty,
                sampled_values=sampled,
            )
        )
    return tuple(columns)


def _inspect_delimited(
    payload: bytes, delimiter: str, *, truncated: bool
) -> tuple[int, tuple[InspectedColumn, ...], int]:
    text, complete = _decode(payload)
    lines = text.splitlines()
    if (truncated or not complete) and lines:
        # The last line of a prefix is probably cut in half; a half row must not
        # be reported as a short row.
        lines = lines[:-1]
    if not lines:
        return 0, (), 0
    reader = csv.reader(lines, delimiter=delimiter)
    records = [row for row in reader if row]
    if not records:
        return 0, (), 0
    headers = [cell.strip() for cell in records[0]]
    data_rows = records[1 : 1 + SAMPLE_ROW_LIMIT]
    return 1, _sample_columns(headers, data_rows), len(data_rows)


def _inspect_vcf(payload: bytes) -> tuple[int, tuple[InspectedColumn, ...], int]:
    """Read the VCF header block and the column line, nothing more.

    Locating ``#CHROM`` is text handling. Whether the records beneath it are
    biologically coherent is not decided here.
    """
    text, complete = _decode(payload)
    lines = text.splitlines()
    if not complete and lines:
        lines = lines[:-1]
    meta_lines = 0
    headers: list[str] = []
    data_rows: list[list[str]] = []
    for line in lines:
        if line.startswith("##"):
            meta_lines += 1
            continue
        if line.startswith("#CHROM"):
            headers = [cell.strip() for cell in line.lstrip("#").split("\t")]
            headers[0] = "CHROM"
            meta_lines += 1
            continue
        if not headers:
            continue
        if len(data_rows) >= SAMPLE_ROW_LIMIT:
            break
        data_rows.append(line.split("\t"))
    return meta_lines, _sample_columns(headers, data_rows), len(data_rows)


def _is_parseable_json(payload: bytes) -> bool:
    try:
        json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


__all__ = [
    "INSPECTION_BYTES",
    "SAMPLE_ROW_LIMIT",
    "StreamingFileInspector",
]
