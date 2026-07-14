import { useState, useCallback, useRef, useEffect } from "react";
import type { RecordedAction, ContextElement } from "./types";
import { streamExecuteAgentic } from "./agenticApi";
import type { AgenticStreamEvent, ExecuteResult, HealResult, GenerateRunResult, GenerateAgenticResult } from "./agenticApi";
import TicketIntegration from "./TicketIntegration";

interface AgenticTesterProps {
  apiBase: string;
  url: string;
  repoDir: string;
  recordedActions?: RecordedAction[];
  contextElements?: ContextElement[];
}

function parseAssertions(raw: string): { type: string; expected: string; target?: string; pattern?: string }[] {
  return raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      // "url matches playwright" / "url contains X" / "url is X"
      const urlMatch = line.match(/^url\s+(matches|contains|is|equals|=)\s+(.+)$/i);
      if (urlMatch) {
        const v = urlMatch[2].trim();
        return { type: "url", pattern: v, expected: v };
      }
      // "text: X" / "contains X" / "has text X"
      const textMatch = line.match(/^(?:text|contains|has\s+text)\s*:?\s*(.+)$/i);
      if (textMatch) {
        const v = textMatch[1].trim();
        return { type: "text", expected: v, target: v };
      }
      const idx = line.indexOf(":");
      if (idx === -1) return { type: "visibility", expected: line, target: line };
      const type = line.slice(0, idx).trim().toLowerCase();
      const expected = line.slice(idx + 1).trim();
      if (type === "url") return { type: "url", pattern: expected, expected };
      if (type === "text" || type === "contains") return { type: "text", expected, target: expected };
      return { type, expected, target: type === "visibility" ? expected : undefined };
    });
}

