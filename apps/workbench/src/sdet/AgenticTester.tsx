import { useState, useCallback } from "react";
import type { RecordedAction, ContextElement } from "./types";

interface AgenticTesterProps {
  apiBase: string;
  url: string;
  repoDir: string;
  recordedActions?: RecordedAction[];
  contextElements?: ContextElement[];
}

interface ExecuteStep {
  step: number;
  action: string;
  target: string;
  kind?: string;
  value?: string;
  ok: boolean;
  thought?: string;
  url?: string;
  interactive_elements?: unknown[];
  duration_ms?: number;
  timestamp?: string;
}

interface ExecuteAssertion {
  type: string;
  description?: string;
  passed?: boolean;
  detail?: string;
}

interface ExecuteResult {
  success: boolean;
  goal_reached?: boolean;
  error?: string;
  trace?: {
    goal: string;
    url: string;
    backend: string;
    goal_reached?: boolean;
    final_url?: string;
    total_duration_ms?: number;
    token_estimate?: number;
    steps: ExecuteStep[];
    assertions: ExecuteAssertion[];
  };
}

interface HealResult {
  success: boolean;
  original_code?: string;
  healed_code?: string;
  changed_locators?: string[];
  verification?: { passed?: boolean; error?: string; detail?: string };
  error?: string;
}

function parseAssertions(raw: string): { type: string; expected: string; target?: string }[] {
  return raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf(":");
      if (idx === -1) return { type: "visibility", expected: line, target: line };
      const type = line.slice(0, idx).trim().toLowerCase();
      const expected = line.slice(idx + 1).trim();
      return { type, expected, target: type === "visibility" ? expected : undefined };
    });
}

