import Fastify, { type FastifyInstance } from "fastify";

import { RUN_EVENT_SCHEMA_VERSION } from "./contracts.js";

export interface BuildOptions {
  version?: string;
}

/**
 * Sprint 1 scaffold. The runs API, OIDC/RBAC and dispatch land in Sprint 5
 * (E5-S1..S6). This server exists so Compose, health checks and the web shell
 * have a real control plane to talk to.
 */
export function buildServer(options: BuildOptions = {}): FastifyInstance {
  const version = options.version ?? "0.1.0";
  const app = Fastify({ logger: false, disableRequestLogging: true });

  app.get("/healthz", async () => ({
    status: "ok",
    service: "control-plane",
    version,
  }));

  app.get("/readyz", async (_request, reply) => {
    // No DB client yet (E5-S1). Until then readiness reports whether a URL is
    // configured instead of pretending to probe it.
    const db = process.env.DATABASE_URL ? "configured" : "not_configured";
    const requireDb = process.env.FACTORY_REQUIRE_DB === "true";
    const ready = !(requireDb && db !== "configured");
    if (!ready) reply.code(503);
    return { ready, db, version };
  });

  app.get("/v1/meta", async () => ({
    service: "control-plane",
    version,
    sprint: 1,
    contract: RUN_EVENT_SCHEMA_VERSION,
  }));

  return app;
}
