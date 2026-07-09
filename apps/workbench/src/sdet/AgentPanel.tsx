import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import type { ContextElement, RecordedAction, OpenCodeEvent } from "./types";
import { buildMessageGroups } from "./types";
import StepIndicator from "./StepIndicator";
import MessageList from "./MessageList";
import ElementChip from "./ElementChip";
import SuggestionChips from "./SuggestionChips";
import TicketIntegration from "./TicketIntegration";
import ErrorBoundary from "../ErrorBoundary";

interface OpenCodeState {
  testCode: string | null;
  opencodeEvents: OpenCodeEvent[];
  opencodeRunning: boolean;
  opencodeLiveCode: string;
  opencodeFinalCode: string | null;
}

interface AgentPanelProps {
  apiBase: string;
  url: string;
  repoDir: string;
  onRepoDirChange: (dir: string) => void;
  contextElements: ContextElement[];
  recordedActions: RecordedAction[];
  onRemoveElement: (id: string) => void;
  onClearElements: () => void;
  onElementSelectionChange?: (active: boolean) => void;
  onOpencodeStateChange?: (state: OpenCodeState) => void;
}

interface RepoContextInfo {
  page_objects: string[];
  utilities: string[];
}

function phaseIndex(nodeId: string): number {
  return parseInt(nodeId.replace("N", ""), 10) || 0;
}

