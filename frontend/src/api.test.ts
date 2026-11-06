import { afterEach, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

it("stops retrying after a persistent unauthorized response", async () => {
  const fetcher = vi.fn(
    async (path: string) =>
      new Response(
        JSON.stringify(
          path.endsWith("/session")
            ? { token: "test-session" }
            : { detail: "Invalid session" },
        ),
        { status: path.endsWith("/session") ? 200 : 401 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const { api } = await import("./api");
  await expect(api("/health")).rejects.toThrow("Invalid session");
  expect(fetcher).toHaveBeenCalledTimes(4);
});

it("recovers when the service starts after the initial connection failed", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new Error("Service not started"))
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ token: "test-session" })),
    )
    .mockResolvedValueOnce(new Response(JSON.stringify({ version: "0.1.0" })));
  vi.stubGlobal("fetch", fetcher);
  const { api } = await import("./api");
  await expect(api("/health")).rejects.toThrow("Service not started");
  await expect(api("/health")).resolves.toEqual({ version: "0.1.0" });
  expect(
    fetcher.mock.calls.at(-1)?.[1].headers.get("x-voiceledger-token"),
  ).toBe("test-session");
});
