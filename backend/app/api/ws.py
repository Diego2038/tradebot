"""WebSocket hub and endpoint for the bot API (spec 07, Tarea 2).

This module bridges the secret-free spec-04 :class:`EventPublisher` to every
connected frontend WebSocket client (R3):

- :func:`serialize_event` -- a pure function turning an :class:`OrderEvent` into a
  JSON-safe dict using **only** the event's declared, secret-free fields.
- :class:`WebSocketHub` -- subscribes once to the publisher, keeps a set of
  connected sockets, and fans out each event as JSON. A send failure or a
  disconnect drops that single socket without affecting the others and never
  interrupts the bot (R3.4, R3.5).
- ``GET /ws/bot`` -- the endpoint the frontend connects to (R3.1).

The publisher's callbacks are **synchronous**; the hub bridges them to
**async** sends via an internal :class:`asyncio.Queue`. ``_on_event`` only
enqueues (never blocks the publisher) and a background task consumes the queue
and broadcasts, so a slow or broken client cannot stall event production.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.execution.events import EventPublisher, OrderEvent

logger = logging.getLogger(__name__)

router = APIRouter()


def serialize_event(event: OrderEvent) -> dict[str, Any]:
    """Serialize an :class:`OrderEvent` to a JSON-safe, secret-free dict (R3.3).

    Uses **only** the event's declared fields. ``Decimal`` values become
    strings (lossless), the ``datetime`` becomes an ISO-8601 string, and the
    ``EventType`` becomes its ``str`` value. No credential material is ever part
    of an :class:`OrderEvent`, so the payload is secret-free by construction.
    """
    return {
        "event_type": event.event_type.value,
        "symbol": event.symbol,
        "side": event.side,
        "qty": str(event.qty) if event.qty is not None else None,
        "price": str(event.price) if event.price is not None else None,
        "order_id": event.order_id,
        "reason": event.reason,
        "timestamp": event.timestamp.isoformat(),
    }


class WebSocketHub:
    """Bridges the spec-04 :class:`EventPublisher` to all connected clients (R3).

    Subscribes ``self._on_event`` to the publisher exactly once at construction
    (R3.2). The synchronous publisher callback only enqueues events onto an
    internal :class:`asyncio.Queue`; a background task drains the queue and
    broadcasts to the connected sockets. A client whose send fails is dropped
    and the broadcast continues with the rest (R3.5); a disconnect removes the
    client without affecting the others (R3.4).
    """

    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher
        self._connections: set[WebSocket] = set()
        self._queue: asyncio.Queue[OrderEvent] = asyncio.Queue()
        self._consumer_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Subscribe once (R3.2). The publisher de-duplicates identical callbacks.
        self._publisher.subscribe(self._on_event)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a client connection (R3.1).

        Starts the background broadcast consumer the first time a client
        connects (so it runs on the app's event loop) and records the loop for
        thread-safe enqueueing from the synchronous publisher callback.
        """
        await websocket.accept()
        self._connections.add(websocket)
        self._loop = asyncio.get_running_loop()
        self._ensure_consumer()

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a client from the connection set (R3.4).

        Removing a socket that is not registered is a no-op, so a double
        disconnect is safe and never affects the other clients.
        """
        self._connections.discard(websocket)

    def _ensure_consumer(self) -> None:
        """Start the background broadcast consumer if it is not already running."""
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        """Drain the queue forever, broadcasting each event to all clients."""
        while True:
            event = await self._queue.get()
            try:
                await self.broadcast(event)
            finally:
                self._queue.task_done()

    def _on_event(self, event: OrderEvent) -> None:
        """Publisher callback: enqueue the event for broadcast (R3.3).

        Runs on the publisher's (synchronous, possibly non-loop) thread. It only
        enqueues and never blocks the publisher. When called from a different
        thread than the app loop, it schedules the enqueue thread-safely.
        """
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                self._queue.put_nowait(event)
            else:
                loop.call_soon_threadsafe(self._queue.put_nowait, event)
        else:
            # No loop recorded yet (no client has connected): enqueue directly.
            self._queue.put_nowait(event)

    async def broadcast(self, event: OrderEvent) -> None:
        """Send the JSON-serialized event to every client; drop failures (R3.2, R3.5).

        Serializes the event once and sends it to each connected client. If a
        send raises (broken or slow client), that connection is dropped and the
        loop continues with the remaining clients. This method never raises to
        its caller, so a bad client cannot interrupt the bot.
        """
        payload = serialize_event(event)
        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.warning(
                    "Dropping WebSocket client after send failure for event %s",
                    event.event_type,
                    exc_info=True,
                )
                self._connections.discard(websocket)


@router.websocket("/ws/bot")
async def bot_feed(websocket: WebSocket) -> None:
    """Real-time event feed endpoint (R3.1, R3.4).

    Registers the client on the app's :class:`WebSocketHub`
    (``app.state.ws_hub``, wired by Tarea 4), keeps the connection open by
    awaiting client messages, and cleans up on disconnect. Access to the hub is
    defensive: if it is not yet wired, the socket is accepted and closed cleanly.
    """
    hub: WebSocketHub | None = getattr(websocket.app.state, "ws_hub", None)
    if hub is None:
        await websocket.accept()
        await websocket.close()
        return

    await hub.connect(websocket)
    try:
        while True:
            # Block until the client sends something or disconnects. We ignore
            # the content; this only keeps the connection open and detects the
            # disconnect so we can clean up (R3.4).
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
    except Exception:
        # Any other failure: drop this client cleanly without affecting others.
        hub.disconnect(websocket)
