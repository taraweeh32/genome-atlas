"""The evidence layer.

Evidence is its own first-class concept. It is not a variant, not an annotation
value, not a clinical assertion, not an interpretation criterion, not a
classification and
not a human interpretation. This package models:

* **an evidence source version** — a registered, versioned external or internal
  resource that evidence came from, held in the existing scientific resource
  registry (kind ``evidence_resource``);
* **an evidence record** — one discrete piece of evidence about one variant, with
  its source identity, source release, retrieval time, context, origin, method
  and provenance;
* **an ingestion batch** — one validated delivery of evidence records, idempotent
  by payload digest, with its validation findings;
* **a conflict set** — disagreement between retained records, computed on read.

Two rules this package never breaks: it does **not** decide whether evidence
satisfies any interpretation criterion or supports any classification, and it
never
overwrites one source's evidence with another's. Disagreement is preserved.
"""
