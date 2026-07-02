import { useState, useCallback, useEffect, useMemo } from "react";
import type { ContextElement, RecordedAction } from "./types";
import { buildMessageGroups } from "./types";
import StepIndicator from "./StepIndicator";
import MessageList from "./MessageList";
import ElementChip from "./ElementChip";
import SuggestionChips from "./SuggestionChips";

interface AgentPanelProps {
  apiBase: string;
  url: string;
  contextElements: ContextElement[];
  recordedActions: RecordedAction[];
  onRemoveElement: (id: string) => void;
  onClearElements: () => void;
  onElementSelectionChange?: (active: boolean) => void;
}

function phaseIndex(nodeId: string): number {
  return parseInt(nodeId.replace("N", ""), 10) || 0;
}

export default function AgentPanel({
  apiBase,
  url,
  contextElements,
  recordedActions,
  onRemoveElement,
  onClearElements,
  onElementSelectionChange,
}: AgentPanelProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [chips, setChips] = useState<{ id: string; label: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testCode, setTestCode] = useState<string | null>(null);
  const [sessionComplete, setSessionComplete] = useState(false);
  const [currentNodeId, setCurrentNodeId] = useState("N0");

  const groups = useMemo(() => buildMessageGroups(messages), [messages]);
  const currentPhase = useMemo(() => phaseIndex(currentNodeId), [currentNodeId]);

  const isSelecting = currentNodeId === "N9";

  useEffect(() => {
    onElementSelectionChange?.(isSelecting && !sessionComplete);
  }, [isSelecting, sessionComplete, onElementSelectionChange]);

  const displayChips = useMemo(() => {
    if (chips.length > 0) return chips;
    if (isSelecting && !loading) return [{ id: "done_sel", label: "I'm done selecting elements" }];
    return [];
  }, [chips, isSelecting, loading]);

  const startSession = useCallback(async () => {
    if (!url) return;
    setLoading(true);
    setError(null);
    setMessages([]);
    setChips([]);
    setTestCode(null);
    setSessionComplete(false);
    try {
      const res = await fetch(`${apiBase}/api/workbench/session/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, elements: [], load_model: false }),
      });
      if (!res.ok) throw new Error(`Session start failed: ${res.status}`);
      const data = await res.json();
      setSessionId(data.session_id);
      setMessages(data.messages || []);
      setChips(data.suggestion_chips || []);
      setCurrentNodeId(data.current_node || "N0");
    } catch (e: any) {
      setError(e.message);
      setSessionId(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, url]);

  const sendMessage = useCallback(async (text: string) => {
    if (!sessionId || !text.trim() || loading) return;
    const userMsg = { role: "user", content: text.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
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
    try {
      const res = await fetch(`${apiBase}/api/workbench/session/${sessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: text.trim(),
          selected_elements: elementsPayload,
          recorded_actions: actionsPayload,
          use_model: true,
        }),
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
    sendMessage(label);
  }, [sendMessage]);

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

  return (
    <div className="ap-panel">
      <StepIndicator
        currentNodeId={currentNodeId}
        visitedCount={groups.length}
        totalSteps={16}
      />

      <div className="ap-messages">
        <MessageList groups={groups} loading={loading} onBack={handleBack} />
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

      {testCode && (
        <div className="ap-test-code">
          <div className="ap-test-code-header">
            <span>Generated Test</span>
            <button className="ap-btn" onClick={() => navigator.clipboard.writeText(testCode)}>Copy</button>
          </div>
          <pre className="ap-test-code-pre"><code>{testCode}</code></pre>
        </div>
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
