// PaperTradingBanner (R5): a persistent, always-visible notice that the app
// operates exclusively in paper trading with no real money. App.tsx renders it
// unconditionally so it is present on every view (R5.1, R5.2).
export function PaperTradingBanner(): JSX.Element {
  return (
    <div
      role="status"
      data-testid="paper-trading-banner"
      style={{
        backgroundColor: "#fff3cd",
        color: "#664d03",
        border: "1px solid #ffe69c",
        borderRadius: "4px",
        padding: "0.5rem 0.75rem",
        fontWeight: 600,
        textAlign: "center",
      }}
    >
      Paper Trading — dinero ficticio, sin dinero real
    </div>
  );
}
