// AccountPanel (R2): displays the paper account balance and status once it is
// loaded; shows a load error when the account request failed, or a discreet
// empty state when there is no account and no error yet.
//
// Presentation only: the same fields are laid out as KPI tiles. Each tile keeps
// its original test id and label text ("Cash: ", "Poder de compra: ",
// "Estado: ", "Modo: "); the label is just rendered on its own line.
import type { AccountStatus } from "../types";

export interface AccountPanelProps {
  account: AccountStatus | null;
  error?: string | null;
}

export function AccountPanel(props: AccountPanelProps): JSX.Element {
  const { account, error } = props;

  return (
    <section aria-label="Cuenta paper" className="card card--accent">
      <div className="card__header">
        <h2 className="card__title">Cuenta paper</h2>
      </div>

      <div className="card__body">
        {account ? (
          // Balance + status when the snapshot is present (R2.2).
          <div data-testid="account-details" className="kpi-row">
            <div className="kpi kpi--hero">
              <span data-testid="account-cash" className="kpi__value">
                <span className="kpi__inline-label">Cash: </span>
                {account.cash}
              </span>
            </div>
            <div className="kpi">
              <span data-testid="account-buying-power" className="kpi__value">
                <span className="kpi__inline-label">Poder de compra: </span>
                {account.buying_power}
              </span>
            </div>
            <div className="kpi">
              <span data-testid="account-status" className="kpi__value">
                <span className="kpi__inline-label">Estado: </span>
                {account.status}
              </span>
            </div>
            <div className="kpi">
              <span data-testid="account-mode" className="kpi__value">
                <span className="kpi__inline-label">Modo: </span>
                {account.mode}
              </span>
            </div>
          </div>
        ) : error ? (
          // Load error (R2.3).
          <p role="alert" className="alert">
            {error}
          </p>
        ) : (
          // Discreet empty state.
          <p data-testid="account-empty" className="empty-state">
            Sin datos de cuenta
          </p>
        )}
      </div>
    </section>
  );
}
