import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { AccountStatus, BotStatus, CredentialMetadata } from "./types";

// --- Mock the apiClient module so no real network call is made. ---
// We keep the real ApiError class (App branches on `error_code`), and replace
// only the `apiClient` instance methods with spies. The spies are created via
// vi.hoisted so they exist when the hoisted vi.mock factory runs.
const {
  getCredentials,
  getAccount,
  getBotStatus,
  saveCredentials,
  deleteCredentials,
  startBot,
  stopBot,
} = vi.hoisted(() => ({
  getCredentials: vi.fn(),
  getAccount: vi.fn(),
  getBotStatus: vi.fn(),
  saveCredentials: vi.fn(),
  deleteCredentials: vi.fn(),
  startBot: vi.fn(),
  stopBot: vi.fn(),
}));

vi.mock("./services/apiClient", async () => {
  const actual = await vi.importActual<typeof import("./services/apiClient")>(
    "./services/apiClient",
  );
  return {
    ...actual,
    apiClient: {
      getCredentials,
      getAccount,
      getBotStatus,
      saveCredentials,
      deleteCredentials,
      startBot,
      stopBot,
    },
  };
});

// --- Mock useBotEvents so no real WebSocket is opened. ---
vi.mock("./hooks/useBotEvents", () => ({
  useBotEvents: () => ({ events: [], connectionStatus: "connecting" }),
}));

import { App } from "./App";

const NO_CREDENTIALS: CredentialMetadata = {
  exists: false,
  key_id_last4: null,
  validation_status: null,
  updated_at: null,
};

const EXISTING_CREDENTIALS: CredentialMetadata = {
  exists: true,
  key_id_last4: "AB12",
  validation_status: "valid",
  updated_at: "2024-01-01T00:00:00Z",
};

const ACCOUNT: AccountStatus = {
  cash: "100000",
  buying_power: "100000",
  status: "ACTIVE",
  mode: "paper",
};

const BOT_STATUS: BotStatus = {
  state: "stopped",
  mode: "random",
  symbol: "BTC/USD",
};

describe("App composition", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getCredentials.mockResolvedValue(NO_CREDENTIALS);
    getAccount.mockResolvedValue(ACCOUNT);
    getBotStatus.mockResolvedValue(BOT_STATUS);
  });

  it("(a) requests GET /credentials on mount", async () => {
    render(<App />);
    await waitFor(() => {
      expect(getCredentials).toHaveBeenCalledTimes(1);
    });
  });

  it("(b) renders the PaperTradingBanner (R5.1)", async () => {
    render(<App />);
    expect(screen.getByTestId("paper-trading-banner")).toBeInTheDocument();
    // Let the mount effect settle so no state update happens after the assertion.
    await waitFor(() => {
      expect(getCredentials).toHaveBeenCalled();
    });
  });

  it("(c) when credentials exist, also requests the account", async () => {
    getCredentials.mockResolvedValue(EXISTING_CREDENTIALS);

    render(<App />);

    await waitFor(() => {
      expect(getAccount).toHaveBeenCalledTimes(1);
    });
    expect(getBotStatus).toHaveBeenCalledTimes(1);
  });

  it("(d) when no credentials exist, does not request the account", async () => {
    render(<App />);

    await waitFor(() => {
      expect(getCredentials).toHaveBeenCalledTimes(1);
    });
    expect(getAccount).not.toHaveBeenCalled();
  });
});
