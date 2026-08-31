// CredentialsForm (R1): API Key ID input + masked Secret input, save/delete,
// metadata-only display, and error resilience.
//
// Secret handling invariant (R1.3): the plaintext Secret exists only transiently
// in the Secret <input> element and the onSave argument. It is NEVER placed in
// persistent React state that gets rendered, and it is cleared after submit. The
// Secret input is a masked (type="password") uncontrolled field read via a ref.
import { useRef, useState } from "react";
import type { CredentialMetadata } from "../types";

export interface CredentialsFormProps {
  metadata: CredentialMetadata;
  onSave: (apiKey: string, secret: string) => Promise<void>;
  onDelete: () => Promise<void>;
  error?: string | null;
}

export function CredentialsForm(props: CredentialsFormProps): JSX.Element {
  const { metadata, onSave, onDelete, error } = props;

  // The API Key ID may be controlled — it is not sensitive.
  const [apiKey, setApiKey] = useState("");
  // The Secret is read from the input at submit time via a ref; it is never
  // held in rendered state (R1.3).
  const secretRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
    e.preventDefault();
    const secret = secretRef.current?.value ?? "";
    void onSave(apiKey, secret);
    // Clear the secret field so the plaintext never lingers in the DOM (R1.3).
    if (secretRef.current) {
      secretRef.current.value = "";
    }
  };

  return (
    <section aria-label="Credenciales de Alpaca" style={{ marginTop: "1.5rem" }}>
      <h2>Credenciales de Alpaca</h2>

      {/* Non-sensitive metadata display when credentials exist (R1.5). The
          Secret is never shown. This stays visible even on error (R1.7). */}
      {metadata.exists && (
        <div data-testid="credentials-metadata" style={{ marginBottom: "1rem" }}>
          <span data-testid="key-id-last4">
            API Key ID (últimos 4): {metadata.key_id_last4}
          </span>
          {" · "}
          <span data-testid="validation-status">
            Validación: {metadata.validation_status}
          </span>
          <div style={{ marginTop: "0.5rem" }}>
            <button
              type="button"
              onClick={() => {
                void onDelete();
              }}
            >
              Eliminar credenciales
            </button>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="credentials-api-key">API Key ID</label>{" "}
          <input
            id="credentials-api-key"
            type="text"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="credentials-secret">API Secret</label>{" "}
          <input
            id="credentials-secret"
            type="password"
            ref={secretRef}
            defaultValue=""
          />
        </div>

        <button type="submit">Guardar</button>
      </form>

      {/* Error message; metadata above remains visible (R1.7). */}
      {error && (
        <p role="alert" style={{ color: "#842029", marginTop: "1rem" }}>
          {error}
        </p>
      )}
    </section>
  );
}