export default function AgenticTester({ apiBase, url, repoDir, recordedActions, contextElements }: AgenticTesterProps) {
  const [goal, setGoal] = useState("");
  const [targetUrl, setTargetUrl] = useState(url);
  const [showJira, setShowJira] = useState(false);
  const [jiraSessionId] = useState(() => crypto.randomUUID());
  const [assertionsText, setAssertionsText] = useState("visibility:Applying For");
  const [backend, setBackend] = useState("mcp");
  const [maxTurns, setMaxTurns] = useState(30);
  const [headless, setHeadless] = useState(true);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Live streaming state (real-time LLM reasoning + actions)
  const [phase, setPhase] = useState<string>("");
  const [reasoning, setReasoning] = useState<string>("");
  const [liveSteps, setLiveSteps] = useState<Array<{ name: string; args?: any; ok?: boolean; result?: string }>>([]);
  const [liveError, setLiveError] = useState<string | null>(null);
  const reasoningRef = useRef<HTMLDivElement | null>(null);

  const [healPath, setHealPath] = useState("");
  const [healError, setHealError] = useState("");
  const [healing, setHealing] = useState(false);
  const [healResult, setHealResult] = useState<HealResult | null>(null);
  const [healReqError, setHealReqError] = useState<string | null>(null);

  const [testPath, setTestPath] = useState("tests/e2e/test_session.ts");
  const [genRunning, setGenRunning] = useState(false);
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  const [genAgenticRunning, setGenAgenticRunning] = useState(false);
  const [genAgentic, setGenAgentic] = useState<GenerateAgenticResult | null>(null);
  const [genAgenticError, setGenAgenticError] = useState<string | null>(null);

  const runExecute = useCallback(async () => {
    if (!goal.trim() || !targetUrl.trim()) {
      setError("Goal and URL are required.");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    setGeneratedCode(null);
    setReasoning("");
    setLiveSteps([]);
    setPhase("starting");
    setLiveError(null);
    try {
      await streamExecuteAgentic(
        apiBase,
        {
          goal: goal.trim(),
          url: targetUrl.trim(),
          backend,
          headless,
          max_turns: maxTurns,
          assertions: parseAssertions(assertionsText),
        },
        (ev: AgenticStreamEvent) => {
          switch (ev.event) {
            case "node":
              setPhase((ev.name as string) || ev.phase || "running");
              break;
            case "thinking_delta":
              setReasoning((r) => r + (ev.text || ""));
              break;
            case "tool_call":
              setLiveSteps((s) => [...s, { name: ev.name, args: ev.arguments, ok: undefined }]);
              break;
            case "tool_result": {
              setLiveSteps((s) => {
                const next = [...s];
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].name === ev.name && next[i].ok === undefined) {
                    next[i] = { ...next[i], ok: ev.ok, result: ev.result ?? ev.error };
                    break;
                  }
                }
                return next;
              });
              break;
            }
            case "done":
              setResult({
                success: !!ev.success,
                goal_reached: ev.goal_reached,
                error: ev.error,
                generated_code: ev.generated_code ?? null,
                trace: ev.trace,
              } as ExecuteResult);
              if (ev.generated_code) setGeneratedCode(ev.generated_code);
              setPhase("done");
              break;
            case "error":
              setLiveError((ev.message as string) || "unknown error");
              setPhase("error");
              break;
          }
        }
      );
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
      const data = (await resp.json()) as GenerateRunResult;
      setGeneratedCode(data.generated_code ?? null);
      setGenError(data.generate_error ?? null);
      setResult(data.execute ?? null);
      setHealResult(data.heal ?? null);
    } catch (e) {
      setGenError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenRunning(false);
    }
  }, [apiBase, goal, targetUrl, assertionsText, repoDir, testPath, backend, headless, maxTurns, buildScenario]);

    const runGenerateAgentic = useCallback(async () => {
      if (!goal.trim() || !targetUrl.trim()) {
        setGenAgenticError("Goal and URL are required.");
        return;
      }
      setGenAgenticRunning(true);
      setGenAgenticError(null);
      setGenAgentic(null);
      setGeneratedCode(null);
      setResult(null);
      setHealResult(null);
      try {
        const resp = await fetch(`${apiBase}/api/workbench/agentic/generate-agentic`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            goal: goal.trim(),
            url: targetUrl.trim(),
            repo_dir: repoDir,
            test_path: testPath.trim(),
            starting_url: "",
            backend,
            headless,
            max_explore_turns: 8,
            max_attempts: 5,
          }),
        });
        if (!resp.ok) {
          const detail = await resp.text();
          throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 300)}`);
        }
        const data = (await resp.json()) as GenerateAgenticResult;
        setGenAgentic(data);
        setGenAgenticError(data.generate_error ?? null);
        setGeneratedCode(data.generated_code ?? null);
        setResult(data.execute ?? null);
        setHealResult(data.heal ?? null);
      } catch (e) {
        setGenAgenticError(e instanceof Error ? e.message : String(e));
      } finally {
        setGenAgenticRunning(false);
      }
    }, [apiBase, goal, targetUrl, repoDir, testPath, backend, headless]);

    // Keep the live reasoning feed pinned to the latest tokens.
    useEffect(() => {
      if (reasoningRef.current) {
        reasoningRef.current.scrollTop = reasoningRef.current.scrollHeight;
      }
    }, [reasoning]);

    return (
    <div className="agentic-tester">
      <div className="panel-header">
        <span>Agentic Tester</span>
        <span className="count">goal-driven live-browser tests</span>
      </div>

      <div className="agentic-form">
        <label className="field">
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            Goal
            <button
              className="go-btn"
              style={{ fontSize: 11, padding: "2px 8px", marginLeft: 4 }}
              onClick={() => setShowJira(!showJira)}
              type="button"
            >
              {showJira ? "Close Jira" : "Import from Jira"}
            </button>
          </span>
          <textarea
            className="url-bar"
            rows={2}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Open the job application form and verify the role dropdown is visible"
          />
        </label>

        {showJira && (
          <div style={{ marginBottom: 12 }}>
            <TicketIntegration
              apiBase={apiBase}
              sessionId={jiraSessionId}
              onSelectTicket={(ticketContext) => {
                setGoal(ticketContext);
                setShowJira(false);
              }}
            />
          </div>
        )}

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
          {running ? "Running..." : "Run + Generate Test"}
        </button>
        {error && <div className="error-bar">{error}</div>}

        {(running || reasoning || liveSteps.length > 0 || liveError) && (
          <div className="agentic-live">
            <div className="panel-header">
              <span>Live Run</span>
              <span className="count">{phase ? `phase: ${phase}` : "connecting…"}</span>
            </div>

            {liveError && <div className="error-bar">{liveError}</div>}

            <div className="live-section">
              <h4>LLM reasoning (streaming)</h4>
              <div className="reasoning-feed" ref={reasoningRef}>
                {reasoning ? reasoning : <span className="muted">waiting for model…</span>}
              </div>
            </div>

            {liveSteps.length > 0 && (
              <div className="live-section">
                <h4>Actions</h4>
                {liveSteps.map((s, i) => (
                  <div key={i} className={`live-step ${s.ok === undefined ? "pending" : s.ok ? "ok" : "fail"}`}>
                    <span className="step-name">{s.name}</span>
                    {s.args && (s.args.target || s.args.value) && (
                      <span className="step-args">
                        {s.args.target}
                        {s.args.value ? ` = ${s.args.value}` : ""}
                      </span>
                    )}
                    <span className="step-state">
                      {s.ok === undefined ? "…" : s.ok ? "ok" : "fail"}
                    </span>
                    {s.result && <div className="step-result">{s.result}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

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
          <button className="go-btn primary" onClick={runGenerateAgentic} disabled={genAgenticRunning}>
            {genAgenticRunning ? "Exploring + Generating..." : "Generate from Goal"}
          </button>
          {genAgenticError && <div className="error-bar">{genAgenticError}</div>}
          <button className="go-btn" onClick={runGenerateRun} disabled={genRunning}>
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

      {genAgentic?.exploration_log && genAgentic.exploration_log.length > 0 && (
        <div className="agentic-result">
          <div className="panel-header"><span>Exploration Steps</span></div>
          <pre className="code-block">{genAgentic.exploration_log.join("\n")}</pre>
        </div>
      )}

      {genAgentic?.observations && genAgentic.observations.length > 0 && (
        <div className="agentic-result">
          <div className="panel-header"><span>Pages Explored ({genAgentic.observations.length})</span></div>
          {genAgentic.observations.map((o, i) => (
            <details key={i} className="obs">
              <summary>{o.url}{o.action_taken ? ` · ${o.action_taken}` : ""}</summary>
              {(o.interactive_elements || []).slice(0, 40).map((e, j) => (
                <div key={j} className="obs-el">
                  <span>{e.role}</span>
                  <span>{e.name}</span>
                </div>
              ))}
            </details>
          ))}
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
