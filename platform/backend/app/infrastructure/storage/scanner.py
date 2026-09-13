"""Malware scanning boundary for uploaded artifacts.

Scanning is an integration boundary, and it fails **closed**: when no scanner is
configured the verdict is ``UNAVAILABLE``, which the upload lifecycle treats as
"may not be used", never as "clean". That distinction is the whole point of
having the port — a deployment without a scanner degrades visibly instead of
silently accepting unscanned genomic uploads.

The signature scanner here is a *development and test* adapter. It recognises
the industry-standard EICAR test string so the quarantine path can be exercised
end to end without shipping malware, and it is refused in production by
``build_scanner``.
"""

from __future__ import annotations

from typing import Protocol

from app.application.ports import ScanResult, ScanVerdict
from app.core.environment import Environment
from app.core.logging import get_logger

logger = get_logger(__name__)

#: The EICAR test signature, split so this source file is not itself flagged.
_EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-" b"ANTIVIRUS-TEST-FILE!$H+H*"

#: Prefix examined by the development scanner. A real scanner reads the whole
#: object; this one is explicitly a bounded stand-in and says so in its detail.
SIGNATURE_SCAN_BYTES = 1024 * 1024


class _HeadReader(Protocol):
    async def read_head(self, key: str, *, max_bytes: int) -> bytes: ...


class UnavailableFileScanner:
    """The production default until a real scanner is deployed.

    Returning ``UNAVAILABLE`` is not a failure of this class: it is the honest
    answer, and it blocks acceptance of every artifact it is asked about.
    """

    name = "none"
    version = "0"

    async def scan(self, key: str) -> ScanResult:
        logger.warning("no malware scanner configured; refusing to report clean")
        return ScanResult(
            verdict=ScanVerdict.UNAVAILABLE,
            scanner_name=self.name,
            scanner_version=self.version,
            detail="no malware scanner is configured for this deployment",
        )


class SignatureFileScanner:
    """Development/test scanner: EICAR signature detection over a bounded prefix.

    Deliberately not presented as protection. It exists so that the quarantine
    lifecycle is covered by real tests rather than asserted in prose.
    """

    name = "development-signature-scanner"
    version = "1"

    def __init__(self, storage: _HeadReader, *, max_bytes: int = SIGNATURE_SCAN_BYTES) -> None:
        self._storage = storage
        self._max_bytes = max_bytes

    async def scan(self, key: str) -> ScanResult:
        try:
            head = await self._storage.read_head(key, max_bytes=self._max_bytes)
        except Exception as exc:  # noqa: BLE001 - any read failure is a failed scan
            return ScanResult(
                verdict=ScanVerdict.FAILED,
                scanner_name=self.name,
                scanner_version=self.version,
                detail=f"the object could not be read for scanning: {type(exc).__name__}",
            )
        if _EICAR in head:
            return ScanResult(
                verdict=ScanVerdict.INFECTED,
                scanner_name=self.name,
                scanner_version=self.version,
                detail="EICAR test signature detected",
            )
        return ScanResult(
            verdict=ScanVerdict.CLEAN,
            scanner_name=self.name,
            scanner_version=self.version,
            detail=f"signature scan over the first {self._max_bytes} bytes",
        )


def build_scanner(
    *, environment: Environment, storage: _HeadReader, enabled: bool
) -> UnavailableFileScanner | SignatureFileScanner:
    """Choose a scanner for this deployment.

    The development scanner is never selected in production, even if
    configuration asks for it: a stand-in must not be able to masquerade as
    protection in a production environment.
    """
    if not enabled:
        return UnavailableFileScanner()
    if environment.is_production_like:
        logger.error(
            "the development signature scanner is not permitted in a production-like "
            "environment; scanning will report unavailable"
        )
        return UnavailableFileScanner()
    return SignatureFileScanner(storage)


__all__ = [
    "SIGNATURE_SCAN_BYTES",
    "SignatureFileScanner",
    "UnavailableFileScanner",
    "build_scanner",
]
