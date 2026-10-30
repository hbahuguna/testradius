import { useState } from "react";
import type { FormEvent } from "react";

import { getHarnessApi } from "../api";
import type { RunSummary } from "../types";
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

export function NewRunPage(): JSX.Element {
  const api = getHarnessApi();
  const [values, setValues] = useState<NewRunFormValues>(INITIAL);
  const [errors, setErrors] = useState<NewRunErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [created, setCreated] = useState<RunSummary | null>(null);

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

  return (
    <section className="page">
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
