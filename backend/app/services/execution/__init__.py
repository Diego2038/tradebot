"""Order execution package (spec 04-order-execution).

The full order-execution pipeline (executor, positions, orders, events) is owned
by spec ``04-order-execution`` and will live in this package once it is
implemented. Until then, this package hosts only :mod:`app.services.execution.risk`,
which defines the risk port types (``ProposedOrder``, ``RiskDecision`` and the
``RiskPort`` protocol).

Those port types are reused as-is by spec ``06-risk-manager``, whose
``RiskManager`` implements ``RiskPort``. Both specs share this exact module path
and type definitions so there is no duplication or conflict: when spec 04 is
implemented it extends this package (adding the executor and its
``AllowAllRiskManager`` pass-through) without redefining the risk port types.
"""
