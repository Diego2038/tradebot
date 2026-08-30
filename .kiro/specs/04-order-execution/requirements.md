# Requisitos — 04 Order Execution

## Introducción
Traduce señales de la estrategia en órdenes reales de compra/venta en la cuenta **paper**
de Alpaca, gestionando Stop-Loss y Take-Profit. Consulta al Risk Manager (spec 06) antes
de enviar cualquier orden.

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Envío de órdenes
**Historia:** Como bot, quiero enviar órdenes de compra/venta a partir de una señal, para
ejecutar la estrategia en la cuenta paper.

Criterios de aceptación (EARS):
1. CUANDO llega una señal `BUY`/`SELL` aprobada por riesgo, EL SISTEMA DEBERÁ enviar la
   orden a Alpaca paper y registrar el resultado (id, estado, cantidad, precio).
2. SI Alpaca rechaza la orden, EL SISTEMA DEBERÁ capturar el error, registrarlo y emitir
   un evento de error al feed en tiempo real (no debe caerse el bot).

### R2 — Stop-Loss y Take-Profit
Criterios de aceptación:
1. CUANDO se abre una posición, EL SISTEMA DEBERÁ poder adjuntar niveles de Stop-Loss y
   Take-Profit según la configuración.
2. CUANDO el precio alcanza SL o TP, EL SISTEMA DEBERÁ cerrar la posición correspondiente.

### R3 — Idempotencia y consistencia
Criterios de aceptación:
1. EL SISTEMA NO DEBERÁ duplicar una orden por reintentos de red (uso de client order id).

### R4 — Eventos en tiempo real
Criterios de aceptación:
1. CUANDO cambia el estado de una orden (enviada, llenada, cancelada, error), EL SISTEMA
   DEBERÁ emitir un evento al feed en tiempo real del frontend.

## Pruebas necesarias (mínimas)
- Señal aprobada → se llama al cliente Alpaca con los parámetros correctos (mock).
- Orden rechazada → se emite evento de error y el bot sigue vivo.
- SL/TP: al alcanzar el nivel simulado se dispara el cierre.
- No se envía orden si el Risk Manager la bloquea.