export default function AgentPanel({
  apiBase,
  url,
  repoDir,
  onRepoDirChange,
  contextElements,
  recordedActions,
  onRemoveElement,
  onClearElements,
  onElementSelectionChange,
  onOpencodeStateChange,
}: AgentPanelProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [chips, setChips] = useState<{ id: string; label: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repoContext, setRepoContext] = useState<RepoContextInfo | null>(null);
  const [testCode, setTestCode] = useState<string | null>(null);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [currentNodeId, setCurrentNodeId] = useState("N0");
  const [opencodeEvents, setOpencodeEvents] = useState<OpenCodeEvent[]>([]);
  const [opencodeRunning, setOpencodeRunning] = useState(false);
  const [opencodeFinalCode, setOpencodeFinalCode] = useState<string | null>(null);
  const [opencodeLiveCode, setOpencodeLiveCode] = useState<string>("");
  const [showTicketPanel, setShowTicketPanel] = useState(false);
  const [opencodeModel, setOpenCodeModel] = useState<string>(
    () => (import.meta.env.VITE_OPENCODE_MODEL as string) || ""
  );
  const opencodeModelRef = useRef(opencodeModel);
  opencodeModelRef.current = opencodeModel;
  const appliedModelRef = useRef<string>("");
  const opencodeLiveRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const groups = useMemo(() => buildMessageGroups(messages), [messages]);
  const currentPhase = useMemo(() => phaseIndex(currentNodeId), [currentNodeId]);

  const isSelecting = currentNodeId === "N9";

  useEffect(() => {
    onElementSelectionChange?.(isSelecting && !sessionComplete);
  }, [isSelecting, sessionComplete, onElementSelectionChange]);

  const displayChips = useMemo(() => {
    if (chips.length > 0) {
      if (!sessionComplete) {
        const hasExplainMore = chips.some((c) => c.label.toLowerCase() === "let me explain more");
        if (hasExplainMore) {
          const filtered = chips.filter((c) => c.label.toLowerCase() !== "let me explain more");
          return [...filtered, { id: "jira_ticket", label: showTicketPanel ? "Close Jira" : "Jira Ticket" }];
        }
      }
      return chips;
    }
    if (isSelecting && !loading) return [{ id: "done_sel", label: "I'm done selecting elements" }];
    return [];
  }, [chips, isSelecting, loading, sessionComplete, showTicketPanel]);

  const startSession = useCallback(async () => {
    if (!url) return;
    setLoading(true);
    setError(null);
    setMessages([]);
    setChips([]);
    setRepoContext(null);
    setTestCode(null);
    setSessionComplete(false);
    setShowTicketPanel(false);
    setOpencodeEvents([]);
    setOpencodeRunning(false);
    setOpencodeFinalCode(null);
    setOpencodeLiveCode("");
    try {
      const res = await fetch(`${apiBase}/api/workbench/session/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          elements: [],
          load_model: false,
          automation_repo: repoDir || undefined,
          opencode_model: opencodeModelRef.current || undefined,
        }),
        signal: AbortSignal.timeout(8000),
      });
      if (!res.ok) throw new Error(`Session start failed: ${res.status}`);
      const data = await res.json();
      setSessionId(data.session_id);
      setMessages(data.messages || []);
      setChips(data.suggestion_chips || []);
      setCurrentNodeId(data.current_node || "N0");
      appliedModelRef.current = opencodeModelRef.current;
      if (data.repo_context) setRepoContext(data.repo_context);
    } catch (e: any) {
      setError(e.message);
      setSessionId(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, url, repoDir]);

  const sendMessage = useCallback(async (text: string) => {
    if (!sessionId || !text.trim() || loading) return;
    const userMsg = { role: "user", content: text.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setShowTicketPanel(false);
    setLoading(true);
    setError(null);
    setChips([]);
    const elementsPayload = contextElements.map((el) => ({
      id: el.id,
      cssPath: el.cssPath,
      tag: el.tag,
      text: el.text,
    }));
    const actionsPayload = recordedActions.length > 0 ? recordedActions.map((a) => ({
      css_path: a.css_path,
      tag: a.tag,
      action_type: a.action_type,
      value: a.value || "",
      text: a.text || "",
      step_order: a.step_order || 0,
      element_id: a.element_id || "",
    })) : undefined;

    let finalContent = text.trim();
    let useModelFlag = true;

    if (currentNodeId === "N14") {
      const generateRequest = {
        url: url,
        elements: elementsPayload,
        actions: actionsPayload,
        scenario: messages.length > 0 ? messages[0].content : "User flow test",
      };
      const agentPrompt = `Please generate a Playwright test in TypeScript based on the following context: ${JSON.stringify(generateRequest)}`;
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "**ACTION REQUIRED:** To generate the test, please copy the following prompt and paste it into the main chat input:\n\n```\n" + agentPrompt + "\n```" },
      ]);
      // Send a generic message to the Workbench API to advance the state, not the full prompt
      finalContent = "Agent ready for test generation. Prompt provided to user for manual execution.";
      useModelFlag = false; // Do not use model for this message
    }

    try {
      const res = await fetch(`${apiBase}/api/workbench/session/${sessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: finalContent,
          selected_elements: elementsPayload,
          recorded_actions: actionsPayload,
          use_model: useModelFlag,
        }),
        signal: AbortSignal.timeout(15000),
      });
      if (!res.ok) throw new Error(`Send failed: ${res.status}`);
      const data = await res.json();
      if (data.type === "error") {
        setError(data.content);
      } else {
        if (data.message) {
          setMessages((prev) => [...prev, { role: data.message.role, content: data.message.content }]);
        }
        setChips(data.suggestion_chips || []);
        setSessionComplete(data.is_complete || false);
        setCurrentNodeId(data.next_node || currentNodeId);
        if (data.test_code) setTestCode(data.test_code);
        if (data.next_node === "N14") {
          setOpencodeRunning(true);
          setOpencodeEvents([]);
          setOpencodeFinalCode(null);
        }
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId, loading, contextElements, recordedActions, apiBase, currentNodeId]);

  const resetToNode = useCallback(async (nodeId: string) => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/api/workbench/session/${sessionId}/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: nodeId }),
        signal: AbortSignal.timeout(8000),
      });
      if (!res.ok) throw new Error(`Reset failed: ${res.status}`);
      const data = await res.json();
      setMessages(data.messages || []);
      setChips(data.suggestion_chips || []);
      setCurrentNodeId(data.current_node || "N0");
      setSessionComplete(false);
      setTestCode(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId, apiBase]);

  const handleChipClick = useCallback((label: string) => {
    if (label === "Jira Ticket" || label === "Close Jira") {
      setShowTicketPanel((prev) => !prev);
      return;
    }
    sendMessage(label);
  }, [sendMessage]);

  const handleModelBlur = useCallback(() => {
    if (sessionId && appliedModelRef.current !== opencodeModelRef.current) {
      startSession();
    }
  }, [sessionId, startSession]);

  const handleBack = useCallback(() => {
    if (groups.length < 2) return;
    const prev = groups[groups.length - 2];
    resetToNode(prev.nodeId);
  }, [groups, resetToNode]);

  const handleRemoveStep = useCallback((nodeId: string) => {
    resetToNode(nodeId);
  }, [resetToNode]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && input.trim() && !loading && sessionId && !sessionComplete) {
      sendMessage(input.trim());
    }
  }, [input, loading, sessionId, sessionComplete, sendMessage]);

  useEffect(() => {
    if (url) startSession();
  }, [url, startSession]);

  useEffect(() => {
    if (!sessionId) return;
    const wsUrl = apiBase.replace(/^http/, "ws") + "/api/workbench/session/" + sessionId + "/ws";
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "opencode_event") {
          setOpencodeEvents((prev) => [...prev, data]);
        } else if (data.type === "opencode_code_chunk") {
          if (data.accumulated) {
            setOpencodeLiveCode(data.accumulated);
          } else {
            setOpencodeLiveCode((prev) => prev + "\n\n" + data.content);
          }
        } else if (data.type === "opencode_complete") {
          setOpencodeRunning(false);
          setOpencodeFinalCode(data.test_code || null);
          if (data.test_code) {
            setTestCode(data.test_code);
            setOpencodeLiveCode(data.test_code);
          }
          if (data.review_message) {
            setMessages((prev) => [...prev, { role: "assistant", content: data.review_message }]);
          }
          if (data.current_node) {
            setCurrentNodeId(data.current_node);
          }
          if (data.suggestion_chips) {
            setChips(data.suggestion_chips);
          }
          if (data.is_complete !== undefined) {
            setSessionComplete(data.is_complete);
          }
        } else if (data.type === "opencode_question") {
          setMessages((prev) => [...prev, { role: "assistant", content: "Question: " + data.content }]);
          setError(null);
        } else if (data.type === "opencode_error") {
          setOpencodeRunning(false);
          setOpencodeEvents((prev) => [...prev, { type: "opencode_error", content: data.content }]);
        }
      } catch { /* ignore */ }
    };

    ws.onclose = () => {
      wsRef.current = null;
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [sessionId, apiBase]);

  // Notify parent of opencode state changes for OutputPanel
  useEffect(() => {
    onOpencodeStateChange?.({
      testCode,
      opencodeEvents,
      opencodeRunning,
      opencodeLiveCode,
      opencodeFinalCode,
    });
  }, [testCode, opencodeEvents, opencodeRunning, opencodeLiveCode, opencodeFinalCode, onOpencodeStateChange]);

  // Auto-scroll stream body when new events or code arrive
  useEffect(() => {
    if (opencodeLiveRef.current) {
      opencodeLiveRef.current.scrollTop = opencodeLiveRef.current.scrollHeight;
    }
  }, [opencodeLiveCode, opencodeEvents.length]);

  return (
    <div className="ap-panel">
      <StepIndicator
        currentNodeId={currentNodeId}
        visitedCount={groups.length}
        totalSteps={16}
      />

      <div className="ap-repo-row">
        <span className="ap-repo-label">Repo</span>
        <input
          className="ap-repo-input"
          type="text"
          value={repoDir}
          onChange={(e) => onRepoDirChange(e.target.value)}
          placeholder="/path/to/project (or set VITE_WORKBENCH_REPO)"
        />
      </div>

      <div className="ap-repo-row">
        <span className="ap-repo-label">Provider/Model</span>
        <input
          className="ap-repo-input"
          type="text"
          value={opencodeModel}
          onChange={(e) => setOpenCodeModel(e.target.value)}
          onBlur={handleModelBlur}
          placeholder="provider/model (e.g. anthropic/claude-...)"
          disabled={loading}
        />
      </div>

      {repoContext && (repoContext.page_objects.length > 0 || repoContext.utilities.length > 0) && (
        <div className="ap-repo-context">
          {repoContext.page_objects.length > 0 && (
            <span className="ap-repo-context-item">
              Page objects: <span className="ap-repo-context-count">{repoContext.page_objects.length}</span>
            </span>
          )}
          {repoContext.utilities.length > 0 && (
            <span className="ap-repo-context-item">
              Utilities: <span className="ap-repo-context-count">{repoContext.utilities.length}</span>
            </span>
          )}
        </div>
      )}

      <div className="ap-messages">
        <MessageList groups={groups} loading={loading} onBack={handleBack} onSendMessage={sendMessage} />
      </div>

      {contextElements.length > 0 && (
        <div className="ap-context">
          <span className="ap-context-label">Elements:</span>
          <div className="ap-context-chips">
            {contextElements.map((el) => (
              <ElementChip key={el.id} element={el} onRemove={onRemoveElement} />
            ))}
          </div>
          <button className="ap-context-clear" onClick={onClearElements}>Clear</button>
        </div>
      )}

      {recordedActions.length > 0 && (
        <div className="ap-actions">
          <span className="ap-actions-label">Recorded Actions ({recordedActions.length})</span>
          <div className="ap-actions-list">
            {recordedActions.map((a, i) => (
              <div key={i} className="ap-action-item">
                <span className="ap-action-step">{a.step_order || i + 1}.</span>
                <span className={`ap-action-type ap-action-${a.action_type}`}>{a.action_type}</span>
                <span className="ap-action-target">&lt;{a.tag}&gt;</span>
                {a.text && <span className="ap-action-text">"{a.text.slice(0, 30)}"</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {(opencodeRunning || opencodeEvents.length > 0 || opencodeLiveCode) && (
        <div className="ap-opencode-stream">
          <div className="ap-opencode-stream-header">
            <span className="ap-opencode-stream-title">TestRadius Agent Activity</span>
            {opencodeRunning && <span className="ap-opencode-stream-spinner" />}
            {!opencodeRunning && <span className="ap-opencode-stream-done"> Done</span>}
          </div>

          <div className="ap-opencode-stream-body" ref={opencodeLiveRef}>
            {opencodeEvents.map((evt, i) => {
              if (evt.type === "opencode_error") {
                return <div key={i} className="ap-opencode-error">Error: {evt.content}</div>;
              }
              if (evt.type === "opencode_complete") return null;
              const e = evt as any;
              if (e.event === "tool_use") {
                const statusIcon = e.status === "completed" ? "✓" : e.status === "running" ? "▶" : "○";
                if (e.command) {
                  return <div key={i} className="ap-opencode-line ap-opencode-bash">
                    <span className="ap-opencode-line-icon">{statusIcon}</span>
                    <span className="ap-opencode-line-tag ap-opencode-tag-bash">bash</span>
                    <span className="ap-opencode-line-body">{e.command}</span>
                    {e.output && <pre className="ap-opencode-line-pre">{e.output}</pre>}
                  </div>;
                }
                if (e.file_content) {
                  return <div key={i} className="ap-opencode-line ap-opencode-write">
                    <span className="ap-opencode-line-icon">{statusIcon}</span>
                    <span className="ap-opencode-line-tag ap-opencode-tag-write">{e.tool}</span>
                    <span className="ap-opencode-line-body">{e.path}</span>
                    <pre className="ap-opencode-line-pre"><code>{e.file_content}</code></pre>
                  </div>;
                }
                if (e.path) {
                  return <div key={i} className="ap-opencode-line ap-opencode-read">
                    <span className="ap-opencode-line-icon">{statusIcon}</span>
                    <span className="ap-opencode-line-tag ap-opencode-tag-read">{e.tool}</span>
                    <span className="ap-opencode-line-body">{e.path}</span>
                  </div>;
                }
                return <div key={i} className="ap-opencode-line">
                  <span className="ap-opencode-line-icon">{statusIcon}</span>
                  <span className="ap-opencode-line-tag">{e.tool}</span>
                  <span className="ap-opencode-line-body">{e.content || e.status}</span>
                </div>;
              }
              if (e.event === "text" && e.content) {
                return <div key={i} className="ap-opencode-text">{e.content}</div>;
              }
              if (e.event === "thinking" && e.content) {
                return <div key={i} className="ap-opencode-think">{e.content}</div>;
              }
              return null;
            })}
            {opencodeLiveCode && (
              <div className="ap-opencode-code-block">
                <div className="ap-opencode-code-block-header">
                  <span className="ap-opencode-code-block-title">Generated Code</span>
                  {opencodeRunning && <span className="ap-opencode-code-block-live">LIVE</span>}
                </div>
                <pre className="ap-opencode-code-block-pre">
                  <code>{opencodeLiveCode}</code>
                </pre>
              </div>
            )}
          </div>
        </div>
      )}

      {testCode && (
        <div className="ap-test-code">
          <div className="ap-test-code-header">
            <span>Generated Test</span>
            <button className="ap-btn" onClick={() => navigator.clipboard.writeText(testCode)}>Copy</button>
          </div>
          <pre className="ap-test-code-pre"><code>{testCode}</code></pre>
        </div>
      )}

      {showTicketPanel && (
        <ErrorBoundary>
          <TicketIntegration apiBase={apiBase} sessionId={sessionId} onSelectTicket={(ctx) => { setInput(ctx); setShowTicketPanel(false); }} />
        </ErrorBoundary>
      )}

      <SuggestionChips chips={displayChips} onChipClick={handleChipClick} disabled={loading} />

      <div className="ap-input-row">
        <input
          className="ap-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={sessionComplete ? "Session complete. Enter a new URL to start." : "Describe the test..."}
          disabled={!sessionId || loading || sessionComplete}
        />
        <button
          className="ap-send-btn"
          onClick={() => sendMessage(input.trim())}
          disabled={!input.trim() || !sessionId || loading || sessionComplete}
        >
          Send
        </button>
      </div>

      {error && <div className="ap-error">{error}</div>}
    </div>
  );
}
