import { useEffect, useState } from "react";

import { getHarnessApi } from "../api";
import type { PlanTestCase, RunSummary, TestPlan } from "../types";
import { countSteps, parsePlan } from "../lib/plan";

interface PlanReviewPageProps {
  runId: string;
  onBack: () => void;
  onApproved: (run: RunSummary) => void;
}

function TestCaseRow({ tc }: { tc: PlanTestCase }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div className="plan__row">
      <button className="plan__row-header" onClick={() => setOpen((o) => !o)}>
        <div className="plan__row-title">
          <span className="plan__badge">{tc.id}</span>
          <span>{tc.title}</span>
        </div>
        <span className="plan__row-meta">
          {tc.steps.length} steps · {tc.expectedChecks.length} checks
          <span className={`plan__chev ${open ? "plan__chev--open" : ""}`}>▸</span>
        </span>
      </button>
      {open && (
        <div className="plan__row-body">
          {tc.category && (
            <p className="plan__detail">
              <strong>Category:</strong> {tc.category}
            </p>
          )}
          {tc.preconditions && (
            <p className="plan__detail">
              <strong>Preconditions:</strong> {tc.preconditions}
            </p>
          )}
          <div className="plan__section">
            <h4>Steps</h4>
            <ol>
              {tc.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </div>
          <div className="plan__section">
            <h4>Expected Checks</h4>
            <ul>
              {tc.expectedChecks.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

export function PlanReviewPage({ runId, onBack, onApproved }: PlanReviewPageProps): JSX.Element {
  const api = getHarnessApi();
  const [run, setRun] = useState<RunSummary | null>(null);
  const [plan, setPlan] = useState<TestPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const runs = await api.listRuns();
        const found = runs.find((r) => r.id === runId) ?? null;
        if (cancelled) return;
        setRun(found);
        if (found?.planId) {
          const pr = await api.getPlan(found.planId);
          if (cancelled) return;
          if (pr) {
            const parsed = parsePlan(pr.plan);
            setPlan(parsed);
          }
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api, runId]);

  const handleApprove = async () => {
    setApproving(true);
    setApproveError(null);
    try {
      const updated = await api.approveRun(runId);
      onApproved(updated);
    } catch (e) {
      setApproveError(e instanceof Error ? e.message : String(e));
    } finally {
      setApproving(false);
    }
  };

  return (
    <section className="page">
      <div className="page__head">
        <div>
          <h2>Plan Review & Checkpoint</h2>
          <p className="muted">
            Review the generated test plan and approve before execution. Approval is required to proceed.
          </p>
        </div>
        <button className="btn btn--ghost" onClick={onBack}>
          ← Back to Runs
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {run && (
        <div className="notice">
          <dl className="notice__meta">
            <div>
              <dt>Run ID</dt>
              <dd className="table__mono">{run.id}</dd>
            </div>
            <div>
              <dt>Target</dt>
              <dd>{run.target}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <span className={`pill ${run.approved ? "pill--ok" : "pill--warn"}`}>
                  {run.approved ? "APPROVED" : run.status}
                </span>
              </dd>
            </div>
            <div>
              <dt>Plan</dt>
              <dd className="table__mono">{run.planId ?? "—"}</dd>
            </div>
          </dl>
        </div>
      )}

      {plan ? (
        <div className="plan">
          <div className="plan__header">
            <div>
              <h3>{plan.testPlanTitle ?? "Test Plan"}</h3>
              <p className="muted">
                {plan.testCases.length} test cases · {countSteps(plan)} steps
                {plan.targetUrl ? ` · ${plan.targetUrl}` : ""}
              </p>
            </div>
            {!run?.approved && (
              <button className="btn" onClick={handleApprove} disabled={approving}>
                {approving ? "Approving…" : "Approve Plan & Enable Execution"}
              </button>
            )}
            {run?.approved && (
              <span className="pill pill--ok">✓ Checkpoint passed — execution allowed</span>
            )}
          </div>
          {approveError && <p className="error">{approveError}</p>}
          {plan.scope && plan.scope.length > 0 && (
            <div className="plan__scope">
              <strong>Scope:</strong> {plan.scope.join(", ")}
            </div>
          )}
          <div className="plan__list">
            {plan.testCases.map((tc) => (
              <TestCaseRow key={tc.id} tc={tc} />
            ))}
          </div>
          {!run?.approved && (
            <div className="plan__footer">
              <button className="btn" onClick={handleApprove} disabled={approving}>
                {approving ? "Approving…" : "Approve Plan & Enable Execution"}
              </button>
              <p className="muted">Execution is blocked until this checkpoint is approved.</p>
            </div>
          )}
        </div>
      ) : (
        !error && (
          <div className="empty">
            <h2>Loading plan…</h2>
            <p>Fetching the generated plan for review.</p>
          </div>
        )
      )}
    </section>
  );
}
