import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiClient, ApiError } from "./apiClient";
import type { BotStatus, CredentialMetadata } from "../types";

const BASE_URL = "http://backend.test";

// `global` may not be typed without @types/node; `globalThis` is standard and
// resolves to the same object, so we mock fetch through it.
const g = globalThis as { fetch: typeof fetch };

function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number }) {
  const ok = init?.ok ?? true;
  const status = init?.status ?? (ok ? 200 : 500);
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: async () => body,
  } as unknown as Response;
}

describe("ApiClient", () => {
  let client: ApiClient;

  beforeEach(() => {
    vi.restoreAllMocks();
    g.fetch = vi.fn();
    client = new ApiClient(BASE_URL);
  });

  it("(a) saveCredentials issues POST /credentials with JSON body and returns parsed metadata", async () => {
    const metadata: CredentialMetadata = {
      exists: true,
      key_id_last4: "K...",
      validation_status: "valid",
      updated_at: "2024-01-01T00:00:00Z",
    };
    (g.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(metadata),
    );

    const result = await client.saveCredentials("PK...", "sec");

    expect(g.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = (g.fetch as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(url).toBe(`${BASE_URL}/credentials`);
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body as string)).toEqual({
      api_key: "PK...",
      secret: "sec",
    });
    expect(result).toEqual(metadata);
  });

  it("(b) a 409 no_credentials response makes startBot throw ApiError with error_code and status", async () => {
    (g.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(
        { error_code: "no_credentials", detail: "configure credentials first" },
        { ok: false, status: 409 },
      ),
    );

    const error = await client.startBot("random").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      error_code: "no_credentials",
      status: 409,
    });
  });

  it("(c) getBotStatus returns the parsed BotStatus", async () => {
    const status: BotStatus = {
      state: "running",
      mode: "predictive",
      symbol: "BTC/USD",
    };
    (g.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(status),
    );

    const result = await client.getBotStatus();

    expect(g.fetch).toHaveBeenCalledWith(
      `${BASE_URL}/bot/status`,
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toEqual(status);
  });

  it("(d) a fetch that rejects (network) throws ApiError with error_code network", async () => {
    (g.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );

    await expect(client.getAccount()).rejects.toMatchObject({
      error_code: "network",
    });
  });
});
