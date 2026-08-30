# Producto: TradeBot

## Qué es
TradeBot es una aplicación web que ejecuta un bot de trading automatizado sobre la
plataforma **Alpaca**, consumiendo su API oficial. El usuario controla el bot desde un
frontend web (Flutter) y observa **en tiempo real** las acciones que el bot va tomando.

## Alcance actual
- **Solo paper trading (dinero ficticio).** La aplicación apunta exclusivamente al
  entorno de pruebas de Alpaca (`https://paper-api.alpaca.markets`). No se opera con
  dinero real bajo ninguna circunstancia en esta fase.
- **Activo inicial:** BTC/USD (cripto, mercado 24/7, cómodo para pruebas).
- **Modos de trading** seleccionables desde el frontend:
  - `random`: el bot decide de forma aleatoria (línea base / sanity check).
  - `predictive`: el bot decide con estrategias basadas en datos históricos
    (ej. cruce de medias móviles, RSI).

## Principios de producto
- **Seguridad de credenciales primero.** La API Key/Secret de Alpaca se ingresa desde
  el frontend, se almacena **cifrada** en la base de datos y solo se descifra en memoria
  del backend en el momento de usarla. Nunca se devuelve descifrada al frontend ni se
  registra en logs.
- **Transparencia en tiempo real.** Toda acción del bot (señal, orden, fill, error,
  cambio de estado) se transmite al frontend por WebSocket.
- **Reversibilidad y control.** El usuario puede arrancar y detener el bot en cualquier
  momento desde la interfaz.
- **Cero fricción de setup.** Todo corre dentro de Docker. Clonar el repo y ejecutar
  `docker compose up` debe bastar para levantar la aplicación completa sin instalar
  dependencias locales.

## No objetivos (por ahora)
- Trading con dinero real.
- Múltiples brokers (solo Alpaca en esta fase).
- Múltiples usuarios / multi-tenant complejo (se asume un usuario / un conjunto de claves).
