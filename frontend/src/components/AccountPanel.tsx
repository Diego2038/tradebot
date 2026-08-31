// AccountPanel (R2): displays the paper account balance and status once it is
// loaded; shows a load error when the account request failed, or a discreet
// empty state when there is no account and no error yet.
import type { AccountStatus } from "../types";

export interface AccountPanelProps {
  account: AccountStatus | null;
  error?: string | null;
}

export function AccountPanel(props: AccountPanelProps): JSX.Element {
  const { account, error } = props;

  return (
    <section aria-label="Cuenta paper" style={{ marginTop: "1.5rem" }}>
      <h2>Cuenta paper</h2>

      {account ? (
        // Balance + status when the snapshot is present (R2.2).
        <div data-testid="account-details">
          <span data-testid="account-cash">Cash: {account.cash}</span>
          {" · "}
          <span data-testid="account-buying-power">
            Poder de compra: {account.buying_power}
          </span>
          {" · "}
          <span data-testid="account-status">Estado: {account.status}</span>
          {" · "}
          <span data-testid="account-mode">Modo: {account.mode}</span>
        </div>
      ) : error ? (
        // Load error (R2.3).
        <p role="alert" style={{ color: "#842029" }}>
          {error}
        </p>
      ) : (
        // Discreet empty state.
        <p data-testid="account-empty" style={{ color: "#6c757d" }}>
          Sin datos de cuenta
        </p>
      )}
    </section>
  );
}
