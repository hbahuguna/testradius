import { useEffect, useState } from "react";

import { getHarnessApi } from "../api";
import type { ExecutionReport } from "../types";

interface ResultsPageProps {
  runId?: string;
}

function downloadBlob(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function buildHtmlReport(report: ExecutionReport) {
  const rows = report.executed
    .map(
      (tc) => `
      <tr>
        <td><strong>${tc.id}</strong><br/>${tc.title}</td>
        <td>${tc.category ?? ""}</td>
        <td>${tc.status}</td>
        <td>${(tc.assertions ?? []).map((a) => `<div>• ${a.check} <em>(${a.status})</em></div>`).join("") || "—"}</td>
        <td>${tc.screenshots?.length ?? 0}</td>
      </tr>
    `,
    )
    .join("");
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>TestRadius Report - ${report.target}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; color: #1e293b; }
    header { margin-bottom: 32px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
    th { background: #f8fafc; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }
    .meta { display: flex; gap: 24px; margin-top: 12px; color: #475569; }
  </style>
</head>
<body>
  <header>
    <h1>TestRadius Test Report</h1>
    <p>Target: ${report.target}</p>
    <div class="meta">
      <span>Status: ${report.status}</span>
      <span>Test Cases: ${report.count ?? report.executed.length}</span>
      <span>Plan: ${report.source_plan ?? "—"}</span>
      <span>Evidence: ${report.evidence}</span>
    </div>
  </header>
  <table>
    <thead>
      <tr>
        <th>Test Case</th>
        <th>Category</th>
        <th>Status</th>
        <th>Assertions</th>
        <th>Screenshots</th>
      </tr>
    </thead>
    <tbody>
      ${rows}
    </tbody>
  </table>
</body>
</html>`;
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
          <div className="page__head-actions">
            <button
              className="btn btn--ghost btn--sm"
              onClick={() => downloadBlob(`testradius-results-${runId}.json`, JSON.stringify(report, null, 2), "application/json")}
            >
              Export JSON
            </button>
            <button
              className="btn btn--ghost btn--sm"
              onClick={() => downloadBlob(`testradius-results-${runId}.html`, buildHtmlReport(report), "text/html")}
            >
              Export HTML
            </button>
          </div>

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
