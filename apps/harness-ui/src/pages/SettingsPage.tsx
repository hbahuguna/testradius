import { useEffect, useMemo, useState } from "react";

import { getHarnessApi } from "../api";
import type { E2BValidationResult, ExecutorType, SystemExecutorConfig } from "../types";

const EXECUTORS: { value: ExecutorType; label: string; description: string }[] = [
  { value: "local", label: "Local (Playwright)", description: "Run browser tests locally using Playwright." },
  { value: "cloudroom", label: "Cloud Room", description: "Run tests via Cloud Room integration." },
  { value: "e2b", label: "E2B Sandbox", description: "Run compiled test plans in self-hosted/managed E2B sandboxes." },
];

function pickExecutor(cfg: SystemExecutorConfig | null): ExecutorType {
  const raw = (cfg?.executor_type || "local").toLowerCase();
  if (raw === "cloudroom" || raw === "e2b" || raw === "local") return raw;
  return "local";
}

export function SettingsPage(): JSX.Element {
  const api = getHarnessApi();
  const [system, setSystem] = useState<SystemExecutorConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedExecutor, setSelectedExecutor] = useState<ExecutorType>("local");
  const [e2bApiUrl, setE2bApiUrl] = useState("");
  const [e2bDomain, setE2bDomain] = useState("");
  const [e2bApiKey, setE2bApiKey] = useState("");
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<E2BValidationResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const cfg = await api.getSystemExecutor();
        if (cancelled) return;
        setSystem(cfg);
        setSelectedExecutor(pickExecutor(cfg));
        setE2bApiUrl(cfg.e2b_api_url || cfg.e2b_url || "");
        setE2bDomain(cfg.e2b_domain || "8.231.230.69.nip.io:3002");
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api]);

  const e2bStatus = useMemo(() => {
    if (validation) return validation.ok ? "Validated" : validation.configured ? "Configured (validation failed)" : "Not configured";
    if (system?.e2b_configured || system?.has_e2b_key) return "Configured via environment";
    return "Not configured";
  }, [system, validation]);

  const validateE2B = async () => {
    try {
      setValidating(true);
      setError(null);
      const result = await api.validateE2BConnection({
        api_key: e2bApiKey || undefined,
        api_url: e2bApiUrl || undefined,
        domain: e2bDomain || undefined,
      });
      setValidation(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setValidating(false);
    }
  };

  return (
    <section className="page">
      <div className="page__head">
        <div>
          <h2>Settings</h2>
          <p className="muted">
            Configure executor selection and validate E2B connectivity. Secrets should remain in environment variables (e.g.{" "}
            <code>E2B_API_KEY</code>, <code>GEMINI_API_KEY</code>) — never committed to the repo.
          </p>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Loading system configuration…</p>}

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Executor Selection</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Current system executor: <strong>{system?.executor_type ?? "unknown"}</strong>. Selection here is a UI preference for
          upcoming runs; backend execution mode is controlled by <code>EXECUTOR_TYPE</code>/<code>EXECUTOR</code> environment config.
        </p>
        <div style={{ display: "grid", gap: 8 }}>
          {EXECUTORS.map((opt) => (
            <label key={opt.value} className="card" style={{ display: "flex", gap: 12, alignItems: "flex-start", cursor: "pointer" }}>
              <input
                type="radio"
                name="executor"
                checked={selectedExecutor === opt.value}
                onChange={() => setSelectedExecutor(opt.value)}
                style={{ marginTop: 4 }}
              />
              <div>
                <div>
                  <strong>{opt.label}</strong> <span className="muted">({opt.value})</span>
                </div>
                <div className="muted">{opt.description}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>E2B Connection</h3>
          <span className={validation?.ok ? "pill pill--ok" : system?.e2b_configured || validation?.configured ? "pill pill--warn" : "pill pill--muted"}>
            {e2bStatus}
          </span>
        </div>
        <p className="muted">
          For self-hosted E2B (Embed/VM), configure <code>E2B_API_KEY</code>, <code>E2B_API_URL</code> (if applicable), and{" "}
          <code>E2B_DOMAIN</code> in the backend environment. Example self-hosted proxy domain: <code>8.231.230.69.nip.io:3002</code>.
        </p>

        <div style={{ display: "grid", gap: 10, maxWidth: 720 }}>
          <label>
            <div className="muted">E2B API URL (optional)</div>
            <input
              className="input"
              value={e2bApiUrl}
              onChange={(e) => setE2bApiUrl(e.target.value)}
              placeholder="https://... or leave blank to use environment/default"
              style={{ width: "100%" }}
            />
          </label>
          <label>
            <div className="muted">E2B Domain / Sandbox Proxy (self-hosted)</div>
            <input
              className="input"
              value={e2bDomain}
              onChange={(e) => setE2bDomain(e.target.value)}
              placeholder="8.231.230.69.nip.io:3002"
              style={{ width: "100%" }}
            />
          </label>
          <label>
            <div className="muted">E2B API Key (validation only — not persisted)</div>
            <input
              className="input"
              type="password"
              value={e2bApiKey}
              onChange={(e) => setE2bApiKey(e.target.value)}
              placeholder="Paste key only for validation; prefer E2B_API_KEY env var"
              autoComplete="off"
              style={{ width: "100%" }}
            />
          </label>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn" onClick={validateE2B} disabled={validating}>
              {validating ? "Validating…" : "Validate E2B Connection"}
            </button>
            <span className="muted">Validation does not create sandboxes and does not store secrets.</span>
          </div>
        </div>

        {validation && (
          <div className="card" style={{ marginTop: 12, background: "var(--panel, #111)" }}>
            <p style={{ marginTop: 0 }}>
              <strong>Result:</strong> {validation.ok ? "Connection/config looks valid" : "Validation incomplete/failed"}
            </p>
            {validation.message && <p className="muted">{validation.message}</p>}
            {validation.warning && <p className="muted">{validation.warning}</p>}
            {validation.checks && validation.checks.length > 0 && (
              <ul style={{ marginBottom: 0 }}>
                {validation.checks.map((c) => (
                  <li key={`${c.name}-${c.detail ?? ""}`}>
                    <code>{c.name}</code>: {c.ok ? "ok" : "failed"}
                    {c.detail ? ` — ${c.detail}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>System Status</h3>
        <pre className="table__mono" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
          {JSON.stringify(system ?? { loading: true }, null, 2)}
        </pre>
      </div>
    </section>
  );
}
