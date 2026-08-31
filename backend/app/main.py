"""Punto de arranque de la API de TradeBot.

Esqueleto inicial. Los routers de cada feature (spec) se montarán aquí a medida
que se implementen: alpaca-client, data-feed, strategy-engine, order-execution,
backtest-engine, risk-manager, bot-api.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import backtest as backtest_api
from app.api import bot as bot_api
from app.api import credentials as credentials_api
from app.api import market_data as market_data_api
from app.api import ws as ws_api
from app.core.config import get_settings
from app.core.security import EncryptionError
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.alpaca_client.barrier import assert_paper_only
from app.services.alpaca_client.errors import (
    AccountQueryError,
    CredentialsRequiredError,
    InvalidCredentialsError,
    PaperOnlyViolationError,
    TransientAlpacaError,
)
from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.alpaca_client.repository import CredentialRepository
from app.services.backtest.errors import (
    InvalidActionError,
    InvalidDateRangeError,
)
from app.services.bot.orchestrator import BotOrchestrator
from app.services.data_feed.errors import (
    InvalidRangeError,
    InvalidTimeframeError,
)
from app.services.data_feed.historical import HistoricalDataService
from app.services.data_feed.models import Bar
from app.services.data_feed.streaming import MarketDataStreamer
from app.services.execution.events import EventPublisher
from app.services.execution.executor import OrderExecutor
from app.services.execution.positions import PositionManager
from app.services.risk import RiskManager
from app.services.strategies.errors import UnknownStrategyError
from app.services.strategies.registry import build_default_engine
from app.api.ws import WebSocketHub

# Importar los modelos registra sus tablas en Base.metadata antes de create_all.
import app.db.models  # noqa: F401

settings = get_settings()

# Logging explícito: sin esto los logs de la aplicación (nivel INFO) no llegan a
# stdout y el pipeline del bot queda invisible en `docker compose logs backend`.
# Con DEBUG=true en el entorno se sube el detalle a DEBUG.
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, debug=settings.debug)

# Crear las tablas al arranque. En esta fase basta con create_all; una
# herramienta de migraciones puede introducirse en una spec posterior.
Base.metadata.create_all(bind=engine)

# CORS abierto en desarrollo para permitir al frontend Flutter web conectarse.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routers de la capa cliente de Alpaca (spec 01-alpaca-client).
app.include_router(credentials_api.router)
app.include_router(credentials_api.account_router)

# Router opcional de datos históricos (spec 02-data-feed, Tarea 6).
app.include_router(market_data_api.router)

# Router del backtest engine (spec 05-backtest-engine).
app.include_router(backtest_api.router)


# ---------------------------------------------------------------------------
# Cableado del pipeline del bot (spec 07-bot-api, Tarea 4).
#
# Se construyen UNA sola vez al arranque los singletons compartidos que forman
# el pipeline de trading, inyectando el RiskManager REAL (spec 06) en el
# OrderExecutor en lugar del AllowAllRiskManager provisional (decisión de
# integración clave de esta spec).
#
# Sesión de BD dedicada de larga vida: el AlpacaClientFactory (spec 01) necesita
# un CredentialRepository con una Session. Como el bot es un proceso único y de
# larga duración (fase single-user / single-bot), se crea una sesión dedicada
# para su pipeline en lugar de una sesión por request. El resto de endpoints REST
# siguen usando la dependency get_db (sesión por request) sin cambios.
# ---------------------------------------------------------------------------
_bot_db = SessionLocal()
_bot_repository = CredentialRepository(_bot_db)
_bot_factory = AlpacaClientFactory(_bot_repository, settings)

# Pub/sub en memoria de OrderEvent (spec 04); el WebSocketHub se suscribe a él.
_event_publisher = EventPublisher()

# Motor de estrategias con las estrategias por defecto (spec 03).
_strategy_engine = build_default_engine()

# RiskManager REAL (spec 06) con límites conservadores desde Settings. Se inyecta
# en el OrderExecutor sustituyendo al AllowAllRiskManager provisional (spec 04).
_risk_manager = RiskManager(
    daily_loss_limit=settings.risk_daily_loss_limit,
    max_qty=settings.risk_max_qty,
)

_order_executor = OrderExecutor(
    _bot_factory,
    _risk_manager,
    _event_publisher,
    symbol=settings.default_symbol,
    qty=settings.default_qty,
)
_position_manager = PositionManager(_bot_factory, _event_publisher)
_market_streamer = MarketDataStreamer(_bot_factory, symbol=settings.default_symbol)

# Ventanas (en minutos) que prueba la precarga de barras, de menor a mayor. La
# primera que devuelva datos gana. Motivo: el feed de cripto de Alpaca puede
# devolver una respuesta VACÍA para una ventana reciente (retraso de publicación,
# hueco puntual de datos), lo que antes se traducía en "0 barras precargadas" de
# forma intermitente. Ampliar la ventana es la forma más simple y barata de
# recuperarse de ese caso.
_PRELOAD_WINDOWS_MINUTES: tuple[int, ...] = (300, 720, 1440)


def _preload_bars() -> list[Bar]:
    """Precarga barras 1Min recientes del símbolo por defecto para el warm-up.

    Por qué está escrita así:

    - **Ventana creciente** (``_PRELOAD_WINDOWS_MINUTES``): el feed de cripto
      puede devolver vacío para una ventana reciente y dejar a ``predictive``
      sin sus >= 20 barras (con el feed en vivo a ~1 barra/minuto, eso son ~20
      minutos de HOLD forzado). Se reintenta con ventanas cada vez más amplias y
      se devuelve la PRIMERA lista no vacía.
    - **Sesión de BD propia y de vida corta**: esta función la ejecuta el
      orchestrator en un worker thread vía ``asyncio.to_thread``, y las
      ``Session`` de SQLAlchemy no son thread-safe. Crear/cerrar aquí una sesión
      propia elimina ese riesgo por construcción en lugar de compartir la sesión
      de larga vida del pipeline (``_bot_db``).
    - **Best-effort pero OBSERVABLE**: los fallos no pueden impedir el arranque,
      así que se devuelve ``[]``; pero cada intento fallido (excepción o
      respuesta vacía) se registra en el log, de modo que "0 barras" ya no es
      indistinguible de "no hay datos".

    ``get_bars`` devuelve la lista ya ordenada ascendente. Es síncrona (usa
    requests) y por eso el orchestrator la lanza fuera del event loop.
    """
    db = SessionLocal()
    try:
        service = HistoricalDataService(
            AlpacaClientFactory(CredentialRepository(db), settings)
        )
        for window in _PRELOAD_WINDOWS_MINUTES:
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=window)
            try:
                bars = service.get_bars(
                    settings.default_symbol, "1Min", start, end
                )
            except Exception as exc:  # noqa: BLE001 - se registra y se reintenta
                logger.warning(
                    "Historical bar preload attempt failed "
                    "(symbol=%s window=%dmin): %s: %s",
                    settings.default_symbol,
                    window,
                    type(exc).__name__,
                    exc,
                )
                logger.debug("Preload attempt traceback", exc_info=True)
                continue

            if bars:
                logger.info(
                    "Historical bar preload got %d bars "
                    "(symbol=%s window=%dmin)",
                    len(bars),
                    settings.default_symbol,
                    window,
                )
                return bars

            logger.warning(
                "Historical bar preload returned an EMPTY series "
                "(symbol=%s window=%dmin); retrying with a wider window",
                settings.default_symbol,
                window,
            )

        logger.warning(
            "Historical bar preload returned no data after %d attempts "
            "(symbol=%s); predictive will need ~20 live bars to warm up",
            len(_PRELOAD_WINDOWS_MINUTES),
            settings.default_symbol,
        )
        return []
    finally:
        db.close()


# El orchestrator verifica que existan credenciales activas antes de arrancar
# (R2.3): un start sin credenciales -> CredentialsRequiredError -> 409.
_bot_orchestrator = BotOrchestrator(
    _market_streamer,
    _strategy_engine,
    _order_executor,
    _position_manager,
    symbol=settings.default_symbol,
    credential_check=lambda: _bot_repository.get_active() is not None,
    bar_preloader=_preload_bars,
)

# Hub que puentea el EventPublisher a los clientes WebSocket (R3).
_ws_hub = WebSocketHub(_event_publisher)

# Publicar los singletons compartidos en app.state para que los routers los lean.
app.state.bot_orchestrator = _bot_orchestrator
app.state.ws_hub = _ws_hub

# Routers del bot: control REST (spec 07 Tarea 4) y feed WebSocket (Tarea 2).
app.include_router(bot_api.router)
app.include_router(ws_api.router)


def _error_response(status_code: int, error_code: str, detail: str) -> JSONResponse:
    """Construye una respuesta de error estable a partir de textos estáticos.

    Los mensajes provienen SOLO de cadenas fijas: nunca se serializa el
    contenido de la excepción, de modo que ningún secreto (API Key/Secret en
    claro) puede filtrarse a la respuesta ni a los logs (R1.4).
    """
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error_code, "detail": detail},
    )


# Exception handlers: cada error de dominio se mapea a un status HTTP distinto y
# a un ``error_code`` estable, de forma que el frontend pueda distinguir un fallo
# de autenticación (401) de uno transitorio (502) programáticamente (R2.3). Sin
# filtrar secretos en ningún caso (R1.4).
@app.exception_handler(EncryptionError)
def _handle_encryption_error(request: Request, exc: EncryptionError) -> JSONResponse:
    return _error_response(
        503, "encryption_unavailable", "encryption key unavailable or invalid"
    )


@app.exception_handler(InvalidCredentialsError)
def _handle_invalid_credentials(
    request: Request, exc: InvalidCredentialsError
) -> JSONResponse:
    return _error_response(401, "invalid_credentials", "invalid Alpaca credentials")


@app.exception_handler(TransientAlpacaError)
def _handle_transient(request: Request, exc: TransientAlpacaError) -> JSONResponse:
    return _error_response(
        502, "transient_error", "temporary problem reaching Alpaca, try again"
    )


@app.exception_handler(AccountQueryError)
def _handle_account_query(request: Request, exc: AccountQueryError) -> JSONResponse:
    return _error_response(502, "account_query_failed", "account query failed")


# Errores de dominio del data-feed (spec 02-data-feed, Tarea 6). Se validan en
# proceso ANTES de cualquier llamada a Alpaca, de modo que el frontend pueda
# distinguir un timeframe no soportado (400 invalid_timeframe) de un rango de
# fechas inválido (400 invalid_range) programáticamente (R1.4, R1.5).
@app.exception_handler(InvalidTimeframeError)
def _handle_invalid_timeframe(
    request: Request, exc: InvalidTimeframeError
) -> JSONResponse:
    return _error_response(400, "invalid_timeframe", "unsupported timeframe")


@app.exception_handler(InvalidRangeError)
def _handle_invalid_range(request: Request, exc: InvalidRangeError) -> JSONResponse:
    return _error_response(400, "invalid_range", "invalid date range")


@app.exception_handler(CredentialsRequiredError)
def _handle_credentials_required(
    request: Request, exc: CredentialsRequiredError
) -> JSONResponse:
    return _error_response(409, "no_credentials", "no credentials configured")


@app.exception_handler(PaperOnlyViolationError)
def _handle_paper_only(request: Request, exc: PaperOnlyViolationError) -> JSONResponse:
    return _error_response(500, "paper_only_violation", "paper-only barrier violation")


# Bot API (spec 07-bot-api): un modo de estrategia no registrado en POST
# /bot/start se mapea a 400 invalid_mode, distinguible del 409 no_credentials
# (que reutiliza el handler de CredentialsRequiredError ya definido) (R2.4).
@app.exception_handler(UnknownStrategyError)
def _handle_unknown_strategy(
    request: Request, exc: UnknownStrategyError
) -> JSONResponse:
    return _error_response(400, "invalid_mode", "unknown strategy mode")


# Backtest engine (spec 05-backtest-engine): errores de dominio del motor de
# replay. Se distinguen de los errores del data-feed: aquí InvalidDateRangeError
# proviene del propio engine (el data-feed valida el rango ANTES y produce
# invalid_range), e InvalidActionError indica que una estrategia devolvió una
# acción fuera de BUY/SELL/HOLD durante el replay (R1.8, R1.9). Un modo no
# registrado reutiliza el handler de UnknownStrategyError (400 invalid_mode).
@app.exception_handler(InvalidDateRangeError)
def _handle_invalid_date_range(
    request: Request, exc: InvalidDateRangeError
) -> JSONResponse:
    return _error_response(400, "invalid_date_range", "invalid backtest date range")


@app.exception_handler(InvalidActionError)
def _handle_invalid_action(request: Request, exc: InvalidActionError) -> JSONResponse:
    return _error_response(
        400, "invalid_action", "strategy returned an invalid action"
    )


@app.on_event("startup")
def _enforce_paper_only() -> None:
    """Barrera dura: una mala configuración impide arrancar (R5.2)."""
    assert_paper_only(get_settings())


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Health check simple para Docker/compose y para el frontend."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "mode": "paper" if settings.alpaca_paper_only else "LIVE",
        "default_symbol": settings.default_symbol,
    }
