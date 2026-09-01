// Dashboard (R4.2, R4.3): renders the real-time list of bot events as a table.
// Events arrive already most-recent-first from `useBotEvents`; the Dashboard
// renders them in the received order and does NOT reorder them (R4.3). Each row
// shows event_type, symbol, side, qty, price and timestamp; nullable fields are
// shown with a discreet dash (R4.2).
//
// Presentation only: the type/side cells are wrapped in a badge whose colour is
// derived from the value, so each cell's text content is unchanged.
import type { BotEvent } from "../types";
import { ActivityChart } from "./ActivityChart";

export interface DashboardProps {
  events: BotEvent[];
}

// Renders a possibly-null field value with a dash placeholder when absent.
function cell(value: string | null): string {
  return value == null || value === "" ? "—" : value;
}

// Picks the badge colour variant for a type/side value. Unknown values are
// neutral, so arbitrary strings are always rendered safely.
function badgeVariant(value: string): string {
  const normalized = value.toUpperCase();
  if (normalized === "BUY") {
    return "badge--buy";
  }
  if (normalized === "SELL") {
    return "badge--sell";
  }
  if (normalized === "ERROR" || normalized === "REJECTED") {
    return "badge--error";
  }
  return "badge--neutral";
}

// A cell value rendered as a badge, or as discreet muted text when absent.
function BadgeCell(props: { value: string | null }): JSX.Element {
  const text = cell(props.value);
  if (text === "—") {
    return <span className="cell--muted">{text}</span>;
  }
  return <span className={`badge ${badgeVariant(text)}`}>{text}</span>;
}

export function Dashboard(props: DashboardProps): JSX.Element {
  const { events } = props;

  return (
    <section aria-label="Eventos del bot" className="card">
      <div className="card__header">
        <h2 className="card__title">Eventos en tiempo real</h2>
      </div>

      <div className="card__body">
        {events.length === 0 ? (
          // Discreet empty state.
          <p data-testid="dashboard-empty" className="empty-state">
            Sin eventos todavía
          </p>
        ) : (
          <>
            {/* Live price chart derived from the same events (presentation only). */}
            <ActivityChart events={events} />

            <div className="table-wrap">
              <table data-testid="events-table" className="table">
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
                      <td data-testid="event-type">
                        <BadgeCell value={event.event_type} />
                      </td>
                      <td data-testid="event-symbol">{cell(event.symbol)}</td>
                      <td data-testid="event-side">
                        <BadgeCell value={event.side} />
                      </td>
                      <td data-testid="event-qty" className="cell--num">
                        {cell(event.qty)}
                      </td>
                      <td data-testid="event-price" className="cell--num">
                        {cell(event.price)}
                      </td>
                      <td data-testid="event-timestamp" className="cell--muted">
                        {cell(event.timestamp)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
