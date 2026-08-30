# Stack técnico y comandos

## Componentes
- **Frontend:** Flutter (target **web**). Servido como estáticos tras un build.
- **Backend:** Python 3.12 + **FastAPI** (REST + WebSocket). SDK oficial `alpaca-py`.
- **Base de datos:** PostgreSQL 16.
- **Orquestación:** Docker + Docker Compose. Builds multi-stage para no requerir SDKs
  instalados en la máquina anfitriona.

## Reglas de arranque (Docker-first)
- Todo se ejecuta en contenedores. El objetivo es: `docker compose up` levanta
  `db` + `backend` + `frontend` sin instalar nada localmente.
- El frontend Flutter web se **compila dentro de Docker** (stage de build con el SDK) y
  se sirve como estáticos (stage ligero, ej. nginx). No es necesario tener Flutter local
  para ejecutar la app; sí es cómodo para desarrollar.
- Nunca hardcodear secretos. Config vía variables de entorno (`.env`, no versionado).

## Comandos habituales
- Levantar todo: `docker compose up --build`
- Levantar en segundo plano: `docker compose up -d --build`
- Ver logs del backend: `docker compose logs -f backend`
- Detener: `docker compose down`
- Tests del backend (dentro del contenedor): `docker compose run --rm backend pytest`

## Convenciones de backend
- Estructura por capas: `api/` (routers), `core/` (config, seguridad), `services/`
  (lógica de dominio: alpaca client, data feed, estrategias, ejecución, riesgo),
  `db/` (modelos, sesión, repositorios), `schemas/` (Pydantic).
- Tipado estático con type hints. Pydantic para validación.
- Tests con **pytest**. Mantener las pruebas mínimas pero suficientes: por cada spec,
  cubrir el "camino feliz" y los bordes críticos (auth, cifrado, límites de riesgo).

## Seguridad de credenciales
- Cifrado simétrico (Fernet / AES-GCM) con una clave maestra provista por entorno
  (`APP_ENCRYPTION_KEY`). La API Key de Alpaca se guarda cifrada; se descifra solo en
  el backend, en memoria, al construir el cliente.
- El endpoint de guardado nunca devuelve el secreto; el de lectura solo indica si existe
  y metadatos no sensibles (ej. últimos 4 caracteres).

## Alpaca (paper trading)
- Base URL fija a paper trading: `https://paper-api.alpaca.markets`.
- Data feed de cripto de Alpaca para BTC/USD.
- La configuración debe impedir apuntar a producción por accidente (flag explícito).
