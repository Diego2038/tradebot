// Dashboard (R4.2, R4.3): renders the real-time list of bot events as a table.
// Events arrive already most-recent-first from `useBotEvents`; the Dashboard
// renders them in the received order and does NOT reorder them (R4.3). Each row
// shows event_type, symbol, side, qty, price and timestamp; nullable fields are
// shown with a discreet dash (R4.2).
import type { BotEvent } from "../types";

export interface DashboardProps {
  events: BotEvent[];
}

// Renders a possibly-null field value with a dash placeholder when absent.
function cell(value: string | null): string {
  return value == null || value === "" ? "—" : value;
}

export function Dashboard(props: DashboardProps): JSX.Element {
  const { events } = props;

  return (
    <section aria-label="Eventos del bot" style={{ marginTop: "1.5rem" }}>
      <h2>Eventos en tiempo real</h2>

      {events.length === 0 ? (
        // Discreet empty state.
        <p data-testid="dashboard-empty" style={{ color: "#6c757d" }}>
          Sin eventos todavía
        </p>
      ) : (
        <table data-testid="events-table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th scope="col">Tipo</th>
              <th scope="col">Símbolo</th>
              <th scope="col">Lado</th>
              <th scope="col">Cantidad</th>
              <th scope="col">Precio</th>
              <th scope="col">Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {/* Rendered in received order (already most-recent-first) — no sorting (R4.3). */}
            {events.map((event, index) => (
              <tr
                // Events have no guaranteed unique id; index keeps insertion order stable.
                key={`${event.timestamp}-${index}`}
                data-testid="event-row"
              >
                <td data-testid="event-type">{cell(event.event_type)}</td>
                <td data-testid="event-symbol">{cell(event.symbol)}</td>
                <td data-testid="event-side">{cell(event.side)}</td>
                <td data-testid="event-qty">{cell(event.qty)}</td>
                <td data-testid="event-price">{cell(event.price)}</td>
                <td data-testid="event-timestamp">{cell(event.timestamp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
