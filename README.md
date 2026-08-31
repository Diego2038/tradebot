# TradeBot

Bot de trading automatizado sobre **Alpaca** (API oficial), controlado desde una interfaz web y con seguimiento **en tiempo real** de todas las acciones que ejecuta. El backend está construido en **FastAPI (Python)**, el frontend en **React + TypeScript (Vite)**, la persistencia en **PostgreSQL**, y toda la aplicación se levanta con **Docker** sin necesidad de instalar dependencias en tu máquina.

> ⚠️ **Solo paper trading (dinero ficticio).**
> La aplicación opera exclusivamente contra el entorno de pruebas de Alpaca (`https://paper-api.alpaca.markets`). **No se usa dinero real bajo ninguna circunstancia en esta fase.** Existe una barrera explícita (`ALPACA_PAPER_ONLY=true`) que impide apuntar a producción por accidente.

---

## Tabla de contenidos

- [¿Qué es TradeBot?](#qué-es-tradebot)
- [Características](#características)
- [Arquitectura](#arquitectura)
- [Tecnologías](#tecnologías)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Variables de entorno](#variables-de-entorno)
- [Ejecución](#ejecución)
- [Uso de la aplicación](#uso-de-la-aplicación)
- [Pruebas](#pruebas)
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
- 🐳 **Cero fricción de setup:** clonar el repo y ejecutar un comando basta para levantar toda la aplicación. No necesitas instalar Python, Node ni PostgreSQL localmente.

---

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
3. Genera una **API Key** y su **Secret** de paper.
4. Ingrésalas en la web de TradeBot (ver siguiente sección). El backend las cifra antes de guardarlas.

---

## Uso de la aplicación

1. **Configura tus credenciales:** en la web (http://localhost:8080), pega tu API Key/Secret de Alpaca **paper**. Se cifran y almacenan; nunca se devuelven descifradas.
2. **Elige el modo de trading:** `random` o `predictive`.
3. **Arranca el bot** con el botón de inicio.
4. **Observa en tiempo real** en el dashboard: señales, órdenes, ejecuciones, cambios de estado y errores llegan por WebSocket.
5. **Detén el bot** cuando quieras desde la interfaz.

---

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

El `05-backtest-engine` simula una estrategia sobre datos históricos de BTC/USD (reproduce las barras en orden, reutiliza la misma interfaz `Strategy` que la operación en vivo, simula las operaciones en memoria sin tocar Alpaca) y reporta métricas de desempeño: retorno total, número de operaciones, win rate y drawdown máximo.

### No objetivos (por ahora)

- Trading con dinero real.
- Múltiples brokers (solo Alpaca en esta fase).
- Multiusuario / multi-tenant complejo (se asume un usuario / un conjunto de claves).
