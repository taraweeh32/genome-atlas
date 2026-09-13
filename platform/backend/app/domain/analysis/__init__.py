"""Analysis, execution, job and scheduling domain.

Orchestration only. Nothing in this package computes a scientific result: it
decides *whether* work may be requested, *when* it runs, *where* it may run,
*how many times* it may be attempted, and *what must be recorded* about it. The
computation itself happens in the independently deployed scientific subsystem,
reached only through ``app.scientific.contracts``.
"""

from __future__ import annotations
