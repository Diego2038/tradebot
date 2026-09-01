// PaperTradingBanner (R5): a persistent, always-visible notice that the app
// operates exclusively in paper trading with no real money. App.tsx renders it
// unconditionally so it is present on every view (R5.1, R5.2).
//
// Presentation only: rendered as a pill styled by `styles.css`. The role, the
// test id and the text are part of the contract and stay unchanged.
export function PaperTradingBanner(): JSX.Element {
  return (
    <span
      role="status"
      data-testid="paper-trading-banner"
      className="pill pill--paper"
    >
      <span className="pill__dot" aria-hidden="true" />
      Paper Trading — dinero ficticio, sin dinero real
    </span>
  );
}
