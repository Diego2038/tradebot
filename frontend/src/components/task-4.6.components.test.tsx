// Spec 08 · Task 4.6 — Inline component tests (dedicated materialization).
//
// The user chose to gather the four checks required by task 4.6 into a single
// dedicated file for direct task->file traceability. There is intentional
// overlap with the per-component test files; this file exists so the task's
// four requirements (R1.3, R1.5, R4.2, R5.1) can be read and run in one place.
//
// Task 4.6 asks to verify:
//   1. The Secret input is type="password" and the submitted Secret does not
//      appear in the DOM.
//   2. Existing credential metadata renders only non-sensitive fields.
//   3. The Dashboard renders one event with all required fields.
//   4. The PaperTradingBanner is present.
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CredentialsForm } from "./CredentialsForm";
import { Dashboard } from "./Dashboard";
import { PaperTradingBanner } from "./PaperTradingBanner";
import type { BotEvent, CredentialMetadata } from "../types";

const noCredentials: CredentialMetadata = {
  exists: false,
  key_id_last4: null,
  validation_status: null,
  updated_at: null,
};

const existingCredentials: CredentialMetadata = {
  exists: true,
  key_id_last4: "WXYZ",
  validation_status: "valid",
  updated_at: "2024-01-01T00:00:00Z",
};

describe("Spec 08 · Task 4.6 · Inline component tests", () => {
  it("renders the Secret input masked and never leaks the submitted Secret to the DOM", async () => {
    // Feature: 08-web-frontend, Task 4.6: Secret input is type="password" and the
    // submitted Secret does not appear in the DOM — Validates: Requirements 1.3
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onDelete = vi.fn().mockResolvedValue(undefined);

    render(
      <CredentialsForm
        metadata={noCredentials}
        onSave={onSave}
        onDelete={onDelete}
      />,
    );

    const secretInput = screen.getByLabelText("API Secret") as HTMLInputElement;
    expect(secretInput).toHaveAttribute("type", "password");

    const secretValue = "top-secret-4p6";
    await user.type(screen.getByLabelText("API Key ID"), "PKKEY46");
    await user.type(secretInput, secretValue);
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith("PKKEY46", secretValue);
    // The field is cleared and the plaintext Secret is nowhere in the DOM.
    expect(secretInput.value).toBe("");
    expect(document.body.textContent).not.toContain(secretValue);
  });

  it("renders existing credential metadata with only non-sensitive fields", () => {
    // Feature: 08-web-frontend, Task 4.6: existing metadata shows only
    // non-sensitive fields (last4 + validation, never the secret)
    // — Validates: Requirements 1.5
    render(
      <CredentialsForm
        metadata={existingCredentials}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByTestId("key-id-last4")).toHaveTextContent("WXYZ");
    expect(screen.getByTestId("validation-status")).toHaveTextContent("valid");
    // The Secret field is never populated from metadata.
    const secretInput = screen.getByLabelText("API Secret") as HTMLInputElement;
    expect(secretInput.value).toBe("");
  });

  it("renders one Bot_Event row with all required fields", () => {
    // Feature: 08-web-frontend, Task 4.6: the Dashboard renders one event with
    // all required fields — Validates: Requirements 4.2
    const filled: BotEvent = {
      event_type: "FILLED",
      symbol: "BTC/USD",
      side: "buy",
      qty: "0.5",
      price: "65000.00",
      order_id: "abc-123",
      reason: null,
      timestamp: "2024-01-01T10:00:00Z",
    };

    render(<Dashboard events={[filled]} />);

    const rows = screen.getAllByTestId("event-row");
    expect(rows).toHaveLength(1);

    const row = within(rows[0]);
    expect(row.getByTestId("event-type")).toHaveTextContent("FILLED");
    expect(row.getByTestId("event-symbol")).toHaveTextContent("BTC/USD");
    expect(row.getByTestId("event-side")).toHaveTextContent("buy");
    expect(row.getByTestId("event-qty")).toHaveTextContent("0.5");
    expect(row.getByTestId("event-price")).toHaveTextContent("65000.00");
    expect(row.getByTestId("event-timestamp")).toHaveTextContent(
      "2024-01-01T10:00:00Z",
    );
  });

  it("always renders the paper-trading indicator", () => {
    // Feature: 08-web-frontend, Task 4.6: the PaperTradingBanner is present
    // — Validates: Requirements 5.1
    render(<PaperTradingBanner />);

    const banner = screen.getByTestId("paper-trading-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent?.toLowerCase()).toContain("paper");
  });
});
