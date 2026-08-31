"""Configuración de la aplicación, cargada desde variables de entorno."""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Aplicación
    app_name: str = "TradeBot"
    debug: bool = False

    # Base de datos
    database_url: str = "postgresql+psycopg://tradebot:tradebot@db:5432/tradebot"

    # Clave maestra de cifrado (Fernet). OBLIGATORIA en producción.
    # Genera una con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    app_encryption_key: str = ""

    # Alpaca: SIEMPRE paper trading en esta fase.
    alpaca_paper_base_url: str = "https://paper-api.alpaca.markets"
    # Barrera de seguridad: debe permanecer True. Impide apuntar a producción.
    alpaca_paper_only: bool = True

    # Activo por defecto
    default_symbol: str = "BTC/USD"

    # Límites de riesgo del bot (spec 06-risk-manager, inyectados en el
    # OrderExecutor). Valores por defecto conservadores; se pueden ajustar por
    # entorno. Se usan Decimal para no perder precisión monetaria.
    risk_daily_loss_limit: Decimal = Decimal("100")
    risk_max_qty: Decimal = Decimal("0.01")
    # Cantidad por orden que envía el OrderExecutor (paper). Conservadora.
    default_qty: Decimal = Decimal("0.001")


@lru_cache
def get_settings() -> Settings:
    return Settings()
