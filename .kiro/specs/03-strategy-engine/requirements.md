# Requisitos — 03 Strategy Engine

## Introducción
Motor de estrategias que transforma datos de mercado en señales (comprar / vender /
mantener). Define una interfaz común y provee al menos dos estrategias seleccionables
desde el frontend: **random** (línea base) y **predictive** (basada en históricos:
cruce de medias móviles, RSI).

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Interfaz de estrategia común (plug-and-play)
**Historia:** Como desarrollador, quiero una interfaz común de estrategia, para poder
añadir nuevas estrategias sin tocar el resto del sistema.

Criterios de aceptación (EARS):
1. EL SISTEMA DEBERÁ definir una interfaz `Strategy` que reciba datos de mercado y
   devuelva una señal (`BUY` | `SELL` | `HOLD`) con metadatos (motivo, timestamp).
2. CUANDO se registra una nueva estrategia, EL SISTEMA DEBERÁ poder seleccionarla por
   nombre sin cambios en los consumidores.

### R2 — Estrategia aleatoria (random)
Criterios de aceptación:
1. CUANDO el modo es `random`, EL SISTEMA DEBERÁ emitir señales aleatorias respetando la
   interfaz común (útil como sanity check de todo el pipeline).
2. EL SISTEMA DEBERÁ permitir fijar una semilla para reproducibilidad en pruebas.

### R3 — Estrategia predictiva (histórica)
**Historia:** Como usuario, quiero un modo predictivo basado en datos pasados, para que
las decisiones no sean puro azar.

Criterios de aceptación:
1. CUANDO el modo es `predictive`, EL SISTEMA DEBERÁ calcular indicadores (ej. cruce de
   medias móviles y/o RSI) sobre las barras históricas y emitir la señal correspondiente.
2. SI no hay suficientes datos para el indicador, EL SISTEMA DEBERÁ emitir `HOLD`.

### R4 — Selección de modo
Criterios de aceptación:
1. EL SISTEMA DEBERÁ exponer el modo activo y permitir cambiarlo (desde el bot-api /
   frontend) entre `random` y `predictive`.

## Pruebas necesarias (mínimas)
- Estrategia random con semilla fija produce señales deterministas.
- Cruce de medias: dataset construido que fuerza un cruce → señal BUY/SELL esperada.
- RSI en sobrecompra/sobreventa → señal esperada.
- Datos insuficientes → HOLD.
