# TradeBot

Bot de trading automatizado sobre **Alpaca** (API oficial), controlado desde una web en
React + TypeScript (Vite). Backend en FastAPI, base de datos PostgreSQL, todo orquestado
con Docker.

> **Solo paper trading.** La aplicación opera exclusivamente contra el entorno de pruebas
> de Alpaca (`https://paper-api.alpaca.markets`). No se usa dinero real en esta fase.

## Características

- Bot con dos modos seleccionables desde la web: **random** (línea base) y **predictive**
  (estrategias sobre históricos: cruce de medias móviles, RSI).
- Activo inicial: **BTC/USD**.
- **API Key de Alpaca cifrada** en la base de datos; solo se descifra en memoria del
  backend al usarla. Nunca se devuelve al frontend ni se registra en logs.
- **Feed en tiempo real** (WebSocket) de las acciones del bot en el dashboard.
- Todo dockerizado: `docker compose up` levanta la app completa, sin instalar nada local.

## Arquitectura

```
frontend (React + Vite) ──REST/WebSocket──▶  backend (FastAPI)  ──▶  Alpaca (paper)
                                                    │
                                                    ▼
                                              PostgreSQL (credenciales cifradas, estado)
```

## Puesta en marcha

Requisito único: **Docker** + **Docker Compose**.

1. Copia la plantilla de entorno y genera la clave de cifrado:
   ```bash
   cp .env.example .env
   # Genera APP_ENCRYPTION_KEY y pégala en .env:
   docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
   ```
2. Levanta todo:
   ```bash
   docker compose up --build
   ```
3. Abre:
   - Frontend: http://localhost:8080
   - Backend (health): http://localhost:8000/health
4. Desde la web, ingresa tu **API Key/Secret de Alpaca paper** (cuenta gratuita, solo
   email en https://alpaca.markets). El backend las cifra antes de guardarlas.

## Tests (backend)

```bash
docker compose run --rm backend pytest
```

## Estructura por specs

El desarrollo está organizado en features modulares bajo `.kiro/specs/`. Cada uno se
implementa en su propia sesión **Spec** de Kiro (requisitos → diseño → tareas):

| Spec | Feature | Código |
|------|---------|--------|
| `01-alpaca-client`   | Conexión REST/WS, auth y saldo (paper) | `backend/app/services/alpaca_client/` |
| `02-data-feed`       | Datos de mercado (histórico + tiempo real) | `backend/app/services/data_feed/` |
| `03-strategy-engine` | Estrategias: random + predictive (SMA, RSI) | `backend/app/services/strategies/` |
| `04-order-execution` | Órdenes, Stop-Loss, Take-Profit | `backend/app/services/execution/` |
| `05-backtest-engine` | Simulación con datos históricos | `backend/app/services/backtest/` |
| `06-risk-manager`    | Límites de pérdida y tamaño de lote | `backend/app/services/risk/` |
| `07-bot-api`         | FastAPI: REST/WebSocket hacia el frontend | `backend/app/api/` |
| `08-web-frontend`    | React + Vite: control + dashboard en vivo | `frontend/src/` |

## Estado actual

Esqueleto listo (Opción A): scaffolding dockerizado, steering y borradores de
`requirements.md` en los 8 specs. La implementación de cada feature se hará en sesiones
Spec dedicadas, empezando por `01-alpaca-client`.
