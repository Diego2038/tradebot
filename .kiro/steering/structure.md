# Estructura del monorepo

```
tradebot/
├── docker-compose.yml        # Orquesta db + backend + frontend
├── .env.example              # Plantilla de variables de entorno (sin secretos reales)
├── .gitignore
├── README.md
├── backend/                  # FastAPI (Python)
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py           # Arranque FastAPI, montaje de routers y WS
│   │   ├── core/             # config, seguridad (cifrado), constantes
│   │   ├── api/              # routers REST + WebSocket
│   │   ├── services/         # dominio: alpaca_client, data_feed, strategies,
│   │   │                     #          execution, backtest, risk
│   │   ├── db/               # modelos SQLAlchemy, sesión, repositorios
│   │   └── schemas/          # modelos Pydantic (entrada/salida)
│   └── tests/                # pytest
└── frontend/                 # Flutter (web)
    ├── Dockerfile            # multi-stage: build con SDK + serve estáticos
    ├── pubspec.yaml
    └── lib/
        ├── main.dart
        ├── screens/          # pantallas (setup de claves, dashboard)
        ├── services/         # cliente REST + WebSocket hacia el backend
        └── models/           # modelos de datos del frontend
```

## Mapa specs ↔ código
- `01-alpaca-client`  → `backend/app/services/alpaca_client/`
- `02-data-feed`      → `backend/app/services/data_feed/`
- `03-strategy-engine`→ `backend/app/services/strategies/`
- `04-order-execution`→ `backend/app/services/execution/`
- `05-backtest-engine`→ `backend/app/services/backtest/`
- `06-risk-manager`   → `backend/app/services/risk/`
- `07-bot-api`        → `backend/app/api/` + `backend/app/main.py`
- `08-web-frontend`   → `frontend/lib/`

## Convenciones de nombres
- Python: `snake_case` para módulos y funciones, `PascalCase` para clases.
- Dart: `lowerCamelCase` para variables/métodos, `PascalCase` para clases/widgets.
- Specs numerados por orden de dependencia (01 es la base; 07 y 08 dependen del resto).
```
