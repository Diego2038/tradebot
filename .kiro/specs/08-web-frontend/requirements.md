# Requisitos — 08 Web Frontend

## Introducción
Aplicación React + TypeScript (Vite) que permite configurar las credenciales de Alpaca,
elegir el modo del bot y observar en **tiempo real** sus acciones. Consume la API del
spec 07.

> Borrador inicial (sesión Vibe). Se refinará en una sesión **Spec** dedicada.

## Requisitos

### R1 — Configuración de credenciales
**Historia:** Como usuario, quiero ingresar mi API Key/Secret de Alpaca desde la web, para
conectar el bot a mi cuenta paper.

Criterios de aceptación (EARS):
1. EL SISTEMA DEBERÁ ofrecer un formulario para enviar API Key/Secret al backend (que las
   cifra). El Secret se ingresa en un campo oculto y no se vuelve a mostrar.
2. CUANDO ya existen credenciales, EL SISTEMA DEBERÁ indicarlo mostrando solo metadatos no
   sensibles (ej. últimos 4 caracteres).

### R2 — Selección de modo y control del bot
Criterios de aceptación:
1. EL SISTEMA DEBERÁ permitir elegir el modo (`random` | `predictive`) y arrancar/detener
   el bot desde la interfaz.
2. EL SISTEMA DEBERÁ mostrar el estado actual del bot (activo/inactivo, modo, símbolo).

### R3 — Dashboard en tiempo real
**Historia:** Como usuario, quiero ver en vivo las acciones del bot, para seguir lo que
hace sin recargar la página.

Criterios de aceptación:
1. CUANDO el bot emite eventos por WebSocket, EL SISTEMA DEBERÁ mostrarlos en un panel en
   vivo (señales, órdenes, fills, bloqueos de riesgo, errores).
2. CUANDO se pierde la conexión WebSocket, EL SISTEMA DEBERÁ intentar reconectar e indicar
   el estado de conexión al usuario.

### R4 — Indicador de entorno
Criterios de aceptación:
1. EL SISTEMA DEBERÁ mostrar de forma visible que se está operando en **paper trading**
   (sin dinero real).

## Pruebas necesarias (mínimas)
- Test de componente: el formulario de credenciales no revela el Secret ingresado.
- Test de componente: al recibir un evento simulado por el stream, el dashboard lo renderiza.
- El indicador de "paper trading" está siempre visible.