export default function AgenticTester({ apiBase, url, repoDir, recordedActions, contextElements }: AgenticTesterProps) {
  const [goal, setGoal] = useState("");
  const [targetUrl, setTargetUrl] = useState(url);
  const [assertionsText, setAssertionsText] = useState("visibility:Applying For");
  const [backend, setBackend] = useState("mcp");
  const [maxTurns, setMaxTurns] = useState(30);
  const [headless, setHeadless] = useState(true);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [healPath, setHealPath] = useState("");
  const [healError, setHealError] = useState("");
  const [healing, setHealing] = useState(false);
  const [healResult, setHealResult] = useState<HealResult | null>(null);
  const [healReqError, setHealReqError] = useState<string | null>(null);

  const [testPath, setTestPath] = useState("tests/e2e/test_session.ts");
  const [genRunning, setGenRunning] = useState(false);
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  const runExecute = useCallback(async () => {
    if (!goal.trim() || !targetUrl.trim()) {
      setError("Goal and URL are required.");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const resp = await fetch(`${apiBase}/api/workbench/agentic/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal: goal.trim(),
          url: targetUrl.trim(),
          backend,
          headless,
          max_turns: maxTurns,
          assertions: parseAssertions(assertionsText),
        }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 300)}`);
      }
      setResult((await resp.json()) as ExecuteResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }, [apiBase, goal, targetUrl, backend, headless, maxTurns, assertionsText]);

  const runHeal = useCallback(async () => {
    if (!healPath.trim()) {
      setHealReqError("Test path is required.");
      return;
    }
    setHealing(true);
    setHealReqError(null);
    setHealResult(null);
    try {
      const resp = await fetch(`${apiBase}/api/workbench/agentic/heal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          test_path: healPath.trim(),
          error_output: healError,
          url: targetUrl.trim(),
          backend,
          headless,
        }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 300)}`);
      }
      setHealResult((await resp.json()) as HealResult);
    } catch (e) {
      setHealReqError(e instanceof Error ? e.message : String(e));
    } finally {
      setHealing(false);
    }
  }, [apiBase, healPath, healError, targetUrl, backend, headless]);

  const buildScenario = useCallback((): string => {
    const parts = [goal.trim() || "(no goal provided)"];
    if (recordedActions && recordedActions.length) {
      parts.push("\nRecorded actions:");
      for (const a of recordedActions) {
        parts.push(`- ${a.action_type} ${a.tag} "${a.text || ""}"${a.value ? ` = ${a.value}` : ""}`);
      }
    }
    if (contextElements && contextElements.length) {
      parts.push("\nSelected elements:");
      for (const e of contextElements) {
        parts.push(`- ${e.tag} "${e.text || ""}" (${e.cssPath})`);
      }
    }
    return parts.join("\n");
  }, [goal, recordedActions, contextElements]);

  const runGenerateRun = useCallback(async () => {
    if (!goal.trim() || !targetUrl.trim()) {
      setGenError("Goal and URL are required.");
      return;
    }
    setGenRunning(true);
    setGenError(null);
    setGeneratedCode(null);
    setResult(null);
    setHealResult(null);
    try {
      const resp = await fetch(`${apiBase}/api/workbench/agentic/generate-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario: buildScenario(),
          url: targetUrl.trim(),
          goal: goal.trim(),
          assertions: parseAssertions(assertionsText),
          repo_dir: repoDir,
          test_path: testPath.trim(),
          backend,
          headless,
          max_turns: maxTurns,
        }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 300)}`);
      }
      const data = (await resp.json()) as {
        generated_code: string | null;
        generate_error: string | null;
        execute: ExecuteResult | null;
        heal: HealResult | null;
      };
      setGeneratedCode(data.generated_code);
      setGenError(data.generate_error);
      setResult(data.execute);
      setHealResult(data.heal);
    } catch (e) {
      setGenError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenRunning(false);
    }
  }, [apiBase, goal, targetUrl, assertionsText, repoDir, testPath, backend, headless, maxTurns, buildScenario]);

  return (
    <div className="agentic-tester">
      <div className="panel-header">
        <span>Agentic Tester</span>
        <span className="count">goal-driven live-browser tests</span>
      </div>

      <div className="agentic-form">
        <label className="field">
          <span>Goal</span>
          <textarea
            className="url-bar"
            rows={2}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Open the job application form and verify the role dropdown is visible"
          />
        </label>

        <label className="field">
          <span>URL</span>
          <input
            className="url-bar"
            type="text"
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            placeholder="https://testradius.dev/jobs"
          />
        </label>

        <label className="field">
          <span>Assertions (one per line: type:expected)</span>
          <textarea
            className="url-bar"
            rows={2}
            value={assertionsText}
            onChange={(e) => setAssertionsText(e.target.value)}
            placeholder="visibility:Applying For"
          />
        </label>

        <div className="field-row">
          <label className="field">
            <span>Backend</span>
            <select
              className="url-bar"
              value={backend}
              onChange={(e) => setBackend(e.target.value)}
            >
              <option value="mcp">mcp</option>
              <option value="cli">cli</option>
            </select>
          </label>
          <label className="field">
            <span>Max turns</span>
            <input
              className="url-bar"
              type="number"
              value={maxTurns}
              onChange={(e) => setMaxTurns(Number(e.target.value) || 30)}
            />
          </label>
          <label className="field checkbox">
            <input
              type="checkbox"
              checked={headless}
              onChange={(e) => setHeadless(e.target.checked)}
            />
            <span>Headless</span>
          </label>
        </div>

        <button className="go-btn" onClick={runExecute} disabled={running}>
          {running ? "Running..." : "Run Agentic Test"}
        </button>
        {error && <div className="error-bar">{error}</div>}

        <div className="gen-run">
          <label className="field">
            <span>Test path (artifact)</span>
            <input
              className="url-bar"
              type="text"
              value={testPath}
              onChange={(e) => setTestPath(e.target.value)}
              placeholder="tests/e2e/test_session.ts"
            />
          </label>
          <button className="go-btn primary" onClick={runGenerateRun} disabled={genRunning}>
            {genRunning ? "Generating + Running..." : "Generate + Run"}
          </button>
          {genError && <div className="error-bar">{genError}</div>}
        </div>
      </div>

      {generatedCode && (
        <div className="agentic-result">
          <div className="panel-header"><span>Generated Spec</span></div>
          <pre className="code-block">{generatedCode}</pre>
        </div>
      )}

      {result && (
        <div className="agentic-result">
          <div className={`badge ${result.success ? "ok" : "fail"}`}>
            {result.success ? "SUCCESS" : "FAILED"}
            {result.trace?.goal_reached !== undefined &&
              ` · goal reached: ${result.trace.goal_reached ? "yes" : "no"}`}
          </div>
          {result.error && <div className="error-bar">{result.error}</div>}

          {result.trace && (
            <>
              <div className="trace-meta">
                <span>{result.trace.url}</span>
                {result.trace.final_url && result.trace.final_url !== result.trace.url && (
                  <span> → {result.trace.final_url}</span>
                )}
                {result.trace.total_duration_ms != null && (
                  <span> · {(result.trace.total_duration_ms / 1000).toFixed(1)}s</span>
                )}
              </div>

              {result.trace.assertions?.length > 0 && (
                <div className="assertions">
                  <h4>Assertions</h4>
                  {result.trace.assertions.map((a, i) => (
                    <div key={i} className={`assert ${a.passed ? "ok" : "fail"}`}>
                      <span>{a.type}</span>
                      <span>{a.description || ""}</span>
                      <span>{a.passed ? "PASS" : "FAIL"}</span>
                      {a.detail && <span className="detail">{a.detail}</span>}
                    </div>
                  ))}
                </div>
              )}

              <details className="steps">
                <summary>{result.trace.steps?.length || 0} steps</summary>
                {result.trace.steps?.map((s) => (
                  <div key={s.step} className={`step ${s.ok ? "ok" : "fail"}`}>
                    <span className="step-n">#{s.step}</span>
                    <span className="step-act">{s.action}</span>
                    <span className="step-tgt">{s.target}</span>
                    {s.value && <span className="step-val">= {s.value}</span>}
                    <span className="step-ok">{s.ok ? "ok" : "fail"}</span>
                    {s.thought && <div className="step-thought">{s.thought}</div>}
                  </div>
                ))}
              </details>
            </>
          )}
        </div>
      )}

      <div className="panel-header heal-header">
        <span>Self-Heal Test</span>
      </div>
      <div className="agentic-form">
        <label className="field">
          <span>Test path</span>
          <input
            className="url-bar"
            type="text"
            value={healPath}
            onChange={(e) => setHealPath(e.target.value)}
            placeholder="tests/example.spec.ts"
          />
        </label>
        <label className="field">
          <span>Error output</span>
          <textarea
            className="url-bar"
            rows={3}
            value={healError}
            onChange={(e) => setHealError(e.target.value)}
            placeholder="Paste the failing test output here (optional)"
          />
        </label>
        <button className="go-btn" onClick={runHeal} disabled={healing}>
          {healing ? "Healing..." : "Heal Test"}
        </button>
        {healReqError && <div className="error-bar">{healReqError}</div>}

        {healResult && (
          <div className="agentic-result">
            <div className={`badge ${healResult.success ? "ok" : "fail"}`}>
              {healResult.success ? "HEALED" : "HEAL FAILED"}
            </div>
            {healResult.error && <div className="error-bar">{healResult.error}</div>}
            {healResult.changed_locators && healResult.changed_locators.length > 0 && (
              <div className="changed">
                Changed: {healResult.changed_locators.join(", ")}
              </div>
            )}
            {healResult.healed_code && (
              <pre className="code-block">{healResult.healed_code}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
