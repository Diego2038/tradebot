// App (spec 08): top-level composition and state.
//
// App owns the top-level frontend state (credentials metadata, account, bot
// status, busy flag, per-section error messages) and composes the presentation
// components. All I/O goes through the isolated services: `apiClient` (REST) and
// `useBotEvents` (WebSocket via BotStream). App owns no domain logic; it renders
// backend state and forwards user intent.
//
// Load sequence (on mount): getCredentials(); if credentials exist, also
// getAccount() (R2.1) and getBotStatus() (R3.4). Errors are captured per section
// so a failure in one area never blanks the whole UI (R1.7, R2.3). The
// PaperTradingBanner is rendered unconditionally so it is present on every view
// (R5.1).
import { useEffect, useState } from "react";
import { apiClient, ApiError } from "./services/apiClient";
import { useBotEvents } from "./hooks/useBotEvents";
import { PaperTradingBanner } from "./components/PaperTradingBanner";
import { CredentialsForm } from "./components/CredentialsForm";
import { AccountPanel } from "./components/AccountPanel";
import { BotControls } from "./components/BotControls";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { Dashboard } from "./components/Dashboard";
import type {
  AccountStatus,
  BotStatus,
  CredentialMetadata,
  Mode,
} from "./types";

const EMPTY_METADATA: CredentialMetadata = {
  exists: false,
  key_id_last4: null,
  validation_status: null,
  updated_at: null,
};

const INITIAL_BOT_STATUS: BotStatus = {
  state: "stopped",
  mode: "random",
  symbol: "BTC/USD",
};

// Extracts a clear message from an unknown error value.
function messageOf(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}

export function App(): JSX.Element {
  const [credentialMetadata, setCredentialMetadata] =
    useState<CredentialMetadata>(EMPTY_METADATA);
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatus>(INITIAL_BOT_STATUS);
  const [busy, setBusy] = useState(false);
  // Independent in-flight flags per bot operation so a hung Start never blocks
  // Stop (product principle: reversibility and control).
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  const [credentialsError, setCredentialsError] = useState<string | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [botError, setBotError] = useState<string | null>(null);

  // Real-time events + WebSocket connection status (R4).
  const { events, connectionStatus } = useBotEvents();

  // Loads account + bot status when credentials exist (R2.1, R3.4). Each call is
  // guarded independently so one failure does not block the other.
  async function loadAccountAndStatus(): Promise<void> {
    try {
      const acc = await apiClient.getAccount();
      setAccount(acc);
      setAccountError(null);
    } catch (err) {
      setAccountError(
        messageOf(err, "No se pudo cargar la cuenta."),
      );
    }

    try {
      const status = await apiClient.getBotStatus();
      setBotStatus(status);
    } catch (err) {
      setBotError(messageOf(err, "No se pudo cargar el estado del bot."));
    }
  }

  // Load sequence on mount (R1.4, R2.1, R3.4).
  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const metadata = await apiClient.getCredentials();
        if (cancelled) {
          return;
        }
        setCredentialMetadata(metadata);
        setCredentialsError(null);
        if (metadata.exists) {
          await loadAccountAndStatus();
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        // A missing-credentials response is a normal state, not a load error.
        if (err instanceof ApiError && err.error_code === "no_credentials") {
          setCredentialMetadata(EMPTY_METADATA);
          return;
        }
        setCredentialsError(
          messageOf(err, "No se pudieron cargar las credenciales."),
        );
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
    // Run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Handlers wired to apiClient ---

  async function onSave(apiKey: string, secret: string): Promise<void> {
    setBusy(true);
    setCredentialsError(null);
    try {
      const result = await apiClient.saveCredentials(apiKey, secret);
      setCredentialMetadata(result);
      if (result.exists) {
        await loadAccountAndStatus();
      }
    } catch (err) {
      // Keep previously displayed metadata visible on error (R1.7).
      setCredentialsError(
        messageOf(err, "No se pudieron guardar las credenciales."),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(): Promise<void> {
    setBusy(true);
    setCredentialsError(null);
    try {
      await apiClient.deleteCredentials();
      setCredentialMetadata(EMPTY_METADATA);
      setAccount(null);
      setAccountError(null);
    } catch (err) {
      setCredentialsError(
        messageOf(err, "No se pudieron eliminar las credenciales."),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onStart(mode: Mode): Promise<void> {
    setStarting(true);
    setBotError(null);
    try {
      const result = await apiClient.startBot(mode);
      setBotStatus(result);
    } catch (err) {
      // Branch on the stable error_code, not the message text (R3.6, R3.7). The
      // displayed state stays as-is (stopped) on failure.
      if (err instanceof ApiError && err.error_code === "no_credentials") {
        setBotError(
          "Configura tus credenciales de Alpaca antes de arrancar el bot.",
        );
      } else if (err instanceof ApiError && err.error_code === "invalid_mode") {
        setBotError("Modo inválido.");
      } else {
        setBotError("No se pudo arrancar el bot.");
      }
    } finally {
      setStarting(false);
    }
  }

  async function onStop(): Promise<void> {
    setStopping(true);
    setBotError(null);
    try {
      const result = await apiClient.stopBot();
      setBotStatus(result);
    } catch (err) {
      setBotError(messageOf(err, "No se pudo detener el bot."));
    } finally {
      setStopping(false);
    }
  }

  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        maxWidth: 720,
        margin: "0 auto",
        padding: "2rem",
      }}
    >
      {/* Persistent paper-trading indicator: rendered unconditionally (R5.1). */}
      <PaperTradingBanner />

      <h1>TradeBot</h1>

      <ConnectionStatus status={connectionStatus} />

      <CredentialsForm
        metadata={credentialMetadata}
        onSave={onSave}
        onDelete={onDelete}
        error={credentialsError}
      />

      <AccountPanel account={account} error={accountError} />

      <BotControls
        status={botStatus}
        busy={busy}
        starting={starting}
        stopping={stopping}
        onStart={onStart}
        onStop={onStop}
        error={botError}
      />

      <Dashboard events={events} />
    </main>
  );
}
