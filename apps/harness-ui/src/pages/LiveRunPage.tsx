import { useEffect, useRef, useState } from "react";

import { getHarnessApi } from "../api";
import type { LiveExecutionState } from "../types";

interface LiveRunPageProps {
  runId: string;
  onBack: () => void;
}

function statusBadge(status: string) {
  if (status === "COMPLETED") return "pill pill--ok";
  if (status === "RUNNING" || status === "PREPARING" || status === "QUEUED") return "pill pill--warn";
  if (status === "FAILED" || status === "ABORTED") return "pill";
  return "pill pill--muted";
}

function stageMessage(status: string, hasSandbox: boolean): string {
  if (status === "QUEUED") return "Queued — waiting to create the E2B sandbox…";
  if (status === "PREPARING")
    return hasSandbox
      ? "Sandbox created — starting the desktop session…"
      : "Preparing E2B sandbox… (first run can take 1–3 minutes)";
  if (status === "RUNNING") return "Executing compiled plan in the sandbox… video records the full run.";
  if (status === "FAILED") return "Run failed — see the error log below.";
  if (status === "COMPLETED") return "Run finished.";
  return `Status: ${status}`;
}

function stepBadge(status: string) {
  if (status === "COMPLETED") return "pill pill--ok";
  if (status === "RUNNING") return "pill pill--warn";
  if (status === "FAILED") return "pill";
  if (status === "SKIPPED") return "pill pill--muted";
  return "pill pill--muted";
}

