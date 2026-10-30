import { useEffect, useState } from "react";

import { getHarnessApi } from "../api";
import type { RunSummary } from "../types";

export function RunsPage(): JSX.Element {
  const api = getHarnessApi();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listRuns()
      .then((r) => {
        if (!cancelled) setRuns(r);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  const statusClass = (r: RunSummary) => {
    if (r.approved) return "pill pill--ok";
    if (r.status === "COMPLETED") return "pill pill--ok";
    if (r.status === "APPROVED" || r.status === "PLANNING") return "pill pill--warn";
    return "pill";
  };

  return (
    <section className="page">
      <div className="page__head">
        <h2>Run history</h2>
        <span className={`pill ${api.mode === "http" ? "pill--ok" : "pill--warn"}`}>
          {api.mode === "http" ? "live data" : "mock data"}
        </span>
      </div>

      {error && <p className="error">Failed to load runs: {error}</p>}

      {runs === null && !error && <p className="muted">Loading runs…</p>}

      {runs && runs.length === 0 && (
        <div className="empty">
          <h2>No runs yet</h2>
          <p>
            Runs created via the CLI or the New Run form will appear here with live
            status, current step, and links to evidence.
          </p>
          <pre className="code">python3.14 -m harness testradius run</pre>
        </div>
      )}

      {runs && runs.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Target</th>
              <th>Status</th>
              <th>Plan</th>
              <th>Tests</th>
              <th>Evidence</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td className="table__mono">{r.id}</td>
                <td>{r.target}</td>
                <td>
                  <span className={statusClass(r)}>
                    {r.approved ? "APPROVED" : r.status}
                  </span>
                </td>
                <td>
                  {r.planId ? (
                    <a className="link" href={`#/plan-review/${r.id}`}>
                      Review plan
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="table__mono">{r.count}</td>
                <td className="table__mono table__truncate">{r.evidence || "—"}</td>
                <td>
                  {r.planId && !r.approved ? (
                    <a className="btn btn--ghost btn--sm" href={`#/plan-review/${r.id}`}>
                      Approve
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
