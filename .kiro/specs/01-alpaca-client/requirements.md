# Requisitos — 01 Alpaca Client

## Introducción
Capa de conexión con la API oficial de Alpaca (**solo paper trading**). Encapsula
autenticación, consulta de cuenta/saldo y la construcción del cliente a partir de
credenciales cifradas. Es la base de la que dependen los demás specs.

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Guardar credenciales de Alpaca de forma segura
**Historia:** Como usuario, quiero ingresar mi API Key/Secret de Alpaca desde el
frontend, para que el bot pueda operar en mi cuenta paper sin exponer mis credenciales.

Criterios de aceptación (EARS):
1. CUANDO el usuario envía API Key y Secret, EL SISTEMA DEBERÁ cifrarlas antes de
   persistirlas en PostgreSQL (nunca en texto plano).
2. EL SISTEMA NO DEBERÁ devolver el Secret descifrado en ninguna respuesta ni escribirlo
   en logs.
3. CUANDO se consultan las credenciales guardadas, EL SISTEMA DEBERÁ devolver solo
   metadatos no sensibles (ej. si existen y los últimos 4 caracteres de la key).

### R2 — Validar credenciales contra Alpaca
**Historia:** Como usuario, quiero saber si mis credenciales son válidas, para confiar
en que el bot podrá operar.

Criterios de aceptación:
1. CUANDO se guardan credenciales nuevas, EL SISTEMA DEBERÁ validarlas contra el endpoint
   de cuenta de Alpaca paper y reportar éxito o fallo.
2. SI las credenciales son inválidas, EL SISTEMA DEBERÁ responder con un error claro sin
   persistir credenciales que no funcionan.

### R3 — Consultar cuenta y saldo
**Historia:** Como usuario, quiero ver el saldo y estado de mi cuenta paper.

Criterios de aceptación:
1. CUANDO se solicita el estado de cuenta, EL SISTEMA DEBERÁ devolver saldo (cash),
   poder de compra y estado de la cuenta desde Alpaca.

### R4 — Barrera de paper trading
Criterios de aceptación:
1. EL SISTEMA DEBERÁ construir el cliente apuntando siempre a `paper-api.alpaca.markets`.
2. SI la configuración intentara apuntar a producción, EL SISTEMA DEBERÁ rechazar el
   arranque mientras `ALPACA_PAPER_ONLY` sea true.

## Pruebas necesarias (mínimas)
- Ida y vuelta de cifrado/descifrado de credenciales (ya iniciada en `test_security.py`).
- La respuesta de "consultar credenciales" no incluye el secreto.
- Construcción del cliente usa la base URL de paper (con cliente Alpaca mockeado).
- Manejo de credenciales inválidas (mock que simula 401/403).
