# Requisitos — 07 Bot API

## Introducción
Capa FastAPI que expone toda la funcionalidad al frontend: gestión de credenciales,
arranque/parada del bot, selección de modo (random/predictive), estado y el **feed en
tiempo real por WebSocket** de las acciones del bot. Orquesta los specs 01–06.

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Endpoints de credenciales
Criterios de aceptación (EARS):
1. EL SISTEMA DEBERÁ exponer `POST /credentials` para guardar (cifradas) las claves de
   Alpaca y `GET /credentials` para consultar solo metadatos no sensibles.

### R2 — Control del bot
**Historia:** Como usuario, quiero arrancar y detener el bot y elegir su modo, para
controlar cuándo y cómo opera.

Criterios de aceptación:
1. EL SISTEMA DEBERÁ exponer `POST /bot/start` (con modo `random`|`predictive`),
   `POST /bot/stop` y `GET /bot/status`.
2. SI no hay credenciales válidas guardadas, `POST /bot/start` DEBERÁ fallar con un
   mensaje claro.
3. EL SISTEMA DEBERÁ mantener siempre el modo paper (nunca dinero real).

### R3 — Feed en tiempo real (WebSocket)
**Historia:** Como usuario, quiero ver en vivo lo que hace el bot, para tener
transparencia total.

Criterios de aceptación:
1. EL SISTEMA DEBERÁ exponer `GET /ws/bot` (WebSocket) que emita eventos: señal, orden,
   fill, cambio de estado, bloqueo por riesgo y errores.
2. CUANDO un evento ocurre en cualquier servicio, EL SISTEMA DEBERÁ difundirlo a todos los
   clientes WebSocket conectados.

## Pruebas necesarias (mínimas)
- `/health` responde y reporta modo paper (ya cubierto por el esqueleto).
- `POST /credentials` guarda cifrado y `GET /credentials` no expone el secreto.
- `POST /bot/start` sin credenciales → error claro.
- Un cliente WebSocket recibe un evento publicado por el backend.
