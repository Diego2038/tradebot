# TradeBot

**Language / Idioma:** [🇬🇧 English](#tradebot--english) · [🇪🇸 Español](#tradebot--español)

---

<a id="tradebot--english"></a>

# TradeBot &nbsp;·&nbsp; English

Automated trading bot on top of **Alpaca** (official API), controlled from a web interface and with **real-time** tracking of every action it takes. The backend is built with **FastAPI (Python)**, the frontend with **React + TypeScript (Vite)**, persistence uses **PostgreSQL**, and the whole application spins up with **Docker** without installing any dependency on your machine.

> ⚠️ **Paper trading only (fake money).**
> The application runs exclusively against Alpaca's test environment (`https://paper-api.alpaca.markets`). **No real money is used under any circumstance in this phase.** An explicit barrier (`ALPACA_PAPER_ONLY=true`) prevents accidentally pointing at production.

---

## Table of contents

- [What is TradeBot?](#what-is-tradebot)
- [Features](#features)
- [Architecture](#architecture-en)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment variables](#environment-variables)
- [Running the app](#running-the-app)
- [Using the app (step by step)](#using-the-app-step-by-step)
- [Tests](#tests-en)
- [Useful commands](#useful-commands)
- [Project structure](#project-structure)
- [Credential security](#credential-security)
- [Project status](#project-status)

---

## What is TradeBot?

TradeBot is a web application that runs an automated trading bot on the **Alpaca** platform, consuming its official API. You control the bot from the frontend (start, stop, pick a strategy) and watch, in real time, every signal, order, fill, error, or state change the bot produces.

- **Initial asset:** BTC/USD (crypto, 24/7 market, convenient for testing).
- **Trading modes** selectable from the web UI:
  - `random`: the bot decides at random (baseline / sanity check).
  - `predictive`: the bot decides using strategies based on historical data (moving-average crossover, RSI).

---

## Features

- 🤖 **Two trading modes** selectable from the web: `random` and `predictive`.
- 🔐 **Alpaca API Key encrypted** in the database (Fernet symmetric encryption). It is decrypted only in the backend's memory when building the client. It is never returned to the frontend nor written to logs.
- 📡 **Real-time transparency:** every bot action is streamed to the frontend over WebSocket.
- ▶️⏹️ **Full control:** start and stop the bot at any moment from the interface.
- 📊 **Backtesting from the web:** simulate a strategy over historical BTC/USD data (deterministic, reproducible with a seed) and review its performance metrics.
- 🐳 **Zero setup friction:** clone the repo and run one command to bring up the whole app. No need to install Python, Node, or PostgreSQL locally.

---

<a id="architecture-en"></a>

## Architecture

```
┌─────────────────────────┐        REST + WebSocket        ┌─────────────────────────┐
│  Frontend                │ ─────────────────────────────▶ │  Backend                 │       ┌──────────────────────┐
│  React + TypeScript      │ ◀───────────────────────────── │  FastAPI (Python 3.12)   │ ────▶ │  Alpaca (paper API)  │
│  (Vite, served by nginx) │        live actions (WS)        │                          │       └──────────────────────┘
└─────────────────────────┘                                 └───────────┬─────────────┘
                                                                          │
                                                                          ▼
                                                            ┌─────────────────────────┐
                                                            │  PostgreSQL 16           │
                                                            │  (encrypted credentials, │
                                                            │   bot state)             │
                                                            └─────────────────────────┘
```

The three services (`db`, `backend`, `frontend`) are orchestrated with Docker Compose.

---

## Tech stack

| Layer          | Technologies |
|----------------|-------------|
| **Frontend**   | React 18 · TypeScript 5 · Vite 5 · served as static files with nginx |
| **Backend**    | Python 3.12 · FastAPI (REST + WebSocket) · SQLAlchemy · official `alpaca-py` SDK · Pydantic |
| **Database**   | PostgreSQL 16 |
| **Encryption** | Fernet (`cryptography`) with an environment-provided master key |
| **Orchestration** | Docker · Docker Compose (multi-stage builds) |
| **Testing**    | Backend: `pytest` + `hypothesis` · Frontend: `vitest` + `fast-check` |

---

## Prerequisites

> 🐧 **Reference operating system: Linux** (shell **bash**). The commands in this README are written for Linux. On macOS they are equivalent (usually without `sudo`); on Windows we recommend **WSL2**.

The only mandatory dependency is Docker:

- **Docker Engine** 24+
- **Docker Compose** v2 (bundled in modern Docker as `docker compose`)

Check they are installed:

```bash
sudo docker --version
sudo docker compose version
```

If you don't have Docker on Linux, install it (Ubuntu/Debian):

```bash
curl -fsSL https://get.docker.com | sudo sh
```

> 💡 **Optional, for local development only** (not needed to run the app): Node.js 20+ (frontend with `npm run dev`) and Python 3.12+ (backend).

---

## Installation

### 1. Clone the repository

```bash
git clone <REPOSITORY_URL> tradebot
cd tradebot
```

### 2. Create your environment file

```bash
cp .env.example .env
```

### 3. Generate the encryption key (`APP_ENCRYPTION_KEY`)

The application **will not start** without this key. Generate it with Docker (no local Python needed) and paste the result into `.env`:

```bash
sudo docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
```

Copy the printed line and place it in `.env`:

```ini
APP_ENCRYPTION_KEY=paste_the_generated_key_here
```

> The remaining variables (`POSTGRES_*`, `ALPACA_PAPER_ONLY`, `DEFAULT_SYMBOL`, URLs) already ship with valid defaults (see [Environment variables](#environment-variables)).
> **The Alpaca API Key/Secret do NOT go in `.env`**: you enter them from the frontend and the backend stores them encrypted.

---

## Environment variables

The `.env` file is **created from the `.env.example` template** (`cp .env.example .env`, see [Installation](#installation)). The template ships valid defaults for everything except `APP_ENCRYPTION_KEY`, which you must generate.

> 🔒 The `.env` is **not versioned** (it's in `.gitignore`): it holds your encryption key. What does get committed is `.env.example`, with no real secrets.

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `POSTGRES_USER` | No | `tradebot` | PostgreSQL user. |
| `POSTGRES_PASSWORD` | No | `tradebot` | PostgreSQL password. Change it if you expose the database. |
| `POSTGRES_DB` | No | `tradebot` | Database name. |
| `APP_ENCRYPTION_KEY` | **Yes** | *(empty)* | Fernet master key to encrypt the Alpaca API Key. **The app won't start without it.** Generate it as shown in [Installation](#installation). |
| `ALPACA_PAPER_ONLY` | No | `true` | Safety barrier. Must stay `true` in this phase: it prevents trading against production (real money). |
| `DEFAULT_SYMBOL` | No | `BTC/USD` | The asset the bot trades by default. |
| `API_BASE_URL` | No | `http://localhost:8000` | Backend base URL the frontend consumes (REST). |
| `WS_BASE_URL` | No | `ws://localhost:8000/ws/bot` | Backend WebSocket URL for live actions. |
| `DEBUG` | No | `false` | Enables backend debug mode (more verbose logs). |

> ⚠️ The **Alpaca API Key/Secret are not environment variables**: you enter them from the frontend and the backend stores them encrypted in the database. Never put them in `.env`.

---

## Running the app

Bring up the whole application (db + backend + frontend) with a single command:

```bash
sudo docker compose up --build
```

To leave it running in the background:

```bash
sudo docker compose up -d --build
```

Once startup finishes, open in your browser:

| Service | URL |
|---------|-----|
| **Frontend (web app)** | http://localhost:8080 |
| **Backend — health check** | http://localhost:8000/health |

### Get Alpaca credentials (paper, free)

1. Create a free account at https://alpaca.markets (email only).
2. In the dashboard, switch to **Paper Trading**.
3. Under the **Trading API** section, generate a paper **API Key** and its **Secret**. (Use Trading API, not Broker API.)
4. Keep both handy — you'll paste them into the TradeBot web UI in the next section.

> 📖 Reference: [How to connect to the Alpaca API (get your API Key and Secret)](https://alpaca.markets/learn/connect-to-alpaca-api?ref=alpaca.markets).

---

## Using the app (step by step)

Once the app is running and you have your paper API Key/Secret, follow these steps in the web UI at **http://localhost:8080**:

### 1. Enter your API Key and Secret

- In the **credentials** form, paste your Alpaca **paper** API Key and Secret.
- Click **Save**. The backend encrypts them (Fernet) and stores them; they are never returned decrypted to the frontend nor written to logs.
- Once saved, the account panel loads your paper account snapshot (buying power, etc.), confirming the credentials work.

> The Secret is write-only from the UI's point of view: after saving, the app only shows non-sensitive metadata (for example, the last 4 characters of the key).

### 2. Choose the trading mode

- Pick a mode in the selector: **`random`** (decides at random — best to sanity-check the whole pipeline end to end) or **`predictive`** (decides from historical indicators: moving-average crossover, RSI).

### 3. Press **Start** to launch the bot

- Click the **Start** button. The bot connects to Alpaca's market-data stream and begins evaluating the strategy on each incoming price.
- In `random` mode you'll see activity almost immediately. In `predictive` mode it may take a while to trade, since it needs enough bars to compute its indicators (expect many HOLDs at first — that's normal).

### 4. Watch actions in real time

- The **dashboard** shows every event streamed over WebSocket: signals, submitted orders, fills, state changes, and errors — most recent first.

### 5. Press **Stop** to halt the bot whenever you want

- Click the **Stop** button to stop the bot at any moment. It stops evaluating the strategy and releases the market-data connection.
- Stop is always available while the bot runs, honoring the product principle of reversibility and control.

### 6. Run a backtest (optional)

A **backtest** simulates a strategy over historical BTC/USD data **without trading for real** — it replays past bars in order and simulates the trades the strategy would have taken.

- In the **Backtest** panel, choose the **mode** (`random` or `predictive`), a **timeframe** (`1Min`, `5Min`, `15Min`, `1Hour`, `1Day`), and a **date range** (start and end). Optionally set a **seed**.
- You can also set the **position size** (`qty`, in BTC) used on every simulated trade. This matters for readability: with the default (0.001 BTC) the notional per trade is only ~0.08% of the 100,000 simulated capital, so the percentages come out microscopic. Raising it (for example `1`) yields metrics with actual meaning.
- Press **Ejecutar backtest** (Run backtest). When it finishes, the panel shows the performance metrics — **total return**, **number of trades**, **win rate** and **maximum drawdown** — plus the absolute figures **net P&L**, **starting equity** and **final equity**, the number of **bars evaluated** and the list of simulated trades.
- `trade_count` counts **completed round trips** (buy then sell), the only ones that move equity. The `trades` list holds **every BUY/SELL signal executed**, so it can be longer: a sell with no open position is recorded but produces no P&L.
- The backtest is **deterministic**: with the same seed and date range it always produces the same result, which makes runs reproducible and comparable.

> 🔁 **After changing frontend code**, rebuild its container so nginx serves the new build:
> ```bash
> sudo docker compose up -d --build frontend
> ```
> If you ever need to stop the bot without the UI, you can call the API directly: `curl -X POST http://localhost:8000/bot/stop`.

---

<a id="tests-en"></a>

## Tests

The project ships automated tests for backend and frontend. Everything runs inside Docker, with nothing installed locally.

### Backend tests (pytest)

Simplest way, using Docker Compose:

```bash
sudo docker compose run --rm backend pytest
```

Isolated alternative (from the `backend/` folder), without depending on the stack:

```bash
sudo docker run --rm -v "$PWD":/app -w /app python:3.12-slim sh -c "pip -q install pytest pytest-asyncio hypothesis sqlalchemy pydantic pydantic-settings cryptography fastapi httpx && python -m pytest tests/ -q"
```

### Frontend tests (vitest)

From the project root:

```bash
sudo docker run --rm -v "$PWD/frontend":/app -w /app node:20-alpine sh -c "npm install && npm run build && npm test"
```

> The tests cover the "happy path" and the critical edges (authentication, credential encryption, risk limits), keeping the suite minimal but sufficient.

---

## Useful commands

Follow the backend logs live:

```bash
sudo docker compose logs -f backend
```

Follow all services' logs:

```bash
sudo docker compose logs -f
```

Follow the logs of a specific container by its ID, to check for failures (first list the running containers to get the ID):

```bash
sudo docker ps
sudo docker logs -f <container-id>
```

> 💡 `docker ps` lists each container with its ID, image, and status. Copy the ID of the service you want to inspect (`tradebot-backend`, `tradebot-frontend`, or `postgres`) and pass it to `docker logs -f` to follow its output live and spot any error.

Stop the application:

```bash
sudo docker compose down
```

Stop and also delete the database data (⚠️ destructive):

```bash
sudo docker compose down -v
```

Rebuild from scratch without cache:

```bash
sudo docker compose build --no-cache
```

---

## Project structure

```
tradebot/
├── docker-compose.yml        # Orchestrates db + backend + frontend
├── .env.example              # Environment variables template (no secrets)
├── README.md
├── backend/                  # FastAPI (Python)
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py           # FastAPI startup, routers and WebSocket
│   │   ├── core/             # config, security (encryption), constants
│   │   ├── api/              # REST + WebSocket routers
│   │   ├── services/         # domain: alpaca_client, data_feed, strategies, execution, risk...
│   │   ├── db/               # SQLAlchemy models, session, repositories
│   │   └── schemas/          # Pydantic models (input/output)
│   └── tests/                # pytest
└── frontend/                 # React + TypeScript (Vite)
    ├── Dockerfile            # multi-stage: build with Node + serve with nginx
    ├── nginx.conf
    └── src/
        ├── App.tsx           # main screen
        ├── components/       # UI (key setup, dashboard)
        └── services/         # REST + WebSocket client to the backend
```

### Module map (specs → code)

Development is organized into modular features under `.kiro/specs/`, numbered by dependency order:

| Spec | Feature | Code |
|------|---------|------|
| `01-alpaca-client`   | REST/WS connection, auth and balance (paper)  | `backend/app/services/alpaca_client/` |
| `02-data-feed`       | Market data (historical + real time)           | `backend/app/services/data_feed/` |
| `03-strategy-engine` | Strategies: random + predictive (SMA, RSI)     | `backend/app/services/strategies/` |
| `04-order-execution` | Buy/sell orders, Stop-Loss, Take-Profit        | `backend/app/services/execution/` |
| `05-backtest-engine` | Simulation over historical data                | `backend/app/services/backtest/` |
| `06-risk-manager`    | Daily loss limits and order size               | `backend/app/services/risk/` |
| `07-bot-api`         | FastAPI: REST/WebSocket toward the frontend    | `backend/app/api/` + `backend/app/main.py` |
| `08-web-frontend`    | React + Vite: control + live dashboard         | `frontend/src/` |

---

## Credential security

- **Symmetric encryption (Fernet)** with an environment-provided master key (`APP_ENCRYPTION_KEY`).
- The Alpaca API Key/Secret is entered from the frontend, **stored encrypted** in the database, and decrypted **only in the backend's memory** at the moment of building the client.
- The save endpoint **never returns the secret**; the read endpoint only reports whether it exists plus non-sensitive metadata (e.g. the last 4 characters).
- **Never hardcode secrets.** All sensitive configuration goes through environment variables (`.env`, not versioned).
- Explicit `ALPACA_PAPER_ONLY=true` barrier to prevent accidentally trading against production.

---

## Project status

Functional application in the paper-trading phase. **All 8 specs are implemented and tested** (backend and frontend with their test suites green):

- ✅ `01-alpaca-client` · ✅ `02-data-feed` · ✅ `03-strategy-engine` · ✅ `04-order-execution` · ✅ `05-backtest-engine` · ✅ `06-risk-manager` · ✅ `07-bot-api` · ✅ `08-web-frontend`

The `05-backtest-engine` simulates a strategy over historical BTC/USD data (replays bars in order, reuses the same `Strategy` interface as live operation, simulates trades in memory without touching Alpaca) and reports performance metrics: total return, number of trades, win rate, and maximum drawdown. It is now exposed via `POST /backtest` and wired to the frontend, so you can launch backtests directly from the web UI.

### Non-goals (for now)

- Real-money trading.
- Multiple brokers (only Alpaca in this phase).
- Multi-user / complex multi-tenant (a single user / single set of keys is assumed).

<br>

---
---

<br>

<a id="tradebot--español"></a>

# TradeBot &nbsp;·&nbsp; Español

Bot de trading automatizado sobre **Alpaca** (API oficial), controlado desde una interfaz web y con seguimiento **en tiempo real** de todas las acciones que ejecuta. El backend está construido en **FastAPI (Python)**, el frontend en **React + TypeScript (Vite)**, la persistencia en **PostgreSQL**, y toda la aplicación se levanta con **Docker** sin necesidad de instalar dependencias en tu máquina.

> ⚠️ **Solo paper trading (dinero ficticio).**
> La aplicación opera exclusivamente contra el entorno de pruebas de Alpaca (`https://paper-api.alpaca.markets`). **No se usa dinero real bajo ninguna circunstancia en esta fase.** Existe una barrera explícita (`ALPACA_PAPER_ONLY=true`) que impide apuntar a producción por accidente.

---

## Tabla de contenidos

- [¿Qué es TradeBot?](#qué-es-tradebot)
- [Características](#características)
- [Arquitectura](#arquitectura-es)
- [Tecnologías](#tecnologías)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Variables de entorno](#variables-de-entorno)
- [Ejecución](#ejecución)
- [Uso de la aplicación (paso a paso)](#uso-de-la-aplicación-paso-a-paso)
- [Pruebas](#pruebas-es)
- [Comandos útiles](#comandos-útiles)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Seguridad de credenciales](#seguridad-de-credenciales)
- [Estado del proyecto](#estado-del-proyecto)

---

## ¿Qué es TradeBot?

TradeBot es una aplicación web que ejecuta un bot de trading automatizado sobre la plataforma **Alpaca**, consumiendo su API oficial. El usuario controla el bot desde el frontend (arrancar, detener, elegir estrategia) y observa en tiempo real cada señal, orden, ejecución (*fill*), error o cambio de estado que el bot genera.

- **Activo inicial:** BTC/USD (cripto, mercado 24/7, cómodo para pruebas).
- **Modos de trading** seleccionables desde la web:
  - `random`: el bot decide de forma aleatoria (línea base / *sanity check*).
  - `predictive`: el bot decide con estrategias basadas en datos históricos (cruce de medias móviles, RSI).

---

## Características

- 🤖 **Dos modos de trading** seleccionables desde la web: `random` y `predictive`.
- 🔐 **API Key de Alpaca cifrada** en la base de datos (cifrado simétrico Fernet). Solo se descifra en memoria del backend al construir el cliente. Nunca se devuelve al frontend ni se escribe en logs.
- 📡 **Transparencia en tiempo real:** toda acción del bot se transmite al frontend por WebSocket.
- ▶️⏹️ **Control total:** arranca y detén el bot en cualquier momento desde la interfaz.
- 📊 **Backtesting desde la web:** simula una estrategia sobre datos históricos de BTC/USD (determinista, reproducible con una seed) y revisa sus métricas de rendimiento.
- 🐳 **Cero fricción de setup:** clonar el repo y ejecutar un comando basta para levantar toda la aplicación. No necesitas instalar Python, Node ni PostgreSQL localmente.

---

<a id="arquitectura-es"></a>

## Arquitectura

```
┌─────────────────────────┐        REST + WebSocket        ┌─────────────────────────┐
│  Frontend                │ ─────────────────────────────▶ │  Backend                 │       ┌──────────────────────┐
│  React + TypeScript      │ ◀───────────────────────────── │  FastAPI (Python 3.12)   │ ────▶ │  Alpaca (paper API)  │
│  (Vite, servido x nginx) │      acciones en vivo (WS)      │                          │       └──────────────────────┘
└─────────────────────────┘                                 └───────────┬─────────────┘
                                                                          │
                                                                          ▼
                                                            ┌─────────────────────────┐
                                                            │  PostgreSQL 16           │
                                                            │  (credenciales cifradas, │
                                                            │   estado del bot)        │
                                                            └─────────────────────────┘
```

Los tres servicios (`db`, `backend`, `frontend`) se orquestan con Docker Compose.

---

## Tecnologías

| Capa           | Tecnologías |
|----------------|-------------|
| **Frontend**   | React 18 · TypeScript 5 · Vite 5 · servido como estáticos con nginx |
| **Backend**    | Python 3.12 · FastAPI (REST + WebSocket) · SQLAlchemy · SDK oficial `alpaca-py` · Pydantic |
| **Base de datos** | PostgreSQL 16 |
| **Cifrado**    | Fernet (`cryptography`) con clave maestra por entorno |
| **Orquestación** | Docker · Docker Compose (builds multi-stage) |
| **Testing**    | Backend: `pytest` + `hypothesis` · Frontend: `vitest` + `fast-check` |

---

## Requisitos previos

> 🐧 **Sistema operativo de referencia: Linux** (shell **bash**). Los comandos de este README están escritos para Linux. En macOS son equivalentes (sin `sudo` en la mayoría de casos); en Windows se recomienda usar **WSL2**.

La única dependencia obligatoria es Docker:

- **Docker Engine** 24+
- **Docker Compose** v2 (incluido en Docker moderno como `docker compose`)

Verifica que estén instalados:

```bash
sudo docker --version
sudo docker compose version
```

Si no tienes Docker en Linux, instálalo (Ubuntu/Debian):

```bash
curl -fsSL https://get.docker.com | sudo sh
```

> 💡 **Opcional, solo para desarrollo local** (no necesario para ejecutar la app): Node.js 20+ (frontend con `npm run dev`) y Python 3.12+ (backend).

---

## Instalación

### 1. Clona el repositorio

```bash
git clone <URL_DEL_REPOSITORIO> tradebot
cd tradebot
```

### 2. Crea tu archivo de entorno

```bash
cp .env.example .env
```

### 3. Genera la clave de cifrado (`APP_ENCRYPTION_KEY`)

La aplicación **no arranca** sin esta clave. Genérala con Docker (no necesitas Python local) y pega el resultado en `.env`:

```bash
sudo docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
```

Copia la línea que imprime y colócala en `.env`:

```ini
APP_ENCRYPTION_KEY=pega_aqui_la_clave_generada
```

> Las demás variables (`POSTGRES_*`, `ALPACA_PAPER_ONLY`, `DEFAULT_SYMBOL`, URLs) ya vienen con valores por defecto válidos (ver [Variables de entorno](#variables-de-entorno)).
> **La API Key/Secret de Alpaca NO va en `.env`**: se ingresa desde el frontend y el backend la guarda cifrada.

---

## Variables de entorno

El archivo `.env` **se crea a partir de la plantilla `.env.example`** (`cp .env.example .env`, ver [Instalación](#instalación)). La plantilla trae valores por defecto válidos para todo salvo `APP_ENCRYPTION_KEY`, que debes generar tú.

> 🔒 El `.env` **no se versiona** (está en `.gitignore`): contiene tu clave de cifrado. El que sí se sube al repo es `.env.example`, sin secretos reales.

| Variable | Obligatoria | Valor por defecto | Descripción |
|----------|:-----------:|-------------------|-------------|
| `POSTGRES_USER` | No | `tradebot` | Usuario de PostgreSQL. |
| `POSTGRES_PASSWORD` | No | `tradebot` | Contraseña de PostgreSQL. Cámbiala si expones la base de datos. |
| `POSTGRES_DB` | No | `tradebot` | Nombre de la base de datos. |
| `APP_ENCRYPTION_KEY` | **Sí** | *(vacío)* | Clave maestra Fernet para cifrar la API Key de Alpaca. **La app no arranca sin ella.** Genérala como se indica en [Instalación](#instalación). |
| `ALPACA_PAPER_ONLY` | No | `true` | Barrera de seguridad. Debe permanecer en `true` en esta fase: impide operar contra producción (dinero real). |
| `DEFAULT_SYMBOL` | No | `BTC/USD` | Activo con el que opera el bot por defecto. |
| `API_BASE_URL` | No | `http://localhost:8000` | URL base del backend que consume el frontend (REST). |
| `WS_BASE_URL` | No | `ws://localhost:8000/ws/bot` | URL del WebSocket del backend para las acciones en vivo. |
| `DEBUG` | No | `false` | Activa el modo de depuración del backend (logs más verbosos). |

> ⚠️ La **API Key/Secret de Alpaca no son variables de entorno**: se ingresan desde el frontend y el backend las almacena cifradas en la base de datos. Nunca las pongas en `.env`.

---

## Ejecución

Levanta toda la aplicación (db + backend + frontend) con un solo comando:

```bash
sudo docker compose up --build
```

Para dejarlo corriendo en segundo plano:

```bash
sudo docker compose up -d --build
```

Cuando termine el arranque, abre en tu navegador:

| Servicio | URL |
|----------|-----|
| **Frontend (aplicación web)** | http://localhost:8080 |
| **Backend — health check**    | http://localhost:8000/health |

### Obtener credenciales de Alpaca (paper, gratis)

1. Crea una cuenta gratuita en https://alpaca.markets (solo requiere email).
2. En el panel, cambia a **Paper Trading**.
3. En la sección **Trading API**, genera una **API Key** y su **Secret** de paper. (Usa Trading API, no Broker API.)
4. Ténlas a mano: las pegarás en la web de TradeBot en la siguiente sección.

> 📖 Referencia: [Cómo conectarse a la API de Alpaca (obtener tu API Key y Secret)](https://alpaca.markets/learn/connect-to-alpaca-api?ref=alpaca.markets).

---

## Uso de la aplicación (paso a paso)

Con la app levantada y tu API Key/Secret de paper a mano, sigue estos pasos en la web en **http://localhost:8080**:

### 1. Ingresa tu API Key y Secret

- En el formulario de **credenciales**, pega tu API Key y Secret de Alpaca **paper**.
- Pulsa **Save** (Guardar). El backend las cifra (Fernet) y las almacena; nunca se devuelven descifradas al frontend ni se escriben en logs.
- Al guardarlas, el panel de cuenta carga el resumen de tu cuenta paper (poder de compra, etc.), confirmando que las credenciales funcionan.

> El Secret es de solo escritura desde la vista de la UI: tras guardarlo, la app solo muestra metadatos no sensibles (por ejemplo, los últimos 4 caracteres de la clave).

### 2. Elige el modo de trading

- Selecciona un modo en el selector: **`random`** (decide al azar — ideal para validar el pipeline completo de punta a punta) o **`predictive`** (decide con indicadores históricos: cruce de medias móviles, RSI).

### 3. Pulsa **Start** para arrancar el bot

- Haz clic en el botón **Start**. El bot se conecta al stream de datos de mercado de Alpaca y empieza a evaluar la estrategia en cada precio que llega.
- En modo `random` verás actividad casi de inmediato. En modo `predictive` puede tardar en operar, porque necesita acumular suficientes barras para calcular sus indicadores (al principio es normal ver muchos HOLD).

### 4. Observa las acciones en tiempo real

- El **dashboard** muestra cada evento transmitido por WebSocket: señales, órdenes enviadas, ejecuciones (*fills*), cambios de estado y errores, con el más reciente primero.

### 5. Pulsa **Stop** para detener el bot cuando quieras

- Haz clic en el botón **Stop** para detener el bot en cualquier momento. Deja de evaluar la estrategia y libera la conexión de datos de mercado.
- Stop está siempre disponible mientras el bot corre, respetando el principio de producto de reversibilidad y control.

### 6. Ejecuta un backtest (opcional)

Un **backtest** simula una estrategia sobre datos históricos de BTC/USD **sin operar en real**: reproduce las barras pasadas en orden y simula las operaciones que la estrategia habría tomado.

- En el panel de **Backtest**, elige el **modo** (`random` o `predictive`), un **timeframe** (`1Min`, `5Min`, `15Min`, `1Hour`, `1Day`) y un **rango de fechas** (inicio y fin). Opcionalmente fija una **seed**.
- También puedes indicar el **tamaño de posición** (`qty`, en BTC) usado en cada operación simulada. Importa para poder leer los resultados: con el valor por defecto (0.001 BTC) el nocional por operación es solo ~0,08% del capital simulado de 100.000, así que los porcentajes salen diminutos. Subirlo (por ejemplo a `1`) da métricas con significado.
- Pulsa **Ejecutar backtest**. Al terminar, el panel muestra las métricas de rendimiento — **retorno total**, **número de operaciones**, **win rate** y **drawdown máximo** — además de las cifras absolutas **P&L neto**, **equity inicial** y **equity final**, el número de **barras evaluadas** y la lista de operaciones simuladas.
- `trade_count` cuenta las **operaciones completas de ida y vuelta** (compra y posterior venta), las únicas que mueven la equity. La lista `trades` recoge **todas las señales BUY/SELL ejecutadas**, por lo que puede ser más larga: una venta sin posición abierta se registra pero no genera P&L.
- El backtest es **determinista**: con la misma seed y el mismo rango de fechas produce siempre el mismo resultado, lo que hace las ejecuciones reproducibles y comparables.

> 🔁 **Tras cambiar código del frontend**, reconstruye su contenedor para que nginx sirva el nuevo build:
> ```bash
> sudo docker compose up -d --build frontend
> ```
> Si alguna vez necesitas detener el bot sin la UI, puedes llamar a la API directamente: `curl -X POST http://localhost:8000/bot/stop`.

---

<a id="pruebas-es"></a>

## Pruebas

El proyecto incluye pruebas automatizadas en backend y frontend. Todo se ejecuta dentro de Docker, sin instalar nada local.

### Pruebas del backend (pytest)

La forma más simple, usando Docker Compose:

```bash
sudo docker compose run --rm backend pytest
```

Alternativa aislada (desde la carpeta `backend/`), sin depender del stack:

```bash
sudo docker run --rm -v "$PWD":/app -w /app python:3.12-slim sh -c "pip -q install pytest pytest-asyncio hypothesis sqlalchemy pydantic pydantic-settings cryptography fastapi httpx && python -m pytest tests/ -q"
```

### Pruebas del frontend (vitest)

Desde la raíz del proyecto:

```bash
sudo docker run --rm -v "$PWD/frontend":/app -w /app node:20-alpine sh -c "npm install && npm run build && npm test"
```

> Las pruebas cubren el "camino feliz" y los bordes críticos (autenticación, cifrado de credenciales, límites de riesgo), manteniendo el conjunto mínimo pero suficiente.

---

## Comandos útiles

Ver logs del backend en vivo:

```bash
sudo docker compose logs -f backend
```

Ver logs de todos los servicios:

```bash
sudo docker compose logs -f
```

Ver los logs de un contenedor específico por su ID, para revisar si existe alguna falla (primero lista los contenedores en ejecución para obtener el ID):

```bash
sudo docker ps
sudo docker logs -f <id-container>
```

> 💡 `docker ps` lista cada contenedor con su ID, imagen y estado. Copia el ID del servicio que quieras inspeccionar (`tradebot-backend`, `tradebot-frontend` o `postgres`) y pásalo a `docker logs -f` para seguir su salida en vivo y detectar cualquier error.

Detener la aplicación:

```bash
sudo docker compose down
```

Detener y borrar también los datos de la base de datos (⚠️ destructivo):

```bash
sudo docker compose down -v
```

Reconstruir desde cero sin caché:

```bash
sudo docker compose build --no-cache
```

---

## Estructura del proyecto

```
tradebot/
├── docker-compose.yml        # Orquesta db + backend + frontend
├── .env.example              # Plantilla de variables de entorno (sin secretos)
├── README.md
├── backend/                  # FastAPI (Python)
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py           # Arranque FastAPI, routers y WebSocket
│   │   ├── core/             # config, seguridad (cifrado), constantes
│   │   ├── api/              # routers REST + WebSocket
│   │   ├── services/         # dominio: alpaca_client, data_feed, strategies, execution, risk...
│   │   ├── db/               # modelos SQLAlchemy, sesión, repositorios
│   │   └── schemas/          # modelos Pydantic (entrada/salida)
│   └── tests/                # pytest
└── frontend/                 # React + TypeScript (Vite)
    ├── Dockerfile            # multi-stage: build con Node + serve con nginx
    ├── nginx.conf
    └── src/
        ├── App.tsx           # pantalla principal
        ├── components/       # UI (setup de claves, dashboard)
        └── services/         # cliente REST + WebSocket hacia el backend
```

### Mapa de módulos (specs → código)

El desarrollo está organizado en features modulares bajo `.kiro/specs/`, numerados por orden de dependencia:

| Spec | Feature | Código |
|------|---------|--------|
| `01-alpaca-client`   | Conexión REST/WS, auth y saldo (paper)       | `backend/app/services/alpaca_client/` |
| `02-data-feed`       | Datos de mercado (histórico + tiempo real)   | `backend/app/services/data_feed/` |
| `03-strategy-engine` | Estrategias: random + predictive (SMA, RSI)  | `backend/app/services/strategies/` |
| `04-order-execution` | Órdenes de compra/venta, Stop-Loss, Take-Profit | `backend/app/services/execution/` |
| `05-backtest-engine` | Simulación con datos históricos              | `backend/app/services/backtest/` |
| `06-risk-manager`    | Límites de pérdida diaria y tamaño de lote   | `backend/app/services/risk/` |
| `07-bot-api`         | FastAPI: REST/WebSocket hacia el frontend    | `backend/app/api/` + `backend/app/main.py` |
| `08-web-frontend`    | React + Vite: control + dashboard en vivo    | `frontend/src/` |

---

## Seguridad de credenciales

- **Cifrado simétrico (Fernet)** con una clave maestra provista por entorno (`APP_ENCRYPTION_KEY`).
- La API Key/Secret de Alpaca se ingresa desde el frontend, se **almacena cifrada** en la base de datos y solo se descifra **en memoria del backend** en el momento de construir el cliente.
- El endpoint de guardado **nunca devuelve el secreto**; el de lectura solo indica si existe y metadatos no sensibles (p. ej. los últimos 4 caracteres).
- **Nunca hardcodees secretos.** Toda configuración sensible va por variables de entorno (`.env`, no versionado).
- Barrera explícita `ALPACA_PAPER_ONLY=true` para impedir operar contra producción por accidente.

---

## Estado del proyecto

Aplicación funcional en fase de paper trading. **Los 8 specs están implementados y probados** (backend y frontend con sus suites de pruebas en verde):

- ✅ `01-alpaca-client` · ✅ `02-data-feed` · ✅ `03-strategy-engine` · ✅ `04-order-execution` · ✅ `05-backtest-engine` · ✅ `06-risk-manager` · ✅ `07-bot-api` · ✅ `08-web-frontend`

El `05-backtest-engine` simula una estrategia sobre datos históricos de BTC/USD (reproduce las barras en orden, reutiliza la misma interfaz `Strategy` que la operación en vivo, simula las operaciones en memoria sin tocar Alpaca) y reporta métricas de desempeño: retorno total, número de operaciones, win rate y drawdown máximo. Ahora está expuesto vía `POST /backtest` y conectado al frontend, así que puedes lanzar backtests directamente desde la web.

### No objetivos (por ahora)

- Trading con dinero real.
- Múltiples brokers (solo Alpaca en esta fase).
- Multiusuario / multi-tenant complejo (se asume un usuario / un conjunto de claves).
