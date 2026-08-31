import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CredentialsForm } from "./CredentialsForm";
import type { CredentialMetadata } from "../types";

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

describe("CredentialsForm", () => {
  it("(a) the Secret input is masked (type='password') (R1.1)", () => {
    render(
      <CredentialsForm
        metadata={noCredentials}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const secretInput = screen.getByLabelText("API Secret");
    expect(secretInput).toHaveAttribute("type", "password");
  });

  it("(b) submitting calls onSave with apiKey+secret; secret is cleared and not in the DOM (R1.2, R1.3)", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <CredentialsForm
        metadata={noCredentials}
        onSave={onSave}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const apiKeyInput = screen.getByLabelText("API Key ID");
    const secretInput = screen.getByLabelText("API Secret") as HTMLInputElement;
    const secretValue = "super-secret-value-123";

    await user.type(apiKeyInput, "PKTESTKEYID");
    await user.type(secretInput, secretValue);
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith("PKTESTKEYID", secretValue);

    // After submit the secret field is cleared...
    expect(secretInput.value).toBe("");
    // ...and the plaintext secret must not appear anywhere in the DOM (R1.3).
    expect(document.body.textContent).not.toContain(secretValue);
  });

  it("(c) with metadata.exists shows last4 + validation_status and not the secret; delete calls onDelete (R1.5, R1.6)", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);

    render(
      <CredentialsForm
        metadata={existingCredentials}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={onDelete}
      />,
    );

    expect(screen.getByTestId("key-id-last4")).toHaveTextContent("WXYZ");
    expect(screen.getByTestId("validation-status")).toHaveTextContent("valid");

    // The metadata display never renders a secret field value.
    const secretInput = screen.getByLabelText("API Secret") as HTMLInputElement;
    expect(secretInput.value).toBe("");

    await user.click(
      screen.getByRole("button", { name: "Eliminar credenciales" }),
    );
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("(d) renders the error via role='alert' while keeping metadata visible (R1.7)", () => {
    render(
      <CredentialsForm
        metadata={existingCredentials}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
        error="No se pudieron guardar las credenciales"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "No se pudieron guardar las credenciales",
    );
    // Metadata remains visible alongside the error (R1.7).
    expect(screen.getByTestId("key-id-last4")).toHaveTextContent("WXYZ");
  });
});
