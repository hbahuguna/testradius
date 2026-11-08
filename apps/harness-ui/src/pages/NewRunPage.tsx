import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { getHarnessApi } from "../api";
import type {
  CompilePlanResult,
  JiraFetchResult,
  RunSummary,
  SystemIntegrations,
} from "../types";
import {
  DEFAULT_MODEL,
  GEMINI_MODELS,
  toCreateRunInput,
  validateNewRun,
  type NewRunErrors,
  type NewRunFormValues,
} from "../lib/validation";

const INITIAL: NewRunFormValues = {
  target: "",
  goal: "",
  context: "",
  model: DEFAULT_MODEL,
};

type CuStep = "jira" | "compile" | "run";

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((v) => String(v)) : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stepPill(active: boolean, done: boolean, label: string) {
  return (
    <span className={`pill ${active ? "pill--ok" : done ? "pill--ok" : "pill--muted"}`}>{label}</span>
  );
}

export function NewRunPage(): JSX.Element {
  const api = getHarnessApi();
  const [values, setValues] = useState<NewRunFormValues>(INITIAL);
  const [errors, setErrors] = useState<NewRunErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [created, setCreated] = useState<RunSummary | null>(null);

  // ---- Computer-use E2E wizard (Jira -> compile -> E2B/Gemini CU) ----
  const [step, setStep] = useState<CuStep>("jira");
  const [integrations, setIntegrations] = useState<SystemIntegrations | null>(null);
  const [jiraUrl, setJiraUrl] = useState("https://testsquadai.atlassian.net");
  const [issueKey, setIssueKey] = useState("KAN-1");
  const [jiraEmail, setJiraEmail] = useState("");
  const [jiraToken, setJiraToken] = useState("");
  const [jiraPat, setJiraPat] = useState("");
  const [targetUrl, setTargetUrl] = useState("https://testradius.dev");
  const [mode, setMode] = useState("local_spike");
  const [live, setLive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [cuError, setCuError] = useState<string | null>(null);
  const [jiraResult, setJiraResult] = useState<JiraFetchResult | null>(null);
  const [compileResult, setCompileResult] = useState<CompilePlanResult | null>(null);
  const [startedRunId, setStartedRunId] = useState<string | null>(null);

  useEffect(() => {
    if (api.mode !== "http") return;
    api
      .getSystemIntegrations()
      .then((r) => {
        setIntegrations(r);
        if (r.jira_site) setJiraUrl(r.jira_site);
      })
      .catch(() => {
        setIntegrations(null);
      });
  }, [api]);

  const set = (field: keyof NewRunFormValues) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
  ) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    const validation = validateNewRun(values);
    setErrors(validation);
    if (Object.keys(validation).length > 0) return;

    setSubmitting(true);
    try {
      const run = await api.createRun(toCreateRunInput(values));
      setCreated(run);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const fetchJira = async () => {
    setCuError(null);
    setBusy(true);
    try {
      const res = await api.fetchJiraContext({
        jira_url: jiraUrl.trim(),
        issue_key: issueKey.trim(),
        email: jiraEmail.trim() || undefined,
        api_token: jiraToken.trim() || undefined,
        pat: jiraPat.trim() || undefined,
        save: true,
      });
      setJiraResult(res);
      setCompileResult(null);
      setStartedRunId(null);
      setStep("compile");
    } catch (err) {
      setCuError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const compile = async () => {
    if (!jiraResult) return;
    setCuError(null);
    setBusy(true);
    try {
      const res = await api.compileTestPlan({
        context_bundle: jiraResult.context_bundle,
        sut: {
          base_url: targetUrl.trim(),
          environment: "staging",
          browser: "chromium",
          viewport: { width: 1440, height: 900 },
        },
        mode,
        save: true,
      });
      if (!res.ok && !res.compiled_plan) {
        const validation = asRecord(res.validation);
        const issues = stringList(validation.issues ?? res.error);
        setCuError(
          `Compile failed (${res.error ?? "validation"}). ${issues.length ? `Issues: ${issues.join("; ")}` : ""}`.trim(),
        );
      }
      setCompileResult(res);
      if (res.compiled_plan) setStep("run");
    } catch (err) {
      setCuError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const startRun = async () => {
    if (!compileResult?.compiled_plan) return;
    setCuError(null);
    setBusy(true);
    try {
      const res = await api.startComputerUseRun({
        compiled_plan: compileResult.compiled_plan,
        target_url: targetUrl.trim(),
        mode,
        loop: "per_step",
        live,
      });
      setStartedRunId(res.id);
      window.location.hash = `#/live/${res.id}`;
    } catch (err) {
      setCuError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (created) {
    return (
      <section className="page">
        <div className="notice notice--ok">
          <h2>Run created</h2>
          <p>
            The harness will generate a test plan for{" "}
            <strong>{created.target}</strong>. The plan-review checkpoint
            (approval before execution) arrives in STORY-H002.2.
          </p>
          <dl className="notice__meta">
            <div>
              <dt>Run ID</dt>
              <dd className="table__mono">{created.id}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <span className="pill pill--warn">{created.status}</span>
              </dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd className="table__mono">{created.createdAt ?? "—"}</dd>
            </div>
          </dl>
          <div className="notice__actions">
            <a className="btn" href="#/runs">
              View in Runs
            </a>
            <button
              className="btn btn--ghost"
              onClick={() => {
                setCreated(null);
                setValues(INITIAL);
              }}
            >
              Start another run
            </button>
          </div>
        </div>
      </section>
    );
  }

  const bundle = jiraResult ? asRecord(jiraResult.context_bundle) : {};
  const acs = stringList(bundle.acceptance_criteria);
  const plan = compileResult?.compiled_plan ? asRecord(compileResult.compiled_plan) : null;
  const cases = plan && Array.isArray(plan.cases) ? plan.cases : [];
  const validation = compileResult ? asRecord(compileResult.validation) : null;

  return (
    <section className="page">
      <div className="page__head">
        <div>
          <h2>New Manual QA Run</h2>
          <p className="muted">
            Full E2E from the UI: Jira context → Gemini test-plan compile → E2B sandbox +
            Gemini computer-use. No backend commands needed once the API is running.
          </p>
        </div>
        <span className={`pill ${api.mode === "http" ? "pill--ok" : "pill--warn"}`}>
          {api.mode === "http" ? "live backend" : "mock data"}
        </span>
      </div>

      {api.mode !== "http" && (
        <div className="notice">
          <p>
            This UI is in <strong>mock data</strong> mode. To run the live E2E flow, start the
            UI with <code>VITE_USE_MOCKS=0</code> and point the proxy at the running harness
            API, then reload this page.
          </p>
        </div>
      )}

      {api.mode === "http" && (
        <div className="notice">
          <dl className="notice__meta">
            <div>
              <dt>Jira</dt>
              <dd>{integrations ? (integrations.jira_configured ? "Configured (backend env)" : "Not configured") : "Checking…"}</dd>
            </div>
            <div>
              <dt>Gemini</dt>
              <dd>
                {integrations
                  ? integrations.gemini_configured
                    ? `Configured (${integrations.gemini_model || "default model"})`
                    : "Not configured"
                  : "Checking…"}
              </dd>
            </div>
            <div>
              <dt>E2B</dt>
              <dd>
                {integrations
                  ? integrations.e2b_configured
                    ? `Configured (${integrations.e2b_template || "desktop-chromium"})`
                    : "Not configured"
                  : "Checking…"}
              </dd>
            </div>
          </dl>
          <p className="muted">
            Secrets stay in the backend environment (<code>JIRA_API_TOKEN</code>/
            <code>JIRA_PAT</code>, <code>GEMINI_API_KEY</code>, <code>E2B_API_KEY</code>). They
            are never displayed or stored from this form.
          </p>
        </div>
      )}

      <div className="page__head-actions" style={{ margin: "16px 0" }}>
        {stepPill(step === "jira", step !== "jira", "1. Jira context")}
        {stepPill(step === "compile", step === "run" || step === "compile", "2. Compile plan")}
        {stepPill(step === "run", false, "3. Execute in sandbox")}
      </div>

      {cuError && <p className="error">{cuError}</p>}

      <fieldset disabled={busy || api.mode !== "http"} style={{ border: 0, padding: 0, margin: 0 }}>
        <form className="form" onSubmit={(e) => { e.preventDefault(); void fetchJira(); }}>
          <div className="form__field">
            <label htmlFor="jira-url">Jira site</label>
            <input id="jira-url" type="url" value={jiraUrl} onChange={(e) => setJiraUrl(e.target.value)} placeholder="https://testsquadai.atlassian.net" />
            <p className="form__hint">Backend uses <code>JIRA_SITE</code> if left blank here.</p>
          </div>
          <div className="form__field">
            <label htmlFor="issue-key">Jira issue key</label>
            <input id="issue-key" type="text" value={issueKey} onChange={(e) => setIssueKey(e.target.value)} placeholder="KAN-1" />
          </div>
          <div className="form__field">
            <label htmlFor="jira-email">Jira email (optional)</label>
            <input id="jira-email" type="email" value={jiraEmail} onChange={(e) => setJiraEmail(e.target.value)} placeholder="you@example.com" autoComplete="off" />
            <p className="form__hint">Only needed when the backend has no <code>JIRA_EMAIL</code>. Used for this fetch only.</p>
          </div>
          <div className="form__field">
            <label htmlFor="jira-token">Jira API token (optional)</label>
            <input id="jira-token" type="password" value={jiraToken} onChange={(e) => setJiraToken(e.target.value)} autoComplete="off" placeholder="Transient — used for this fetch only, never stored" />
          </div>
          <div className="form__field">
            <label htmlFor="jira-pat">Jira PAT (optional, Server/DC)</label>
            <input id="jira-pat" type="password" value={jiraPat} onChange={(e) => setJiraPat(e.target.value)} autoComplete="off" placeholder="Transient — used for this fetch only, never stored" />
          </div>
          <div className="form__field">
            <label htmlFor="cu-target">Target SUT URL</label>
            <input id="cu-target" type="url" value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} placeholder="https://testradius.dev" />
          </div>
          <div className="form__actions">
            <button className="btn" type="submit" disabled={busy || step !== "jira"}>
              {busy && step === "jira" ? "Fetching Jira…" : "Fetch Jira context"}
            </button>
            {jiraResult && (
              <span className="pill pill--ok">
                {jiraResult.issue_key}: {acs.length || jiraResult.acceptance_criteria_count || 0} AC(s) fetched
              </span>
            )}
          </div>
        </form>

        {jiraResult && (
          <div className="notice" style={{ marginTop: 16 }}>
            <h3>Normalized context</h3>
            <dl className="notice__meta">
              <div><dt>Ticket</dt><dd className="table__mono">{String(bundle.ticket_id ?? jiraResult.issue_key)}</dd></div>
              <div><dt>Title</dt><dd>{String(bundle.title ?? "—")}</dd></div>
              <div><dt>ACs</dt><dd>{acs.length}</dd></div>
              <div><dt>Saved</dt><dd className="table__mono">{jiraResult.saved ?? "—"}</dd></div>
            </dl>
            {acs.length > 0 && (
              <ul>
                {acs.map((a, i) => (<li key={i}>{a}</li>))}
              </ul>
            )}
          </div>
        )}

        <form className="form" style={{ marginTop: 24 }} onSubmit={(e) => { e.preventDefault(); void compile(); }}>
          <div className="form__field">
            <label htmlFor="cu-mode">Compile mode</label>
            <select id="cu-mode" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="local_spike">local_spike (spike)</option>
              <option value="production">production</option>
            </select>
          </div>
          <div className="form__actions">
            <button className="btn" type="submit" disabled={busy || !jiraResult || step === "run"}>
              {busy && step === "compile" ? "Compiling with Gemini…" : "Compile test plan"}
            </button>
            {compileResult && (
              <span className={`pill ${compileResult.ok ? "pill--ok" : "pill--warn"}`}>
                {compileResult.ok ? "plan compiled" : "compile failed"}
              </span>
            )}
          </div>
        </form>

        {plan && (
          <div className="notice" style={{ marginTop: 16 }}>
            <h3>Compiled plan</h3>
            <dl className="notice__meta">
              <div><dt>Plan ID</dt><dd className="table__mono">{String(plan.plan_id ?? "—")}</dd></div>
              <div><dt>Title</dt><dd>{String(plan.title ?? "—")}</dd></div>
              <div><dt>Cases</dt><dd>{cases.length}</dd></div>
              <div><dt>Validation</dt><dd>{validation ? (validation.ok === false ? "failed" : "ok") : "—"}{compileResult?.artifact_path ? ` · ${compileResult.artifact_path}` : ""}</dd></div>
            </dl>
            {cases.map((c, ci) => {
              const rec = asRecord(c);
              const steps = Array.isArray(rec.steps) ? rec.steps : [];
              return (
                <div key={ci} className="plan__row">
                  <p className="plan__row-title">{String(rec.case_id ?? `Case ${ci + 1}`)} — {String(rec.title ?? "")}</p>
                  <ol>
                    {steps.map((s, si) => {
                      const sr = asRecord(s);
                      return <li key={si}>{String(sr.step_id ?? `S${si + 1}`)}: {String(sr.intent ?? sr.action_type ?? "")} <span className="muted">({String(sr.action_type ?? "")})</span></li>;
                    })}
                  </ol>
                </div>
              );
            })}
          </div>
        )}

        <form className="form" style={{ marginTop: 24 }} onSubmit={(e) => { e.preventDefault(); void startRun(); }}>
          <div className="form__field">
            <label>
              <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />{" "}
              Live execution (real E2B + Gemini). Uncheck for mock sandbox.
            </label>
            <p className="form__hint">
              Requires backend env: <code>E2B_API_KEY</code>, <code>GEMINI_API_KEY</code>/
              <code>GOOGLE_API_KEY</code>, <code>E2B_API_URL</code>, <code>E2B_DOMAIN</code>,
              <code>E2B_DESKTOP_TEMPLATE=desktop-chromium</code>, <code>E2B_SECURE=false</code>.
            </p>
          </div>
          <div className="form__actions">
            <button className="btn" type="submit" disabled={busy || !plan}>
              {busy && step === "run" ? "Starting…" : "Start computer-use run"}
            </button>
            {startedRunId && (
              <a className="btn btn--ghost" href={`#/live/${startedRunId}`}>Open live run {startedRunId}</a>
            )}
          </div>
        </form>
      </fieldset>

      <hr style={{ margin: "32px 0", borderColor: "rgba(148,163,184,.25)" }} />
      <h2>Legacy run (plan-review flow)</h2>
      <p className="muted">The original lightweight flow below still works, but the E2E computer-use flow above is the recommended path.</p>
      <form className="form" onSubmit={onSubmit} noValidate>
        <div className="form__field">
          <label htmlFor="target">Target URL</label>
          <input
            id="target"
            type="url"
            placeholder="https://testradius.dev"
            value={values.target}
            onChange={set("target")}
            aria-invalid={Boolean(errors.target)}
          />
          {errors.target && <p className="form__error">{errors.target}</p>}
          <p className="form__hint">The site the sandboxed browser will drive.</p>
        </div>

        <div className="form__field">
          <label htmlFor="goal">Goal</label>
          <textarea
            id="goal"
            rows={3}
            placeholder="Verify homepage, navigation, CTAs, and responsive layout"
            value={values.goal}
            onChange={set("goal")}
            aria-invalid={Boolean(errors.goal)}
          />
          {errors.goal && <p className="form__error">{errors.goal}</p>}
          <p className="form__hint">What should this run verify? The planner turns this into test cases.</p>
        </div>

        <div className="form__field">
          <label htmlFor="context">
            Context <span className="form__optional">(optional)</span>
          </label>
          <input
            id="context"
            type="text"
            placeholder="T-1 or samples/context_sample.json"
            value={values.context}
            onChange={set("context")}
          />
          <p className="form__hint">Ticket ID or context bundle with ACs, Figma links, prior bugs.</p>
        </div>

        <div className="form__field">
          <label htmlFor="model">Gemini model</label>
          <select id="model" value={values.model} onChange={set("model")}>
            {GEMINI_MODELS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          {errors.model && <p className="form__error">{errors.model}</p>}
          <p className="form__hint">Used for plan generation. API key stays in GEMINI_API_KEY — never here.</p>
        </div>

        {submitError && <p className="error">Failed to create run: {submitError}</p>}

        <div className="form__actions">
          <button className="btn" type="submit" disabled={submitting}>
            {submitting ? "Creating…" : "Create run"}
          </button>
          <span className={`pill ${api.mode === "http" ? "pill--ok" : "pill--warn"}`}>
            {api.mode === "http" ? "live" : "mock"} submit
          </span>
        </div>
      </form>
    </section>
  );
}
