"""Risk Manager domain package (spec 06-risk-manager).

Public exports for the risk package: the concrete :class:`RiskManager`
(``RiskPort`` implementation), the :class:`EquityProvider` port and its optional
:class:`AccountServiceEquityProvider` adapter, and the :class:`RiskConfigError`
raised on invalid configuration.
"""

from app.services.risk.equity import AccountServiceEquityProvider, EquityProvider
from app.services.risk.errors import RiskConfigError
from app.services.risk.manager import RiskManager

__all__ = [
    "RiskManager",
    "EquityProvider",
    "AccountServiceEquityProvider",
    "RiskConfigError",
]
