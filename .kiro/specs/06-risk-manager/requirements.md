# Requisitos — 06 Risk Manager

## Introducción
Reglas de protección que se aplican ANTES de ejecutar cualquier orden: límite de pérdida
diaria y tamaño de posición (lote). Es la última barrera antes de enviar una orden a
Alpaca.

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Límite de pérdida diaria
**Historia:** Como usuario, quiero un tope de pérdida diaria, para que el bot no siga
operando en un mal día.

Criterios de aceptación (EARS):
1. CUANDO la pérdida acumulada del día alcanza el límite configurado, EL SISTEMA DEBERÁ
   bloquear nuevas órdenes de apertura hasta el siguiente día.
2. CUANDO se bloquea por pérdida, EL SISTEMA DEBERÁ emitir un evento al feed en tiempo
   real explicando el motivo.

### R2 — Tamaño de posición (lote)
Criterios de aceptación:
1. CUANDO se va a abrir una posición, EL SISTEMA DEBERÁ calcular el tamaño según las
   reglas (ej. % del capital) y rechazar órdenes que excedan el máximo permitido.

### R3 — Evaluación previa a la orden
Criterios de aceptación:
1. EL SISTEMA DEBERÁ exponer una función `evaluar(orden_propuesta) -> permitida | rechazada`
   que el spec 04 consulta antes de enviar cualquier orden.

## Pruebas necesarias (mínimas)
- Pérdida bajo el límite → orden permitida; al alcanzar el límite → bloqueada.
- Tamaño de lote dentro del máximo → permitido; por encima → rechazado.
- El bloqueo emite el evento correspondiente.
