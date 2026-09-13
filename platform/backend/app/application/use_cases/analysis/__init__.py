"""Analysis orchestration use cases.

Orchestration only: this package decides *whether* work may be requested, in
which scope, with which frozen configuration, and how the resulting durable job
is scheduled. It contains no scientific algorithm — the scientific meaning of a
configuration section belongs to the independent scientific subsystem behind the
integration contract.
"""
