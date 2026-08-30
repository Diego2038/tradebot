# Requisitos — 05 Backtest Engine

## Introducción
Simulador que ejecuta una estrategia sobre datos históricos de BTC/USD para estimar su
desempeño antes de operarla en vivo (aunque sea en paper). Reutiliza la misma interfaz de
estrategia del spec 03.

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Ejecutar backtest
**Historia:** Como usuario, quiero probar una estrategia contra el pasado, para saber si
vale la pena antes de dejarla operar.

Criterios de aceptación (EARS):
1. CUANDO se solicita un backtest con estrategia, símbolo, timeframe y rango, EL SISTEMA
   DEBERÁ reproducir las barras en orden y aplicar la estrategia paso a paso.
2. EL SISTEMA DEBERÁ simular las operaciones (entradas/salidas) sin tocar Alpaca.

### R2 — Métricas de resultado
Criterios de aceptación:
1. AL terminar, EL SISTEMA DEBERÁ reportar métricas mínimas: retorno total, número de
   operaciones, win rate y drawdown máximo.

### R3 — Consistencia con la operación en vivo
Criterios de aceptación:
1. EL SISTEMA DEBERÁ usar la misma interfaz `Strategy` que el motor en vivo, para que el
   comportamiento sea comparable.

## Pruebas necesarias (mínimas)
- Backtest sobre dataset pequeño y conocido → métricas esperadas.
- Estrategia que nunca opera → 0 operaciones, retorno 0.
- Reproducibilidad: mismo input + misma semilla → mismo resultado.
