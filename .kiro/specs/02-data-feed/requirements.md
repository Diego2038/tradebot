# Requisitos — 02 Data Feed

## Introducción
Captura de datos de mercado de BTC/USD desde Alpaca: histórico (barras/velas) para las
estrategias y backtesting, y streaming en tiempo real para la operación en vivo.

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Datos históricos
**Historia:** Como motor de estrategia, necesito barras históricas de BTC/USD, para
calcular indicadores y hacer backtesting.

Criterios de aceptación (EARS):
1. CUANDO se solicitan barras para un símbolo, timeframe y rango, EL SISTEMA DEBERÁ
   devolverlas normalizadas (timestamp, open, high, low, close, volume).
2. SI Alpaca no devuelve datos para el rango, EL SISTEMA DEBERÁ responder con una lista
   vacía y sin error fatal.

### R2 — Streaming en tiempo real
**Historia:** Como bot en operación, necesito precios en vivo de BTC/USD, para reaccionar
a movimientos del mercado.

Criterios de aceptación:
1. CUANDO el bot está activo, EL SISTEMA DEBERÁ suscribirse al stream de Alpaca y emitir
   cada actualización a los consumidores internos (estrategia, WebSocket del frontend).
2. CUANDO la conexión de streaming se cae, EL SISTEMA DEBERÁ reintentar la reconexión con
   backoff, sin tumbar la aplicación.

### R3 — Normalización única
Criterios de aceptación:
1. EL SISTEMA DEBERÁ exponer un formato de dato de mercado único e independiente del SDK,
   para que estrategias y backtest no dependan de detalles de Alpaca.

## Pruebas necesarias (mínimas)
- Normalización de una barra de Alpaca al formato interno.
- Rango sin datos devuelve lista vacía (cliente mockeado).
- Lógica de reintento de reconexión (simulando desconexión).
