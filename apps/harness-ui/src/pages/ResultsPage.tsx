import { useEffect, useState } from "react";

import { getHarnessApi } from "../api";
import type { ExecutionReport } from "../types";

interface ResultsPageProps {
  runId?: string;
}

export function ResultsPage({ runId = "20261030103857" }: ResultsPageProps): JSX.Element {
  const api = getHarnessApi();
  const [report, setReport] = useState<ExecutionReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getRun(runId)
      .then((r) => {
        if (!cancelled) setReport(r);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [api, runId]);

  const passed = report?.executed.filter((tc) => tc.status !== "ERROR").length ?? 0;
  const failed = report?.executed.filter((tc) => tc.status === "ERROR").length ?? 0;
  const total = report?.count ?? report?.executed.length ?? 0;

  return (
    <section className="page">
      <div className="page__head">
        <div>
          <h2>Results &amp; Assertions</h2>
          <p className="muted">Per-test-case pass/fail with executed assertions.</p>
        </div>
        <div className="page__head-actions">
          <span className={`pill ${api.mode === "http" ? "pill--ok" : "pill--warn"}`}>
            {api.mode === "http" ? "live" : "mock"}
          </span>
          <a className="btn btn--ghost" href="#/runs">
            ← Back to Runs
          </a>
        </div>
      </div>

      {error && <p className="error">Failed to load results: {error}</p>}

      {!report && !error && <p className="muted">Loading results…</p>}

      {report && (
        <>
          <div className="results__summary">
            <div className="results__card">
              <span className="results__card-label">Status</span>
              <span className={`pill ${report.status === "COMPLETED" ? "pill--ok" : "pill--warn"}`}>
                {report.status}
              </span>
            </div>
            <div className="results__card">
              <span className="results__card-label">Passed</span>
              <span className="results__card-value results__card-value--ok">{passed}</span>
            </div>
            <div className="results__card">
              <span className="results__card-label">Failed</span>
              <span className="results__card-value results__card-value--bad">{failed}</span>
            </div>
            <div className="results__card">
              <span className="results__card-label">Total</span>
              <span className="results__card-value">{total}</span>
            </div>
            <div className="results__card">
              <span className="results__card-label">Target</span>
              <span className="results__card-target">{report.target}</span>
            </div>
          </div>

          <div className="results__table">
            <div className="results__row results__row--header">
              <span>Test Case</span>
              <span>Category</span>
              <span>Status</span>
              <span>Assertions</span>
              <span>Screenshots</span>
            </div>
            {report.executed.map((tc) => {
              const isOpen = open === tc.id;
              const assertionCount = tc.assertions?.length ?? 0;
              const passCount = tc.assertions?.filter((a) => a.status !== "ERROR" && a.status !== "FAIL").length ?? 0;
              return (
                <div key={tc.id} className="results__group">
                  <button className="results__row results__row--body" onClick={() => setOpen(isOpen ? null : tc.id)}>
                    <span className="results__id">
                      <span className="plan__badge">{tc.id}</span>
                      <span>{tc.title}</span>
                    </span>
                    <span className="muted">{tc.category ?? "—"}</span>
                    <span>
                      <span className={`pill ${tc.status === "ERROR" ? "" : "pill--ok"}`}>{tc.status}</span>
                    </span>
                    <span className="muted">
                      {assertionCount > 0 ? `${passCount}/${assertionCount} recorded` : "—"}
                    </span>
                    <span className="muted">{tc.screenshots?.length ?? 0}</span>
                  </button>
                  {isOpen && (
                    <div className="results__details">
                      {tc.steps.length > 0 && (
                        <div className="results__section">
                          <h4>Steps</h4>
                          <ol>
                            {tc.steps.map((s, i) => (
                              <li key={i}>{s}</li>
                            ))}
                          </ol>
                        </div>
                      )}
                      {tc.expectedChecks.length > 0 && (
                        <div className="results__section">
                          <h4>Expected Checks</h4>
                          <ul>
                            {tc.expectedChecks.map((c, i) => (
                              <li key={i}>{c}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {tc.assertions && tc.assertions.length > 0 && (
                        <div className="results__section">
                          <h4>Assertions</h4>
                          <div className="results__assertions">
                            {tc.assertions.map((a, i) => (
                              <div key={i} className="results__assertion">
                                <span>{a.check}</span>
                                <span className={`pill ${a.status === "RECORDED" ? "pill--ok" : ""}`}>{a.status}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {tc.error && (
                        <div className="results__section">
                          <h4>Error</h4>
                          <pre className="evidence__pre">{tc.error}</pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