export function LiveRunPage({ runId, onBack }: LiveRunPageProps): JSX.Element {
  const api = getHarnessApi();
  const [state, setState] = useState<LiveExecutionState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef<number>();

  const load = async () => {
    try {
      const live = await api.getLiveState(runId);
      setState(live);
      if (live?.status === "RUNNING") setRunning(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    load();
    pollRef.current = window.setInterval(load, 1500);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const start = async () => {
    try {
      await api.startRun(runId);
      setRunning(true);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const pct = state && state.progress.total > 0 ? Math.round((state.progress.completed / state.progress.total) * 100) : 0;
  const working =
    state?.status === "QUEUED" || state?.status === "PREPARING" || state?.status === "RUNNING";
  const showIndeterminate = Boolean(working) && (!state || state.progress.total === 0 || state.progress.completed === 0);
  const isE2B =
    state?.executorType === "e2b" ||
    state?.executorType === "gemini_computer_use" ||
    Boolean(state?.sandboxId || state?.template);

  return (
    <section className="page">
      <div className="page__head">
        <div>
          <h2>Live Execution</h2>
          <p className="muted">Step list, current step, status, and live logs (polling).</p>
        </div>
        <button className="btn btn--ghost" onClick={onBack}>
          ← Back to Runs
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {state?.status === "FAILED" && state.logs.length > 0 && (
        <div className="notice" style={{ marginBottom: 16 }}>
          <h3>Run failed</h3>
          <pre className="evidence__pre">{state.logs[state.logs.length - 1]?.message ?? "Unknown error"}</pre>
          <p className="muted">
            Common causes: E2B API unreachable (firewall IP allowlist), missing or wrong
            E2B_API_KEY, template/memory-pool exhaustion, or Gemini key/model errors. Restart
            the API with the live env exported, then start a new run.
          </p>
        </div>
      )}

      <div className="live__header">
        <div className="live__meta">
          <div>
            <dt>Run ID</dt>
            <dd className="table__mono">{runId}</dd>
          </div>
          {state && (
            <>
              <div>
                <dt>Target</dt>
                <dd>{state.target}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>
                  <span className={statusBadge(state.status)}>{state.status}</span>
                </dd>
              </div>
              <div>
                <dt>Progress</dt>
                <dd>
                  {state.progress.completed}/{state.progress.total} · {state.progress.failed} failed ({pct}%)
                </dd>
              </div>
            </>
          )}
        </div>
        <div className="live__actions">
          {!state && <span className="pill pill--muted">loading</span>}
          {state?.status === "APPROVED" && !running && (
            <button className="btn" onClick={start}>
              Start Execution
            </button>
          )}
          {state?.status === "RUNNING" && <span className="pill pill--warn">● LIVE</span>}
          {state?.status === "COMPLETED" && (
            <a className="btn btn--ghost" href={`#/results/${state.runId}`}>
              View Results
            </a>
          )}
          {state?.video && (
            <a className="btn btn--ghost" href={`/${state.video}`} target="_blank" rel="noreferrer">
              Open video
            </a>
          )}
        </div>
      </div>

      {state && (
        <div className="live__progress" aria-live="polite">
          <p className="muted" style={{ margin: "0 0 8px" }}>
            {stageMessage(state.status, Boolean(state.sandboxId))}{" "}
            {state.progress.total > 0 && (
              <span>
                ({state.progress.completed}/{state.progress.total} steps · {pct}%)
              </span>
            )}
          </p>
          <div className="live__bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            {showIndeterminate ? (
              <div className="live__bar-fill live__bar-fill--indeterminate" />
            ) : (
              <div className="live__bar-fill" style={{ width: `${pct}%` }} />
            )}
          </div>
        </div>
      )}

      {state?.video && (
        <div className="live__panel" style={{ marginBottom: 16 }}>
          <div className="live__panel-header">
            <h3>Run Video</h3>
            <span className="muted">full run recording</span>
          </div>
          <video controls className="evidence__video-player" style={{ width: "100%" }}>
            <source src={`/${state.video}`} type={state.video.endsWith(".webm") ? "video/webm" : "video/mp4"} />
            Your browser does not support the video tag.
          </video>
        </div>
      )}

      {state && isE2B && (
        <div className="live__panel" style={{ marginBottom: 16 }}>
          <div className="live__panel-header">
            <h3>E2B Sandbox</h3>
            <span className="muted">status updates via polling</span>
          </div>
          <div className="live__meta" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            <div>
              <dt>Sandbox ID</dt>
              <dd className="table__mono">{state.sandboxId || "pending / not reported"}</dd>
            </div>
            <div>
              <dt>Template</dt>
              <dd className="table__mono">{state.template || "not reported"}</dd>
            </div>
            <div>
              <dt>Executor Status</dt>
              <dd><span className={statusBadge(state.status)}>{state.status}</span></dd>
            </div>
            <div>
              <dt>Artifacts</dt>
              <dd>
                {state.artifactsUrl ? (
                  <a href={state.artifactsUrl} target="_blank" rel="noreferrer">Open artifacts</a>
                ) : state.evidenceDir ? (
                  <span className="table__mono">{state.evidenceDir}</span>
                ) : (
                  <span className="muted">not available yet</span>
                )}
              </dd>
            </div>
          </div>
        </div>
      )}

      <div className="live__grid">
        <div className="live__panel">
          <div className="live__panel-header">
            <h3>Test Steps</h3>
            <span className="muted">{state?.steps.length ?? 0} steps</span>
          </div>
          <div className="live__steps">
            {state?.steps.map((step) => (
              <div key={step.id} className={`live__step ${state.currentStepId === step.id ? "live__step--current" : ""}`}>
                <div className="live__step-main">
                  <span className="plan__badge">{step.testCaseId}</span>
                  <div>
                    <p className="live__step-title">{step.title}</p>
                    {step.currentAction && <p className="live__step-action">{step.currentAction}</p>}
                  </div>
                </div>
                <div className="live__step-meta">
                  <span className={stepBadge(step.status)}>{step.status}</span>
                  {step.durationMs ? <span className="muted">{(step.durationMs / 1000).toFixed(1)}s</span> : null}
                </div>
              </div>
            ))}
            {!state && <p className="muted">No live state available yet.</p>}
            {state && state.steps.length === 0 && <p className="muted">No steps reported.</p>}
          </div>
        </div>

        <div className="live__panel">
          <div className="live__panel-header">
            <h3>Console / Harness Logs</h3>
            <span className="muted">{state?.logs.length ?? 0} entries</span>
          </div>
          <div className="live__logs">
            {state?.logs
              .slice()
              .reverse()
              .map((log) => (
                <div key={log.id} className={`live__log live__log--${log.level}`}>
                  <span className="live__log-ts">{log.ts}</span>
                  <span className="live__log-level">[{log.level}]</span>
                  <span className="live__log-msg">{log.message}</span>
                </div>
              ))}
            {!state && <p className="muted">Waiting for logs…</p>}
          </div>
        </div>
      </div>
    </section>
  );
}
