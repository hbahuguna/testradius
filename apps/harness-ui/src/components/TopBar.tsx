import type { Route } from "../App";

import { getHarnessApi } from "../api";

const TITLES: Record<Route, { title: string; subtitle: string }> = {
  runs: { title: "Runs", subtitle: "Every harness execution, live and historical" },
  "new-run": { title: "New Run", subtitle: "Context in, plan out, approve before execution" },
  "plan-review": { title: "Plan Review", subtitle: "Checkpoint: approve before execution" },
  live: { title: "Live Execution", subtitle: "Step list, current step, logs, real-time status" },
  evidence: { title: "Evidence Center", subtitle: "Screenshots, video, traces, console and network" },
  results: { title: "Results", subtitle: "Per-test assertions, pass/fail, exportable reports" },
  settings: { title: "Settings", subtitle: "Model, policy, and sandbox configuration" },
};

export function TopBar({ route }: { route: Route }): JSX.Element {
  const meta = TITLES[route];
  const api = getHarnessApi();
  return (
    <header className="topbar">
      <div>
        <h1 className="topbar__title">{meta.title}</h1>
        <p className="topbar__subtitle">{meta.subtitle}</p>
      </div>
      <div className="topbar__status">
        <span className="pill pill--muted">harness v0.1.0</span>
        <span className={`pill ${api.mode === "http" ? "pill--ok" : "pill--warn"}`}>
          API: {api.mode}
        </span>
      </div>
    </header>
  );
}
