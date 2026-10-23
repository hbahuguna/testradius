import { describe, expect, it } from "vitest";

import { buildServer } from "../src/app.js";

describe("control-plane scaffold", () => {
  it("reports liveness", async () => {
    const app = buildServer();
    const response = await app.inject({ method: "GET", url: "/healthz" });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({
      status: "ok",
      service: "control-plane",
      version: "0.1.0",
    });
    await app.close();
  });

  it("reports readiness without pretending to have a database", async () => {
    const app = buildServer();
    const response = await app.inject({ method: "GET", url: "/readyz" });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toMatchObject({ ready: true, db: "not_configured" });
    await app.close();
  });

  it("fails readiness when a database is required but not configured", async () => {
    process.env.FACTORY_REQUIRE_DB = "true";
    delete process.env.DATABASE_URL;

    const app = buildServer();
    const response = await app.inject({ method: "GET", url: "/readyz" });

    expect(response.statusCode).toBe(503);
    expect(response.json()).toMatchObject({ ready: false });

    delete process.env.FACTORY_REQUIRE_DB;
    await app.close();
  });

  it("exposes build metadata for the web shell", async () => {
    const app = buildServer({ version: "9.9.9" });
    const response = await app.inject({ method: "GET", url: "/v1/meta" });

    expect(response.json()).toEqual({
      service: "control-plane",
      version: "9.9.9",
      sprint: 1,
      contract: "1",
    });
    await app.close();
  });
});
