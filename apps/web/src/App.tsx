import { useEffect, useState } from "react";

import type { HealthResponse, RunEvent } from "@testradius/shared-types";

type ControlPlaneHealth = Pick<HealthResponse, "version"> & {
  status: string;
  service: string;
};

// Type-checked against the shared package; erased at build time so the runtime
// bundle does not depend on the workspace package.
const CONTRACT_VERSION: RunEvent["schema_version"] = "1";

const SURFACES = [
  { name: "Dashboard", detail: "Run throughput, gate pass rate, coverage", sprint: "Sprint 6" },
  { name: "Runs", detail: "History, phases, agent steps, verdicts", sprint: "Sprint 5" },
  { name: "Evidence", detail: "Screenshots, video, traces, network logs", sprint: "Sprint 6" },
  { name: "Policy", detail: "Egress, budgets, redaction, escalation", sprint: "Sprint 6" },
];

export default function App(): JSX.Element {
  const [health, setHealth] = useState<ControlPlaneHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async (): Promise<void> => {
      try {
        const response = await fetch("/api/healthz");
        if (!response.ok) throw new Error(`control plane returned ${response.status}`);
        const body = (await response.json()) as ControlPlaneHealth;
        if (!cancelled) {
          setHealth(body);
          setError(null);
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "unknown error");
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const status = error ? "unreachable" : health ? "reachable" : "checking";

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">TestRadius</p>
          <h1>Testing Factory</h1>
        </div>
        <span className={`pill pill--${status}`} data-testid="cp-status">
          control plane: {status}
        </span>
      </header>

      <main>
        <section className="intro">
          <h2>One run, end to end</h2>
          <p>
            Isolate → Select → Generate → Execute → Prove → Gate → Report. The UI is a read model
            over the control plane; the cell stays UI-less and ephemeral.
          </p>
          {error ? (
            <p className="error" role="alert">
              Could not reach the control plane: {error}
            </p>
          ) : null}
        </section>

        <section className="grid" aria-label="Planned surfaces">
          {SURFACES.map((surface) => (
            <article key={surface.name} className="card">
              <div className="card__head">
                <h3>{surface.name}</h3>
                <span className="tag">{surface.sprint}</span>
              </div>
              <p>{surface.detail}</p>
            </article>
          ))}
        </section>
      </main>

      <footer>
        <span>Sprint 1 — foundation + cell skeleton · contract v{CONTRACT_VERSION}</span>
        {health ? <span data-testid="cp-version">cp v{health.version}</span> : null}
      </footer>
    </div>
  );
}
